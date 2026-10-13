#!/usr/bin/env python3
"""Kiro census enrichment — brings kiro_files to parity with the broad census
so that "each spec is enriched with full repository metadata, complete commit
history, and parsed document structure" holds for the Kiro census too (v1.1).

Four resumable phases (run in order):
  --phase repos     GET /repos/{name} for the 12,910 distinct Kiro repos -> kiro_repos
  --phase content   GET git_url (blobs API, raw accept) for 98,574 artifacts
                    -> file_content/_sha/_bytes on kiro_files (exact July blobs:
                    the stored blob sha pins the snapshot content)
  --phase commits   GET /repos/{r}/commits?path=... (paginated) -> kiro_file_commits
                    + file_total_commits/commit_history_status on kiro_files
  --phase features  parse 39 structural features locally -> kiro_content_features

Reuses: fetch_spec_files (tokens/DB), fetch_commit_history (rotator, commit
pagination + parsing), analyze_content (the 39-feature extractor).

Usage:
  python3 kiro_enrich.py --phase repos [--limit N] [--workers K]
  python3 kiro_enrich.py --status
"""
import argparse, hashlib, logging, sys, threading, time
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f
import fetch_commit_history as fch
import analyze_content as ac

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DB = "specdriven"
MAX_BYTES = 2_000_000
# Snapshot parity: the broad census's commit-history crawl finished at this
# instant (MAX(spec_files.commit_history_fetched_at)). Kiro histories are
# fetched with `until=` this timestamp so both censuses end at the same point.
COMMIT_CUTOFF = "2026-07-11T18:47:37Z"
_tl = threading.local()

def conn():
    if getattr(_tl, "c", None) is None:
        _tl.c = f.get_db_connection(DB)
    return _tl.c

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------- schema
REPO_COLS = [
 ("repo_id","BIGINT"),("repo_node_id","VARCHAR(255)"),("repo_url","TEXT"),
 ("repo_homepage","TEXT"),("repo_description","TEXT"),("repo_fork","TINYINT(1)"),
 ("repo_visibility","VARCHAR(32)"),("owner_login","VARCHAR(255)"),("owner_id","BIGINT"),
 ("owner_type","VARCHAR(64)"),("repo_stars","INT"),("repo_forks","INT"),
 ("repo_watchers","INT"),("repo_open_issues","INT"),("repo_size_kb","INT"),
 ("repo_language","VARCHAR(128)"),("repo_license_key","VARCHAR(64)"),
 ("repo_license_spdx_id","VARCHAR(64)"),("repo_default_branch","VARCHAR(255)"),
 ("repo_topics","TEXT"),("repo_archived","TINYINT(1)"),("repo_disabled","TINYINT(1)"),
 ("repo_is_template","TINYINT(1)"),("repo_created_at","VARCHAR(64)"),
 ("repo_updated_at","VARCHAR(64)"),("repo_pushed_at","VARCHAR(64)"),
]

def ensure_schema(c):
    cur = c.cursor()
    cols = ",\n  ".join(f"{n} {t}" for n, t in REPO_COLS)
    cur.execute(f"""CREATE TABLE IF NOT EXISTS kiro_repos (
      repo_name VARCHAR(511) PRIMARY KEY,
      {cols},
      fetch_status VARCHAR(16), fetched_at VARCHAR(64)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cur.execute("SHOW COLUMNS FROM kiro_files")
    have = {r[0] for r in cur.fetchall()}
    for name, ddl in [("file_content","LONGTEXT"),("file_content_sha","CHAR(64)"),
                      ("file_content_bytes","INT"),("content_fetch_status","VARCHAR(16)"),
                      ("file_total_commits","INT"),("commit_history_status","VARCHAR(16)")]:
        if name not in have:
            cur.execute(f"ALTER TABLE kiro_files ADD COLUMN {name} {ddl}")
    cur.execute("""CREATE TABLE IF NOT EXISTS kiro_file_commits (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      kiro_file_id BIGINT NOT NULL,
      repo_name VARCHAR(511), file_path TEXT,
      seq_from_oldest INT, commit_sha VARCHAR(64),
      authored_at VARCHAR(64), author_name TEXT, author_email VARCHAR(512),
      author_login VARCHAR(255), author_id BIGINT,
      committed_at VARCHAR(64), committer_name TEXT, committer_email VARCHAR(512),
      committer_login VARCHAR(255), committer_id BIGINT,
      message LONGTEXT, html_url TEXT,
      KEY k_file (kiro_file_id)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    fcols = ",\n  ".join(f"{n} {t}" for n, t in ac.FEATURES)
    cur.execute(f"""CREATE TABLE IF NOT EXISTS kiro_content_features (
      kiro_file_id BIGINT PRIMARY KEY,
      {fcols}
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    c.commit(); cur.close()

# ---------------------------------------------------------------- phase: repos
def fetch_repo(rot, name):
    code, js = fch._get(rot, f"{f.GITHUB_API}/repos/{name}", {})
    if code != 200 or js is None:
        return name, None, ("missing" if code in (404, 451) else "error")
    lic = js.get("license") or {}
    own = js.get("owner") or {}
    vals = dict(repo_id=js.get("id"), repo_node_id=js.get("node_id"),
        repo_url=js.get("html_url"), repo_homepage=js.get("homepage"),
        repo_description=js.get("description"), repo_fork=int(bool(js.get("fork"))),
        repo_visibility=js.get("visibility"), owner_login=own.get("login"),
        owner_id=own.get("id"), owner_type=own.get("type"),
        repo_stars=js.get("stargazers_count"), repo_forks=js.get("forks_count"),
        repo_watchers=js.get("watchers_count"), repo_open_issues=js.get("open_issues_count"),
        repo_size_kb=js.get("size"), repo_language=js.get("language"),
        repo_license_key=lic.get("key"), repo_license_spdx_id=lic.get("spdx_id"),
        repo_default_branch=js.get("default_branch"),
        repo_topics=",".join(js.get("topics") or []),
        repo_archived=int(bool(js.get("archived"))), repo_disabled=int(bool(js.get("disabled"))),
        repo_is_template=int(bool(js.get("is_template"))),
        repo_created_at=js.get("created_at"), repo_updated_at=js.get("updated_at"),
        repo_pushed_at=js.get("pushed_at"))
    return name, vals, "done"

def phase_repos(rot, limit, workers):
    c = f.get_db_connection(DB); cur = c.cursor()
    cur.execute("""SELECT DISTINCT k.repo_name FROM kiro_files k
                   LEFT JOIN kiro_repos r ON r.repo_name = k.repo_name
                   WHERE r.repo_name IS NULL OR r.fetch_status = 'error'""")
    todo = [r[0] for r in cur.fetchall()]
    if limit: todo = todo[:limit]
    logging.info("repos to fetch: %d", len(todo))
    done = [0]
    def work(name):
        n, vals, st = fetch_repo(rot, name)
        lc = conn(); k = lc.cursor()
        if vals is None:
            k.execute("REPLACE INTO kiro_repos (repo_name, fetch_status, fetched_at) VALUES (%s,%s,%s)",
                      (n, st, now()))
        else:
            cols = list(vals.keys())
            sql = (f"REPLACE INTO kiro_repos (repo_name,{','.join(cols)},fetch_status,fetched_at) "
                   f"VALUES ({','.join(['%s']*(len(cols)+3))})")
            k.execute(sql, [n] + [vals[x] for x in cols] + [st, now()])
        lc.commit(); k.close()
        done[0] += 1
        if done[0] % 500 == 0: logging.info("repos: %d/%d", done[0], len(todo))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    logging.info("phase repos complete: %d", len(todo))

# ---------------------------------------------------------------- phase: content
def raw_blob(rot, git_url):
    """Fetch a blob's raw bytes via the git blobs API url (token-bound fallback)."""
    for _ in range(rot.n * f.MAX_RETRIES):
        headers = {"Authorization": f"Bearer {rot.next_token()}",
                   "Accept": "application/vnd.github.raw+json"}
        try:
            resp = requests.get(git_url, headers=headers, timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(3); continue
        if resp.status_code == 200:
            return resp.content, "done"
        if resp.status_code in (403, 429):
            time.sleep(2); continue
        if resp.status_code in (404, 409, 451):
            return None, "missing"
        time.sleep(2)
    return None, "error"

def cdn_blob(rot, html_url, git_url):
    """Fetch content from the raw CDN (no token, no rate limit) via the pinned
    commit sha in html_url: github.com/{r}/blob/{sha}/{p} ->
    raw.githubusercontent.com/{r}/{sha}/{p}. Falls back to the blobs API when
    the CDN cannot serve it (e.g. commit gone but blob alive)."""
    raw_url = html_url.replace("https://github.com/", "https://raw.githubusercontent.com/", 1)\
                      .replace("/blob/", "/", 1)
    for attempt in range(3):
        try:
            resp = requests.get(raw_url, timeout=25)
        except requests.exceptions.RequestException:
            time.sleep(2); continue
        if resp.status_code == 200:
            return resp.content, "done"
        if resp.status_code in (404, 410, 451):
            return raw_blob(rot, git_url)      # CDN miss -> API by blob sha
        if resp.status_code == 429:
            time.sleep(10); continue
        time.sleep(2)
    return raw_blob(rot, git_url)

def phase_content(rot, limit, workers):
    c = f.get_db_connection(DB); cur = c.cursor()
    cur.execute("""SELECT id, html_url, git_url FROM kiro_files
                   WHERE content_fetch_status IS NULL OR content_fetch_status='error'""")
    todo = cur.fetchall()
    if limit: todo = todo[:limit]
    logging.info("contents to fetch: %d", len(todo))
    done = [0]
    def work(row):
        fid, html_url, git_url = row
        data, st = cdn_blob(rot, html_url, git_url)
        lc = conn()
        if getattr(_tl, "pcur", None) is None:
            _tl.pcur = lc.cursor(prepared=True)
        k = _tl.pcur
        if data is None:
            k.execute("UPDATE kiro_files SET content_fetch_status=%s WHERE id=%s", (st, fid))
        else:
            if len(data) > MAX_BYTES:
                data = data[:MAX_BYTES]; st = "toobig"
            sha = hashlib.sha256(data).hexdigest()
            text = data.decode("utf-8", "replace")
            k.execute("""UPDATE kiro_files SET file_content=%s, file_content_sha=%s,
                         file_content_bytes=%s, content_fetch_status=%s WHERE id=%s""",
                      (text, sha, len(data), st, fid))
        lc.commit()
        done[0] += 1
        if done[0] % 2000 == 0: logging.info("content: %d/%d", done[0], len(todo))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    logging.info("phase content complete: %d", len(todo))

# ---------------------------------------------------------------- phase: commits
def fetch_path_commits_until(rot, repo_full_name, file_path):
    """fch.fetch_path_commits with `until=COMMIT_CUTOFF`: same pagination and
    status semantics, but the API only returns commits whose commit date is at
    or before the broad census's crawl end."""
    url = f"{f.GITHUB_API}/repos/{repo_full_name}/commits"
    items_all, page = [], 1
    while True:
        code, items = fch._get(rot, url, {"path": file_path, "per_page": fch.PER_PAGE,
                                          "page": page, "until": COMMIT_CUTOFF})
        if code != 200:
            if code in (404, 409, 451) and page == 1:
                return [], "empty"
            if items is None and page == 1:
                return [], "error"
            break
        if not items:
            break
        items_all.extend(items)
        if len(items) < fch.PER_PAGE:
            break
        page += 1
        if page > fch.MAX_COMMIT_PAGES:
            return items_all, "truncated"
    return items_all, ("done" if items_all else "empty")

def phase_commits(rot, limit, workers):
    c = f.get_db_connection(DB); cur = c.cursor()
    cur.execute("""SELECT id, repo_name, file_path FROM kiro_files
                   WHERE commit_history_status IS NULL OR commit_history_status='error'""")
    todo = cur.fetchall()
    if limit: todo = todo[:limit]
    logging.info("commit histories to fetch: %d", len(todo))
    done = [0]
    import random
    import mysql.connector
    def persist(fid, repo, path, commits, st):
        """One file's transaction, retried on InnoDB deadlock (error 1213)."""
        for attempt in range(6):
            lc = conn(); k = lc.cursor(prepared=True)
            try:
                k.execute("DELETE FROM kiro_file_commits WHERE kiro_file_id=%s", (fid,))
                for i, node in enumerate(reversed(commits), start=1):
                    p = fch.parse_commit(node)
                    k.execute("""INSERT INTO kiro_file_commits
                      (kiro_file_id, repo_name, file_path, seq_from_oldest, commit_sha,
                       authored_at, author_name, author_email, author_login, author_id,
                       committed_at, committer_name, committer_email, committer_login,
                       committer_id, message, html_url)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (fid, repo, path, i, p.get("sha"),
                       p.get("at"), p.get("author"), p.get("author_email"),
                       p.get("author_login"), p.get("author_id"),
                       p.get("committer_at"), p.get("committer"), p.get("committer_email"),
                       p.get("committer_login"), p.get("committer_id"),
                       p.get("message"), p.get("html_url")))
                k.execute("UPDATE kiro_files SET file_total_commits=%s, commit_history_status=%s WHERE id=%s",
                          (len(commits), st, fid))
                lc.commit(); k.close()
                return
            except mysql.connector.Error as e:
                k.close()
                try: lc.rollback()
                except Exception: pass
                if getattr(e, "errno", None) in (1213, 1205) and attempt < 5:
                    time.sleep(0.2 + random.random() * (attempt + 1))
                    continue
                raise
    def work(row):
        fid, repo, path = row
        try:
            commits, st = fetch_path_commits_until(rot, repo, path)
            persist(fid, repo, path, commits, st)
        except Exception as e:
            logging.warning("commits worker failed for %s %s: %s", repo, path, e)
            try:
                lc = conn(); k = lc.cursor()
                k.execute("UPDATE kiro_files SET commit_history_status='error' WHERE id=%s", (fid,))
                lc.commit(); k.close()
            except Exception:
                pass
        done[0] += 1
        if done[0] % 1000 == 0: logging.info("commits: %d/%d", done[0], len(todo))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    logging.info("phase commits complete: %d", len(todo))

# ---------------------------------------------------------------- phase: features
def phase_features(limit):
    """Paged by id (short queries) rather than one long streaming SELECT, which
    MySQL kills with 'Lost connection' when the read outlives net timeouts."""
    rc = f.get_db_connection(DB); rcur = rc.cursor()
    wc = f.get_db_connection(DB); wk = wc.cursor(prepared=True)
    cols = ",".join(ac.FCOLS)
    ph = ",".join(["%s"] * (len(ac.FCOLS) + 1))
    n, last_id = 0, 0
    while True:
        rcur.execute("""SELECT k.id, k.file_content FROM kiro_files k
                        LEFT JOIN kiro_content_features cf ON cf.kiro_file_id = k.id
                        WHERE k.id > %s AND k.file_content IS NOT NULL
                          AND cf.kiro_file_id IS NULL
                        ORDER BY k.id LIMIT 1000""", (last_id,))
        rows = rcur.fetchall()
        if not rows: break
        for fid, text in rows:
            vals = ac.extract(text or "")
            wk.execute(f"REPLACE INTO kiro_content_features (kiro_file_id,{cols}) VALUES ({ph})",
                       (fid, *vals))
            n += 1
            last_id = fid
            if limit and n >= limit: break
        wc.commit()
        if n % 10000 < 1000: logging.info("features: %d", n)
        if limit and n >= limit: break
    wc.commit()
    logging.info("phase features complete: %d", n)

# ---------------------------------------------------------------- status / main
def status():
    c = f.get_db_connection(DB); cur = c.cursor()
    def one(q): cur.execute(q); return cur.fetchone()[0]
    print("kiro_repos          :", f"{one('SELECT COUNT(*) FROM kiro_repos'):,}",
          "done:", one("SELECT COUNT(*) FROM kiro_repos WHERE fetch_status='done'"))
    print("content done        :", f"{one(chr(39).join(['SELECT COUNT(*) FROM kiro_files WHERE content_fetch_status=','done',''])):,}")
    print("content missing/err :", one("SELECT COUNT(*) FROM kiro_files WHERE content_fetch_status IN ('missing','error','toobig')"))
    print("commits done        :", f"{one(chr(39).join(['SELECT COUNT(*) FROM kiro_files WHERE commit_history_status=','done',''])):,}")
    print("kiro_file_commits   :", f"{one('SELECT COUNT(*) FROM kiro_file_commits'):,}")
    print("features            :", f"{one('SELECT COUNT(*) FROM kiro_content_features'):,}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["repos", "content", "commits", "features"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    c = f.get_db_connection(DB)
    ensure_schema(c)
    if args.status:
        status(); return
    rot = fch.LockedRotator(f.get_github_tokens())
    logging.info("tokens: %d, workers: %d, phase: %s", rot.n, args.workers, args.phase)
    if args.phase == "repos":    phase_repos(rot, args.limit, args.workers)
    elif args.phase == "content": phase_content(rot, args.limit, args.workers)
    elif args.phase == "commits": phase_commits(rot, args.limit, args.workers)
    elif args.phase == "features": phase_features(args.limit)
    status()

if __name__ == "__main__":
    main()
