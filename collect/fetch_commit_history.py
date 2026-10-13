#!/usr/bin/env python3
"""
Phase 2 — commit history for the KEPT spec files (not_spec_filter = 0).

For each kept file we walk its full path-history once (GitHub's
`GET /repos/{owner}/{repo}/commits?path=<file>&per_page=100`, newest-first,
paged to the end). That single walk yields, in one pass:

  * the FIRST (oldest) commit   -> stored in new file_first_commit_* columns on
                                   spec_files (a full mirror of file_last_commit_*)
  * the TOTAL commit count       -> file_total_commits
  * every INTERMEDIATE commit    -> one row each in the new spec_file_commits table
                                   (seq_from_oldest = 1 is the first commit)

For files with a handful of commits (the common case) this is a SINGLE API call.
These are core-REST calls (5,000/hr/token), not the search limit, so across the
token pool the whole kept set is a few-hour crawl. Fully resumable via the
commit_history_status column; re-running only touches unfinished files.

Usage:
  python3 fetch_commit_history.py                 # run the crawl (resumable)
  python3 fetch_commit_history.py --status        # progress only, no API calls
  python3 fetch_commit_history.py --limit 20      # process only N files (smoke test)
  python3 fetch_commit_history.py --schema-only   # create columns/table, then exit
  python3 fetch_commit_history.py --reset-file <file_url_sha16>   # re-queue one file

NOTE: per-commit added/deleted line stats are NOT fetched here (that needs one
extra call PER COMMIT and is a separate, much heavier phase). We store every
field the commits-list endpoint returns for free.
"""

import argparse
import os
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import mysql.connector
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

DEADLOCK_ERRNOS = (1213, 1205)   # deadlock, lock-wait-timeout — retry the txn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_NAME = "specdriven"
COMMITS_TABLE = "spec_file_commits"
MAX_COMMIT_PAGES = 100          # 100 pages x 100 = 10,000 commits/file cap (safety)
PER_PAGE = 100
BATCH = 2000                    # files pulled from the DB per work batch
PROGRESS_EVERY = 200            # print a progress line every N files
# Aggregate core-API ceiling is ~26 req/s (5000/hr x 19 tokens spread evenly).
# Each worker is latency-bound at ~3.7 req/s, so ~7 workers ride just under the
# ceiling without provoking 403 backoffs. The 403/429 handler self-throttles
# regardless, so a higher value stays correct (it just sleeps more).
DEFAULT_WORKERS = 7


class LockedRotator:
    """Thread-safe wrapper over TokenRotator: next_token() atomically returns the
    current token and advances, so concurrent workers spread across the pool."""

    def __init__(self, tokens):
        self._r = f.TokenRotator(tokens)
        self._lock = threading.Lock()
        self.n = self._r.n

    def next_token(self) -> str:
        with self._lock:
            t = self._r.current
            self._r.advance()
            return t


# Each worker thread gets its own MySQL connection (connections aren't shareable
# across threads). Lazily created on first use, keyed by thread.
_tl = threading.local()


def _conn():
    if getattr(_tl, "conn", None) is None:
        _tl.conn = f.get_db_connection(DB_NAME)
    return _tl.conn

# The first-commit columns mirror file_last_commit_* exactly. Each tuple is
# (suffix, DDL type); the column name is "file_first_commit_<suffix>", and the
# suffix is also the key returned by parse_commit() below.
FIRST_COMMIT_COLS = [
    ("sha", "VARCHAR(64)"), ("node_id", "VARCHAR(255)"), ("html_url", "TEXT"),
    ("message", "LONGTEXT"), ("comment_count", "INT"), ("at", "VARCHAR(64)"),
    ("author", "TEXT"), ("author_email", "VARCHAR(512)"), ("author_login", "VARCHAR(255)"),
    ("author_id", "BIGINT"), ("author_type", "VARCHAR(64)"), ("author_html_url", "TEXT"),
    ("author_avatar_url", "TEXT"), ("author_site_admin", "TINYINT(1)"),
    ("committer", "TEXT"), ("committer_email", "VARCHAR(512)"), ("committer_at", "VARCHAR(64)"),
    ("committer_login", "VARCHAR(255)"), ("committer_id", "BIGINT"), ("committer_type", "VARCHAR(64)"),
    ("committer_html_url", "TEXT"), ("committer_avatar_url", "TEXT"), ("committer_site_admin", "TINYINT(1)"),
    ("tree_sha", "VARCHAR(64)"), ("parents", "TEXT"), ("verified", "TINYINT(1)"),
    ("verification_reason", "VARCHAR(64)"), ("verified_at", "VARCHAR(64)"),
    ("signature", "LONGTEXT"), ("signature_payload", "LONGTEXT"),
]


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

def _existing_columns(cur, table):
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
    return {r[0] for r in cur.fetchall()}


def ensure_schema(conn):
    cur = conn.cursor()
    have = _existing_columns(cur, f.TABLE_FILES)

    adds = []
    for suffix, ddl in FIRST_COMMIT_COLS:
        col = f"file_first_commit_{suffix}"
        if col not in have:
            adds.append(f"ADD COLUMN `{col}` {ddl}")
    if "file_total_commits" not in have:
        adds.append("ADD COLUMN `file_total_commits` INT NULL")
    if "commit_history_status" not in have:
        # pending -> done | empty | truncated | error
        adds.append("ADD COLUMN `commit_history_status` VARCHAR(16) NULL")
    if "commit_history_fetched_at" not in have:
        adds.append("ADD COLUMN `commit_history_fetched_at` VARCHAR(32) NULL")
    if adds:
        cur.execute(f"ALTER TABLE `{f.TABLE_FILES}` " + ", ".join(adds))
        logging.info("Added %d column(s) to %s", len(adds), f.TABLE_FILES)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS `{COMMITS_TABLE}` (
          `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          `file_url_sha16` CHAR(16) NOT NULL,
          `repo_name` VARCHAR(512),
          `file_path` TEXT,
          `seq_from_oldest` INT,          -- 1 = first/oldest commit
          `commit_sha` VARCHAR(64),
          `node_id` VARCHAR(255),
          `html_url` TEXT,
          `message` LONGTEXT,
          `comment_count` INT,
          `authored_at` VARCHAR(64),
          `author_name` TEXT,
          `author_email` VARCHAR(512),
          `author_login` VARCHAR(255),
          `author_id` BIGINT,
          `author_type` VARCHAR(64),
          `committed_at` VARCHAR(64),
          `committer_name` TEXT,
          `committer_email` VARCHAR(512),
          `committer_login` VARCHAR(255),
          `committer_id` BIGINT,
          `committer_type` VARCHAR(64),
          `tree_sha` VARCHAR(64),
          `parents` TEXT,
          `verified` TINYINT(1),
          `verification_reason` VARCHAR(64),
          UNIQUE KEY `uq_file_commit` (`file_url_sha16`, `commit_sha`),
          KEY `idx_file` (`file_url_sha16`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    # Match spec_files' collation so JOINs on file_url_sha16 don't hit an
    # "illegal mix of collations" error. Safe/no-op if already correct.
    cur.execute(f"ALTER TABLE `{COMMITS_TABLE}` CONVERT TO CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci")
    conn.commit()
    cur.close()


# --------------------------------------------------------------------------
# Commit fetching (paginated, token-rotating)
# --------------------------------------------------------------------------

def _get(rotator, url, params):
    """One GET with round-robin tokens + 403/429 + network-error handling.
    Returns (status_code, json) ; json is None on give-up. Thread-safe: each
    attempt grabs the next token atomically, so concurrent callers spread out."""
    max_attempts = rotator.n * f.MAX_RETRIES
    throttled = 0
    for _ in range(max_attempts):
        headers = {
            "Authorization": f"Bearer {rotator.next_token()}",
            "Accept": "application/vnd.github+json",
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.exceptions.RequestException as e:
            logging.warning("Network error fetching commits (%s); retrying...", e)
            time.sleep(3)
            continue
        if resp.status_code == 200:
            return 200, resp.json()
        if resp.status_code in (403, 429):
            # Next attempt already uses the next token; only sleep once a full lap
            # of the pool has come back throttled.
            throttled += 1
            if throttled % rotator.n == 0:
                reset = resp.headers.get("X-RateLimit-Reset")
                sleep_time = max(int(reset) - time.time() + 5, f.RETRY_DELAY) if reset else f.RETRY_DELAY
                logging.warning("All tokens throttled; sleeping %.0fs", sleep_time)
                time.sleep(sleep_time)
            continue
        if resp.status_code in (404, 409, 451):
            # 404 gone/renamed, 409 empty repo, 451 DMCA -> no history to get.
            return resp.status_code, None
        logging.warning("GitHub API error %s for %s", resp.status_code, url)
        time.sleep(2)
    return None, None


def fetch_path_commits(rotator, repo_full_name, file_path):
    """Return (commits_newest_first, status) where status is
    'done' | 'truncated' | 'empty' | 'error'."""
    url = f"{f.GITHUB_API}/repos/{repo_full_name}/commits"
    items_all = []
    page = 1
    while True:
        code, items = _get(rotator, url, {"path": file_path, "per_page": PER_PAGE, "page": page})
        if code != 200:
            if code in (404, 409, 451) and page == 1:
                return [], "empty"      # nothing to fetch (repo gone / empty)
            if items is None and page == 1:
                return [], "error"      # gave up on the very first page
            break                       # partial history already collected
        if not items:
            break
        items_all.extend(items)
        if len(items) < PER_PAGE:
            break
        page += 1
        if page > MAX_COMMIT_PAGES:
            return items_all, "truncated"
    # GitHub returns 200 [] for a valid repo but a path with no history (e.g. a
    # file deleted between phase 1 and 2); label that 'empty' rather than 'done'.
    return items_all, ("done" if items_all else "empty")


def parse_commit(node):
    """Flatten a commits-list entry into suffix-keyed fields (keys match the
    file_first_commit_<suffix> columns and feed the per-commit table too)."""
    commit = node.get("commit") or {}
    ga = commit.get("author") or {}         # git author: name/email/date
    gc = commit.get("committer") or {}      # git committer: name/email/date
    ha = node.get("author") or {}           # GitHub user who authored
    hc = node.get("committer") or {}        # GitHub user who committed
    ver = commit.get("verification") or {}
    tree = commit.get("tree") or {}
    parents = ", ".join(p.get("sha") for p in (node.get("parents") or []) if p.get("sha"))
    return {
        "sha": node.get("sha"),
        "node_id": node.get("node_id"),
        "html_url": node.get("html_url"),
        "message": commit.get("message"),
        "comment_count": commit.get("comment_count"),
        "at": ga.get("date"),
        "author": ga.get("name"),
        "author_email": ga.get("email"),
        "author_login": ha.get("login"),
        "author_id": ha.get("id"),
        "author_type": ha.get("type"),
        "author_html_url": ha.get("html_url"),
        "author_avatar_url": ha.get("avatar_url"),
        "author_site_admin": f._bool_or_none(ha.get("site_admin")),
        "committer": gc.get("name"),
        "committer_email": gc.get("email"),
        "committer_at": gc.get("date"),
        "committer_login": hc.get("login"),
        "committer_id": hc.get("id"),
        "committer_type": hc.get("type"),
        "committer_html_url": hc.get("html_url"),
        "committer_avatar_url": hc.get("avatar_url"),
        "committer_site_admin": f._bool_or_none(hc.get("site_admin")),
        "tree_sha": tree.get("sha"),
        "parents": parents or None,
        "verified": f._bool_or_none(ver.get("verified")),
        "verification_reason": ver.get("reason"),
        "verified_at": ver.get("verified_at"),
        "signature": ver.get("signature"),
        "signature_payload": ver.get("payload"),
    }


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

_FIRST_COLS_SQL = ", ".join(f"file_first_commit_{s}=%s" for s, _ in FIRST_COMMIT_COLS)
_UPDATE_FILE_SQL = (
    f"UPDATE {f.TABLE_FILES} SET {_FIRST_COLS_SQL}, "
    "file_total_commits=%s, commit_history_status=%s, commit_history_fetched_at=%s "
    "WHERE file_url_sha16=%s"
)

_COMMIT_INSERT_SQL = f"""
    INSERT INTO {COMMITS_TABLE}
      (file_url_sha16, repo_name, file_path, seq_from_oldest, commit_sha, node_id,
       html_url, message, comment_count, authored_at, author_name, author_email,
       author_login, author_id, author_type, committed_at, committer_name,
       committer_email, committer_login, committer_id, committer_type, tree_sha,
       parents, verified, verification_reason)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""


def persist(conn, file_id, repo, path, commits_newest_first, status):
    """Write first-commit columns + total + every intermediate commit for one file.
    Idempotent: existing commit rows for the file are cleared first. Retries the
    whole transaction on InnoDB deadlock / lock-wait-timeout (expected under
    concurrency; the documented remedy is to restart the transaction)."""
    oldest = commits_newest_first[-1] if commits_newest_first else None
    total = len(commits_newest_first)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    first = parse_commit(oldest) if oldest else {s: None for s, _ in FIRST_COMMIT_COLS}
    file_vals = [first.get(s) for s, _ in FIRST_COMMIT_COLS] + [total, status, now, file_id]

    commit_rows = []
    for i, node in enumerate(reversed(commits_newest_first), start=1):  # oldest -> newest
        p = parse_commit(node)
        commit_rows.append((
            file_id, repo, path, i, p["sha"], p["node_id"], p["html_url"],
            p["message"], p["comment_count"], p["at"], p["author"], p["author_email"],
            p["author_login"], p["author_id"], p["author_type"], p["committer_at"],
            p["committer"], p["committer_email"], p["committer_login"], p["committer_id"],
            p["committer_type"], p["tree_sha"], p["parents"], p["verified"],
            p["verification_reason"],
        ))

    def write(prepared):
        # Per-row execute (not executemany): mysql-connector's executemany
        # rewrites the multi-row VALUES clause and produces malformed SQL on some
        # commit-message content. `prepared=True` sends params over the binary
        # protocol, bypassing client-side string-escaping entirely — needed for
        # the ~1e-5 of rows with a very large message/GPG payload (~9-11 KB) that
        # break that escaping in a multi-param statement (loses NO data).
        cur = conn.cursor(prepared=prepared)
        cur.execute(_UPDATE_FILE_SQL, file_vals)
        cur.execute(f"DELETE FROM {COMMITS_TABLE} WHERE file_url_sha16=%s", (file_id,))
        for r in commit_rows:
            cur.execute(_COMMIT_INSERT_SQL, r)
        conn.commit()
        cur.close()

    used_prepared = False
    for attempt in range(6):
        try:
            write(prepared=used_prepared)
            return total
        except mysql.connector.Error as e:
            conn.rollback()
            if e.errno in DEADLOCK_ERRNOS and attempt < 5:
                time.sleep(0.05 * (attempt + 1))   # brief backoff, then restart txn
                continue
            # Escaping broke on a large param -> retry once via a prepared cursor.
            if not used_prepared and e.errno == 1064:
                used_prepared = True
                logging.info("Retrying %s via prepared statement (large-param escaping)", file_id)
                continue
            raise


# --------------------------------------------------------------------------
# Run loop
# --------------------------------------------------------------------------

def count_pending(cur):
    cur.execute(
        f"SELECT COUNT(*) FROM {f.TABLE_FILES} "
        "WHERE not_spec_filter = 0 AND commit_history_status IS NULL")
    return cur.fetchone()[0]


def process_one(rotator, file_id, repo, path):
    """Fetch + persist one file on this thread's own connection. Always leaves a
    terminal status (done/empty/truncated/error) so a bad row can never be
    re-selected forever. Returns commit count written."""
    try:
        commits, status = fetch_path_commits(rotator, repo, path)
        return persist(_conn(), file_id, repo, path, commits, status)
    except Exception as e:  # noqa: BLE001 - never let one file kill the run
        logging.warning("Error on %s/%s: %s -> marking error", repo, path, e)
        try:
            conn = _conn()
            cur = conn.cursor()
            cur.execute(
                f"UPDATE {f.TABLE_FILES} SET commit_history_status='error', "
                "commit_history_fetched_at=%s WHERE file_url_sha16=%s",
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), file_id))
            conn.commit(); cur.close()
        except Exception as e2:  # noqa: BLE001
            logging.warning("Also failed to mark error for %s: %s", file_id, e2)
        return 0


def run(conn, rotator, limit=None, workers=DEFAULT_WORKERS):
    cur = conn.cursor()
    total_pending = count_pending(cur)
    cur.execute(
        f"SELECT COUNT(*) FROM {f.TABLE_FILES} "
        "WHERE not_spec_filter = 0 AND commit_history_status IS NOT NULL")
    already = cur.fetchone()[0]
    cur.close()

    goal = total_pending if limit is None else min(limit, total_pending)
    logging.info("Kept files needing history: %s (already done: %s). Target this run: %s (workers=%d)",
                 f"{total_pending:,}", f"{already:,}", f"{goal:,}", workers)

    processed = commits_written = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while processed < goal:
            take = min(BATCH, goal - processed)
            cur = conn.cursor()
            cur.execute(
                f"SELECT file_url_sha16, repo_name, file_path FROM {f.TABLE_FILES} "
                "WHERE not_spec_filter = 0 AND commit_history_status IS NULL "
                f"LIMIT {take}")
            batch = cur.fetchall()
            cur.close()
            if not batch:
                break

            # Submit the whole batch and drain it before selecting the next one,
            # so no in-flight row is ever re-selected.
            futures = [pool.submit(process_one, rotator, fid, repo, path)
                       for fid, repo, path in batch]
            for fut in as_completed(futures):
                commits_written += fut.result()
                processed += 1
                if processed % PROGRESS_EVERY == 0 or processed == goal:
                    el = time.time() - t0
                    rate = processed / el if el else 0
                    eta_min = ((goal - processed) / rate / 60) if rate else 0
                    pct = 100 * processed / goal if goal else 100
                    logging.info(
                        "  %s/%s files (%.1f%%) | %s commits | %.1f files/s | ETA %.0f min",
                        f"{processed:,}", f"{goal:,}", pct, f"{commits_written:,}", rate, eta_min)

    el = time.time() - t0
    logging.info("DONE this run: %s files, %s commits, %.0f min.",
                 f"{processed:,}", f"{commits_written:,}", el / 60)


def print_status(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {f.TABLE_FILES} WHERE not_spec_filter = 0")
    kept = cur.fetchone()[0]
    cur.execute(
        f"SELECT COALESCE(commit_history_status,'(pending)'), COUNT(*) "
        f"FROM {f.TABLE_FILES} WHERE not_spec_filter = 0 "
        "GROUP BY commit_history_status ORDER BY 2 DESC")
    rows = cur.fetchall()
    cur.execute(f"SELECT COUNT(*), COALESCE(SUM(file_total_commits),0) FROM {f.TABLE_FILES} "
                "WHERE commit_history_status IS NOT NULL AND not_spec_filter = 0")
    fdone, fcommits = cur.fetchone()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {COMMITS_TABLE}")
        crows = cur.fetchone()[0]
    except Exception:
        crows = 0
    cur.close()

    print("\n=== commit-history status (kept files, not_spec_filter=0) ===")
    print(f"  kept files            : {kept:,}")
    for st, n in rows:
        print(f"    {st:<12} {n:>10,}  ({100*n/kept:.1f}%)")
    print(f"  files with history    : {fdone:,}")
    print(f"  total commits recorded: {int(fcommits):,} (in file cols) / {crows:,} (rows in {COMMITS_TABLE})")


def main():
    ap = argparse.ArgumentParser(description="Fetch commit history for kept spec files.")
    ap.add_argument("--status", action="store_true", help="Show progress, no API calls.")
    ap.add_argument("--schema-only", action="store_true", help="Create columns/table then exit.")
    ap.add_argument("--limit", type=int, default=None, help="Process only N files (smoke test).")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help=f"Concurrent workers (default {DEFAULT_WORKERS}; ~26 req/s ceiling self-throttles).")
    ap.add_argument("--reset-file", metavar="SHA16", help="Re-queue one file (clear its status).")
    args = ap.parse_args()

    conn = f.get_db_connection(DB_NAME)
    # This connection only READS batches of pending work; autocommit so each
    # SELECT sees rows the worker connections have committed (otherwise a
    # long-lived REPEATABLE-READ snapshot hides finished rows from the producer).
    conn.autocommit = True
    ensure_schema(conn)

    if args.schema_only:
        print("Schema ready.")
        conn.close()
        return
    if args.reset_file:
        cur = conn.cursor()
        cur.execute(f"UPDATE {f.TABLE_FILES} SET commit_history_status=NULL WHERE file_url_sha16=%s",
                    (args.reset_file,))
        cur.execute(f"DELETE FROM {COMMITS_TABLE} WHERE file_url_sha16=%s", (args.reset_file,))
        conn.commit(); cur.close()
        print(f"Re-queued {args.reset_file}.")
        conn.close()
        return
    if args.status:
        print_status(conn)
        conn.close()
        return

    tokens = f.get_github_tokens()
    rotator = LockedRotator(tokens)
    logging.info("Using %d token(s), %d workers.", rotator.n, args.workers)
    run(conn, rotator, limit=args.limit, workers=args.workers)
    print_status(conn)
    conn.close()


if __name__ == "__main__":
    main()
