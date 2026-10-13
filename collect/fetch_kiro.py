#!/usr/bin/env python3
"""
Kiro spec collector — rewritten to match the rigor of the spec.md census
(fetch_spec_files.py). Kiro doesn't use spec.md, so it was invisible to that
census; its artifacts live at .kiro/specs/<feature>/{requirements,design,tasks,
bugfix}.md .

Rigor (the three things the first version got wrong):
  1. PLAN pass splits each size range while the (unreliable) totalCount >= 400,
     staying FAR below the 1000-result fetch ceiling (same MAX_PARTITION_SIZE the
     census uses, since GitHub's totalCount undercounts near/above it).
  2. FETCH pages until an ACTUALLY short/empty page (len < 100) — never using the
     totalCount estimate to bound pagination.
  3. On a page FAILURE (all tokens exhausted), the partition is left PENDING and
     retried on the next run — pages are never silently dropped.

Resumable via kiro_plan (one row per size leaf, per filename).

  python3 fetch_kiro.py --schema
  python3 fetch_kiro.py --plan        # build/refresh the partition plan
  python3 fetch_kiro.py               # fetch pending partitions (resumable)
  python3 fetch_kiro.py --status
  python3 fetch_kiro.py --wipe        # drop kiro_files + kiro_plan and start over
"""
import argparse, logging, posixpath, sys, time
import os
from datetime import datetime, timezone
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DB = "specdriven"
KINDS = ["requirements.md", "design.md", "tasks.md", "bugfix.md"]
MAX_SIZE = 600000
SPLIT_THRESHOLD = 400      # split while totalCount >= this (totalCount unreliable above it)
PER_PAGE = 100
MAX_PAGES = 10             # GitHub hard cap: 10 pages * 100 = 1000 results
MAX_ATTEMPTS_MULT = 6      # retry attempts = tokens * this

_S = requests.Session()
_last = [0.0]
MIN_INTERVAL = 0.8         # min seconds between search calls (avoid secondary limit)

class Rot:
    def __init__(self, toks): self.t=toks; self.n=len(toks); self.i=0
    def nxt(self):
        x=self.t[self.i]; self.i=(self.i+1)%self.n; return x

def _search(q, page, rot):
    """Robust code-search call. Returns (total_count, items) or (None, None) after
    exhausting retries. Honors rate-limit reset / Retry-After; rotates tokens."""
    for attempt in range(rot.n * MAX_ATTEMPTS_MULT):
        dt = time.time() - _last[0]
        if dt < MIN_INTERVAL: time.sleep(MIN_INTERVAL - dt)
        tok = rot.nxt()
        try:
            r = _S.get("https://api.github.com/search/code",
                       params={"q": q, "per_page": PER_PAGE, "page": page},
                       headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                "X-GitHub-Api-Version": "2022-11-28"}, timeout=30)
        except requests.RequestException:
            _last[0]=time.time(); time.sleep(2); continue
        _last[0]=time.time()
        if r.status_code == 200:
            j = r.json(); return j.get("total_count", 0), j.get("items", [])
        if r.status_code == 422:
            return 0, []
        if r.status_code in (403, 429):
            ra = r.headers.get("Retry-After")
            rem = r.headers.get("X-RateLimit-Remaining")
            if ra and ra.isdigit(): time.sleep(min(float(ra), 60))
            elif rem == "0":
                reset = int(r.headers.get("X-RateLimit-Reset", "0") or 0)
                time.sleep(min(max(0.0, reset - time.time()) + 1, 60))
            else:
                time.sleep(3)
            continue
        time.sleep(2)
    return None, None

def ensure_schema(conn):
    cur=conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS kiro_files (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        repo_name VARCHAR(511) NOT NULL, owner_login VARCHAR(255), repo_id BIGINT,
        file_path VARCHAR(1000) NOT NULL, file_name VARCHAR(255), kind VARCHAR(16),
        feature VARCHAR(400), file_sha VARCHAR(64), html_url TEXT, git_url TEXT, fetched_at VARCHAR(32),
        UNIQUE KEY uq (repo_name(140), file_path(280)), KEY idx_repo (repo_name(140)), KEY idx_kind (kind)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cur.execute("""CREATE TABLE IF NOT EXISTS kiro_plan (
        filename VARCHAR(32) NOT NULL, min_size INT NOT NULL, max_size INT NOT NULL,
        est_count INT, status VARCHAR(12) NULL, files_stored INT NULL, truncated TINYINT NULL,
        PRIMARY KEY (filename, min_size, max_size)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    conn.commit(); cur.close()

def kind_of(name):
    return {"requirements.md":"requirements","design.md":"design","tasks.md":"tasks","bugfix.md":"bugfix"}.get(name.lower(),"other")

def store(conn, items):
    cur=conn.cursor(); now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); rows=[]
    for it in items:
        path=it.get("path",""); repo=it.get("repository",{}) or {}
        feat=None
        if ".kiro/specs/" in path: feat=path.split(".kiro/specs/",1)[1].split("/")[0]
        rows.append((repo.get("full_name"),(repo.get("owner") or {}).get("login"),repo.get("id"),
                     path[:1000],it.get("name"),kind_of(it.get("name","")),(feat or "")[:400],
                     it.get("sha"),it.get("html_url"),it.get("git_url"),now))
    if rows:
        cur.executemany("""INSERT IGNORE INTO kiro_files
          (repo_name,owner_login,repo_id,file_path,file_name,kind,feature,file_sha,html_url,git_url,fetched_at)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
        conn.commit()
    cur.close(); return len(rows)

def build_plan(conn, rot):
    """Recursively split each filename's size range while totalCount >= threshold."""
    cur=conn.cursor()
    for fn in KINDS:
        base=f"path:.kiro/specs filename:{fn}"
        queue=[(0,MAX_SIZE)]; leaves=0
        while queue:
            lo,hi=queue.pop()
            tc,_=_search(f"{base} size:{lo}..{hi}",1,rot)
            if tc is None:
                logging.error("plan count failed for %s %d..%d; rerun --plan to finish", fn, lo, hi); return False
            if tc==0: continue
            if tc>=SPLIT_THRESHOLD and hi-lo>1:
                mid=(lo+hi)//2; queue.append((lo,mid)); queue.append((mid+1,hi)); continue
            cur.execute("""INSERT INTO kiro_plan (filename,min_size,max_size,est_count,status)
                VALUES (%s,%s,%s,%s,'pending')
                ON DUPLICATE KEY UPDATE est_count=VALUES(est_count)""",(fn,lo,hi,tc))
            conn.commit(); leaves+=1
        logging.info("planned %s: %d leaves", fn, leaves)
    cur.close(); return True

def _fetch_page(q, page, rot):
    """Fetch one page, retrying SHORT pages — GitHub code search transiently
    returns fewer than per_page items even when more exist; a retry usually fills
    it. Returns the fullest response seen, or None on hard failure. Stops retrying
    when it gets a full page, a stably-repeating short count (genuine last page),
    or an empty page."""
    best = None; prev_len = -1; stable = 0
    for _ in range(5):
        tc, items = _search(q, page, rot)
        if items is None:
            return None
        if best is None or len(items) > len(best):
            best = items
        if len(items) == PER_PAGE or len(items) == 0:
            break                          # full or empty -> definitive
        stable = stable + 1 if len(items) == prev_len else 0
        prev_len = len(items)
        if stable >= 1:                    # same short count twice -> genuine last page
            break
        time.sleep(1.5)                    # transient short -> retry
    return best


def fetch_leaf(conn, fn, lo, hi, rot):
    """Page until a genuinely EMPTY page (not merely a short one); each page is
    retried to defeat code-search short-page flakiness. On hard failure return
    None so the caller leaves the partition PENDING for retry."""
    base=f"path:.kiro/specs filename:{fn}"; q=f"{base} size:{lo}..{hi}"
    stored=0; page=1
    while page<=MAX_PAGES:
        items=_fetch_page(q,page,rot)
        if items is None:
            return None, stored            # hard failure -> pending
        if not items:
            break                          # genuinely empty -> true end
        stored+=store(conn,items)
        page+=1
    truncated=1 if page>MAX_PAGES else 0    # only if a full 10 pages were non-empty
    return ("truncated" if truncated else "done"), stored, truncated

def run_fetch(conn, rot):
    cur=conn.cursor()
    cur.execute("SELECT filename,min_size,max_size FROM kiro_plan WHERE status='pending' ORDER BY est_count")
    pending=cur.fetchall(); cur.close()
    logging.info("fetch: %d pending partitions", len(pending))
    done=0; failed=0; trunc=0
    for fn,lo,hi in pending:
        res=fetch_leaf(conn,fn,lo,hi,rot)
        if res[0] is None:
            failed+=1
            logging.warning("partition %s %d..%d failed; left pending for retry", fn, lo, hi)
            continue
        status,stored,truncated=res
        trunc+=truncated
        c2=conn.cursor()
        c2.execute("UPDATE kiro_plan SET status='done', files_stored=%s, truncated=%s WHERE filename=%s AND min_size=%s AND max_size=%s",
                   (stored,truncated,fn,lo,hi)); conn.commit(); c2.close()
        done+=1
        if done%100==0: logging.info("  fetched %d/%d partitions", done, len(pending))
    logging.info("fetch pass done: %d done, %d failed (pending), %d truncated", done, failed, trunc)
    return failed

def status(conn):
    cur=conn.cursor()
    cur.execute("SELECT status, COUNT(*), SUM(files_stored) FROM kiro_plan GROUP BY status")
    print("\n=== kiro_plan partitions ==="); tot_leaves=0
    for s,n,fs in cur.fetchall(): print(f"  {str(s):<10} {n:,} partitions  ({int(fs or 0):,} files)"); tot_leaves+=n
    cur.execute("SELECT SUM(truncated) FROM kiro_plan"); tr=cur.fetchone()[0]
    if tr: print(f"  ⚠ {int(tr)} truncated partitions (hit 1000 ceiling — should be 0)")
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT repo_name), COUNT(DISTINCT repo_name, feature) FROM kiro_files")
    n,r,feat=cur.fetchone(); print(f"\n=== kiro_files: {n:,} files, {r:,} repos, {feat:,} distinct specs ===")
    cur.execute("SELECT kind, COUNT(*) FROM kiro_files GROUP BY kind ORDER BY 2 DESC")
    print("  by kind:", dict(cur.fetchall())); cur.close()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--schema",action="store_true"); ap.add_argument("--plan",action="store_true")
    ap.add_argument("--status",action="store_true"); ap.add_argument("--wipe",action="store_true")
    args=ap.parse_args()
    conn=f.get_db_connection(DB)
    if args.wipe:
        cur=conn.cursor(); cur.execute("DROP TABLE IF EXISTS kiro_files"); cur.execute("DROP TABLE IF EXISTS kiro_plan")
        conn.commit(); cur.close(); print("wiped."); ensure_schema(conn); conn.close(); return
    ensure_schema(conn)
    if args.schema: print("schema ready."); conn.close(); return
    if args.status: status(conn); conn.close(); return
    rot=Rot(f.get_github_tokens())
    cur=conn.cursor(); cur.execute("SELECT COUNT(*) FROM kiro_plan"); planned=cur.fetchone()[0]; cur.close()
    if args.plan or planned==0:
        if not build_plan(conn, rot): conn.close(); return
    run_fetch(conn, rot)
    status(conn); conn.close()

if __name__=="__main__":
    main()
