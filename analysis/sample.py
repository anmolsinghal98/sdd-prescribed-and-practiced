#!/usr/bin/env python3
"""THE analysis sample. Frozen 2026-09-20.

Every empirical result in the paper runs on one frozen population, loaded
through here. Never re-derive the filters in a result script: a claim must not
be computed on a slightly different population.

    from sample import load, SQL_WHERE, NAMED_TOOLS

    repos, n_files = load()        # 253 repos, 36,236 files, 13,113 commits

The 266 repositories the paper reports are these 253 plus Kiro's 13, which live
in their own tables because Kiro's layout is invisible to a spec.md census.

The population
--------------
named  only files attributed to a named tool; each repo's file count and
       commit count are counted over those files, and the >=10-commit
       practice filter is applied to them.
       253 repos, 36,236 files, 13,113 distinct spec commits
       NOTE this population is 90.6% OpenSpec + Spec Kit and by construction
       contains no self-invented practice.

The original analysis also defined a wider `all` tier (566 repos, 42,345
files, 24,317 commits) that includes files carrying no tool fingerprint. No
result in the paper is computed on it, so it is not shipped here; `load(tier=
"all")` fails with instructions rather than quietly returning this population
under the other name.

Repository filters
------------------
    artifact    spec.md / specs.md, kept rows only (not_spec_filter = 0)
    popularity  >= 10 stars
    status      public, not archived, not a fork
    license     a recognised SPDX id (excludes '' and 'NOASSERTION')
    practice    >= 10 DISTINCT commits touching the tier's spec files

Why distinct commits, not SUM(file_total_commits)
-------------------------------------------------
One commit usually touches many spec files at once (OpenSpec writes a whole
change folder in a single commit). Summing the per-file counter gives 110,220
for this tier against 38,002 actual commits: 65.5% inflation. We count distinct
commit_sha from spec_file_commits.

Caveats that travel with every claim
------------------------------------
* repo_stars / repo_license_spdx_id / repo_archived are as-of-crawl snapshots.
* repo_archived is unreliable: 2 flagged rows in the whole 575,633-row census,
  so "non-archived" is effectively a no-op. Re-check via the API if a claim
  depends on it.
* repo_fork and repo_private are already 0 for every row (excluded at
  collection time); kept explicit only so the definition reads completely.
* 11.7% of files duplicate another file's content (archived copies).
  Deduplicate on file_content_sha for content claims.
* The top 10 repos hold 42% of files (46% in the named tier). Prefer per-repo
  aggregation and always report the tool breakdown.
* spec_role='archived' is the spec's lifecycle stage, NOT repo archival.
* file_last_commit_at has 2 bogus rows dated 2032. Exclude them from any
  max/range over that column. file_first_commit_at is clean.
* The census excluded files whose first commit predates 2024-01-01, so the
  generic buckets are left-censored at that date; earliest dates for them are
  a collection boundary, not a first appearance. Named tools are uncensored.
"""
import sys, os, csv, argparse, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from specmine import (connect, SQL_WHERE, NAMED_TOOLS, GENERIC_BUCKETS,
                      MIN_STARS, MIN_COMMITS)

# The 'all' tier's numbers are recorded for the record but are not
# reproducible from this package; see load().
FROZEN = {"named": dict(repos=253, files=36236, commits=13113)}


def load(conn=None, tier="named", min_commits=MIN_COMMITS):
    """Return (repos, n_files) for the given tier.

    Each repo dict: repo, stars, license, files, commits, tools,
    tool_attributed. `files`/`commits` are counted over the tier's files only.
    """
    if tier == "all":
        raise SystemExit(
            "The 'all' tier is not in this package.\n\n"
            "It is the wider robustness population -- 566 repositories, 42,345\n"
            "files, 24,317 distinct spec commits -- including files that carry\n"
            "no tool fingerprint. No result in the paper is computed on it, so\n"
            "the packaged dataset holds the 'named' tier only and would return\n"
            "the wrong population if this were allowed to proceed.\n\n"
            "To reproduce it, take the full corpus from ZENODO_DOI_PLACEHOLDER\n"
            "and run build_dataset.py without the named-tool restriction.")
    if tier != "named":
        raise ValueError(f"tier must be 'named' in this package, got {tier!r}")
    own = conn is None
    conn = conn or connect()
    cur = conn.cursor()

    cur.execute(f"""SELECT s.repo_name, s.file_url_sha16, s.spec_tool,
                           MAX(s.repo_stars), MAX(s.repo_license_spdx_id)
                    FROM spec_files s WHERE {SQL_WHERE}
                    GROUP BY s.repo_name, s.file_url_sha16, s.spec_tool""")
    meta, nfiles, tools, in_tier = {}, collections.Counter(), collections.defaultdict(set), set()
    for repo, sha16, tool, stars, lic in cur.fetchall():
        meta[repo] = (int(stars), lic)
        if tier == "named" and tool not in NAMED_TOOLS:
            continue
        in_tier.add(sha16)
        nfiles[repo] += 1
        if tool:
            tools[repo].add(tool)

    shas = collections.defaultdict(set)
    cur.execute(f"""SELECT s.repo_name, s.file_url_sha16, k.commit_sha
                    FROM spec_files s
                    JOIN spec_file_commits k ON k.file_url_sha16 = s.file_url_sha16
                    WHERE {SQL_WHERE}""")
    for repo, sha16, commit in cur.fetchall():
        if sha16 in in_tier:
            shas[repo].add(commit)

    repos = []
    for r, n in nfiles.items():
        c = len(shas.get(r, ()))
        if c >= min_commits:
            stars, lic = meta[r]
            repos.append(dict(repo=r, stars=stars, license=lic, files=n, commits=c,
                              tools=sorted(tools[r]),
                              tool_attributed=bool(tools[r] & NAMED_TOOLS)))
    repos.sort(key=lambda x: (-x["commits"], -x["files"], x["repo"]))
    cur.close()
    if own:
        conn.close()
    return repos, sum(x["files"] for x in repos)


def kiro_repos(path=None):
    """The 13 Kiro repositories that complete the 266."""
    path = path or os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "kiro_keep.txt")
    return sorted(set(open(path).read().split()))


def _write(repos, path):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["repo_name", "stars", "license", "spec_files", "spec_commits",
                    "tools", "tool_attributed"])
        for x in repos:
            w.writerow([x["repo"], x["stars"], x["license"], x["files"], x["commits"],
                        ";".join(x["tools"]), int(x["tool_attributed"])])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="check both tiers against FROZEN")
    ap.add_argument("--tier", choices=["named"], default="named")
    ap.add_argument("--outdir", default=".")
    a = ap.parse_args()
    conn = connect()
    tiers = [a.tier]
    drift = False
    for t in tiers:
        repos, nf = load(conn, tier=t)
        nc = sum(x["commits"] for x in repos)
        got = dict(repos=len(repos), files=nf, commits=nc)
        print(f"[{t:<5}] repos {len(repos):,} | spec files {nf:,} | distinct spec commits {nc:,}")
        bad = {k: (FROZEN[t][k], got[k]) for k in FROZEN[t] if FROZEN[t][k] != got[k]}
        if bad:
            drift = True
            for k, (exp, act) in bad.items():
                print(f"         DRIFT {k}: frozen {exp:,} -> now {act:,}")
        elif a.verify:
            print("         matches the frozen definition")
        if not a.verify:
            p = os.path.join(a.outdir, "sample_repos_named.csv")
            _write(repos, p)
            na = sum(1 for x in repos if not x["tool_attributed"])
            print(f"         wrote {p}  (unattributed repos: {na})")
    conn.close()
    if a.verify and drift:
        sys.exit(1)


if __name__ == "__main__":
    main()
