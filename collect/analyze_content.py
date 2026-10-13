#!/usr/bin/env python3
"""
Tier-1 deterministic content analysis for the KEPT spec files that have been
fetched (content_fetch_status='done'). Reads file_content, extracts ~40
structural/stylistic features per file with pure regex/markdown parsing (no LLM,
no network), and writes one row per file into spec_content_features.

Everything here is census-scale and free: it runs over the whole fetched corpus.
Resumable — only files not yet in the features table are processed — so it can be
run now against the partial fetch and re-run when the crawl completes.

Features captured:
  * size/shape     : bytes, lines, words, headings, max heading depth
  * markdown rich  : code fences, mermaid, tables, links, images, list items,
                     checkboxes (+ checked)
  * requirement    : EARS "shall", Gherkin WHEN/THEN, user-story, OpenSpec
    style             #### Scenario:, delta headers (ADDED/MODIFIED/REMOVED)
  * sections       : presence of Requirements / Acceptance Criteria / User
                     Scenarios / Non-goals / Out of scope / Overview / Success
                     Criteria / Edge cases / Open questions / Dependencies / Purpose
  * quality/stub   : [NEEDS CLARIFICATION], TODO/TBD/FIXME, leftover *(mandatory)*,
                     lorem-ipsum, tiny/near-empty, unfilled-placeholder
  * language       : detected natural language (langdetect)
  * content_family : tool guessed from CONTENT markers (to compare vs path)

Usage:
  python3 analyze_content.py                 # analyze all 'done' rows (resumable)
  python3 analyze_content.py --reset         # drop + rebuild the features table
  python3 analyze_content.py --summary       # print aggregate summary, no compute
  python3 analyze_content.py --limit 5000
"""
import argparse
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0            # deterministic
    _HAS_LANG = True
except Exception:
    _HAS_LANG = False

DB_NAME = "specdriven"
KEEP = "not_spec_filter = 0"
TABLE = "spec_content_features"
BATCH = 4000

# ---- feature schema: (column, sql_type). Order == the tuple extract() returns. ----
FEATURES = [
    ("n_bytes", "INT"), ("n_lines", "INT"), ("n_words", "INT"),
    ("n_headings", "INT"), ("max_heading_depth", "INT"),
    ("n_code_fences", "INT"), ("n_mermaid", "INT"), ("n_tables", "INT"),
    ("n_links", "INT"), ("n_images", "INT"),
    ("n_list_items", "INT"), ("n_checkboxes", "INT"), ("n_checked", "INT"),
    ("n_shall", "INT"), ("n_gherkin", "INT"),
    ("n_scenario_blocks", "INT"), ("n_delta_headers", "INT"),
    ("n_needs_clarification", "INT"), ("n_todo", "INT"),
    ("has_ears", "TINYINT"), ("has_gherkin", "TINYINT"), ("has_user_story", "TINYINT"),
    ("has_requirements", "TINYINT"), ("has_acceptance_criteria", "TINYINT"),
    ("has_user_scenarios", "TINYINT"), ("has_non_goals", "TINYINT"),
    ("has_out_of_scope", "TINYINT"), ("has_overview", "TINYINT"),
    ("has_success_criteria", "TINYINT"), ("has_edge_cases", "TINYINT"),
    ("has_open_questions", "TINYINT"), ("has_dependencies", "TINYINT"),
    ("has_purpose", "TINYINT"), ("has_mandatory_marker", "TINYINT"),
    ("is_tiny", "TINYINT"), ("has_unfilled_placeholder", "TINYINT"), ("has_lorem", "TINYINT"),
    ("lang", "VARCHAR(8)"), ("content_family", "VARCHAR(24)"),
]
FCOLS = [c for c, _ in FEATURES]

# ---- precompiled patterns ----
RE_HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$', re.M)
RE_FENCE = re.compile(r'^```', re.M)
RE_MERMAID = re.compile(r'^```\s*mermaid', re.M | re.I)
RE_TABLE_SEP = re.compile(r'^\s*\|?[\s:]*-{2,}[-\s:|]*\|', re.M)
RE_LINK = re.compile(r'(?<!\!)\[[^\]]+\]\([^)]+\)')
RE_IMG = re.compile(r'!\[[^\]]*\]\([^)]+\)')
RE_LIST = re.compile(r'^\s*[-*+]\s+', re.M)
RE_CHECKBOX = re.compile(r'^\s*[-*+]\s+\[([ xX])\]', re.M)
RE_SHALL = re.compile(r'\bshall\b', re.I)
RE_GHERKIN = re.compile(r'(?im)^\s*[-*>]?\s*\**\s*(WHEN|THEN|GIVEN)\b')
RE_USERSTORY = re.compile(r'(?i)\bas an?\b[^\n]{0,60}\bi want\b')
RE_SCENARIO = re.compile(r'(?im)^#{2,4}\s+scenario\b')
RE_DELTA = re.compile(r'(?im)^#{1,3}\s+(ADDED|MODIFIED|REMOVED|RENAMED)\b')
RE_NEEDS = re.compile(r'\[NEEDS[ _]CLARIFICATION', re.I)
RE_TODO = re.compile(r'\b(TODO|TBD|FIXME)\b')
RE_MANDATORY = re.compile(r'\*\(mandatory\)\*', re.I)
RE_LOREM = re.compile(r'lorem ipsum', re.I)
RE_URL = re.compile(r'https?://\S+')


def _norm(h):
    return re.sub(r'[`*_]', '', h).strip().lower()


def guess_family(text_l, n_scenario, n_delta, has_mandatory):
    if n_scenario and n_delta:
        return "openspec"
    if has_mandatory or "user scenarios & testing" in text_l:
        return "speckit"
    if "requested changes (diff)" in text_l or "## implementation plan" in text_l and "## specification" in text_l:
        return "caffeine"
    if "@spec:" in text_l or "requirements (ears format)" in text_l:
        return "moai"
    if "expected deliverable" in text_l and "spec scope" in text_l:
        return "agent_os"
    if n_delta:
        return "openspec"
    return "unknown"


def extract(text):
    """Return a tuple matching FCOLS from raw markdown text."""
    n_bytes = len(text.encode("utf-8", "replace"))
    n_lines = text.count("\n") + 1
    words = text.split()
    n_words = len(words)
    headings = [(len(m.group(1)), _norm(m.group(2))) for m in RE_HEADING.finditer(text)]
    heads = {h for _, h in headings}
    n_headings = len(headings)
    max_depth = max((lvl for lvl, _ in headings), default=0)

    n_code_fences = len(RE_FENCE.findall(text)) // 2
    n_mermaid = len(RE_MERMAID.findall(text))
    n_tables = len(RE_TABLE_SEP.findall(text))
    n_links = len(RE_LINK.findall(text))
    n_images = len(RE_IMG.findall(text))
    n_list = len(RE_LIST.findall(text))
    checks = RE_CHECKBOX.findall(text)
    n_checkboxes = len(checks)
    n_checked = sum(1 for c in checks if c in "xX")

    n_shall = len(RE_SHALL.findall(text))
    n_gherkin = len(RE_GHERKIN.findall(text))
    n_scenario = len(RE_SCENARIO.findall(text))
    n_delta = len(RE_DELTA.findall(text))
    n_needs = len(RE_NEEDS.findall(text))
    n_todo = len(RE_TODO.findall(text))

    def has(sub):  # any heading containing substring
        return int(any(sub in h for h in heads))

    has_mandatory = int(bool(RE_MANDATORY.search(text)))
    text_l = text.lower()

    row = [
        n_bytes, n_lines, n_words, n_headings, max_depth,
        n_code_fences, n_mermaid, n_tables, n_links, n_images,
        n_list, n_checkboxes, n_checked,
        n_shall, n_gherkin, n_scenario, n_delta, n_needs, n_todo,
        int(n_shall > 0), int(n_gherkin > 0), int(bool(RE_USERSTORY.search(text)) or has("user stor")),
        has("requirement"), has("acceptance criteria"),
        int(has("user scenario") or has("user stor")), int(has("non-goal") or has("non goals")),
        has("out of scope"), has("overview"), has("success criteria"),
        has("edge case"), has("open question"), has("dependenc"), has("purpose"),
        has_mandatory,
        int(n_words < 30), int(n_needs > 0 or n_todo > 0), int(bool(RE_LOREM.search(text))),
    ]
    # language (on de-URL'd, de-fenced sample for accuracy)
    lang = "na"
    if _HAS_LANG and n_words >= 5:
        sample = RE_URL.sub(" ", text)[:2000]
        try:
            lang = detect(sample)
        except Exception:
            lang = "unknown"
    row.append(lang)
    row.append(guess_family(text_l, n_scenario, n_delta, has_mandatory))
    return tuple(row)


def _extract_kv(item):
    fid, text = item
    return fid, extract(text or "")


def ensure_table(conn, drop=False):
    cur = conn.cursor()
    if drop:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE}")
    cols = ",\n  ".join(f"{c} {t}" for c, t in FEATURES)
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        file_url_sha16 CHAR(16) NOT NULL PRIMARY KEY,
        {cols}
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    conn.commit(); cur.close()


def build(limit, workers):
    reader = f.get_db_connection(DB_NAME); reader.autocommit = True
    writer = f.get_db_connection(DB_NAME)
    rcur = reader.cursor()
    placeholders = ",".join(["%s"] * (1 + len(FCOLS)))
    insert = (f"REPLACE INTO {TABLE} (file_url_sha16, {', '.join(FCOLS)}) "
              f"VALUES ({placeholders})")
    processed = 0
    pool = ProcessPoolExecutor(max_workers=workers)
    while True:
        take = BATCH if limit is None else min(BATCH, limit - processed)
        if take <= 0:
            break
        rcur.execute(
            f"""SELECT s.file_url_sha16, s.file_content
                FROM spec_files s
                LEFT JOIN {TABLE} t ON t.file_url_sha16 = s.file_url_sha16
                WHERE s.{KEEP} AND s.content_fetch_status='done'
                  AND s.file_content IS NOT NULL AND t.file_url_sha16 IS NULL
                LIMIT {take}""")
        rows = rcur.fetchall()
        if not rows:
            break
        results = list(pool.map(_extract_kv, rows, chunksize=200))
        wcur = writer.cursor()
        wcur.executemany(insert, [(fid, *feats) for fid, feats in results])
        writer.commit(); wcur.close()
        processed += len(rows)
        print(f"  analyzed {processed:,}", flush=True)
    pool.shutdown()
    rcur.close(); reader.close(); writer.close()
    print(f"FINISHED. analyzed {processed:,} files.")


def summary(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
    n = cur.fetchone()[0]
    if not n:
        print("features table empty."); return
    print(f"\n=== content features summary ({n:,} files analyzed) ===")
    aggs = [
        ("median words", "SELECT AVG(x) FROM (SELECT n_words x FROM {t} ORDER BY n_words LIMIT 2 OFFSET (SELECT COUNT(*)/2 FROM {t})) z"),
    ]
    # simple prevalence table
    flags = ["has_ears", "has_gherkin", "has_user_story", "has_requirements",
             "has_acceptance_criteria", "has_user_scenarios", "has_out_of_scope",
             "has_mandatory_marker", "is_tiny", "has_unfilled_placeholder"]
    sel = ", ".join(f"AVG({c})*100" for c in flags)
    cur.execute(f"SELECT {sel} FROM {TABLE}")
    vals = cur.fetchone()
    print("  prevalence (% of files):")
    for name, v in zip(flags, vals):
        print(f"    {name:<26} {float(v):5.1f}%")
    cur.execute(f"SELECT AVG(n_words), AVG(n_headings), AVG(n_shall), AVG(n_scenario_blocks) FROM {TABLE}")
    w, h, sh, sc = cur.fetchone()
    print(f"  avg words={float(w):.0f}  headings={float(h):.1f}  shall={float(sh):.2f}  scenario_blocks={float(sc):.2f}")
    cur.execute(f"SELECT lang, COUNT(*) c FROM {TABLE} GROUP BY lang ORDER BY c DESC LIMIT 8")
    print("  top languages:", ", ".join(f"{l}:{c:,}" for l, c in cur.fetchall()))
    cur.execute(f"SELECT content_family, COUNT(*) c FROM {TABLE} GROUP BY content_family ORDER BY c DESC")
    print("  content_family:", ", ".join(f"{fam}:{c:,}" for fam, c in cur.fetchall()))
    cur.close()


def main():
    ap = argparse.ArgumentParser(description="Tier-1 deterministic content features (resumable).")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    conn = f.get_db_connection(DB_NAME)
    ensure_table(conn, drop=args.reset)
    if args.summary:
        summary(conn); conn.close(); return
    conn.close()
    if not _HAS_LANG:
        print("WARN: langdetect not available; lang will be 'na'.")
    build(args.limit, args.workers)
    conn = f.get_db_connection(DB_NAME)
    summary(conn); conn.close()


if __name__ == "__main__":
    main()
