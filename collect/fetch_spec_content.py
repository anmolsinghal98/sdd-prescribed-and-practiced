#!/usr/bin/env python3
"""
Phase 3 — raw file CONTENT for the KEPT spec files (not_spec_filter = 0).

For each kept file we fetch its raw markdown from the GitHub CDN:

    https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}

pinned to file_last_commit_sha (immutable, so the text matches the metadata
snapshot we already stored). The CDN needs NO token and is not subject to the
5,000/hr REST limit, so this runs with more workers than the API crawls.

Stored back onto spec_files (one column, as requested), plus a content hash so we
can measure duplication / detect change later without a separate blob table:

  file_content        LONGTEXT  -- the raw markdown (truncated at MAX_BYTES)
  file_content_sha    CHAR(64)  -- sha256 of the fetched bytes (dedup key)
  file_content_bytes  INT       -- size actually fetched
  content_fetch_status VARCHAR  -- done | missing (404/410) | toobig | error
  content_fetched_at  VARCHAR

Fully resumable via content_fetch_status: re-running only touches rows that are
NULL or 'error'. Writes use a PREPARED cursor (binary protocol) because the
content parameter is large and client-side escaping mangles big params
(the lesson from the Phase-2 crawl).

Usage:
  python3 fetch_spec_content.py                 # run (resumable)
  python3 fetch_spec_content.py --status        # progress only, no fetching
  python3 fetch_spec_content.py --schema-only   # add columns, then exit
  python3 fetch_spec_content.py --limit 200     # fetch only N files (smoke test)
  python3 fetch_spec_content.py --workers 16
  python3 fetch_spec_content.py --reset-errors  # re-queue 'error' rows
"""

import argparse
import os
import hashlib
import logging
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
KEEP = "not_spec_filter = 0"
BATCH = 3000                 # files pulled from the DB per work batch
PROGRESS_EVERY = 1000
DEFAULT_WORKERS = 16         # CDN, no token limit; network-latency bound
MAX_BYTES = 2_000_000        # cap a single file at 2 MB (specs are tiny; guard blobs)
TIMEOUT = 25
RAW_HOST = "https://raw.githubusercontent.com"
# The CDN has a cumulative per-IP budget (~tens of thousands) that resets over
# time; when hit it returns 429/403. We back off + retry rather than burning the
# row into a terminal error, and cool the whole crawl down between throttled
# batches so we self-pace under the limit instead of racing the queue into errors.
THROTTLE_CODES = (429, 403)
RETRY_CODES = (429, 403, 500, 502, 503, 504)
MAX_TRIES = 6
COOLDOWN = 90                # seconds to pause the crawl after a throttled batch

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "spec-research/1.0"
# Size the urllib3 connection pool to the worker count (default 10 < workers ->
# "connection pool is full" churn). One host, so a single generous adapter.
_ADAPTER = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=64)
_SESSION.mount("https://", _ADAPTER)

# --- authenticated Contents-API mode (reliable, per-token 5,000/hr x 19) -------
API_HOST = "https://api.github.com"
API_MAX_TRIES = 8            # rotate through tokens on 403/429 before giving up


class LockedRotator:
    """Thread-safe round-robin token pool: next_token() atomically returns the
    current token and advances, so concurrent workers spread across all tokens."""

    def __init__(self, tokens):
        self._tokens = tokens
        self.n = len(tokens)
        self._i = 0
        self._lock = threading.Lock()

    def next_token(self):
        with self._lock:
            t = self._tokens[self._i]
            self._i = (self._i + 1) % self.n
            return t


def api_fetch_one(row, rotator):
    """Contents-API variant of fetch_one. Uses `Accept: raw` so the endpoint
    returns raw file bytes (not base64), counted against the per-token 5,000/hr
    REST budget. Rotates tokens on 403/429; honors X-RateLimit-Reset only after a
    full lap of the pool is exhausted. Same return contract as fetch_one."""
    file_id, repo_name, sha, branch, path = row
    ref = sha or branch or "HEAD"
    p = urllib.parse.quote(path, safe="/")
    url = f"{API_HOST}/repos/{repo_name}/contents/{p}?ref={urllib.parse.quote(ref, safe='')}"
    for attempt in range(API_MAX_TRIES):
        token = rotator.next_token()
        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/vnd.github.raw",
                   "X-GitHub-Api-Version": "2022-11-28"}
        try:
            r = _SESSION.get(url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 20)); continue
        sc = r.status_code
        if sc == 200:
            data = r.content or b""
            status = "done"
            if len(data) > MAX_BYTES:
                data, status = data[:MAX_BYTES], "toobig"
            return file_id, data.decode("utf-8", "replace"), \
                hashlib.sha256(data).hexdigest(), len(data), status
        if sc in (404, 410, 451):
            return file_id, None, None, None, "missing"
        if sc == 403 and "too_large" in r.text.lower():
            return file_id, None, None, None, "toobig"     # >1MB: needs blob API (rare)
        if sc in (403, 429):
            # Rate limited on THIS token. If the primary budget is exhausted the
            # header says so; only sleep to reset after we've lapped the pool.
            if r.headers.get("X-RateLimit-Remaining") == "0" and attempt >= rotator.n:
                reset = int(r.headers.get("X-RateLimit-Reset", "0") or 0)
                wait = max(0.0, reset - time.time()) + 1.0
                time.sleep(min(wait, 60))
            else:
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    time.sleep(min(float(ra), 60))
            continue
        return file_id, None, None, None, "error"
    return file_id, None, None, None, "throttled"

NEW_COLS = [
    ("file_content", "LONGTEXT NULL"),
    ("file_content_sha", "CHAR(64) NULL"),
    ("file_content_bytes", "INT NULL"),
    ("content_fetch_status", "VARCHAR(16) NULL"),
    ("content_fetched_at", "VARCHAR(32) NULL"),
]

_UPDATE_SQL = (
    "UPDATE spec_files SET file_content=%s, file_content_sha=%s, "
    "file_content_bytes=%s, content_fetch_status=%s, content_fetched_at=%s "
    "WHERE file_url_sha16=%s"
)


def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute("""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='spec_files'""")
    have = {r[0] for r in cur.fetchall()}
    for name, decl in NEW_COLS:
        if name not in have:
            cur.execute(f"ALTER TABLE spec_files ADD COLUMN {name} {decl}")
            logging.info("added column %s", name)
    conn.commit()
    cur.close()


def raw_url(repo_name, ref, path):
    p = "/".join(urllib.parse.quote(seg) for seg in path.split("/"))
    return f"{RAW_HOST}/{repo_name}/{ref}/{p}"


def fetch_one(row):
    """row = (file_id, repo_name, sha, default_branch, file_path).
    Returns (file_id, content_or_None, sha256_or_None, nbytes, status) where
    status is done | missing | toobig | error | throttled. 'throttled' is
    RETRYABLE (the caller leaves the row pending and retries after a cooldown);
    'error' is for genuinely unexpected responses."""
    file_id, repo_name, sha, branch, path = row
    ref = sha or branch or "HEAD"
    url = raw_url(repo_name, ref, path)
    for attempt in range(MAX_TRIES):
        try:
            r = _SESSION.get(url, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 20)); continue          # transient net error
        sc = r.status_code
        if sc == 200:
            data = r.content or b""
            status = "done"
            if len(data) > MAX_BYTES:
                data, status = data[:MAX_BYTES], "toobig"
            return file_id, data.decode("utf-8", "replace"), \
                hashlib.sha256(data).hexdigest(), len(data), status
        if sc in (404, 410, 451):
            return file_id, None, None, None, "missing"           # genuinely gone
        if sc in RETRY_CODES:
            ra = r.headers.get("Retry-After")
            wait = float(ra) if (ra and ra.isdigit()) else min(2 ** attempt, 30)
            time.sleep(wait); continue                            # throttle / 5xx: back off
        return file_id, None, None, None, "error"                 # unexpected code
    # Exhausted retries while being throttled/5xx -> retryable, not terminal.
    return file_id, None, None, None, "throttled"


def print_status(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM spec_files WHERE {KEEP}")
    kept = cur.fetchone()[0]
    cur.execute(f"""SELECT COALESCE(content_fetch_status,'(pending)') s, COUNT(*)
                    FROM spec_files WHERE {KEEP} GROUP BY s ORDER BY 2 DESC""")
    print(f"\n=== content fetch status (kept={kept:,}) ===")
    for s, n in cur.fetchall():
        print(f"  {s:<12} {n:>9,}  ({100*n/kept:.1f}%)")
    cur.close()


def run(workers, limit, fetcher=fetch_one):
    reader = f.get_db_connection(DB_NAME)
    reader.autocommit = True          # fresh snapshot each batch (avoid stale reads)
    writer = f.get_db_connection(DB_NAME)
    rcur = reader.cursor()
    processed = 0
    counts = {"done": 0, "missing": 0, "toobig": 0, "error": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            take = BATCH if limit is None else min(BATCH, limit - processed)
            if take <= 0:
                break
            rcur.execute(
                f"""SELECT file_url_sha16, repo_name, file_last_commit_sha,
                           repo_default_branch, file_path
                    FROM spec_files
                    WHERE {KEEP} AND (content_fetch_status IS NULL)
                    LIMIT {take}""")
            rows = rcur.fetchall()
            if not rows:
                break
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            wcur = writer.cursor(prepared=True)   # binary protocol for big params
            throttled = 0
            for res in pool.map(fetcher, rows):
                file_id, text, sha256, nbytes, status = res
                if status == "throttled":
                    # leave the row pending (status stays NULL) so it is retried
                    # next batch after the cooldown; do NOT write a terminal status.
                    throttled += 1
                    continue
                wcur.execute(_UPDATE_SQL, (text, sha256, nbytes, status, now, file_id))
                counts[status] = counts.get(status, 0) + 1
                processed += 1
                if processed % PROGRESS_EVERY == 0:
                    logging.info("processed %s  (done=%s missing=%s toobig=%s error=%s)",
                                 f"{processed:,}", counts["done"], counts["missing"],
                                 counts["toobig"], counts["error"])
            writer.commit()
            wcur.close()
            if throttled:
                logging.warning("throttled on %s/%s of batch -> cooling down %ss "
                                "(rows left pending, will retry)", throttled, len(rows), COOLDOWN)
                time.sleep(COOLDOWN)
    rcur.close(); reader.close(); writer.close()
    logging.info("FINISHED. processed=%s  %s", f"{processed:,}", counts)


def reset_errors(conn):
    cur = conn.cursor()
    cur.execute(f"UPDATE spec_files SET content_fetch_status=NULL "
                f"WHERE {KEEP} AND content_fetch_status='error'")
    conn.commit()
    print(f"re-queued {cur.rowcount:,} error rows.")
    cur.close()


def main():
    ap = argparse.ArgumentParser(description="Fetch raw spec-file content for the kept set (resumable).")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--schema-only", action="store_true")
    ap.add_argument("--reset-errors", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--api", action="store_true",
                    help="Use the authenticated Contents API (token pool, ~95k/hr) "
                         "instead of the raw CDN. Reliable pacing for the bulk/tail.")
    args = ap.parse_args()

    conn = f.get_db_connection(DB_NAME)
    ensure_schema(conn)
    if args.schema_only:
        print("schema ready."); conn.close(); return
    if args.reset_errors:
        reset_errors(conn); print_status(conn); conn.close(); return
    if args.status:
        print_status(conn); conn.close(); return
    conn.close()

    if args.api:
        rotator = LockedRotator(f.get_github_tokens())
        logging.info("Contents-API mode: %d tokens, %d workers", rotator.n, args.workers)
        run(args.workers, args.limit, fetcher=lambda row: api_fetch_one(row, rotator))
    else:
        run(args.workers, args.limit)
    conn = f.get_db_connection(DB_NAME)
    print_status(conn)
    conn.close()


if __name__ == "__main__":
    main()
