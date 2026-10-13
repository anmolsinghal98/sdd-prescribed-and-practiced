#!/usr/bin/env python3
"""
Version-pin the tasks.md->code links: attach an ANCHOR commit SHA (so every
declared code path resolves to a specific, immutable file version) and validate
that the path actually EXISTS in the repo at that commit.

Adds to openspec_code_refs:
  anchor_sha        CHAR(40)   -- the change's completion commit (the archived
                                  spec.md's file_last_commit_sha). Resolve code at
                                  raw.githubusercontent.com/<repo>/<anchor_sha>/<path>
  exists_at_anchor  TINYINT    -- 1 = path present at anchor, 0 = absent
                                  (declared-but-not-built / renamed), NULL = unchecked
  resolved_path     VARCHAR    -- full repo path when the declared token was a bare
                                  filename (e.g. CachedReport.swift) resolved uniquely

  --anchors   populate anchor_sha only (free, no fetch)
  (default)   populate anchors, then fetch the tree at each distinct (repo, anchor_sha)
              and set exists_at_anchor / resolved_path  (resumable)
  --status
"""
import argparse
import os
import logging
import posixpath
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DB_NAME = "specdriven"
CODEREFS = "openspec_code_refs"
BATCH = 400
DEFAULT_WORKERS = 12
TIMEOUT = 30
MAX_TRIES = 25       # must exceed the token count so the reset-wait branch fires

_SESSION = requests.Session()
_SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=64))


class LockedRotator:
    def __init__(self, tokens):
        self._t = tokens; self.n = len(tokens); self._i = 0; self._lock = threading.Lock()
    def next_token(self):
        with self._lock:
            t = self._t[self._i]; self._i = (self._i + 1) % self.n; return t


_local = threading.local()
def _conn():
    if not getattr(_local, "conn", None):
        _local.conn = f.get_db_connection(DB_NAME)
    return _local.conn


def ensure_columns(conn):
    cur = conn.cursor()
    cur.execute(f"""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='{CODEREFS}'""")
    have = {r[0] for r in cur.fetchall()}
    for name, decl in (("anchor_sha", "CHAR(40) NULL"),
                       ("exists_at_anchor", "TINYINT NULL"),
                       ("resolved_path", "VARCHAR(700) NULL")):
        if name not in have:
            cur.execute(f"ALTER TABLE {CODEREFS} ADD COLUMN {name} {decl}")
    if "idx_anchor" not in have:
        try:
            cur.execute(f"ALTER TABLE {CODEREFS} ADD KEY idx_anchor (repo_name(120), anchor_sha)")
        except Exception:
            pass
    conn.commit(); cur.close()


def populate_anchors(conn):
    """anchor = the file_last_commit_sha of the change's specs (they share the
    archive/last commit). Map each tasks.md artifact_path to its change's specs."""
    cur = conn.cursor()
    cur.execute(f"""
      UPDATE {CODEREFS} acr
      JOIN (
        SELECT s.repo_name,
               CONCAT(SUBSTRING_INDEX(s.file_path,'/specs/',1),'/tasks.md') tpath,
               MAX(s.file_last_commit_sha) sha
        FROM spec_files s
        WHERE s.not_spec_filter=0 AND s.spec_tool='openspec'
              AND s.file_path LIKE 'openspec/changes/%/specs/%'
        GROUP BY s.repo_name, tpath
      ) m ON m.repo_name = acr.repo_name AND m.tpath = acr.artifact_path
      SET acr.anchor_sha = m.sha
      WHERE acr.anchor_sha IS NULL""")
    conn.commit()
    print(f"anchors: set on {cur.rowcount:,} code-ref rows.")
    cur.close()


def fetch_tree(repo, sha, rotator):
    url = f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1"
    for attempt in range(MAX_TRIES):
        token = rotator.next_token()
        try:
            r = _SESSION.get(url, headers={"Authorization": f"Bearer {token}",
                             "Accept": "application/vnd.github+json",
                             "X-GitHub-Api-Version": "2022-11-28"}, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 20)); continue
        sc = r.status_code
        if sc == 200:
            j = r.json()
            return [e["path"] for e in j.get("tree", []) if e.get("type") == "blob"], "ok"
        if sc in (404, 409, 422, 451):
            return None, "missing"
        if sc in (403, 429):
            if r.headers.get("X-RateLimit-Remaining") == "0" and attempt >= rotator.n:
                reset = int(r.headers.get("X-RateLimit-Reset", "0") or 0)
                time.sleep(min(max(0.0, reset - time.time()) + 1.0, 60))
            else:
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    time.sleep(min(float(ra), 60))
            continue
        return None, "error"
    return None, "throttled"


def resolve_group(repo, sha, rotator):
    """Fetch tree at (repo, sha); resolve every unchecked code ref for it."""
    conn = _conn(); cur = conn.cursor()
    cur.execute(f"SELECT id, code_path FROM {CODEREFS} "
                f"WHERE repo_name=%s AND anchor_sha=%s AND exists_at_anchor IS NULL", (repo, sha))
    refs = cur.fetchall(); cur.close()
    if not refs:
        return "empty", 0
    paths, status = fetch_tree(repo, sha, rotator)
    if status == "missing":
        # commit/tree genuinely gone -> can't verify; mark 2 (unverifiable), terminal.
        cur = conn.cursor()
        cur.execute(f"UPDATE {CODEREFS} SET exists_at_anchor=2 "
                    f"WHERE repo_name=%s AND anchor_sha=%s AND exists_at_anchor IS NULL", (repo, sha))
        conn.commit(); cur.close()
        return status, 0
    if status != "ok":
        return status, 0   # transient (error/throttled): leave NULL, retry next pass
    pathset = set(paths)
    bybase = defaultdict(list)
    for p in paths:
        bybase[posixpath.basename(p)].append(p)
    updates = []
    for rid, cp in refs:
        if cp in pathset:
            updates.append((1, cp, rid))
        else:
            hits = bybase.get(posixpath.basename(cp), [])
            if len(hits) == 1:
                updates.append((1, hits[0], rid))   # resolved a bare name uniquely
            elif len(hits) > 1:
                updates.append((1, None, rid))       # exists but ambiguous
            else:
                updates.append((0, None, rid))       # not present at anchor
    cur = conn.cursor()
    cur.executemany(f"UPDATE {CODEREFS} SET exists_at_anchor=%s, resolved_path=%s WHERE id=%s", updates)
    conn.commit(); cur.close()
    return "ok", len(updates)


def run(workers, limit):
    rotator = LockedRotator(f.get_github_tokens())
    reader = f.get_db_connection(DB_NAME); reader.autocommit = True
    rcur = reader.cursor()
    done = 0; resolved = 0
    counts = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            take = BATCH if limit is None else min(BATCH, limit - done)
            if take <= 0:
                break
            rcur.execute(f"""SELECT repo_name, anchor_sha FROM {CODEREFS}
                WHERE anchor_sha IS NOT NULL AND exists_at_anchor IS NULL
                GROUP BY repo_name, anchor_sha LIMIT {take}""")
            groups = rcur.fetchall()
            if not groups:
                break
            for status, n in pool.map(lambda g: resolve_group(g[0], g[1], rotator), groups):
                counts[status] = counts.get(status, 0) + 1
                resolved += n; done += 1
                if done % 2000 == 0:
                    logging.info("groups=%s resolved-refs=%s %s", f"{done:,}", f"{resolved:,}", counts)
    rcur.close(); reader.close()
    logging.info("FINISHED groups=%s resolved-refs=%s %s", f"{done:,}", f"{resolved:,}", counts)


def status(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*), SUM(anchor_sha IS NOT NULL), SUM(exists_at_anchor=1), "
                f"SUM(exists_at_anchor=0), SUM(exists_at_anchor=2), SUM(exists_at_anchor IS NULL) FROM {CODEREFS}")
    tot, anc, ex1, ex0, ex2, exn = cur.fetchone()
    print(f"\n=== code-ref resolution ===")
    print(f"  total code refs      : {tot:,}")
    print(f"  with anchor_sha      : {int(anc or 0):,}")
    print(f"  exists at anchor (1) : {int(ex1 or 0):,}")
    print(f"  absent at anchor (0) : {int(ex0 or 0):,}")
    print(f"  unverifiable (2)     : {int(ex2 or 0):,}  (commit/tree gone)")
    print(f"  unchecked (NULL)     : {int(exn or 0):,}")
    if ex1 and (ex1 + ex0):
        print(f"  => declared-path existence rate: {100*ex1/(ex1+ex0):.1f}%")
    cur.close()


def main():
    ap = argparse.ArgumentParser(description="Version-pin + validate tasks.md->code links.")
    ap.add_argument("--anchors", action="store_true", help="populate anchor_sha only")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = ap.parse_args()
    conn = f.get_db_connection(DB_NAME)
    ensure_columns(conn)
    if args.status:
        status(conn); conn.close(); return
    populate_anchors(conn)
    if args.anchors:
        status(conn); conn.close(); return
    conn.close()
    run(args.workers, args.limit)
    conn = f.get_db_connection(DB_NAME); status(conn); conn.close()


if __name__ == "__main__":
    main()
