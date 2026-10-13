#!/usr/bin/env python3
"""
OpenSpec enrichment (steps 1-2 of spec->code): fetch the sibling artifacts of
every OpenSpec change (proposal.md / design.md / tasks.md / …) and parse tasks.md
into DECLARED code links.

Why: OpenSpec keeps code OUTSIDE the openspec/ folder, so a spec's own history
doesn't reach the code. The change's tasks.md is OpenSpec's built-in spec->code
map — it names the files each task touches (e.g. `src/foo.py`) with a done/pending
checkbox. So the enriched unit is the CHANGE: {proposal, design, tasks} + the code
tasks.md declares.

Writes:
  spec_artifact_files(repo_name, file_path, kind, content, content_sha, n_bytes,
                      n_tasks, n_tasks_done, n_code_refs, fetch_status, fetched_at)
  artifact_code_refs (repo_name, artifact_path, code_path, task_done)
  -> then --link folds tasks-declared code into spec_links(rel='code',
     provenance='tasks') for every spec in the change.

Fetched via the authenticated Contents API (Accept: raw) over the token pool.

Usage:
  python3 fetch_openspec_artifacts.py --schema
  python3 fetch_openspec_artifacts.py                 # fetch (resumable)
  python3 fetch_openspec_artifacts.py --limit 300     # smoke test
  python3 fetch_openspec_artifacts.py --link          # emit spec_links code edges
  python3 fetch_openspec_artifacts.py --status
"""
import argparse
import os
import hashlib
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

DB_NAME = "specdriven"
ARTIFACTS = "openspec_artifact_files"
CODEREFS = "openspec_code_refs"
BATCH = 3000
DEFAULT_WORKERS = 12
TIMEOUT = 25
API_MAX_TRIES = 30       # must exceed the token count so the reset-wait branch fires
MAX_BYTES = 1_000_000
MAX_CODE_REFS = 60

CODE_EXT_SET = {"py", "ts", "tsx", "js", "jsx", "go", "rs", "java", "rb", "cpp", "cc",
                "c", "h", "hpp", "cs", "php", "swift", "kt", "scala", "sql", "sh",
                "vue", "svelte", "dart", "ex", "exs", "clj", "m", "mm", "scss", "css",
                "html", "rb", "pl", "lua", "r"}
RE_CHECKBOX = re.compile(r'^\s*[-*+]\s*\[([ xX])\]\s*(.*)$')
# Extract candidate path tokens: backtick-wrapped, or a bare path-looking token.
# We take the WHOLE token then filter by its exact extension (so `foo.csv`/`CLAUDE.md`
# aren't mistaken for `.c`/`.m`).
RE_PATHTOK = re.compile(r'`([^`\n]+?)`|(?<![\w/.])([A-Za-z0-9_][\w./\-]*\.[A-Za-z0-9]{1,6})')


def _code_paths(text):
    """Yield code-file paths from a line/body: full token, filtered by extension."""
    for m in RE_PATHTOK.finditer(text):
        tok = (m.group(1) or m.group(2) or "").strip()
        if not tok or " " in tok or "." not in tok:
            continue
        ext = tok.rsplit(".", 1)[-1].lower()
        if ext in CODE_EXT_SET:
            yield tok

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


def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {ARTIFACTS} (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        repo_name VARCHAR(511) NOT NULL,
        file_path VARCHAR(700) NOT NULL,
        kind VARCHAR(24) NULL,
        content LONGTEXT NULL,
        content_sha CHAR(64) NULL,
        n_bytes INT NULL,
        n_tasks INT NULL,
        n_tasks_done INT NULL,
        n_code_refs INT NULL,
        fetch_status VARCHAR(16) NULL,
        fetched_at VARCHAR(32) NULL,
        UNIQUE KEY uq_af (repo_name(160), file_path(190))
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {CODEREFS} (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        repo_name VARCHAR(511) NOT NULL,
        artifact_path VARCHAR(700) NOT NULL,
        code_path VARCHAR(500) NOT NULL,
        task_done TINYINT NULL,
        UNIQUE KEY uq_cr (repo_name(120), artifact_path(140), code_path(140)),
        KEY idx_af (repo_name(120), artifact_path(140))
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    conn.commit(); cur.close()
    print("schema ready.")


def parse_tasks(text):
    """Return (n_tasks, n_done, {code_path: done_bool}). Code paths come from task
    (checkbox) lines primarily; a path in a checked box is marked done."""
    n_tasks = n_done = 0
    refs = {}
    for line in text.splitlines():
        m = RE_CHECKBOX.match(line)
        if m:
            n_tasks += 1
            done = m.group(1) in "xX"
            n_done += done
            body = m.group(2)
        else:
            done, body = False, line
        for cp in _code_paths(body):
            if cp in refs:
                refs[cp] = refs[cp] or done
            elif len(refs) < MAX_CODE_REFS:
                refs[cp] = done
    return n_tasks, n_done, refs


def api_fetch(repo, path, ref, rotator):
    p = urllib.parse.quote(path, safe="/")
    url = f"https://api.github.com/repos/{repo}/contents/{p}?ref={urllib.parse.quote(ref, safe='')}"
    for attempt in range(API_MAX_TRIES):
        token = rotator.next_token()
        try:
            r = _SESSION.get(url, headers={"Authorization": f"Bearer {token}",
                             "Accept": "application/vnd.github.raw",
                             "X-GitHub-Api-Version": "2022-11-28"}, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 20)); continue
        sc = r.status_code
        if sc == 200:
            return r.content or b"", "done"
        if sc in (404, 410, 451):
            return None, "missing"
        if sc == 403 and "too_large" in r.text.lower():
            return None, "toobig"
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


_UPD = (f"INSERT INTO {ARTIFACTS} (repo_name,file_path,kind,content,content_sha,n_bytes,"
        f"n_tasks,n_tasks_done,n_code_refs,fetch_status,fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        f"ON DUPLICATE KEY UPDATE content=VALUES(content),content_sha=VALUES(content_sha),"
        f"n_bytes=VALUES(n_bytes),n_tasks=VALUES(n_tasks),n_tasks_done=VALUES(n_tasks_done),"
        f"n_code_refs=VALUES(n_code_refs),fetch_status=VALUES(fetch_status),fetched_at=VALUES(fetched_at)")


def worker(job, rotator):
    repo, path, ref = job
    kind = posixpath.basename(path).lower()
    data, status = api_fetch(repo, path, ref or "HEAD", rotator)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n_tasks = n_done = n_refs = None
    refs = {}
    text = None
    if status in ("done",) and data is not None:
        if len(data) > MAX_BYTES:
            data = data[:MAX_BYTES]; status = "toobig"
        text = data.decode("utf-8", "replace")
        if kind == "tasks.md":
            n_tasks, n_done, refs = parse_tasks(text)
            n_refs = len(refs)
    conn = _conn()
    cur = conn.cursor(prepared=True)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None
    nb = len(text.encode("utf-8")) if text is not None else None
    cur.execute(_UPD, (repo, path[:700], kind, text, sha, nb, n_tasks, n_done, n_refs, status, now))
    cur.close()
    if refs:
        cur = conn.cursor()
        cur.executemany(
            f"INSERT IGNORE INTO {CODEREFS} (repo_name,artifact_path,code_path,task_done) VALUES (%s,%s,%s,%s)",
            [(repo, path[:700], cp[:500], int(done)) for cp, done in refs.items()])
        cur.close()
    conn.commit()
    return status


def enum_jobs(rcur, take):
    rcur.execute(f"""
        SELECT s.repo_name, l.target, MIN(s.repo_default_branch)
        FROM spec_links l
        JOIN spec_files s ON s.file_url_sha16 = l.spec_url_sha16
        LEFT JOIN {ARTIFACTS} a ON a.repo_name = s.repo_name AND a.file_path = l.target
        WHERE l.rel='sibling' AND l.provenance='tree' AND s.spec_tool='openspec'
          AND (a.id IS NULL OR a.fetch_status IN ('throttled','error'))
        GROUP BY s.repo_name, l.target
        LIMIT {take}""")
    return rcur.fetchall()


def run(workers, limit):
    rotator = LockedRotator(f.get_github_tokens())
    logging.info("OpenSpec artifacts: %d tokens, %d workers", rotator.n, workers)
    reader = f.get_db_connection(DB_NAME); reader.autocommit = True
    rcur = reader.cursor()
    done = 0
    counts = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            take = BATCH if limit is None else min(BATCH, limit - done)
            if take <= 0:
                break
            jobs = enum_jobs(rcur, take)
            if not jobs:
                break
            for status in pool.map(lambda j: worker(j, rotator), jobs):
                counts[status] = counts.get(status, 0) + 1
                done += 1
                if done % 5000 == 0:
                    logging.info("fetched %s  %s", f"{done:,}", counts)
    rcur.close(); reader.close()
    logging.info("FINISHED. fetched=%s  %s", f"{done:,}", counts)


def link(conn):
    """Fold tasks.md-declared code paths into spec_links for every spec in the change."""
    cur = conn.cursor()
    cur.execute(f"""
      INSERT IGNORE INTO spec_links (spec_url_sha16, rel, target, provenance)
      SELECT DISTINCT l.spec_url_sha16, 'code', LEFT(acr.code_path,500), 'tasks'
      FROM {CODEREFS} acr
      JOIN spec_files s ON s.repo_name = acr.repo_name AND s.not_spec_filter=0
      JOIN spec_links l ON l.spec_url_sha16 = s.file_url_sha16
                        AND l.rel='sibling' AND l.target = acr.artifact_path
      WHERE s.spec_tool='openspec'""")
    conn.commit()
    print(f"linked: {cur.rowcount:,} spec->code (tasks) edges inserted.")
    cur.close()


def status(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COALESCE(fetch_status,'(pending)'), COUNT(*) FROM {ARTIFACTS} GROUP BY 1 ORDER BY 2 DESC")
    print("\n=== artifact fetch status ===")
    for s, n in cur.fetchall(): print(f"  {s:<12} {n:,}")
    cur.execute(f"SELECT kind, COUNT(*), SUM(n_bytes IS NOT NULL) FROM {ARTIFACTS} GROUP BY kind ORDER BY 2 DESC")
    print("  by kind (rows / with content):")
    for k, n, wc in cur.fetchall(): print(f"    {k:<16} {n:,} / {int(wc or 0):,}")
    cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT repo_name, artifact_path) FROM {CODEREFS}")
    r = cur.fetchone(); print(f"  code refs: {r[0]:,} across {r[1]:,} tasks.md files")
    cur.execute(f"SELECT SUM(n_tasks), SUM(n_tasks_done) FROM {ARTIFACTS} WHERE kind='tasks.md'")
    t = cur.fetchone()
    if t and t[0]:
        print(f"  tasks: {int(t[0]):,} total, {int(t[1] or 0):,} done ({100*(t[1] or 0)/t[0]:.0f}%)")
    cur.execute("SELECT COUNT(*) FROM spec_links WHERE provenance='tasks'")
    print(f"  spec->code (tasks) edges in spec_links: {cur.fetchone()[0]:,}")
    cur.close()


def main():
    ap = argparse.ArgumentParser(description="OpenSpec artifact fetch + tasks.md->code linking.")
    ap.add_argument("--schema", action="store_true")
    ap.add_argument("--link", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = ap.parse_args()
    conn = f.get_db_connection(DB_NAME)
    ensure_schema(conn)
    if args.schema:
        conn.close(); return
    if args.link:
        link(conn); status(conn); conn.close(); return
    if args.status:
        status(conn); conn.close(); return
    conn.close()
    run(args.workers, args.limit)
    conn = f.get_db_connection(DB_NAME); status(conn); conn.close()


if __name__ == "__main__":
    main()
