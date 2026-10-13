#!/usr/bin/env python3
"""
Classify spec_files rows. This never deletes: it sets

  not_spec_filter = 1 | 0    (1 = excluded / not an SDD spec, 0 = keep)
  not_spec_notes  = <reason> (the category label; set for BOTH excluded and
                              kept-but-tagged rows so raw vs cleaned is auditable)

Two kinds of rule:
  * EXCLUDE  (flag=1): the file is not the repo's own SDD spec at all
                       (e.g. spack package-cache, vendored deps) -> filter=1.
  * ANNOTATE (flag=0): the file IS a genuine spec but belongs to a distinct
                       category worth tagging (e.g. AI-generator output) -> kept
                       (filter=0) but labelled in notes for later analysis.

Rules are added ONE AT A TIME as each cleaning issue is confirmed. Running the
script re-applies every currently-defined rule idempotently (first-match-wins:
a row already carrying a note is never re-touched), then prints a summary.

Usage:
  python3 classify_specs.py            # apply all defined rules + report
  python3 classify_specs.py --report   # report only, apply nothing
  python3 classify_specs.py --reset     # clear all flags/notes (start over)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

# --------------------------------------------------------------------------
# Rules — each confirmed cleaning issue becomes one entry here.
# `where`  : a raw SQL predicate over spec_files.
# `reason` : the category label written to not_spec_notes.
# `flag`   : 1 = EXCLUDE (not an SDD spec), 0 = ANNOTATE-but-keep. Default 1.
# NOTE: in SQL LIKE, `_` is a wildcard, so a literal underscore must be escaped
# as `\_` (e.g. '%\\_cache/%' matches the literal "_cache/").
# --------------------------------------------------------------------------
RULES = [
    {
        "reason": "package_cache",
        "flag": 1,
        "desc": "spack/cache.spack.io — the whole repo is a package-build-cache mirror "
                "(bot-committed 'specs.md' where 'spec' = a Spack package build spec, not SDD). "
                "All 97,757 files live under _cache/<branch>/; matching the repo is exact and "
                "avoids both missing non-'develop-' prefixes and catching coincidental '_cache' "
                "substrings elsewhere.",
        "where": r"repo_name = 'spack/cache.spack.io' "
                 r"AND file_path LIKE '%\_cache/%' "
                 r"AND LOWER(file_name) IN ('spec.md','specs.md')",
    },
    {
        "reason": "vendored_dependency",
        "flag": 1,
        "desc": "A dependency's OWN spec file, vendored into the repo (not authored by the "
                "repo owner) — e.g. vendor/bitflags/spec.md, node_modules/.../spec.md. "
                "Restricted to genuine vendored-dep dirs and excludes tool-convention paths "
                "(so a capability literally named 'vendor'/'build' inside openspec/ etc. is safe).",
        "where": (
            "("
            "  file_path LIKE '%node_modules/%' OR file_path LIKE '%vendor/%' "
            "  OR file_path LIKE '%site-packages/%' OR file_path LIKE '%venv/%' "
            "  OR file_path LIKE '%.tox/%' OR file_path LIKE '%.nox/%' "
            "  OR file_path LIKE '%third_party/%' OR file_path LIKE '%third-party/%' "
            "  OR file_path LIKE '%bower_components/%'"
            ") AND NOT ("
            "  file_path LIKE 'openspec/%' OR file_path LIKE '%/openspec/%' "
            "  OR file_path LIKE '%.specify/%' OR file_path REGEXP 'specs/[0-9]{3}' "
            "  OR file_path LIKE '%.claude/%' OR file_path LIKE '%.opencode/%' "
            "  OR file_path LIKE '%.trae/%' OR file_path LIKE '%.moai/%' "
            "  OR file_path LIKE '%.cursor/%' OR file_path LIKE '%.kilocode/%' "
            "  OR file_path LIKE 'conductor/%'"
            ")"
        ),
    },
    {
        "reason": "ai_generator_farm",
        "flag": 0,  # ANNOTATE, not exclude: these ARE genuine specs, just machine-authored.
        "desc": "caffeinepub — the GitHub org of the caffeine.ai app-generator. 14,262 spec.md / "
                "src/spec.md files across 13,749 auto-created one-app repos (all commit authors "
                "unlinked, bot-template commit messages, ~0 stars). Kept (they ARE spec docs) but "
                "tagged so AI-generated specs can be separated from human-authored SDD in analysis.",
        "where": "owner_login = 'caffeinepub'",
    },
    {
        "reason": "pre_2024",
        "flag": 1,
        "desc": "First commit predates 2024-01. The file is named spec.md/specs.md but was "
                "created before the spec-driven-development tooling era (Spec Kit / OpenSpec "
                "emerged ~2024-2025), so it is almost always a coincidental protocol / package / "
                "format spec, not an SDD artifact. ~6,705 files, oldest back to 2009. Requires "
                "Phase-2 commit history (file_first_commit_at); rows without history are left alone.",
        "where": "file_first_commit_at IS NOT NULL AND file_first_commit_at < '2024-01'",
    },
    # Issue #5, ... appended here as confirmed.
]


def ensure_columns(conn):
    cur = conn.cursor()
    cur.execute(
        """SELECT COLUMN_NAME FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='spec_files'
           AND COLUMN_NAME IN ('not_spec_filter','not_spec_notes')"""
    )
    have = {r[0] for r in cur.fetchall()}
    if "not_spec_filter" not in have:
        cur.execute("ALTER TABLE spec_files ADD COLUMN not_spec_filter TINYINT(1) NOT NULL DEFAULT 0")
    if "not_spec_notes" not in have:
        cur.execute("ALTER TABLE spec_files ADD COLUMN not_spec_notes VARCHAR(255) NULL")
    conn.commit()
    cur.close()


def apply_rule(conn, rule):
    """Tag rows matching rule['where'] with rule['reason']; return #newly-tagged.

    `reason` is a trusted constant from RULES (kept to [a-z0-9_]), so it's inlined
    directly. We pass NO bound params: the WHERE clauses contain many literal `%`
    (LIKE patterns, e.g. '%site-packages/%') which mysql-connector would otherwise
    try to read as `%s` placeholders.

    `flag` (1=exclude, 0=annotate-keep) sets not_spec_filter. First-match-wins is
    keyed on not_spec_notes IS NULL (NOT on the filter value) so that an
    annotate-keep rule, which leaves filter=0, still marks its rows as processed
    and later rules won't overwrite them.
    """
    reason = rule["reason"]
    flag = int(rule.get("flag", 1))
    if not all(c.isalnum() or c == "_" for c in reason):
        raise ValueError(f"unsafe reason to inline: {reason!r}")
    if flag not in (0, 1):
        raise ValueError(f"flag must be 0 or 1: {flag!r}")
    # First-match-wins: RULES are priority-ordered and a rule only touches rows not
    # yet annotated, so every classified file carries exactly one (most-specific) reason.
    sql = f"""
        UPDATE spec_files
        SET not_spec_filter = {flag}, not_spec_notes = '{reason}'
        WHERE not_spec_notes IS NULL AND ({rule['where']})
    """
    cur = conn.cursor()
    cur.execute(sql)
    n = cur.rowcount
    conn.commit()
    cur.close()
    return n


def reset(conn):
    cur = conn.cursor()
    # Clear every classified row — excluded (filter=1) AND annotate-keep (notes set, filter=0).
    cur.execute("UPDATE spec_files SET not_spec_filter = 0, not_spec_notes = NULL "
                "WHERE not_spec_notes IS NOT NULL OR not_spec_filter = 1")
    conn.commit()
    cur.close()


def report(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM spec_files")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM spec_files WHERE not_spec_filter = 1")
    excluded = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM spec_files WHERE not_spec_filter = 0 AND not_spec_notes IS NOT NULL")
    tagged_kept = cur.fetchone()[0]
    print(f"\n=== classification summary ===")
    print(f"  total files      : {total:,}")
    print(f"  EXCLUDED (filter=1): {excluded:,} ({100*excluded/total:.1f}%)")
    print(f"  kept, of which tagged: {tagged_kept:,} ({100*tagged_kept/total:.1f}%)")
    print(f"  kept, untagged   : {total-excluded-tagged_kept:,} ({100*(total-excluded-tagged_kept)/total:.1f}%)")
    cur.execute(
        "SELECT not_spec_filter, not_spec_notes, COUNT(*) n FROM spec_files "
        "WHERE not_spec_notes IS NOT NULL GROUP BY not_spec_filter, not_spec_notes "
        "ORDER BY not_spec_filter DESC, n DESC"
    )
    print("  by reason (kind / reason / files):")
    for flag, note, n in cur.fetchall():
        kind = "EXCLUDE" if flag == 1 else "keep+tag"
        print(f"    [{kind}] {note:<28} {n:>9,}")
    cur.close()


def main():
    ap = argparse.ArgumentParser(description="Flag non-SDD spec_files rows (reversible).")
    ap.add_argument("--report", action="store_true", help="Report only; apply nothing.")
    ap.add_argument("--reset", action="store_true", help="Clear all flags/notes.")
    args = ap.parse_args()

    conn = f.get_db_connection("specdriven")
    ensure_columns(conn)

    if args.reset:
        reset(conn)
        print("All flags/notes cleared.")
        report(conn)
        conn.close()
        return

    if not args.report:
        for rule in RULES:
            n = apply_rule(conn, rule)
            print(f"[{rule['reason']}] newly flagged: {n:,}   ({rule['desc']})")

    report(conn)
    conn.close()


if __name__ == "__main__":
    main()
