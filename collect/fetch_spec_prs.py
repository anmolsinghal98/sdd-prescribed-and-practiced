#!/usr/bin/env python3
"""
PR-level visibility for a tool's curated core repos: find every PR that modified
a spec file, and capture that PR's FULL changed-file list (spec + code + md +
other) so you can see, per PR, exactly what shipped together.

Tool-generic via --tool {openspec|speckit|...}: it uses <tool>_repos as the repo
set and writes <tool>_prs / <tool>_pr_files / <tool>_pr_discover_queue. "spec dir"
(the tool's spec area, used to separate spec artifacts from real code) is
tool-aware: openspec -> under openspec/ ; speckit -> under specs/ or .specify/.

Discovery is targeted: each spec file's commit history -> the PR(s) containing
those commits (GET /commits/{sha}/pulls) -> then each PR's files.

Stages:
  --tool T --seed       create schema + seed the commit queue
  --tool T --discover   commit -> PRs
  --tool T              PR -> files
  --tool T --rollup     derive touches_code / per-repo counts
  --tool T --status
"""
import argparse, logging, posixpath, re, sys, threading, time, urllib.parse
import os
from concurrent.futures import ThreadPoolExecutor
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DB = "specdriven"
TIMEOUT = 30
MAX_TRIES = 30
WORKERS = 12
BATCH = 400
MAX_FILE_PAGES = 30

CODE_EXT = {"py","ts","tsx","js","jsx","go","rs","java","rb","cpp","cc","c","h","hpp",
            "cs","php","swift","kt","scala","sql","sh","vue","svelte","dart","ex","exs",
            "clj","m","mm","scss","css","html","pl","lua","r"}

# ---- tool context (set in main) ----
TOOL = "openspec"
REPOS = "openspec_repos"; PRS = "openspec_prs"; PRF = "openspec_pr_files"; QUEUE = "openspec_pr_discover_queue"
def set_tool(tool):
    global TOOL, REPOS, PRS, PRF, QUEUE
    TOOL = tool
    REPOS, PRS, PRF, QUEUE = f"{tool}_repos", f"{tool}_prs", f"{tool}_pr_files", f"{tool}_pr_discover_queue"

RE_SPECS_DIR = re.compile(r'(^|/)specs/')
# each tool's spec/config directory prefix(es) — files here are spec artifacts,
# everything else with a code extension counts as "real code".
TOOL_DIRS = {
    "openspec": ["openspec/"], "conductor": ["conductor/"],
    "agent_os": ["agent-os/", ".agent-os/"], "moai": [".moai/"],
    "specweave": [".specweave/"], "claude_code": [".claude/"],
    "opencode": [".opencode/"], "trae": [".trae/"], "cursor": [".cursor/"],
    "codex": [".codex"], "kilocode": [".kilocode/"],
}
def is_specdir(path):
    """Is this changed file inside the tool's spec area (vs real code elsewhere)?"""
    if TOOL == "speckit":
        return bool(RE_SPECS_DIR.search(path)) or path.startswith(".specify/") or "/.specify/" in path
    for d in TOOL_DIRS.get(TOOL, []):
        if path.startswith(d) or ("/" + d) in path:
            return True
    return False

_SESSION = requests.Session()
_SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=64))

class LockedRotator:
    def __init__(self, t): self._t=t; self.n=len(t); self._i=0; self._lock=threading.Lock()
    def next_token(self):
        with self._lock:
            x=self._t[self._i]; self._i=(self._i+1)%self.n; return x

_local = threading.local()
def _conn():
    if not getattr(_local, "conn", None): _local.conn = f.get_db_connection(DB)
    return _local.conn

def _get(url, rotator):
    for attempt in range(MAX_TRIES):
        tok = rotator.next_token()
        try:
            r = _SESSION.get(url, headers={"Authorization": f"Bearer {tok}",
                             "Accept": "application/vnd.github+json",
                             "X-GitHub-Api-Version": "2022-11-28"}, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(min(2**attempt, 20)); continue
        sc = r.status_code
        if sc == 200: return r, "ok"
        if sc in (404,409,410,422,451): return r, "missing"
        if sc in (403,429):
            if r.headers.get("X-RateLimit-Remaining")=="0" and attempt >= rotator.n:
                reset=int(r.headers.get("X-RateLimit-Reset","0") or 0)
                time.sleep(min(max(0.0,reset-time.time())+1.0,60))
            else:
                ra=r.headers.get("Retry-After")
                if ra and ra.isdigit(): time.sleep(min(float(ra),60))
            continue
        return r, "error"
    return None, "throttled"


def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {QUEUE} (
        repo_name VARCHAR(511) NOT NULL, commit_sha CHAR(40) NOT NULL, status VARCHAR(12) NULL,
        PRIMARY KEY (commit_sha, repo_name(80)) ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {PRS} (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        repo_name VARCHAR(511) NOT NULL, pr_number INT NOT NULL,
        title TEXT, state VARCHAR(12), is_merged TINYINT, merged_at VARCHAR(32),
        created_at VARCHAR(32), closed_at VARCHAR(32), author_login VARCHAR(255),
        head_branch VARCHAR(400), base_branch VARCHAR(255),
        n_files INT, n_specdir_files INT, n_spec_files INT, n_code_files INT,
        n_md_files INT, n_other_files INT, additions INT, deletions INT, files_status VARCHAR(12),
        UNIQUE KEY uq (repo_name(120), pr_number), KEY idx_repo (repo_name(120)) )
        ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {PRF} (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        repo_name VARCHAR(511) NOT NULL, pr_number INT NOT NULL,
        file_path VARCHAR(1000) NOT NULL, change_status VARCHAR(12),
        additions INT, deletions INT, is_specdir TINYINT, is_spec TINYINT, is_code TINYINT, ext VARCHAR(16),
        UNIQUE KEY uq (repo_name(100), pr_number, file_path(250)),
        KEY idx_pr (repo_name(100), pr_number) )
        ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    conn.commit(); cur.close()


def seed(conn):
    cur = conn.cursor()
    cur.execute(f"""INSERT IGNORE INTO {QUEUE} (repo_name, commit_sha)
        SELECT DISTINCT s.repo_name, sc.commit_sha
        FROM spec_file_commits sc JOIN spec_files s ON s.file_url_sha16 = sc.file_url_sha16
        JOIN {REPOS} r ON r.repo_name = s.repo_name
        WHERE s.not_spec_filter=0 AND s.spec_tool='{TOOL}' AND sc.commit_sha IS NOT NULL""")
    cur.execute(f"""INSERT IGNORE INTO {QUEUE} (repo_name, commit_sha)
        SELECT DISTINCT s.repo_name, s.file_last_commit_sha
        FROM spec_files s JOIN {REPOS} r ON r.repo_name = s.repo_name
        WHERE s.not_spec_filter=0 AND s.spec_tool='{TOOL}' AND s.file_last_commit_sha IS NOT NULL""")
    conn.commit()
    cur.execute(f"SELECT COUNT(*) FROM {QUEUE}"); print(f"seeded {cur.fetchone()[0]:,} commits.")
    cur.close()


def discover(rotator, workers, limit):
    reader = f.get_db_connection(DB); reader.autocommit = True
    rcur = reader.cursor()
    rcur.execute(f"SELECT repo_name, commit_sha FROM {QUEUE} WHERE status IS NULL" + (f" LIMIT {limit}" if limit else ""))
    jobs = rcur.fetchall(); rcur.close(); reader.close()
    logging.info("discover: %d commits", len(jobs))
    done = [0]
    def work(job):
        repo, sha = job
        r, st = _get(f"https://api.github.com/repos/{repo}/commits/{sha}/pulls", rotator)
        conn = _conn(); cur = conn.cursor()
        if st == "ok":
            for pr in r.json():
                cur.execute(f"""INSERT IGNORE INTO {PRS}
                   (repo_name,pr_number,title,state,is_merged,merged_at,created_at,closed_at,
                    author_login,head_branch,base_branch) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (repo, pr.get("number"), (pr.get("title") or "")[:2000], pr.get("state"),
                    1 if pr.get("merged_at") else 0, pr.get("merged_at"), pr.get("created_at"),
                    pr.get("closed_at"), (pr.get("user") or {}).get("login"),
                    ((pr.get("head") or {}).get("ref") or "")[:400], (pr.get("base") or {}).get("ref")))
        cur.execute(f"UPDATE {QUEUE} SET status=%s WHERE repo_name=%s AND commit_sha=%s",
                    (st if st!="ok" else "done", repo, sha))
        conn.commit(); cur.close()
        return st
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for st in pool.map(work, jobs):
            done[0]+=1
            if done[0] % 1000 == 0: logging.info("discover %d/%d", done[0], len(jobs))
    conn = f.get_db_connection(DB); cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {PRS}"); logging.info("discovered %s spec-touching PRs", f"{cur.fetchone()[0]:,}")
    conn.close()


def fetch_pr_files(repo, num, rotator):
    files = []
    for page in range(1, MAX_FILE_PAGES+1):
        r, st = _get(f"https://api.github.com/repos/{repo}/pulls/{num}/files?per_page=100&page={page}", rotator)
        if st != "ok": return None, st
        chunk = r.json(); files.extend(chunk)
        if len(chunk) < 100: break
    return files, "done"


def classify_file(path):
    base = posixpath.basename(path).lower()
    ext = base.rsplit(".",1)[-1] if "." in base else ""
    sd = is_specdir(path)
    is_spec = sd and base in ("spec.md","specs.md")
    return sd, is_spec, ext in CODE_EXT, ext[:16]


def run_files(rotator, workers, limit):
    reader = f.get_db_connection(DB); reader.autocommit = True
    rcur = reader.cursor(); done = 0; counts = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            take = BATCH if limit is None else min(BATCH, limit-done)
            if take <= 0: break
            rcur.execute(f"SELECT repo_name, pr_number FROM {PRS} WHERE files_status IS NULL LIMIT %s", (take,))
            prs = rcur.fetchall()
            if not prs: break
            def work(pr):
                repo, num = pr
                files, st = fetch_pr_files(repo, num, rotator)
                conn = _conn(); cur = conn.cursor()
                if st == "done":
                    rows=[]; add=dele=0; nsd=nsp=nc=nmd=noth=0
                    for fl in files:
                        p = fl.get("filename","")
                        sd, isp, ic, ext = classify_file(p)
                        a,d = fl.get("additions",0), fl.get("deletions",0); add+=a; dele+=d
                        nsd+=sd; nsp+=isp; nc+=ic
                        if not sd and ext=="md": nmd+=1
                        if not sd and not ic and ext!="md": noth+=1
                        rows.append((repo,num,p[:1000],fl.get("status"),a,d,int(sd),int(isp),int(ic),ext))
                    if rows:
                        cur.executemany(f"""INSERT IGNORE INTO {PRF}
                          (repo_name,pr_number,file_path,change_status,additions,deletions,is_specdir,is_spec,is_code,ext)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
                    cur.execute(f"""UPDATE {PRS} SET n_files=%s,n_specdir_files=%s,n_spec_files=%s,
                       n_code_files=%s,n_md_files=%s,n_other_files=%s,additions=%s,deletions=%s,files_status='done'
                       WHERE repo_name=%s AND pr_number=%s""", (len(files),nsd,nsp,nc,nmd,noth,add,dele,repo,num))
                else:
                    cur.execute(f"UPDATE {PRS} SET files_status=%s WHERE repo_name=%s AND pr_number=%s",(st,repo,num))
                conn.commit(); cur.close()
                return st
            for st in pool.map(work, prs):
                counts[st]=counts.get(st,0)+1; done+=1
                if done % 2000 == 0: logging.info("pr-files %s  %s", f"{done:,}", counts)
    rcur.close(); reader.close()
    logging.info("pr-files done: %s  %s", f"{done:,}", counts)


def _addcol(cur, table, name, decl):
    cur.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s""", (table, name))
    if cur.fetchone()[0] == 0:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def rollup(conn):
    """Derive per-PR and per-repo code-coupling from <tool>_pr_files.
    'code' = a changed file with a source extension, OUTSIDE the tool's spec dir."""
    cur = conn.cursor()
    _addcol(cur, PRS, "touches_code", "TINYINT NULL")
    _addcol(cur, PRS, "n_code_outside", "INT NULL")
    _addcol(cur, PRS, "n_prs_in_repo", "INT NULL")
    _addcol(cur, REPOS, "n_spec_prs", "INT NULL")
    _addcol(cur, REPOS, "n_spec_prs_with_code", "INT NULL")
    _addcol(cur, REPOS, "pct_prs_with_code", "DECIMAL(5,1) NULL")
    conn.commit()
    cur.execute(f"""UPDATE {PRS} p
        LEFT JOIN (SELECT repo_name, pr_number, SUM(is_code=1 AND is_specdir=0) nco
                   FROM {PRF} GROUP BY repo_name, pr_number) x
          ON x.repo_name=p.repo_name AND x.pr_number=p.pr_number
        SET p.n_code_outside=COALESCE(x.nco,0), p.touches_code=(COALESCE(x.nco,0)>0)""")
    cur.execute(f"""UPDATE {PRS} p
        JOIN (SELECT repo_name, COUNT(*) n FROM {PRS} GROUP BY repo_name) x ON x.repo_name=p.repo_name
        SET p.n_prs_in_repo = x.n""")
    cur.execute(f"""UPDATE {REPOS} r
        LEFT JOIN (SELECT repo_name, COUNT(*) n, SUM(touches_code) wc FROM {PRS} GROUP BY repo_name) x
          ON x.repo_name=r.repo_name
        SET r.n_spec_prs=COALESCE(x.n,0), r.n_spec_prs_with_code=COALESCE(x.wc,0),
            r.pct_prs_with_code=CASE WHEN COALESCE(x.n,0)>0 THEN ROUND(100*x.wc/x.n,1) ELSE NULL END""")
    conn.commit()
    print(f"rollup done: {PRS}.touches_code + {REPOS}.n_spec_prs[_with_code] set.")
    cur.close()


def status(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*), SUM(status='done'), SUM(status IS NULL) FROM {QUEUE}")
    n,d,p = cur.fetchone(); print(f"\n=== [{TOOL}] discovery queue: {n or 0:,} commits ({int(d or 0):,} done, {int(p or 0):,} pending) ===")
    cur.execute(f"SELECT COUNT(*), SUM(is_merged), SUM(files_status='done'), SUM(files_status IS NULL) FROM {PRS}")
    n,m,fd,fp = cur.fetchone()
    print(f"=== {PRS}: {n or 0:,} PRs that touched a spec ({int(m or 0):,} merged) ===")
    print(f"    files fetched: {int(fd or 0):,}   pending: {int(fp or 0):,}")
    cur.execute(f"SELECT COUNT(DISTINCT repo_name) FROM {PRS}"); print(f"    across {cur.fetchone()[0]:,} repos")
    cur.execute(f"SELECT AVG(n_code_files), AVG(n_specdir_files), SUM(n_code_files>0), COUNT(*) FROM {PRS} WHERE files_status='done'")
    ac,ao,wc,tot = cur.fetchone()
    if tot: print(f"    per PR avg: {float(ao or 0):.1f} spec-dir files, {float(ac or 0):.1f} code files; "
                  f"{int(wc or 0):,}/{tot:,} PRs ({100*(wc or 0)/tot:.0f}%) touch >=1 code file")
    cur.execute(f"SELECT COUNT(*) FROM {PRF}"); print(f"    {PRF} rows: {cur.fetchone()[0]:,}")
    cur.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", default="openspec")
    ap.add_argument("--seed", action="store_true"); ap.add_argument("--discover", action="store_true")
    ap.add_argument("--rollup", action="store_true"); ap.add_argument("--status", action="store_true")
    ap.add_argument("--limit", type=int, default=None); ap.add_argument("--workers", type=int, default=WORKERS)
    args = ap.parse_args()
    set_tool(args.tool)
    conn = f.get_db_connection(DB); ensure_schema(conn)
    if args.seed: seed(conn); conn.close(); return
    if args.rollup: rollup(conn); status(conn); conn.close(); return
    if args.status: status(conn); conn.close(); return
    conn.close()
    rotator = LockedRotator(f.get_github_tokens())
    if args.discover: discover(rotator, args.workers, args.limit)
    else: run_files(rotator, args.workers, args.limit)
    conn = f.get_db_connection(DB); status(conn); conn.close()


if __name__ == "__main__":
    main()
