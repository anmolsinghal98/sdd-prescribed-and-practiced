#!/usr/bin/env python3
"""
Traceability layer for the KEPT spec files — link each spec to the artifacts
around it (PRs, issues, sibling docs, code, tool anchors, branches).

The store is an EDGE TABLE `spec_links`: one row per discovered link.

  spec_links(spec_url_sha16, rel, target, provenance)
    rel        : pr | issue | ref | sibling | code | anchor | branch
    target     : the pointed-to thing (#142, path, owner/repo#12, TYPE:ID, branch)
    provenance : how we found it (content | branch_header | commit_msg | tree | ...)

Plus denormalized summary columns on spec_files for fast filtering (rollup()).

This script does the FREE/local work:
  --schema     create spec_links + summary columns
  --phase-a    parse file_content + first/last commit messages -> spec_links
  --rollup     recompute spec_files summary columns from spec_links
  --validate   integrity + coverage checks
  --status     coverage report only

Phase B (per-repo git-tree fetch for authoritative siblings + code) is the
networked crawler fetch_repo_trees.py, which writes into the same table.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

DB_NAME = "specdriven"
KEEP = "not_spec_filter = 0"
TABLE = "spec_links"
BATCH = 4000
TARGET_MAX = 500

SIBLINGS = ("tasks.md", "plan.md", "proposal.md", "design.md",
            "data-model.md", "research.md", "spec-lite.md", "quickstart.md")

# ---- parsing patterns (Phase A) ----
RE_BRANCH = re.compile(r'Feature\s+Branch[*_`\s]*:?[*_`\s]*([0-9A-Za-z][\w./-]{1,80})', re.I)
RE_URL_REF = re.compile(r'github\.com/([\w.-]+/[\w.-]+)/(issues|pull)/(\d+)', re.I)
RE_CODELINK = re.compile(
    r'\]\(\s*(?!https?://|#)([^)\s]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|cpp|cc|c|cs|php|swift|kt|scala|sql|sh))\s*\)',
    re.I)
RE_ANCHOR = re.compile(r'@(SPEC|TEST|CODE|DOC)[:\-]([A-Za-z0-9_.\-]{2,60})')
RE_SIBLINK = re.compile(r'\]\(\s*(?!https?://)([^)\s]*(?:' +
                        "|".join(s.replace(".", r"\.") for s in SIBLINGS) + r'))\s*\)', re.I)
# commit-message signals
RE_MERGE_PR = re.compile(r'Merge pull request #(\d+)', re.I)
RE_PAREN_PR = re.compile(r'\(#(\d+)\)')
RE_ISSUE = re.compile(r'\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[^\n#]{0,20}#(\d+)', re.I)
RE_HASH = re.compile(r'(?:^|[^\w`/])#(\d+)\b')


def add(links, spec, rel, target, prov):
    if target is None:
        return
    t = str(target)[:TARGET_MAX]
    links.add((spec, rel, t, prov))


def parse_spec(spec, path, content, msg_first, msg_last):
    """Return a set of (spec, rel, target, provenance) tuples for one spec."""
    links = set()
    content = content or ""
    # -- content-derived --
    m = RE_BRANCH.search(content)
    if m:
        add(links, spec, "branch", m.group(1).strip("`*"), "branch_header")
    for repo, kind, num in RE_URL_REF.findall(content):
        rel = "pr" if kind.lower() == "pull" else "issue"
        add(links, spec, rel, f"{repo}#{num}", "content")
    for m in RE_CODELINK.finditer(content):
        add(links, spec, "code", m.group(1).lstrip("./"), "content")
    for typ, sid in RE_ANCHOR.findall(content):
        add(links, spec, "anchor", f"{typ.upper()}:{sid}", "content")
    for m in RE_SIBLINK.finditer(content):
        add(links, spec, "sibling", m.group(1).lstrip("./"), "content")
    # -- commit-message-derived (first + last) --
    for msg in (msg_first, msg_last):
        if not msg:
            continue
        prs = set(RE_MERGE_PR.findall(msg)) | set(RE_PAREN_PR.findall(msg))
        issues = set(RE_ISSUE.findall(msg))
        for n in prs:
            add(links, spec, "pr", f"#{n}", "commit_msg")
        for n in issues:
            add(links, spec, "issue", f"#{n}", "commit_msg")
        # bare #N not already classified as pr/issue -> generic ref
        classified = prs | issues
        for n in set(RE_HASH.findall(msg)) - classified:
            add(links, spec, "ref", f"#{n}", "commit_msg")
    return links


# --------------------------------------------------------------------------
def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        spec_url_sha16 CHAR(16) NOT NULL,
        rel VARCHAR(16) NOT NULL,
        target VARCHAR({TARGET_MAX}) NOT NULL,
        provenance VARCHAR(24) NOT NULL,
        UNIQUE KEY uq_link (spec_url_sha16, rel, target, provenance),
        KEY idx_spec (spec_url_sha16),
        KEY idx_rel_target (rel, target(120))
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    # summary columns on spec_files
    cur.execute("""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='spec_files'""")
    have = {r[0] for r in cur.fetchall()}
    cols = [
        ("feature_branch", "VARCHAR(255) NULL"),
        ("n_linked_prs", "INT NULL"), ("n_linked_issues", "INT NULL"),
        ("n_sibling_docs", "INT NULL"), ("n_code_links", "INT NULL"),
        ("has_tasks", "TINYINT NULL"), ("has_plan", "TINYINT NULL"),
        ("has_proposal", "TINYINT NULL"), ("has_design", "TINYINT NULL"),
        ("trace_rollup_at", "VARCHAR(32) NULL"),
    ]
    for name, decl in cols:
        if name not in have:
            cur.execute(f"ALTER TABLE spec_files ADD COLUMN {name} {decl}")
    conn.commit(); cur.close()
    print("schema ready.")


def phase_a(conn):
    # re-runnable: clear only the provenances Phase A owns, then repopulate
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {TABLE} WHERE provenance IN ('content','branch_header','commit_msg')")
    conn.commit()
    print(f"cleared {cur.rowcount:,} prior Phase-A rows.")
    cur.close()

    reader = f.get_db_connection(DB_NAME); reader.autocommit = True
    writer = f.get_db_connection(DB_NAME)
    rcur = reader.cursor()
    ins = (f"INSERT IGNORE INTO {TABLE} (spec_url_sha16, rel, target, provenance) "
           f"VALUES (%s,%s,%s,%s)")
    last = ""
    processed = total_links = 0
    while True:
        rcur.execute(
            f"""SELECT file_url_sha16, file_path, file_content,
                       file_first_commit_message, file_last_commit_message
                FROM spec_files
                WHERE {KEEP} AND file_url_sha16 > %s
                ORDER BY file_url_sha16 LIMIT {BATCH}""", (last,))
        rows = rcur.fetchall()
        if not rows:
            break
        batch_links = []
        for sha, path, content, mf, ml in rows:
            for link in parse_spec(sha, path, content, mf, ml):
                batch_links.append(link)
        if batch_links:
            wcur = writer.cursor()
            wcur.executemany(ins, batch_links)
            writer.commit(); wcur.close()
            total_links += len(batch_links)
        processed += len(rows)
        last = rows[-1][0]
        if processed % 40000 == 0:
            print(f"  parsed {processed:,} specs -> {total_links:,} links so far", flush=True)
    rcur.close(); reader.close(); writer.close()
    print(f"Phase A done: {processed:,} specs parsed, {total_links:,} candidate links inserted.")


def rollup(conn):
    cur = conn.cursor()
    # Aggregate the edge table once, then UPDATE-JOIN onto spec_files.
    cur.execute(f"""
      UPDATE spec_files s
      LEFT JOIN (
        SELECT spec_url_sha16 sp,
          MAX(CASE WHEN rel='branch' THEN target END) feature_branch,
          COUNT(DISTINCT CASE WHEN rel='pr' THEN target END) n_prs,
          COUNT(DISTINCT CASE WHEN rel='issue' THEN target END) n_issues,
          COUNT(DISTINCT CASE WHEN rel='sibling' THEN target END) n_sib,
          COUNT(DISTINCT CASE WHEN rel='code' THEN target END) n_code,
          MAX(rel='sibling' AND target LIKE '%tasks.md') has_tasks,
          MAX(rel='sibling' AND target LIKE '%plan.md') has_plan,
          MAX(rel='sibling' AND target LIKE '%proposal.md') has_proposal,
          MAX(rel='sibling' AND target LIKE '%design.md') has_design
        FROM {TABLE} GROUP BY spec_url_sha16
      ) a ON a.sp = s.file_url_sha16
      SET s.feature_branch = a.feature_branch,
          s.n_linked_prs = COALESCE(a.n_prs,0),
          s.n_linked_issues = COALESCE(a.n_issues,0),
          s.n_sibling_docs = COALESCE(a.n_sib,0),
          s.n_code_links = COALESCE(a.n_code,0),
          s.has_tasks = COALESCE(a.has_tasks,0),
          s.has_plan = COALESCE(a.has_plan,0),
          s.has_proposal = COALESCE(a.has_proposal,0),
          s.has_design = COALESCE(a.has_design,0),
          s.trace_rollup_at = DATE_FORMAT(UTC_TIMESTAMP(),'%Y-%m-%dT%H:%i:%sZ')
      WHERE s.{KEEP}""")
    conn.commit()
    print(f"rollup: updated {cur.rowcount:,} spec_files rows.")
    cur.close()


def status(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
    print(f"\n=== spec_links: {cur.fetchone()[0]:,} total edges ===")
    cur.execute(f"SELECT rel, provenance, COUNT(*) n FROM {TABLE} GROUP BY rel, provenance ORDER BY n DESC")
    print("  by rel / provenance:")
    for rel, prov, n in cur.fetchall():
        print(f"    {rel:<9} {prov:<14} {n:>10,}")
    cur.execute(f"SELECT COUNT(*) FROM spec_files WHERE {KEEP}")
    kept = cur.fetchone()[0]
    print(f"\n=== coverage by tool (% of tool's specs with each link kind) ===")
    cur.execute(f"""
      SELECT s.spec_tool, COUNT(*) n,
        AVG(s.feature_branch IS NOT NULL)*100 branch,
        AVG(s.n_linked_prs>0)*100 pr,
        AVG(s.n_linked_issues>0)*100 issue,
        AVG(s.n_sibling_docs>0)*100 sib,
        AVG(s.has_tasks)*100 tasks
      FROM spec_files s WHERE s.{KEEP} AND s.spec_tool IS NOT NULL
      GROUP BY s.spec_tool ORDER BY n DESC LIMIT 12""")
    print(f"  {'tool':<15}{'specs':>8}{'branch':>8}{'pr':>7}{'issue':>7}{'sibling':>8}{'tasks':>7}")
    for tool, n, br, pr, iss, sib, tsk in cur.fetchall():
        print(f"  {tool:<15}{n:>8,}{float(br):>7.0f}%{float(pr):>6.0f}%{float(iss):>6.0f}%{float(sib):>7.0f}%{float(tsk):>6.0f}%")
    cur.close()


def validate(conn):
    cur = conn.cursor()
    ok = True
    def check(label, val, want):
        nonlocal ok
        good = val == want
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {val:,}" + ("" if good else f" (want {want})"))
    print("\n=== validation ===")
    cur.execute(f"SELECT COUNT(*) FROM {TABLE} l LEFT JOIN spec_files s "
                f"ON s.file_url_sha16=l.spec_url_sha16 WHERE s.file_url_sha16 IS NULL")
    check("orphan links (no matching spec)", cur.fetchone()[0], 0)
    cur.execute(f"SELECT COUNT(*) FROM {TABLE} l JOIN spec_files s "
                f"ON s.file_url_sha16=l.spec_url_sha16 WHERE s.not_spec_filter=1")
    check("links pointing at EXCLUDED specs", cur.fetchone()[0], 0)
    cur.execute(f"""SELECT COUNT(*) FROM (SELECT spec_url_sha16,rel,target,provenance,COUNT(*) c
                    FROM {TABLE} GROUP BY spec_url_sha16,rel,target,provenance HAVING c>1) x""")
    check("duplicate edges", cur.fetchone()[0], 0)
    cur.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE target='' OR target IS NULL")
    check("empty targets", cur.fetchone()[0], 0)
    cur.execute(f"SELECT COUNT(DISTINCT rel) FROM {TABLE}")
    print(f"  [info] distinct rel types: {cur.fetchone()[0]}")
    cur.execute(f"SELECT COUNT(DISTINCT spec_url_sha16) FROM {TABLE}")
    linked = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM spec_files WHERE {KEEP}")
    kept = cur.fetchone()[0]
    print(f"  [info] specs with >=1 link: {linked:,} / {kept:,} ({100*linked/kept:.1f}%)")
    print("  => " + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    cur.close()
    return ok


def main():
    ap = argparse.ArgumentParser(description="Spec traceability edge table (Phase A + schema).")
    ap.add_argument("--schema", action="store_true")
    ap.add_argument("--phase-a", action="store_true")
    ap.add_argument("--rollup", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    conn = f.get_db_connection(DB_NAME)
    if args.schema or args.phase_a:
        ensure_schema(conn)
    if args.phase_a:
        phase_a(conn); rollup(conn)
    if args.rollup:
        rollup(conn)
    if args.status or args.phase_a:
        status(conn)
    if args.validate:
        validate(conn)
    conn.close()


if __name__ == "__main__":
    main()
