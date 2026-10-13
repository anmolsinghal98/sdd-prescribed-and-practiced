#!/usr/bin/env python3
"""
Fetch ALL spec.md / specs.md files from GitHub (filename match is case-insensitive
on GitHub's side already - confirmed empirically, one query covers all casings).
No date filtering: every match is stored, and the file's last-commit (most recent
edit) date is recorded alongside it.

API-call budget per matched search hit (all verified empirically against the
live API - see conversation this was written in):
  - 0 extra calls: file name/path/sha/html_url/git_url and repo full_name/
    html_url/description/fork/private/owner.login/owner.type - these are
    embedded in the /search/code response itself.
  - 1 extra call per UNIQUE repo (cached for the run): a real `GET /repos/{full_name}`
    to get stars/forks/watchers/open_issues/language/license/default_branch/
    size/archived/visibility/topics/created_at/updated_at/pushed_at. PyGithub's
    `repo.raw_data` on an object built from a search hit is NOT free - it lazily
    completes via a hidden GET (confirmed), so we deliberately do one real,
    explicit get_repo() call per repo instead and reuse the result.
  - 1 extra call per file: the file's LAST-commit (most recent) timestamp/author.
    GitHub returns commits newest-first, so the most recent commit is simply the
    first item on page 1 of `GET /repos/{full}/commits?path=...` (per_page=1) -
    a single request. Do NOT use `list(repo.get_commits(path=...))` - that walks
    the ENTIRE commit history for the file (one real file had 421 commits / 5
    pages at per_page=100), which is likely why earlier runs of this pipeline
    "kept going and going".

GitHub's code search has no date qualifier (confirmed against current docs),
so adaptive partitioning is done via the `size:` qualifier (bytes, not KB -
the old script's comments called it KB but the API reads it as bytes).

Runs in two phases so progress has a precise denominator:
  1. PLAN pass (count-only): recursively split the `size:` tree using just
     search totalCount calls until every leaf is < MAX_PARTITION_SIZE, then
     persist the leaf partitions + a total-file estimate to `spec_files_plan`
     / `spec_files_run_meta`. Resumable and reused across runs.
  2. FETCH pass: walk the planned leaves, storing files and reporting
     "partition X/N, ~F/T files (P%), ETA ...".

Check progress anytime (even from another terminal, while a run is ongoing):
    python3 fetch_spec_files.py --status
Other flags: --replan (force a fresh plan), --plan-only (compute total only).

Results are stored in the existing MySQL database `specdriven` (same
myDB_user / myDB_pwd credentials as the rest of this project), table
`spec_files`, with the plan/progress in `spec_files_plan` and
`spec_files_run_meta`.
"""

import argparse
import hashlib
import logging
import os
import sys
import time
import requests
from dotenv import load_dotenv
from github import Github, GithubException, RateLimitExceededException

QUERY = "filename:spec.md OR filename:specs.md"
VALID_NAMES = {"spec.md", "specs.md"}

DEFAULT_DB_NAME = "specdriven"
TABLE_FILES = "spec_files"
TABLE_PLAN = "spec_files_plan"          # one row per leaf size-partition (the denominator lives here)
TABLE_RUN_META = "spec_files_run_meta"  # per-run plan totals / completion marker
DEFAULT_RUN_ID = "spec_2024_2026"  # fixed (not date-based) so multi-day runs resume correctly

MAX_RESULTS_PER_PAGE = 100
MAX_SEARCH_RESULTS = 1000
MAX_PARTITION_SIZE = 400  # GitHub's search totalCount is unreliable near/above this
MAX_RETRIES = 5
RETRY_DELAY = 60
GITHUB_API = "https://api.github.com"


# --------------------------------------------------------------------------
# Tokens / rotation
# --------------------------------------------------------------------------

def get_github_tokens() -> list[str]:
    load_dotenv(override=True)
    tokens_str = os.getenv("GITHUB_TOKENS")
    if tokens_str:
        tokens = [t.strip() for t in tokens_str.split(",") if t.strip()]
        if tokens:
            logging.info("Loaded %d token(s) from GITHUB_TOKENS", len(tokens))
            return tokens
    tokens = []
    t = os.getenv("GITHUB_TOKEN")
    if t:
        tokens.append(t)
    for i in range(2, 11):
        t = os.getenv(f"GITHUB_TOKEN_{i}")
        if t:
            tokens.append(t)
    if tokens:
        return tokens
    raise ValueError("No GitHub token(s) found. Set GITHUB_TOKEN or GITHUB_TOKENS in .env")


class TokenRotator:
    """
    Round-robin token pool shared across search / repo-detail / commit calls.

    The code-search endpoint is limited to ~30 req/min PER TOKEN, so we spread
    calls across all tokens proactively (advance after every call) rather than
    hammering one token until it 403s. `advance()` is cyclic, so there is always
    a next token to jump to on throttling.
    """

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.n = len(tokens)
        self.idx = 0

    @property
    def current(self) -> str:
        return self.tokens[self.idx]

    # Backward-compatible alias used by the raw-requests commit path.
    @property
    def token(self) -> str:
        return self.tokens[self.idx]

    def advance(self) -> None:
        self.idx = (self.idx + 1) % self.n

    def rotate(self) -> bool:
        """Move to the next token (cyclic). Always True — there's always a next."""
        self.advance()
        return True


def with_token_rotation(rotator: TokenRotator, fn, *args, **kwargs):
    """
    Call fn(token, ...) using round-robin tokens. On 403/429/rate-limit, jump to
    the next token immediately (PyGithub's own retry is disabled via retry=0, so
    we get control instead of a long single-token backoff). Only sleep if a full
    cycle through every token is throttled.
    """
    throttled = 0
    max_attempts = rotator.n * MAX_RETRIES
    for _ in range(max_attempts):
        token = rotator.current
        try:
            result = fn(token, *args, **kwargs)
            rotator.advance()  # spread the NEXT call onto a different token
            return result
        except RateLimitExceededException:
            rotator.advance()
            throttled += 1
        except GithubException as e:
            if e.status == 404:
                return None
            if e.status in (403, 429):
                rotator.advance()
                throttled += 1
            else:
                logging.warning("GithubException %s: %s", e.status, e.data)
                rotator.advance()
                time.sleep(2)
                continue
        except Exception as e:
            logging.warning("Error in %s: %s", fn.__name__, e)
            rotator.advance()
            time.sleep(2)
            continue
        # A full lap of the pool came back throttled -> wait for the window to reset.
        if throttled and throttled % rotator.n == 0:
            logging.warning(
                "All %d tokens throttled (search limit ~30/min each); sleeping %ds...",
                rotator.n, RETRY_DELAY,
            )
            time.sleep(RETRY_DELAY)
    logging.warning("Max attempts reached for %s; giving up.", fn.__name__)
    return None


# --------------------------------------------------------------------------
# MySQL
# --------------------------------------------------------------------------

def stable_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def get_db_connection(db_name: str):
    load_dotenv(override=True)
    import mysql.connector  # type: ignore

    db_user = os.getenv("myDB_user")
    db_pass = os.getenv("myDB_pwd")
    if not db_user or not db_pass:
        raise RuntimeError("Missing myDB_user / myDB_pwd in environment (.env)")
    conn = mysql.connector.connect(
        host="localhost", port=3306, user=db_user, password=db_pass, database=db_name,
    )
    # Non-strict so a rare oversize field value truncates instead of aborting a
    # long fetch run. Big free-text fields (commit message, signature) are
    # LONGTEXT, so this only ever clips pathological edge cases.
    cur = conn.cursor()
    try:
        cur.execute("SET SESSION sql_mode = ''")
    finally:
        cur.close()
    return conn


FILE_COLUMNS = [
    # --- file (from search hit) ---
    "file_url_sha16", "file_url", "file_path", "file_name", "file_sha", "git_url",
    "search_run_id",
    # --- repo identity / basics ---
    "repo_id", "repo_node_id", "repo_name", "repo_url", "repo_homepage", "repo_description",
    "repo_fork", "repo_private", "repo_visibility",
    # --- owner ---
    "owner_login", "owner_id", "owner_node_id", "owner_type", "owner_html_url",
    "owner_avatar_url", "owner_site_admin",
    # --- repo popularity / size ---
    "repo_stars", "repo_forks", "repo_watchers", "repo_subscribers_count",
    "repo_network_count", "repo_open_issues", "repo_size_kb",
    # --- repo language / license ---
    "repo_language", "repo_license", "repo_license_key", "repo_license_spdx_id",
    "repo_default_branch", "repo_topics",
    # --- repo feature flags / settings ---
    "repo_archived", "repo_disabled", "repo_is_template", "repo_allow_forking",
    "repo_web_commit_signoff_required", "repo_has_issues", "repo_has_projects",
    "repo_has_wiki", "repo_has_pages", "repo_has_downloads", "repo_has_discussions",
    # --- repo clone urls / mirror ---
    "repo_clone_url", "repo_ssh_url", "repo_svn_url", "repo_git_url", "repo_mirror_url",
    # --- repo dates ---
    "repo_created_at", "repo_updated_at", "repo_pushed_at",
    # --- last commit: identity ---
    "file_last_commit_sha", "file_last_commit_node_id", "file_last_commit_html_url",
    "file_last_commit_message", "file_last_commit_comment_count",
    # --- last commit: git author (name/email/date) + GitHub author user ---
    "file_last_commit_at", "file_last_commit_author", "file_last_commit_author_email",
    "file_last_commit_author_login", "file_last_commit_author_id",
    "file_last_commit_author_type", "file_last_commit_author_html_url",
    "file_last_commit_author_avatar_url", "file_last_commit_author_site_admin",
    # --- last commit: git committer (name/email/date) + GitHub committer user ---
    "file_last_commit_committer", "file_last_commit_committer_email",
    "file_last_commit_committer_at", "file_last_commit_committer_login",
    "file_last_commit_committer_id", "file_last_commit_committer_type",
    "file_last_commit_committer_html_url", "file_last_commit_committer_avatar_url",
    "file_last_commit_committer_site_admin",
    # --- last commit: tree / parents / signature verification ---
    "file_last_commit_tree_sha", "file_last_commit_parents",
    "file_last_commit_verified", "file_last_commit_verification_reason",
    "file_last_commit_verified_at", "file_last_commit_signature",
    "file_last_commit_signature_payload",
    # --- bookkeeping ---
    "size_partition_label",
]


def ensure_tables(conn) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{TABLE_FILES}` (
              `file_url_sha16` CHAR(16) NOT NULL PRIMARY KEY,
              `file_url` TEXT NOT NULL,
              `file_path` TEXT,
              `file_name` VARCHAR(255),
              `file_sha` VARCHAR(64),
              `git_url` TEXT,
              `search_run_id` VARCHAR(64),
              `repo_id` BIGINT,
              `repo_node_id` VARCHAR(255),
              `repo_name` VARCHAR(511),
              `repo_url` TEXT,
              `repo_homepage` TEXT,
              `repo_description` TEXT,
              `repo_fork` TINYINT(1),
              `repo_private` TINYINT(1),
              `repo_visibility` VARCHAR(32),
              `owner_login` VARCHAR(255),
              `owner_id` BIGINT,
              `owner_node_id` VARCHAR(255),
              `owner_type` VARCHAR(64),
              `owner_html_url` TEXT,
              `owner_avatar_url` TEXT,
              `owner_site_admin` TINYINT(1),
              `repo_stars` INT,
              `repo_forks` INT,
              `repo_watchers` INT,
              `repo_subscribers_count` INT,
              `repo_network_count` INT,
              `repo_open_issues` INT,
              `repo_size_kb` INT,
              `repo_language` VARCHAR(255),
              `repo_license` VARCHAR(255),
              `repo_license_key` VARCHAR(128),
              `repo_license_spdx_id` VARCHAR(128),
              `repo_default_branch` VARCHAR(255),
              `repo_topics` TEXT,
              `repo_archived` TINYINT(1),
              `repo_disabled` TINYINT(1),
              `repo_is_template` TINYINT(1),
              `repo_allow_forking` TINYINT(1),
              `repo_web_commit_signoff_required` TINYINT(1),
              `repo_has_issues` TINYINT(1),
              `repo_has_projects` TINYINT(1),
              `repo_has_wiki` TINYINT(1),
              `repo_has_pages` TINYINT(1),
              `repo_has_downloads` TINYINT(1),
              `repo_has_discussions` TINYINT(1),
              `repo_clone_url` TEXT,
              `repo_ssh_url` TEXT,
              `repo_svn_url` TEXT,
              `repo_git_url` TEXT,
              `repo_mirror_url` TEXT,
              `repo_created_at` VARCHAR(64),
              `repo_updated_at` VARCHAR(64),
              `repo_pushed_at` VARCHAR(64),
              `file_last_commit_sha` VARCHAR(64),
              `file_last_commit_node_id` VARCHAR(255),
              `file_last_commit_html_url` TEXT,
              `file_last_commit_message` LONGTEXT,
              `file_last_commit_comment_count` INT,
              `file_last_commit_at` VARCHAR(64),
              `file_last_commit_author` TEXT,
              `file_last_commit_author_email` VARCHAR(512),
              `file_last_commit_author_login` VARCHAR(255),
              `file_last_commit_author_id` BIGINT,
              `file_last_commit_author_type` VARCHAR(64),
              `file_last_commit_author_html_url` TEXT,
              `file_last_commit_author_avatar_url` TEXT,
              `file_last_commit_author_site_admin` TINYINT(1),
              `file_last_commit_committer` TEXT,
              `file_last_commit_committer_email` VARCHAR(512),
              `file_last_commit_committer_at` VARCHAR(64),
              `file_last_commit_committer_login` VARCHAR(255),
              `file_last_commit_committer_id` BIGINT,
              `file_last_commit_committer_type` VARCHAR(64),
              `file_last_commit_committer_html_url` TEXT,
              `file_last_commit_committer_avatar_url` TEXT,
              `file_last_commit_committer_site_admin` TINYINT(1),
              `file_last_commit_tree_sha` VARCHAR(64),
              `file_last_commit_parents` TEXT,
              `file_last_commit_verified` TINYINT(1),
              `file_last_commit_verification_reason` VARCHAR(64),
              `file_last_commit_verified_at` VARCHAR(64),
              `file_last_commit_signature` LONGTEXT,
              `file_last_commit_signature_payload` LONGTEXT,
              `size_partition_label` TEXT,
              `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{TABLE_PLAN}` (
              `search_run_id` VARCHAR(64) NOT NULL,
              `partition_label` VARCHAR(255) NOT NULL,
              `min_size` INT NULL,
              `max_size` INT NULL,
              `est_count` INT NOT NULL DEFAULT 0,
              `status` VARCHAR(16) NOT NULL DEFAULT 'pending',   -- pending | done
              `files_stored` INT NOT NULL DEFAULT 0,
              `started_at` TIMESTAMP NULL,
              `completed_at` TIMESTAMP NULL,
              PRIMARY KEY (`search_run_id`, `partition_label`)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{TABLE_RUN_META}` (
              `search_run_id` VARCHAR(64) NOT NULL PRIMARY KEY,
              `plan_partition_count` INT NULL,
              `plan_total_est` INT NULL,
              `plan_completed_at` TIMESTAMP NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        conn.commit()
    finally:
        cur.close()


# --------------------------------------------------------------------------
# Plan table helpers (the plan is the source of truth for "done / total")
# --------------------------------------------------------------------------

def get_run_meta(conn, run_id: str) -> dict | None:
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"SELECT * FROM `{TABLE_RUN_META}` WHERE search_run_id=%s", (run_id,)
        )
        return cur.fetchone()
    finally:
        cur.close()


def is_plan_complete(conn, run_id: str) -> bool:
    meta = get_run_meta(conn, run_id)
    return bool(meta and meta.get("plan_completed_at"))


def save_plan(conn, run_id: str, leaves: list) -> None:
    """Persist the leaf partitions and mark the plan complete for this run.

    leaves: list of (min_size, max_size, label, est_count). Existing plan rows
    for the run are replaced; a matching run-meta row records the totals and
    stamps plan_completed_at so subsequent runs skip planning.
    """
    total_est = sum(int(est or 0) for _, _, _, est in leaves)
    cur = conn.cursor()
    try:
        cur.execute(f"DELETE FROM `{TABLE_PLAN}` WHERE search_run_id=%s", (run_id,))
        ins = f"""
            INSERT INTO `{TABLE_PLAN}`
              (`search_run_id`, `partition_label`, `min_size`, `max_size`, `est_count`, `status`)
            VALUES (%s, %s, %s, %s, %s, 'pending')
        """
        for min_size, max_size, label, est in leaves:
            cur.execute(ins, (run_id, label, min_size, max_size, int(est or 0)))
        cur.execute(
            f"""
            INSERT INTO `{TABLE_RUN_META}`
              (`search_run_id`, `plan_partition_count`, `plan_total_est`, `plan_completed_at`)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
              `plan_partition_count`=VALUES(`plan_partition_count`),
              `plan_total_est`=VALUES(`plan_total_est`),
              `plan_completed_at`=CURRENT_TIMESTAMP
            """,
            (run_id, len(leaves), total_est),
        )
        conn.commit()
    finally:
        cur.close()


def load_pending_partitions(conn, run_id: str) -> list:
    """Return pending leaf partitions as list of dicts, smallest est_count first."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"""SELECT partition_label, min_size, max_size, est_count
                FROM `{TABLE_PLAN}`
                WHERE search_run_id=%s AND status='pending'
                ORDER BY est_count ASC, partition_label ASC""",
            (run_id,),
        )
        return cur.fetchall()
    finally:
        cur.close()


def mark_partition_started(conn, run_id: str, label: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            f"""UPDATE `{TABLE_PLAN}` SET `started_at`=CURRENT_TIMESTAMP
                WHERE search_run_id=%s AND partition_label=%s AND started_at IS NULL""",
            (run_id, label),
        )
        conn.commit()
    finally:
        cur.close()


def mark_partition_fetched(conn, run_id: str, label: str, files_stored: int) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            f"""UPDATE `{TABLE_PLAN}`
                SET `status`='done', `files_stored`=%s, `completed_at`=CURRENT_TIMESTAMP
                WHERE search_run_id=%s AND partition_label=%s""",
            (files_stored, run_id, label),
        )
        conn.commit()
    finally:
        cur.close()


def upsert_files(conn, rows: list[dict]) -> None:
    if not rows:
        return
    cols = FILE_COLUMNS
    sql = f"""
        INSERT INTO `{TABLE_FILES}` ({", ".join(f"`{c}`" for c in cols)})
        VALUES ({", ".join(["%s"] * len(cols))})
        ON DUPLICATE KEY UPDATE
          {", ".join(f"`{c}`=VALUES(`{c}`)" for c in cols if c != "file_url_sha16")}
    """
    cur = conn.cursor()
    skipped = 0
    try:
        for row in rows:
            try:
                cur.execute(sql, tuple(row.get(c) for c in cols))
            except Exception as e:
                # Never let one pathological row abort a multi-hour fetch.
                skipped += 1
                logging.warning(
                    "Skipping row (DB error: %s): file_url=%s", e, row.get("file_url")
                )
        conn.commit()
    finally:
        cur.close()
    if skipped:
        logging.warning("upsert_files: skipped %d/%d row(s) due to DB errors", skipped, len(rows))


# --------------------------------------------------------------------------
# GitHub calls
# --------------------------------------------------------------------------

def run_search_count(token, query):
    g = Github(token, per_page=MAX_RESULTS_PER_PAGE, retry=0)
    return g.search_code(query=query).totalCount


def run_search_page(token, query, page):
    g = Github(token, per_page=MAX_RESULTS_PER_PAGE, retry=0)
    return list(g.search_code(query=query).get_page(page))


def _bool_or_none(v):
    return None if v is None else bool(v)


def fetch_repo_details(token, full_name):
    """One real GET /repos/{full_name}. Only call once per unique repo (cache the result).

    Extracts every non-hypermedia field GitHub returns (URL *templates* and
    token/policy-specific fields like permissions/custom_properties are the only
    things skipped). owner_* is sourced from here too (the search-hit stub only
    carries login/type for free).
    """
    g = Github(token, retry=0)
    repo = g.get_repo(full_name)
    raw = repo.raw_data  # safe here: repo is already fully fetched, no hidden extra call
    lic = raw.get("license") or {}
    owner = raw.get("owner") or {}
    return {
        "repo_id": raw.get("id"),
        "repo_node_id": raw.get("node_id"),
        "repo_homepage": raw.get("homepage"),
        "owner_login": owner.get("login"),
        "owner_id": owner.get("id"),
        "owner_node_id": owner.get("node_id"),
        "owner_type": owner.get("type"),
        "owner_html_url": owner.get("html_url"),
        "owner_avatar_url": owner.get("avatar_url"),
        "owner_site_admin": _bool_or_none(owner.get("site_admin")),
        "repo_stars": raw.get("stargazers_count"),
        "repo_forks": raw.get("forks_count"),
        "repo_watchers": raw.get("watchers_count"),
        "repo_subscribers_count": raw.get("subscribers_count"),
        "repo_network_count": raw.get("network_count"),
        "repo_open_issues": raw.get("open_issues_count"),
        "repo_size_kb": raw.get("size"),
        "repo_language": raw.get("language"),
        "repo_license": lic.get("name"),
        "repo_license_key": lic.get("key"),
        "repo_license_spdx_id": lic.get("spdx_id"),
        "repo_default_branch": raw.get("default_branch"),
        "repo_topics": ", ".join(raw.get("topics") or []),
        "repo_archived": _bool_or_none(raw.get("archived")),
        "repo_disabled": _bool_or_none(raw.get("disabled")),
        "repo_is_template": _bool_or_none(raw.get("is_template")),
        "repo_allow_forking": _bool_or_none(raw.get("allow_forking")),
        "repo_web_commit_signoff_required": _bool_or_none(raw.get("web_commit_signoff_required")),
        "repo_has_issues": _bool_or_none(raw.get("has_issues")),
        "repo_has_projects": _bool_or_none(raw.get("has_projects")),
        "repo_has_wiki": _bool_or_none(raw.get("has_wiki")),
        "repo_has_pages": _bool_or_none(raw.get("has_pages")),
        "repo_has_downloads": _bool_or_none(raw.get("has_downloads")),
        "repo_has_discussions": _bool_or_none(raw.get("has_discussions")),
        "repo_visibility": raw.get("visibility"),
        "repo_clone_url": raw.get("clone_url"),
        "repo_ssh_url": raw.get("ssh_url"),
        "repo_svn_url": raw.get("svn_url"),
        "repo_git_url": raw.get("git_url"),
        "repo_mirror_url": raw.get("mirror_url"),
        "repo_created_at": raw.get("created_at"),
        "repo_updated_at": raw.get("updated_at"),
        "repo_pushed_at": raw.get("pushed_at"),
    }


def get_file_last_commit(rotator: TokenRotator, repo_full_name: str, file_path: str):
    """
    Returns the newest (last / most recent) commit JSON that touched the file,
    using exactly 1 GitHub API call. GitHub returns commits newest-first, so the
    most recent commit is just the first item on page 1 (per_page=1). Do NOT use
    `list(repo.get_commits(path=...))` - that walks the ENTIRE commit history.
    """

    def _get(url, params=None):
        max_attempts = rotator.n * MAX_RETRIES
        throttled = 0
        for _ in range(max_attempts):
            headers = {
                "Authorization": f"Bearer {rotator.current}",
                "Accept": "application/vnd.github+json",
            }
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=30)
            except requests.exceptions.RequestException as e:
                # Transient network error (dropped connection, timeout, DNS, ...).
                # Over a multi-day run these are inevitable; retry on the next
                # token after a short backoff instead of crashing.
                logging.warning("Network error fetching commits (%s); retrying...", e)
                rotator.advance()
                time.sleep(3)
                continue
            if resp.status_code == 200:
                rotator.advance()  # spread the next commit lookup onto another token
                return resp
            if resp.status_code in (403, 429):
                # Jump to the next token immediately; only sleep once a full lap
                # of the pool is throttled.
                rotator.advance()
                throttled += 1
                if throttled % rotator.n == 0:
                    reset = resp.headers.get("X-RateLimit-Reset")
                    sleep_time = max(int(reset) - time.time() + 5, RETRY_DELAY) if reset else RETRY_DELAY
                    logging.warning("All tokens throttled fetching commits; sleeping %.0fs", sleep_time)
                    time.sleep(sleep_time)
                continue
            if resp.status_code == 404:
                return None
            logging.warning("GitHub API error %s for %s", resp.status_code, url)
            rotator.advance()
            time.sleep(2)
        return None

    url = f"{GITHUB_API}/repos/{repo_full_name}/commits"
    resp = _get(url, params={"path": file_path, "per_page": 1, "page": 1})
    if resp is None:
        return None
    items = resp.json()
    return items[0] if items else None


# --------------------------------------------------------------------------
# Per-hit processing
# --------------------------------------------------------------------------

def process_hit(item, rotator: TokenRotator, repo_cache: dict, stats: dict, partition_label: str):
    name = item.name or ""
    if name.lower() not in VALID_NAMES:
        return None

    repo = item.repository
    full_name = repo.full_name
    if not full_name:
        return None

    if full_name not in repo_cache:
        details = with_token_rotation(rotator, fetch_repo_details, full_name)
        if details is None:
            stats["repo_fetch_failed"] += 1
            return None
        repo_cache[full_name] = details
    details = repo_cache[full_name]

    file_path = item.path
    newest = get_file_last_commit(rotator, full_name, file_path) or {}
    commit = newest.get("commit") or {}
    git_author = commit.get("author") or {}       # git author: name/email/date
    git_committer = commit.get("committer") or {}  # git committer: name/email/date
    gh_author = newest.get("author") or {}         # GitHub user who authored
    gh_committer = newest.get("committer") or {}   # GitHub user who committed
    verification = commit.get("verification") or {}
    tree = commit.get("tree") or {}
    parents = ", ".join(p.get("sha") for p in (newest.get("parents") or []) if p.get("sha"))

    row = {
        # file
        "file_url_sha16": stable_id_from_url(item.html_url or ""),
        "file_url": item.html_url,
        "file_path": file_path,
        "file_name": item.name,
        "file_sha": item.sha,
        "git_url": item.git_url,
        "search_run_id": None,  # filled in by caller
        # repo basics from the free search-hit stub
        "repo_name": full_name,
        "repo_url": repo.html_url,
        "repo_description": repo.description,
        "repo_fork": _bool_or_none(repo.fork),
        "repo_private": _bool_or_none(repo.private),
        # everything else about the repo + owner (keys already match columns)
        **details,
        # last commit: identity
        "file_last_commit_sha": newest.get("sha"),
        "file_last_commit_node_id": newest.get("node_id"),
        "file_last_commit_html_url": newest.get("html_url"),
        "file_last_commit_message": commit.get("message"),
        "file_last_commit_comment_count": commit.get("comment_count"),
        # last commit: git author + GitHub author user
        "file_last_commit_at": git_author.get("date"),
        "file_last_commit_author": git_author.get("name"),
        "file_last_commit_author_email": git_author.get("email"),
        "file_last_commit_author_login": gh_author.get("login"),
        "file_last_commit_author_id": gh_author.get("id"),
        "file_last_commit_author_type": gh_author.get("type"),
        "file_last_commit_author_html_url": gh_author.get("html_url"),
        "file_last_commit_author_avatar_url": gh_author.get("avatar_url"),
        "file_last_commit_author_site_admin": _bool_or_none(gh_author.get("site_admin")),
        # last commit: git committer + GitHub committer user
        "file_last_commit_committer": git_committer.get("name"),
        "file_last_commit_committer_email": git_committer.get("email"),
        "file_last_commit_committer_at": git_committer.get("date"),
        "file_last_commit_committer_login": gh_committer.get("login"),
        "file_last_commit_committer_id": gh_committer.get("id"),
        "file_last_commit_committer_type": gh_committer.get("type"),
        "file_last_commit_committer_html_url": gh_committer.get("html_url"),
        "file_last_commit_committer_avatar_url": gh_committer.get("avatar_url"),
        "file_last_commit_committer_site_admin": _bool_or_none(gh_committer.get("site_admin")),
        # last commit: tree / parents / signature verification
        "file_last_commit_tree_sha": tree.get("sha"),
        "file_last_commit_parents": parents or None,
        "file_last_commit_verified": _bool_or_none(verification.get("verified")),
        "file_last_commit_verification_reason": verification.get("reason"),
        "file_last_commit_verified_at": verification.get("verified_at"),
        "file_last_commit_signature": verification.get("signature"),
        "file_last_commit_signature_payload": verification.get("payload"),
        # bookkeeping
        "size_partition_label": partition_label,
    }
    stats["stored"] += 1
    return row


# --------------------------------------------------------------------------
# Adaptive size-based partitioning (bytes; GitHub code search has no date qualifier)
# --------------------------------------------------------------------------

def partition_spec(min_size, max_size):
    """Return (size_query_fragment, label) for a byte-size range."""
    if min_size is not None and max_size is not None:
        return f"size:{min_size}..{max_size}", f"size_{min_size}_to_{max_size}"
    if min_size is not None:
        return f"size:>={min_size}", f"size_gte_{min_size}"
    if max_size is not None:
        return f"size:<={max_size}", f"size_lte_{max_size}"
    return "", "all_sizes"


def _split_range(min_size, max_size):
    """Return the child ranges for a too-big range, or None if it can't be split."""
    if min_size is not None and max_size is not None and max_size - min_size <= 1:
        return None
    if min_size is None and max_size is None:
        return [(None, 5000), (5000, None)]
    if min_size is None:
        middle = max_size // 2
        return [(None, middle), (middle, max_size)]
    if max_size is None:
        increment = min_size if min_size > 10 else 10
        return [(min_size, min_size + increment), (min_size + increment, None)]
    middle = (min_size + max_size) // 2
    if middle > min_size:
        return [(min_size, middle), (middle, max_size)]
    return None


def build_plan(conn, rotator, run_id, *, force=False):
    """
    PLAN PASS (count-only, no repo/commit/file fetching).

    Recursively expands the size-partition tree using only search totalCount
    calls until every leaf has < MAX_PARTITION_SIZE results (or can't be split
    further), then persists the leaves + a precise total estimate to the plan
    table. This is what gives us an exact "done / total" denominator.

    Resumable across runs: if a completed plan already exists it is reused
    unless force=True. Returns the total file estimate, or None if a count
    call failed (rerun to finish planning).
    """
    if not force and is_plan_complete(conn, run_id):
        meta = get_run_meta(conn, run_id)
        logging.info(
            "Reusing existing plan for run %s: %d partitions, ~%s files total.",
            run_id, meta["plan_partition_count"], f'{meta["plan_total_est"]:,}',
        )
        return meta["plan_total_est"]

    logging.info("PLAN PASS: expanding size partitions (count-only)...")
    leaves = []
    queue = [(None, None)]
    counted = 0
    while queue:
        min_size, max_size = queue.pop(0)
        size_q, label = partition_spec(min_size, max_size)
        query = f"{QUERY} {size_q}".strip()
        total = with_token_rotation(rotator, run_search_count, query)
        counted += 1
        if total is None:
            logging.error("Plan aborted: count failed for %s. Rerun to resume planning.", label)
            return None

        if total >= MAX_PARTITION_SIZE:
            children = _split_range(min_size, max_size)
            if children:
                logging.info("  [plan] %s = %d (>= %d) -> split", label, total, MAX_PARTITION_SIZE)
                queue.extend(children)
                continue
            # Can't split further. If it fits the 1000-result fetch ceiling it's
            # still fully fetchable; if not, it's a CAPPED (lossy) leaf - we'll
            # only be able to retrieve the first MAX_SEARCH_RESULTS of it.
            if total > MAX_SEARCH_RESULTS:
                logging.warning(
                    "  [plan] %s = %d CAPPED: can't split and exceeds the %d fetch ceiling; "
                    "~%d files in this size bucket will be unreachable.",
                    label, total, MAX_SEARCH_RESULTS, total - MAX_SEARCH_RESULTS,
                )
            else:
                logging.info("  [plan] %s = %d (can't split; within fetch ceiling)", label, total)
        if total > 0:
            leaves.append((min_size, max_size, label, total))
        if counted % 25 == 0:
            logging.info("  [plan] %d ranges counted, %d leaves so far...", counted, len(leaves))

    save_plan(conn, run_id, leaves)
    total_est = sum(est for _, _, _, est in leaves)
    capped = [(lbl, est) for _, _, lbl, est in leaves if est > MAX_SEARCH_RESULTS]
    if capped:
        unreachable = sum(est - MAX_SEARCH_RESULTS for _, est in capped)
        logging.warning(
            "PLAN: %d CAPPED partition(s), ~%s files potentially unreachable (GitHub counts inflate, "
            "so this is an upper bound). Labels: %s",
            len(capped), f"{unreachable:,}",
            ", ".join(lbl for lbl, _ in capped[:10]) + (" ..." if len(capped) > 10 else ""),
        )
    logging.info(
        "PLAN COMPLETE: %d leaf partitions, ~%s files total (from %d count calls).",
        len(leaves), f"{total_est:,}", counted,
    )
    return total_est


def fetch_partition(conn, rotator, run_id, part, repo_cache, stats):
    """Fetch one already-planned leaf partition. `part` is a dict from the plan table."""
    label = part["partition_label"]
    size_q, _ = partition_spec(part["min_size"], part["max_size"])
    query = f"{QUERY} {size_q}".strip()

    mark_partition_started(conn, run_id, label)
    rows = []
    page = 0
    max_pages = MAX_SEARCH_RESULTS // MAX_RESULTS_PER_PAGE + 1
    last_page_full = False
    while page < max_pages:
        items = with_token_rotation(rotator, run_search_page, query, page)
        if items is None:
            logging.warning("Page fetch failed for %s page %d; leaving partition pending (retry next run).", label, page)
            if rows:
                upsert_files(conn, rows)  # keep partial progress
            return None
        if not items:
            last_page_full = False
            break
        stats["hits_seen"] += len(items)
        for item in items:
            row = process_hit(item, rotator, repo_cache, stats, label)
            if row is not None:
                row["search_run_id"] = run_id
                rows.append(row)
        last_page_full = len(items) == MAX_RESULTS_PER_PAGE
        if not last_page_full:
            break
        page += 1

    # We stopped because we ran out of the 1000-result window while pages were
    # still full -> GitHub had more matches than we could reach: truncated.
    if last_page_full and page >= max_pages:
        stats["capped_partitions"] = stats.get("capped_partitions", 0) + 1
        logging.warning(
            "TRUNCATED: partition %s hit the %d-result ceiling with full pages; "
            "some files in this size bucket were not retrievable.",
            label, MAX_SEARCH_RESULTS,
        )

    upsert_files(conn, rows)
    mark_partition_fetched(conn, run_id, label, len(rows))
    return len(rows)


def _fmt_eta(seconds):
    if seconds is None or seconds != seconds or seconds < 0:  # None / NaN / negative
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def warm_repo_cache(conn, run_id, repo_cache):
    """
    Pre-load repo details already stored in spec_files so a resumed run does not
    re-fetch (GET /repos) repos it fetched on a previous run. Repo fields are
    identical across all files of a repo, so any stored row reconstructs the
    same `details` dict fetch_repo_details would return.
    """
    detail_cols = [
        c for c in FILE_COLUMNS
        if (c.startswith("repo_") or c.startswith("owner_"))
        and c not in {"repo_name", "repo_url", "repo_description", "repo_fork", "repo_private"}
    ]
    cur = conn.cursor(dictionary=True)
    try:
        # GROUP BY picks one row per repo (safe: non-strict sql_mode, and repo
        # fields are constant within a repo).
        cur.execute(
            f"""SELECT `repo_name`, {", ".join(f"`{c}`" for c in detail_cols)}
                FROM `{TABLE_FILES}` WHERE search_run_id=%s GROUP BY `repo_name`""",
            (run_id,),
        )
        for row in cur.fetchall():
            rn = row.pop("repo_name")
            if rn:
                repo_cache[rn] = {c: row.get(c) for c in detail_cols}
    finally:
        cur.close()
    if repo_cache:
        logging.info("Warmed repo cache from prior progress: %d repos already known.", len(repo_cache))


def run_fetch(conn, rotator, run_id, total_est, repo_cache, stats):
    """FETCH PASS: walk pending leaf partitions, reporting precise progress."""
    warm_repo_cache(conn, run_id, repo_cache)
    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"""SELECT COUNT(*) AS total,
                   SUM(status='done') AS done,
                   SUM(CASE WHEN status='done' THEN files_stored ELSE 0 END) AS files_done
            FROM `{TABLE_PLAN}` WHERE search_run_id=%s""",
        (run_id,),
    )
    agg = cur.fetchone()
    cur.close()
    total_parts = int(agg["total"] or 0)
    done_parts = int(agg["done"] or 0)
    files_done = int(agg["files_done"] or 0)  # from previously-completed runs

    pending = load_pending_partitions(conn, run_id)
    logging.info(
        "FETCH PASS: %d/%d partitions already done (~%s/%s files). %d partitions to go.",
        done_parts, total_parts, f"{files_done:,}", f"{total_est:,}", len(pending),
    )

    t0 = time.time()
    files_done_this_run = 0
    for part in pending:
        label = part["partition_label"]
        done_parts += 1
        logging.info(
            "[partition %d/%d] %s (est %d) -> fetching...",
            done_parts, total_parts, label, part["est_count"],
        )
        n = fetch_partition(conn, rotator, run_id, part, repo_cache, stats)
        if n is None:
            done_parts -= 1  # stayed pending
            continue
        files_done += n
        files_done_this_run += n

        elapsed = time.time() - t0
        rate = files_done_this_run / elapsed if elapsed > 0 else 0  # files/sec this run
        remaining = max(total_est - files_done, 0)
        eta = remaining / rate if rate > 0 else None
        pct = (files_done / total_est * 100) if total_est else 0
        logging.info(
            "    +%d stored | %d/%d partitions | ~%s/%s files (%.1f%%) | %.1f files/min | ETA %s | repos cached %d",
            n, done_parts, total_parts, f"{files_done:,}", f"{total_est:,}", pct,
            rate * 60, _fmt_eta(eta), len(repo_cache),
        )


def print_status(conn, run_id):
    """Print a precise progress snapshot from the DB (safe to run in another terminal)."""
    meta = get_run_meta(conn, run_id)
    if not meta or not meta.get("plan_completed_at"):
        print(f"Run '{run_id}': no completed plan yet. Planning may still be in progress.")
        return
    total_est = int(meta["plan_total_est"] or 0)
    total_parts = int(meta["plan_partition_count"] or 0)

    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"""SELECT SUM(status='done') AS done_parts,
                   MIN(started_at) AS first_started,
                   MAX(completed_at) AS last_completed
            FROM `{TABLE_PLAN}` WHERE search_run_id=%s""",
        (run_id,),
    )
    p = cur.fetchone()
    # Capped (lossy) leaves: can't be split below the fetch ceiling, so any
    # matches beyond MAX_SEARCH_RESULTS in that size bucket are unreachable.
    cur.execute(
        f"""SELECT COUNT(*) AS n,
                   COALESCE(SUM(est_count - %s), 0) AS unreachable,
                   COALESCE(SUM(status='done'), 0) AS done
            FROM `{TABLE_PLAN}`
            WHERE search_run_id=%s AND est_count > %s""",
        (MAX_SEARCH_RESULTS, run_id, MAX_SEARCH_RESULTS),
    )
    cap = cur.fetchone()
    cur.execute(
        f"SELECT COUNT(*) AS n FROM `{TABLE_FILES}` WHERE search_run_id=%s", (run_id,)
    )
    stored = int(cur.fetchone()["n"] or 0)
    cur.close()

    done_parts = int(p["done_parts"] or 0)
    pct_parts = (done_parts / total_parts * 100) if total_parts else 0
    pct_files = (stored / total_est * 100) if total_est else 0
    capped_n = int(cap["n"] or 0)
    capped_unreachable = int(cap["unreachable"] or 0)

    # Throughput / ETA from wall-clock between first start and last completion
    rate = None
    if p["first_started"] and p["last_completed"]:
        span = (p["last_completed"] - p["first_started"]).total_seconds()
        if span > 0:
            rate = stored / span  # files/sec
    remaining = max(total_est - stored, 0)
    eta = remaining / rate if rate else None

    print(f"=== Progress for run '{run_id}' ===")
    print(f"  Partitions : {done_parts:,}/{total_parts:,} done ({pct_parts:.1f}%)")
    print(f"  Files      : {stored:,} stored / ~{total_est:,} estimated ({pct_files:.1f}%)")
    print(f"  Remaining  : ~{remaining:,} files")
    if rate is not None:
        print(f"  Throughput : {rate*60:.1f} files/min (avg)   ETA ~{_fmt_eta(eta)}")
    else:
        print("  Throughput : (not enough data yet)")
    if capped_n:
        print(
            f"  ⚠ Capped   : {capped_n:,} partition(s) exceed the {MAX_SEARCH_RESULTS}-result "
            f"fetch ceiling; up to ~{capped_unreachable:,} files unreachable (upper bound)."
        )
    if done_parts >= total_parts and total_parts:
        if capped_n:
            print("  STATUS     : COMPLETE (with capped partitions — see ⚠ above) ⚠")
        else:
            print("  STATUS     : COMPLETE ✅")
    else:
        print("  STATUS     : in progress")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch all spec.md/specs.md files from GitHub.")
    parser.add_argument("--db", default=DEFAULT_DB_NAME, help="MySQL database name (default: specdriven)")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id for resumability bookkeeping")
    parser.add_argument(
        "--status", action="store_true",
        help="Print a precise progress snapshot from the DB and exit (safe while a run is ongoing).",
    )
    parser.add_argument(
        "--replan", action="store_true",
        help="Force a fresh plan pass even if a completed plan already exists.",
    )
    parser.add_argument(
        "--plan-only", action="store_true",
        help="Run only the plan pass (compute the total), then exit without fetching.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    conn = get_db_connection(args.db)
    ensure_tables(conn)

    # --status just reads the DB; no GitHub calls, safe alongside a running job.
    if args.status:
        print_status(conn, args.run_id)
        conn.close()
        return

    logging.info("MySQL connected: db=%s table=%s", args.db, TABLE_FILES)
    tokens = get_github_tokens()
    rotator = TokenRotator(tokens)
    logging.info("Loaded %d GitHub token(s)", len(tokens))

    # PHASE 1: plan (precise denominator)
    total_est = build_plan(conn, rotator, args.run_id, force=args.replan)
    if total_est is None:
        logging.error("Planning did not complete; rerun to resume. Exiting.")
        conn.close()
        return
    if args.plan_only:
        logging.info("--plan-only set; plan is ready (~%s files). Exiting.", f"{total_est:,}")
        conn.close()
        return

    # PHASE 2: fetch
    repo_cache: dict = {}
    stats = {"hits_seen": 0, "repo_fetch_failed": 0, "stored": 0}
    run_fetch(conn, rotator, args.run_id, total_est, repo_cache, stats)

    logging.info(
        "=== Done. hits_seen=%d unique_repos=%d repo_fetch_failed=%d stored_this_run=%d ===",
        stats["hits_seen"], len(repo_cache), stats["repo_fetch_failed"], stats["stored"],
    )
    print_status(conn, args.run_id)
    conn.close()


if __name__ == "__main__":
    main()
