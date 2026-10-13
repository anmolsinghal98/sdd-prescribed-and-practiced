#!/usr/bin/env python3
"""E1 · Extract every markdown heading from the sample's spec files.

Parsing is done by **markdown-it-py**, a CommonMark-compliant parser, in GFM
mode with the front-matter plugin:

    MarkdownIt("gfm-like").use(front_matter_plugin)

That handles fenced and indented code, HTML comments, lists, block quotes,
tables and YAML front matter as block constructs, which a regex over `^#`
cannot. 11% of our files contain fenced code where `# comment` lines are not
headings; the precomputed `n_headings` column counts those and is 19% too high
(756,653 vs 611,290 over the same files).

An earlier hand-rolled parser was replaced by this one after differential
testing: the two agreed on 99.96% of files, but where they differed the library
was right. A mis-detected fence made the hand-rolled version swallow the rest
of the file and silently drop real headings (`## Risks`, `## Dependencies`,
`## Out of Scope` in modu-ai/moai-adk). Use the library.

Three corrections remain on top, all specific to this corpus rather than to
markdown itself:

  1. strip a leading UTF-8 BOM before parsing. A BOM ahead of `---` hides the
     front matter from the plugin, which then yields the YAML body as a heading.
  2. drop headings that are empty once inline HTML comments are removed
     (`# <!-- note -->` is not a heading).
  3. suppress Setext headings whose text is a YAML key. Some templates embed a
     `---`-delimited block MID-file, which the front-matter plugin only detects
     at position 0; its last `key: value` line then underlines as an h2.

Each heading is recorded twice: `raw` as written, and `norm` with links,
images, inline code, HTML, emphasis, `{#anchor}` and leading numbering removed,
lowercased, so `### 3.1. Configurations` aggregates with `## Configurations`.

    python3 extract_headings.py --tier all --out headings.csv
    python3 extract_headings.py --validate      # regression suite, no DB
"""
import sys, os, csv, re, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sample import load
from specmine import connect, SQL_WHERE, NAMED_TOOLS
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

csv.field_size_limit(10_000_000)

MD = MarkdownIt("gfm-like").use(front_matter_plugin)

BOM     = "﻿￾"
COMMENT = re.compile(r"<!--.*?-->", re.S)
YAMLKEY = re.compile(r"^[a-z][A-Za-z0-9_-]*:\s*\S")      # no spaces in a YAML key

_LINK   = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_REFLNK = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")
_IMG    = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_CODE   = re.compile(r"`([^`]*)`")
_EMPH   = re.compile(r"(\*\*\*|\*\*|\*|___|__|_|~~)")
_NUM    = re.compile(r"^(?:step\s+)?\d+(?:\.\d+)*[.):\-]?\s+", re.I)
_TAG    = re.compile(r"<[^>]+>")
_ANCHOR = re.compile(r"\s*\{#[^}]*\}\s*$")


def normalise(h):
    s = _IMG.sub(r"\1", h)
    s = _LINK.sub(r"\1", s)
    s = _REFLNK.sub(r"\1", s)
    s = _CODE.sub(r"\1", s)
    s = _TAG.sub("", s)
    s = _ANCHOR.sub("", s)
    s = _EMPH.sub("", s)
    s = s.replace(" ", " ")
    s = _NUM.sub("", s.strip())
    s = s.strip().strip(":：.-–—").strip()
    return re.sub(r"\s+", " ", s).lower()


def parse(text):
    """-> [(level, raw_heading, line_no, kind)] via markdown-it-py."""
    if not text:
        return []
    text = text.lstrip(BOM)                          # correction 1
    toks = MD.parse(text)
    out = []
    for i, t in enumerate(toks):
        if t.type != "heading_open":
            continue
        raw = toks[i + 1].content.strip() if i + 1 < len(toks) else ""
        raw = COMMENT.sub("", raw).strip()           # correction 2
        if not raw:
            continue
        kind = "atx" if t.markup.startswith("#") else "setext"
        if kind == "setext" and YAMLKEY.match(raw):  # correction 3
            continue
        out.append((int(t.tag[1]), raw, (t.map[0] + 1) if t.map else 0, kind))
    return out


# ------------------------------------------------------------------ regression
CASES = [
 ("# Title",                                  [(1, "Title")]),
 ("###   Spaced   ",                          [(3, "Spaced")]),
 ("## Closed ##",                             [(2, "Closed")]),
 ("#NoSpace",                                 []),
 ("    # indented code",                      []),
 ("```\n# not a heading\n```\n# real",        [(1, "real")]),
 ("~~~py\n# nope\n~~~\n## yes",               [(2, "yes")]),
 ("---\ntitle: x\n---\n# after front matter", [(1, "after front matter")]),
 ("Setext H1\n=====",                         [(1, "Setext H1")]),
 ("Setext H2\n-----",                         [(2, "Setext H2")]),
 ("\n---\n",                                  []),               # thematic break
 ("| a | b |\n|---|---|",                     []),               # GFM table
 ("<!--\n# hidden\n-->\n# shown",             [(1, "shown")]),
 ("####### seven hashes",                     []),
 ("# Trailing  \n## Second",                  [(1, "Trailing"), (2, "Second")]),
 ("- bullet item\n---",                       []),               # list + break
 ("1. numbered\n---",                         []),               # ordered list
 ("> quoted\n---",                            []),               # block quote
 ("﻿---\ntitle: x\n---\n# after BOM",    [(1, "after BOM")]),
 ("real para\n---",                           [(2, "real para")]),
 ("# <!-- just a comment -->",                []),               # empty after strip
 ("status: draft\n---",                       []),               # mid-file YAML
 ("Version 2: the sequel\n---",               [(2, "Version 2: the sequel")]),
 ("## Heading `with code`",                   [(2, "Heading `with code`")]),
 ("> # heading inside a quote",               [(1, "heading inside a quote")]),
]
NORM = [("**Bold** heading", "bold heading"),
        ("1.2 Numbered Section", "numbered section"),
        ("[Link](http://x) here", "link here"),
        ("`code` title:", "code title"),
        ("Step 3: Do it", "do it"),
        ("Overview {#ov}", "overview")]


def validate():
    bad = 0
    for src, want in CASES:
        got = [(l, t) for l, t, _, _ in parse(src)]
        ok = got == want; bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {repr(src)[:46]:<48} -> {got}")
        if not ok: print(f"       expected {want}")
    print(f"\n{len(CASES)-bad}/{len(CASES)} parser cases pass")
    for raw, want in NORM:
        got = normalise(raw); ok = got == want; bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} normalise({raw!r}) = {got!r}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["all", "named"], default="named")
    ap.add_argument("--out", default="headings.csv")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--kiro", action="store_true",
                    help="also emit Kiro's requirements documents")
    a = ap.parse_args()
    if a.validate:
        sys.exit(1 if validate() else 0)

    conn = connect(); cur = conn.cursor()
    repos, nf = load(conn, tier=a.tier)
    keep = {r["repo"] for r in repos}
    print(f"tier {a.tier}: {len(repos):,} repos / {nf:,} files", flush=True)

    cur.execute(f"""SELECT s.file_url_sha16, s.repo_name, s.file_path, s.spec_tool,
                           s.spec_role, s.file_content_sha, s.file_content
                    FROM spec_files s WHERE {SQL_WHERE}""")
    nfiles = nheads = 0
    with open(a.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file_sha16", "repo_name", "file_path", "spec_tool", "spec_role",
                    "content_sha", "level", "position", "kind", "heading_raw", "heading_norm"])
        while True:
            batch = cur.fetchmany(2000)
            if not batch: break
            for sha16, repo, path, tool, role, csha, content in batch:
                if repo not in keep: continue
                # tier 'named' means named-tool FILES, not every file in a
                # named-tool repo: ~300 generic-bucket files live inside them.
                if a.tier == "named" and tool not in NAMED_TOOLS: continue
                hs = parse(content or "")
                nfiles += 1; nheads += len(hs)
                for pos, (lvl, raw, ln, kind) in enumerate(hs, 1):
                    w.writerow([sha16, repo, path, tool, role, csha, lvl, pos, kind,
                                raw[:500], normalise(raw)[:500]])
            if nfiles % 10000 < 2000:
                print(f"   {nfiles:,} files / {nheads:,} headings", flush=True)
        if a.kiro:
            cur2 = conn.cursor()
            cur2.execute("""SELECT kf.id, kf.repo_name, kf.file_path,
                                   kf.file_content_sha, kf.file_content
                            FROM kiro_files kf WHERE kf.kind='requirements'""")
            for fid, repo, path, csha, content in cur2.fetchall():
                hs = parse(content or "")
                nfiles += 1; nheads += len(hs)
                for pos, (lvl, raw, ln, kind) in enumerate(hs, 1):
                    w.writerow([f"kiro:{fid}", repo, path, "kiro", "requirements",
                                csha, lvl, pos, kind, raw[:500], normalise(raw)[:500]])
    print(f"\nwrote {a.out}: {nheads:,} headings from {nfiles:,} files "
          f"({nheads/max(nfiles,1):.1f} per file)")
    conn.close()


if __name__ == "__main__":
    main()
