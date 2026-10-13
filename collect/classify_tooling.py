#!/usr/bin/env python3
"""Attribute each KEPT spec file to the SDD tool/kit that produced it, plus its
lifecycle role. Reversible & idempotent, same spirit as classify_specs.py — this
NEVER deletes and only writes two descriptive columns:

  spec_tool  VARCHAR : the tool family (openspec, speckit, caffeine, ...)
  spec_role  VARCHAR : lifecycle/artifact role where a tool distinguishes them
                       (living | change_proposal | archived | config | feature | na)

Attribution is by PATH FINGERPRINT — validated against a content sample which
showed each tool emits a recognizable markdown template (OpenSpec's
`## ADDED Requirements` + `#### Scenario:`, Spec Kit's `*(mandatory)*` sections,
caffeine.ai's `## Requested Changes (diff)`, etc.). Path and template agree, so
the (free, 100%-coverage) path signal is used as the backbone.

Only rows with not_spec_filter = 0 (the kept set) are classified; excluded rows
are left NULL. Rules are priority-ordered, first-match-wins (guarded on
spec_tool IS NULL), so every kept file gets exactly one most-specific tool.

Usage:
  python3 classify_tooling.py            # apply all rules + report
  python3 classify_tooling.py --report   # report only
  python3 classify_tooling.py --reset     # clear spec_tool / spec_role
"""
import argparse, sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

KEEP = "not_spec_filter = 0"

# Each rule: tool label, role label, and a path predicate. Priority-ordered.
RULES = [
    # --- caffeine.ai generator (already a known org; its own tiny template) ---
    dict(tool="caffeine",  role="na",
         where="owner_login = 'caffeinepub'",
         desc="caffeine.ai app-generator org; `## Summary/Specification/Requested Changes (diff)` template, ~20 lines."),

    # --- OpenSpec (Fission-AI): openspec/ tree, split by lifecycle ---------
    dict(tool="openspec", role="archived",
         where="file_path LIKE 'openspec/changes/archive/%'",
         desc="OpenSpec completed change (archived under openspec/changes/archive/)."),
    dict(tool="openspec", role="change_proposal",
         where="file_path LIKE 'openspec/changes/%'",
         desc="OpenSpec active change proposal (openspec/changes/<x>/specs/.../spec.md)."),
    dict(tool="openspec", role="living",
         where="file_path LIKE 'openspec/specs/%'",
         desc="OpenSpec living/current capability spec (openspec/specs/<cap>/spec.md)."),
    dict(tool="openspec", role="na",
         where="file_path LIKE 'openspec/%'",
         desc="OpenSpec, other location under openspec/."),

    # --- GitHub Spec Kit: .specify config + numbered feature specs ---------
    dict(tool="speckit", role="config",
         where="file_path LIKE '.specify/%' OR file_path LIKE '%/.specify/%'",
         desc="Spec Kit under its .specify/ scaffold (templates/memory/scripts)."),
    dict(tool="speckit", role="feature",
         where=r"file_path REGEXP '(^|/)specs/[0-9]{3}[-_]'",
         desc="Spec Kit numbered feature spec (specs/NNN-name/spec.md); `*(mandatory)*` sections."),

    # --- other named toolchains (each a distinct config dir / template) ----
    dict(tool="conductor", role="na",
         where="file_path LIKE 'conductor/%' OR file_path LIKE '%/conductor/%'",
         desc="Conductor; `## Overview/Functional Requirements/Acceptance Criteria/Out of Scope`."),
    dict(tool="agent_os", role="na",
         where="file_path LIKE 'agent-os/%' OR file_path LIKE '%agent-os/%'",
         desc="Agent OS (Builder Methods); `Spec Requirements Document`, `Spec Scope`, `Expected Deliverable`."),
    dict(tool="specweave", role="na",
         where="file_path LIKE '.specweave/%' OR file_path LIKE '%.specweave/%'",
         desc="SpecWeave; `## User Stories` + `## Acceptance Criteria` (near-universal in sample)."),
    dict(tool="moai", role="na",
         where="file_path LIKE '.moai/%' OR file_path LIKE '%.moai/%'",
         desc="MoAI-ADK (modu-ai); `## History`, `Requirements (EARS format)`, `Exclusions`, @SPEC tags."),
    dict(tool="claude_code", role="config",
         where="file_path LIKE '%.claude/%'",
         desc="Under a .claude/ agent config dir (Claude Code slash-command/skill output)."),
    dict(tool="opencode", role="config",
         where="file_path LIKE '%.opencode/%'",
         desc="Under an .opencode/ agent config dir."),
    dict(tool="trae", role="config",
         where="file_path LIKE '%.trae/%'",
         desc="Under a .trae/ agent config dir (Trae IDE)."),
    dict(tool="codex", role="config",
         where="file_path LIKE '%.codex%'",
         desc="Under a .codex* dir (OpenAI Codex tasks)."),
    dict(tool="cursor", role="config",
         where="file_path LIKE '%.cursor/%'",
         desc="Under a .cursor/ config dir."),
    dict(tool="kilocode", role="config",
         where="file_path LIKE '%.kilocode/%'",
         desc="Under a .kilocode/ config dir."),

    # --- generic / ad-hoc conventions (no tool-specific footprint) ---------
    # --- smaller named tools surfaced by path-fingerprint mining (multi-repo) ---
    dict(tool="gsd", role="config",
         where="file_path LIKE '.gsd/%' OR file_path LIKE '%/.gsd/%'",
         desc="GSD spec framework — specs under a .gsd/ config dir (~181 repos)."),
    dict(tool="zenflow", role="config",
         where="file_path LIKE '.zenflow/%' OR file_path LIKE '%/.zenflow/%'",
         desc="Zenflow — specs under a .zenflow/ config dir (~64 repos)."),
    dict(tool="dot_specs", role="na",
         where="file_path LIKE '.specs/%' OR file_path LIKE '%/.specs/%'",
         desc="A .specs/ hidden spec-dir convention (~250 repos)."),
    dict(tool="kitty_specs", role="na",
         where="file_path LIKE 'kitty-specs/%' OR file_path LIKE '%/kitty-specs/%'",
         desc="kitty-specs/ kit layout (~62 repos)."),

    dict(tool="specs_generic", role="na",
         where=r"file_path REGEXP '(^|/)specs/'",
         desc="A specs/<name>/spec.md layout with no tool marker (mixed OpenSpec-style + ad-hoc)."),
    dict(tool="docs_embedded", role="na",
         where="file_path LIKE 'docs/%' OR file_path LIKE '%/docs/%'",
         desc="Spec kept inside a docs/ tree (documentation-embedded, heterogeneous)."),
    dict(tool="root_bare", role="na",
         where="file_path NOT LIKE '%/%'",
         desc="A bare spec.md / SPECS.md at repo root; longest & most free-form (median ~220 lines)."),
    dict(tool="adhoc_other", role="na",
         where="1=1",
         desc="Everything else: genuine long tail of ad-hoc paths & micro-tools (.specs/, kitty-specs/, specrunner/, ...)."),
]


def ensure_columns(conn):
    cur = conn.cursor()
    cur.execute("""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='spec_files'
                   AND COLUMN_NAME IN ('spec_tool','spec_role')""")
    have = {r[0] for r in cur.fetchall()}
    if "spec_tool" not in have:
        cur.execute("ALTER TABLE spec_files ADD COLUMN spec_tool VARCHAR(32) NULL")
    if "spec_role" not in have:
        cur.execute("ALTER TABLE spec_files ADD COLUMN spec_role VARCHAR(24) NULL")
    conn.commit(); cur.close()


def apply_rule(conn, rule):
    """First-match-wins over the KEPT set, guarded on spec_tool IS NULL.

    tool/role are trusted constants from RULES (validated [a-z0-9_]) so they are
    inlined; the WHERE clauses carry literal % (LIKE) so NO bound params are used.
    """
    tool, role = rule["tool"], rule["role"]
    for v in (tool, role):
        if not all(c.isalnum() or c == "_" for c in v):
            raise ValueError(f"unsafe label to inline: {v!r}")
    sql = f"""UPDATE spec_files SET spec_tool = '{tool}', spec_role = '{role}'
              WHERE {KEEP} AND spec_tool IS NULL AND ({rule['where']})"""
    cur = conn.cursor()
    cur.execute(sql)
    n = cur.rowcount
    conn.commit(); cur.close()
    return n


def reset(conn):
    cur = conn.cursor()
    cur.execute("UPDATE spec_files SET spec_tool = NULL, spec_role = NULL "
                "WHERE spec_tool IS NOT NULL OR spec_role IS NOT NULL")
    conn.commit(); cur.close()


def report(conn):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM spec_files WHERE {KEEP}")
    kept = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM spec_files WHERE {KEEP} AND spec_tool IS NULL")
    unattr = cur.fetchone()[0]
    print("\n=== tooling attribution summary ===")
    print(f"  kept files      : {kept:,}")
    print(f"  attributed      : {kept-unattr:,} ({100*(kept-unattr)/kept:.1f}%)")
    print(f"  unattributed    : {unattr:,}")
    cur.execute(f"""SELECT spec_tool, COUNT(*) n FROM spec_files
                    WHERE {KEEP} AND spec_tool IS NOT NULL
                    GROUP BY spec_tool ORDER BY n DESC""")
    print("  by tool:")
    for tool, n in cur.fetchall():
        print(f"    {tool:<16} {n:>9,}  ({100*n/kept:4.1f}%)")
    cur.execute(f"""SELECT spec_tool, spec_role, COUNT(*) n FROM spec_files
                    WHERE {KEEP} AND spec_role IS NOT NULL AND spec_role<>'na'
                    GROUP BY spec_tool, spec_role ORDER BY n DESC""")
    print("  by role (where a tool splits lifecycle):")
    for tool, role, n in cur.fetchall():
        print(f"    {tool}/{role:<16} {n:>9,}")
    cur.close()


def main():
    ap = argparse.ArgumentParser(description="Attribute kept spec files to their SDD tool (reversible).")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    conn = f.get_db_connection("specdriven")
    ensure_columns(conn)
    if args.reset:
        reset(conn); print("spec_tool / spec_role cleared."); report(conn); conn.close(); return
    if not args.report:
        for rule in RULES:
            n = apply_rule(conn, rule)
            print(f"[{rule['tool']}/{rule['role']}] newly attributed: {n:,}   ({rule['desc']})")
    report(conn)
    conn.close()


if __name__ == "__main__":
    main()
