#!/usr/bin/env python3
"""
Capture the ENTIRE openspec/ folder for the curated OpenSpec core repos
(licensed + >=10 stars), pinned to each repo's current HEAD commit so it is
reproducible. Two tables:

  openspec_repos
    repo_name (PK), owner_login, repo_stars, repo_license_spdx_id,
    default_branch, commit_sha (pinned HEAD), n_files, n_bytes,
    tree_json (JSON [{path,size}] of every openspec/ file = the tree),
    status, fetched_at

  openspec_files   (one row per file under openspec/)
    repo_name, commit_sha, file_path, kind (spec/proposal/design/tasks/plan/
    config/doc/…), role (living/change/archived/root), change_name, capability,
    n_bytes, content, content_sha, fetch_status

Stages:
  --seed     materialize the 524-repo set into openspec_repos (no fetch)
  --trees    per repo: resolve HEAD sha, fetch recursive tree, record the
             openspec/ file list (tree_json) + enumerate openspec_files rows
  (default)  fetch content for enumerated files
  --status

All fetches go through the token pool (Contents API, Accept: raw) with the
rate-limit-reset wait (MAX_TRIES > token count) so throttling self-heals.
"""
import argparse
import os
import hashlib
import json
import logging
import posixpath
import re
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DB = "specdriven"
REPOS = "openspec_repos"
FILES = "openspec_files"
TIMEOUT = 30
MAX_TRIES = 30           # > token count so the reset-wait branch fires
MAX_BYTES = 1_000_000
WORKERS_TREES = 10
WORKERS_FILES = 12
FILE_BATCH = 4000

_SESSION = requests.Session()
_SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=64))


class LockedRotator:
    def __init__(self, t): self._t=t; self.n=len(t); self._i=0; self._lock=threading.Lock()
    def next_token(self):
        with self._lock:
            t=self._t[self._i]; self._i=(self._i+1)%self.n; return t

_local = threading.local()
def _conn():
    if not getattr(_local, "conn", None):
        _local.conn = f.get_db_connection(DB)
    return _local.conn


# ---- path -> structure ------------------------------------------------------
def classify(path):
    """Return (kind, role, change_name, capability) for an openspec/ path."""
    base = posixpath.basename(path).lower()
    kind = {"spec.md": "spec", "proposal.md": "proposal", "design.md": "design",
            "tasks.md": "tasks", "plan.md": "plan", "readme.md": "doc",
            "agents.md": "doc", "claude.md": "doc"}.get(base)
    if kind is None:
        if base.endswith((".yaml", ".yml")): kind = "config"
        elif base.endswith(".json"): kind = "json"
        elif base.endswith(".jsonl"): kind = "jsonl"
        elif base.endswith(".md"): kind = "md-other"
        else: kind = "other"
    role, change_name, capability = "root", None, None
    m = re.match(r"openspec/changes/archive/([^/]+)/", path)
    if m: role, change_name = "archived", m.group(1)
    else:
        m = re.match(r"openspec/changes/([^/]+)/", path)
        if m: role, change_name = "change", m.group(1)
        elif path.startswith("openspec/specs/"): role = "living"
    cm = re.search(r"/specs/([^/]+)/", path)
    if cm: capability = cm.group(1)
    return kind, role, change_name, capability


# ---- HTTP -------------------------------------------------------------------
def _get(url, rotator, accept="application/vnd.github+json"):
    for attempt in range(MAX_TRIES):
        token = rotator.next_token()
        try:
            r = _SESSION.get(url, headers={"Authorization": f"Bearer {token}",
                             "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 20)); continue
        sc = r.status_code
        if sc == 200:
            return r, "ok"
        if sc in (404, 409, 410, 422, 451):
            return r, "missing"
        if sc == 403 and "too_large" in r.text.lower():
            return r, "toobig"
        if sc in (403, 429):
            if r.headers.get("X-RateLimit-Remaining") == "0" and attempt >= rotator.n:
                reset = int(r.headers.get("X-RateLimit-Reset", "0") or 0)
                time.sleep(min(max(0.0, reset - time.time()) + 1.0, 60))
            else:
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit(): time.sleep(min(float(ra), 60))
            continue
        return r, "error"
    return None, "throttled"


# ---- schema -----------------------------------------------------------------
def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {REPOS} (
        repo_name VARCHAR(511) NOT NULL PRIMARY KEY,
        owner_login VARCHAR(255), repo_stars INT, repo_license_spdx_id VARCHAR(128),
        default_branch VARCHAR(255), commit_sha CHAR(40),
        n_files INT, n_bytes BIGINT, tree_json LONGTEXT,
        status VARCHAR(16), fetched_at VARCHAR(32)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {FILES} (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        repo_name VARCHAR(511) NOT NULL, commit_sha CHAR(40),
        file_path VARCHAR(1000) NOT NULL, kind VARCHAR(24), role VARCHAR(16),
        change_name VARCHAR(400), capability VARCHAR(400),
        n_bytes INT, content LONGTEXT, content_sha CHAR(64), fetch_status VARCHAR(16),
        UNIQUE KEY uq (repo_name(120), file_path(300)),
        KEY idx_repo (repo_name(120)), KEY idx_role (role), KEY idx_kind (kind)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    conn.commit(); cur.close()


def seed(conn):
    cur = conn.cursor()
    cur.execute(f"""INSERT IGNORE INTO {REPOS}
        (repo_name, owner_login, repo_stars, repo_license_spdx_id, default_branch, status)
        SELECT repo_name, MAX(owner_login), MAX(repo_stars), MAX(repo_license_spdx_id),
               MAX(repo_default_branch), NULL
        FROM spec_files WHERE not_spec_filter=0 AND spec_tool='openspec'
        GROUP BY repo_name
        HAVING MAX(repo_license_spdx_id) IS NOT NULL AND MAX(repo_stars) >= 10""")
    conn.commit()
    cur.execute(f"SELECT COUNT(*) FROM {REPOS}")
    print(f"seeded {cur.fetchone()[0]:,} repos.")
    cur.close()


# ---- trees pass -------------------------------------------------------------
def process_tree(repo, branch, rotator):
    # resolve HEAD commit sha
    r, st = _get(f"https://api.github.com/repos/{repo}/commits/{urllib.parse.quote(branch or 'HEAD')}", rotator)
    if st != "ok":
        return st, None, []
    sha = r.json().get("sha")
    r, st = _get(f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1", rotator)
    if st != "ok":
        return st, sha, []
    j = r.json()
    osf = [(e["path"], e.get("size", 0)) for e in j.get("tree", [])
           if e.get("type") == "blob" and e["path"].startswith("openspec/")]
    return ("truncated" if j.get("truncated") else "done"), sha, osf


def run_trees(rotator, workers, limit):
    reader = f.get_db_connection(DB); reader.autocommit = True
    rcur = reader.cursor()
    rcur.execute(f"SELECT repo_name, default_branch FROM {REPOS} WHERE status IS NULL"
                 + (f" LIMIT {limit}" if limit else ""))
    repos = rcur.fetchall()
    rcur.close(); reader.close()
    logging.info("trees: %d repos", len(repos))
    done = 0
    def work(rb):
        repo, br = rb
        try:
            status, sha, osf = process_tree(repo, br, rotator)
        except Exception as e:
            logging.warning("%s tree error %s", repo, e); status, sha, osf = "error", None, []
        conn = _conn(); cur = conn.cursor()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nb = sum(s for _, s in osf)
        tree_json = json.dumps([{"path": p, "size": s} for p, s in osf])
        cur.execute(f"UPDATE {REPOS} SET commit_sha=%s,n_files=%s,n_bytes=%s,tree_json=%s,status=%s,fetched_at=%s WHERE repo_name=%s",
                    (sha, len(osf), nb, tree_json, status, now, repo))
        if osf and sha:
            rows = []
            for p, s in osf:
                kind, role, chg, cap = classify(p)
                rows.append((repo, sha, p[:1000], kind, role,
                             (chg or None) and chg[:400], (cap or None) and cap[:400], s))
            cur.executemany(
                f"INSERT IGNORE INTO {FILES} (repo_name,commit_sha,file_path,kind,role,change_name,capability,n_bytes) "
                f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        conn.commit(); cur.close()
        return status, len(osf)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for status, n in pool.map(work, repos):
            done += 1
            if done % 50 == 0:
                logging.info("trees %d/%d", done, len(repos))
    logging.info("trees done: %d repos", done)


# ---- content pass -----------------------------------------------------------
_UPD = (f"UPDATE {FILES} SET content=%s, content_sha=%s, n_bytes=%s, fetch_status=%s WHERE id=%s")

def fetch_file(repo, sha, path, rotator):
    p = "/".join(urllib.parse.quote(seg) for seg in path.split("/"))
    r, st = _get(f"https://api.github.com/repos/{repo}/contents/{p}?ref={sha}", rotator,
                 accept="application/vnd.github.raw")
    if st != "ok":
        return None, None, None, st
    data = r.content or b""
    status = "done"
    if len(data) > MAX_BYTES:
        data, status = data[:MAX_BYTES], "toobig"
    text = data.decode("utf-8", "replace")
    return text, hashlib.sha256(data).hexdigest(), len(data), status


def run_content(rotator, workers, limit):
    reader = f.get_db_connection(DB); reader.autocommit = True
    rcur = reader.cursor()
    done = 0; counts = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            take = FILE_BATCH if limit is None else min(FILE_BATCH, limit - done)
            if take <= 0: break
            rcur.execute(f"SELECT id, repo_name, commit_sha, file_path FROM {FILES} "
                         f"WHERE fetch_status IS NULL AND commit_sha IS NOT NULL LIMIT {take}")
            rows = rcur.fetchall()
            if not rows: break
            def work(row):
                fid, repo, sha, path = row
                try:
                    text, csha, nb, st = fetch_file(repo, sha, path, rotator)
                except Exception:
                    text, csha, nb, st = None, None, None, "error"
                conn = _conn(); cur = conn.cursor(prepared=True)
                cur.execute(_UPD, (text, csha, nb, st, fid))
                conn.commit(); cur.close()
                return st
            for st in pool.map(work, rows):
                counts[st] = counts.get(st, 0) + 1; done += 1
                if done % 5000 == 0:
                    logging.info("content %s  %s", f"{done:,}", counts)
    rcur.close(); reader.close()
    logging.info("content done: %s  %s", f"{done:,}", counts)


def status(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*), SUM(status='done'), SUM(status IS NULL), SUM(n_files), SUM(n_bytes) FROM {REPOS}")
    n, d, pend, nf, nb = cur.fetchone()
    print(f"\n=== {REPOS}: {n} repos ({int(d or 0)} tree-done, {int(pend or 0)} pending) ===")
    print(f"  total openspec/ files: {int(nf or 0):,}   bytes: {int(nb or 0):,}")
    cur.execute(f"SELECT COALESCE(fetch_status,'(pending)'), COUNT(*) FROM {FILES} GROUP BY 1 ORDER BY 2 DESC")
    print(f"  {FILES} content status:")
    for s, c in cur.fetchall(): print(f"    {s:<12} {c:,}")
    cur.execute(f"SELECT role, COUNT(*) FROM {FILES} GROUP BY role ORDER BY 2 DESC")
    print("  files by role:", dict(cur.fetchall()))
    cur.execute(f"SELECT kind, COUNT(*) FROM {FILES} GROUP BY kind ORDER BY 2 DESC")
    print("  files by kind:", dict(cur.fetchall()))
    cur.close()


def main():
    ap = argparse.ArgumentParser(description="Capture full openspec/ folder for the core repos.")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--trees", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    conn = f.get_db_connection(DB)
    ensure_schema(conn)
    if args.seed:
        seed(conn); status(conn); conn.close(); return
    if args.status:
        status(conn); conn.close(); return
    conn.close()
    rotator = LockedRotator(f.get_github_tokens())
    if args.trees:
        run_trees(rotator, args.workers or WORKERS_TREES, args.limit)
    else:
        run_content(rotator, args.workers or WORKERS_FILES, args.limit)
    conn = f.get_db_connection(DB); status(conn); conn.close()


if __name__ == "__main__":
    main()
