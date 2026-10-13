#!/usr/bin/env python3
"""
Phase B of traceability — one recursive git-tree call per repo to discover, for
every spec in that repo, its SIBLING artifacts (tasks/plan/proposal/design/…) and
the code files adjacent to it. Writes edges into spec_links (provenance='tree').

  GET /repos/{owner}/{repo}/git/trees/{ref}?recursive=1   (ref = default branch)

One call returns the repo's whole path list, so all specs in a repo are resolved
together — ~73k repos over the 19-token pool (~95k/hr) ≈ under an hour. Resumable
via a repo_trees table (one row per repo, status done/missing/truncated/error).

Usage:
  python3 fetch_repo_trees.py                 # run (resumable)
  python3 fetch_repo_trees.py --status
  python3 fetch_repo_trees.py --schema-only
  python3 fetch_repo_trees.py --limit 200     # smoke test
  python3 fetch_repo_trees.py --workers 12
"""
import argparse
import logging
import os
import posixpath
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_NAME = "specdriven"
KEEP = "not_spec_filter = 0"
LINKS = "spec_links"
BATCH = 300               # repos per work batch
DEFAULT_WORKERS = 10
TIMEOUT = 30
MAX_TRIES = 6
MAX_CODE_PER_SPEC = 40    # cap code edges per spec to avoid row explosion

SIBLINGS = ("tasks.md", "plan.md", "proposal.md", "design.md",
            "data-model.md", "research.md", "spec-lite.md", "quickstart.md")
CODE_EXT = {"py", "ts", "tsx", "js", "jsx", "go", "rs", "java", "rb", "cpp", "cc",
            "c", "h", "hpp", "cs", "php", "swift", "kt", "scala", "sql", "sh",
            "vue", "svelte", "dart", "ex", "exs", "clj", "m", "mm"}

_SESSION = requests.Session()
_SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=64))


class LockedRotator:
    def __init__(self, tokens):
        self._t = tokens; self.n = len(tokens); self._i = 0; self._lock = threading.Lock()
    def next_token(self):
        with self._lock:
            t = self._t[self._i]; self._i = (self._i + 1) % self.n; return t


def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS repo_trees (
        repo_name VARCHAR(511) NOT NULL PRIMARY KEY,
        status VARCHAR(16) NOT NULL,
        n_entries INT NULL,
        truncated TINYINT NULL,
        fetched_at VARCHAR(32) NULL
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    conn.commit(); cur.close()


def unit_folder(path):
    """The folder that holds a spec's sibling artifacts (proposal/tasks/design).
    OpenSpec change/archive nest the delta spec under a `.../specs/<cap>/` subdir of
    the change folder, so strip from the last `/specs/`:
      openspec/changes/add-auth/specs/auth/spec.md          -> openspec/changes/add-auth
      openspec/changes/archive/2026-01-x/specs/cap/spec.md  -> openspec/changes/archive/2026-01-x
    Living specs (openspec/specs/<cap>/spec.md) have no `/changes/`, so they keep
    their own directory. Everything else: the spec's own directory."""
    d = posixpath.dirname(path)
    if "/changes/" in path and "/specs/" in d:
        return d.rsplit("/specs/", 1)[0]
    return d


def classify_tree(specs, tree_paths):
    """specs: list of (spec_sha, spec_path). tree_paths: iterable of repo file paths.
    Yields (spec_sha, rel, target) edges:
      * sibling: a known doc (tasks/plan/proposal/design/…) anywhere in the spec's
                 unit-folder subtree (the change/feature folder).
      * code   : a code file that is a DIRECT child of the unit folder (adjacent
                 code — e.g. caffeine's app source, Spec Kit contracts/) — capped,
                 to avoid dumping every deep unrelated source file.
    """
    from collections import defaultdict
    by_dir = defaultdict(list)          # dir -> [(basename, fullpath)]
    sibling_paths = []                  # (dir, fullpath) for known sibling docs
    for tp in tree_paths:
        d = posixpath.dirname(tp)
        base = posixpath.basename(tp)
        by_dir[d].append((base, tp))
        if base.lower() in SIBLINGS:
            sibling_paths.append((d, tp))
    for sha, spath in specs:
        unit = unit_folder(spath)
        pref = unit + "/"
        for d, tp in sibling_paths:            # small list -> cheap
            if tp == spath:
                continue
            if d == unit or (unit and d.startswith(pref)):
                yield sha, "sibling", tp
            elif not unit and d == "":         # root spec: root-level siblings only
                yield sha, "sibling", tp
        n = 0
        for base, tp in by_dir.get(unit, []):  # direct children of the unit folder
            if tp == spath:
                continue
            ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
            if ext in CODE_EXT and n < MAX_CODE_PER_SPEC:
                yield sha, "code", tp
                n += 1


def fetch_tree(repo_name, ref, rotator):
    url = f"https://api.github.com/repos/{repo_name}/git/trees/{ref}?recursive=1"
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
            paths = [e["path"] for e in j.get("tree", []) if e.get("type") == "blob"]
            return paths, bool(j.get("truncated")), "done"
        if sc in (404, 409, 451):  # gone / empty repo / unavailable
            return None, False, "missing"
        if sc in (403, 429):
            if r.headers.get("X-RateLimit-Remaining") == "0" and attempt >= rotator.n:
                reset = int(r.headers.get("X-RateLimit-Reset", "0") or 0)
                time.sleep(min(max(0.0, reset - time.time()) + 1.0, 60))
            else:
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    time.sleep(min(float(ra), 60))
            continue
        return None, False, "error"
    return None, False, "error"


def process_repo(repo_name, rotator):
    """Fetch one repo's tree and return (status, n_entries, truncated, edges)."""
    cur = _conn().cursor()   # thread-local conn; do NOT close it (reused by worker)
    cur.execute(f"SELECT file_url_sha16, file_path, repo_default_branch, file_last_commit_sha "
                f"FROM spec_files WHERE {KEEP} AND repo_name = %s", (repo_name,))
    rows = cur.fetchall(); cur.close()
    if not rows:
        return "missing", 0, 0, []
    ref = rows[0][2] or rows[0][3] or "HEAD"
    paths, truncated, status = fetch_tree(repo_name, ref, rotator)
    if status != "done":
        # one fallback: try a commit SHA if the default-branch ref failed
        if rows[0][3] and ref != rows[0][3]:
            paths, truncated, status = fetch_tree(repo_name, rows[0][3], rotator)
        if status != "done":
            return status, 0, 0, []
    tset = set(paths)
    specs = [(r[0], r[1]) for r in rows]
    edges = list(classify_tree(specs, tset))
    return "truncated" if truncated else "done", len(paths), int(truncated), edges


_local = threading.local()
def _conn():
    if not getattr(_local, "conn", None):
        _local.conn = f.get_db_connection(DB_NAME)
    return _local.conn


def worker(repo_name, rotator):
    try:
        status, n, trunc, edges = process_repo(repo_name, rotator)
    except Exception as e:
        logging.warning("repo %s error: %s", repo_name, e)
        status, n, trunc, edges = "error", 0, 0, []
    conn = _conn(); cur = conn.cursor()
    if edges:
        cur.executemany(
            f"INSERT IGNORE INTO {LINKS} (spec_url_sha16, rel, target, provenance) VALUES (%s,%s,%s,'tree')",
            [(s, rel, t[:500]) for s, rel, t in edges])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("REPLACE INTO repo_trees (repo_name, status, n_entries, truncated, fetched_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (repo_name, status, n, trunc, now))
    conn.commit(); cur.close()
    return status, len(edges)


def run(workers, limit):
    rotator = LockedRotator(f.get_github_tokens())
    logging.info("Phase B: %d tokens, %d workers", rotator.n, workers)
    reader = f.get_db_connection(DB_NAME); reader.autocommit = True
    rcur = reader.cursor()
    done = 0; total_edges = 0
    counts = {"done": 0, "truncated": 0, "missing": 0, "error": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            take = BATCH if limit is None else min(BATCH, limit - done)
            if take <= 0:
                break
            rcur.execute(f"""SELECT DISTINCT s.repo_name FROM spec_files s
                LEFT JOIN repo_trees t ON t.repo_name = s.repo_name
                WHERE s.{KEEP} AND s.repo_name IS NOT NULL AND t.repo_name IS NULL
                LIMIT {take}""")
            repos = [r[0] for r in rcur.fetchall()]
            if not repos:
                break
            for status, ne in pool.map(lambda rn: worker(rn, rotator), repos):
                counts[status] = counts.get(status, 0) + 1
                total_edges += ne; done += 1
                if done % 1000 == 0:
                    logging.info("repos=%s edges=%s %s", f"{done:,}", f"{total_edges:,}", counts)
    rcur.close(); reader.close()
    logging.info("FINISHED. repos=%s edges=%s %s", f"{done:,}", f"{total_edges:,}", counts)


def print_status(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(DISTINCT repo_name) FROM spec_files WHERE {KEEP}")
    total = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(status,'(pending)'), COUNT(*) FROM repo_trees GROUP BY status")
    seen = dict(cur.fetchall())
    done = sum(seen.values())
    print(f"\n=== repo_trees: {done:,}/{total:,} repos processed ({100*done/total:.1f}%) ===")
    for s, n in sorted(seen.items(), key=lambda x: -x[1]):
        print(f"  {s:<12} {n:,}")
    cur.execute(f"SELECT COUNT(*) FROM {LINKS} WHERE provenance='tree'")
    print(f"  tree edges in spec_links: {cur.fetchone()[0]:,}")
    cur.close()


def main():
    ap = argparse.ArgumentParser(description="Phase B: per-repo git-tree fetch -> spec_links siblings/code.")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--schema-only", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = ap.parse_args()
    conn = f.get_db_connection(DB_NAME)
    ensure_schema(conn)
    if args.schema_only:
        print("repo_trees ready."); conn.close(); return
    if args.status:
        print_status(conn); conn.close(); return
    conn.close()
    run(args.workers, args.limit)
    conn = f.get_db_connection(DB_NAME); print_status(conn); conn.close()


if __name__ == "__main__":
    main()
