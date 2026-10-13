#!/usr/bin/env python3
"""Adoption-over-time series for the two timeline figures.

    python3 analysis/build_timeline.py --out data/build

Writes two files:

  timeline_sample.json   the analysis sample, 266 repositories. Adoptions and
                         specs per month per tool. Behind the appendix figure.
  timeline_census.json   every repository in the corpus. Adoptions per month
                         per tool. Behind Figure 1.

A repository adopts a tool in the month of the first commit of its earliest
file attributed to that tool, so a repository using two tools contributes an
adoption to each and the series are not a partition of the repository count.
Every spec carries exactly one attribution, so the per-month file counts are.

Repositories are keyed case-insensitively: GitHub treats repository names that
way, one repository in the census is recorded under two spellings, and
counting them separately inflates the census by one.

This script did not exist while the paper was written -- the series were built
by hand -- which is why it is here.
"""
import argparse, collections, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from specmine import connect, NAMED_TOOLS, SQL_WHERE, placeholders
from sample import load


def month(v):
    return v[:7] if v and len(v) >= 7 else None


def census(c):
    """Adoptions per tool per month over the whole corpus."""
    ad = collections.defaultdict(collections.Counter)
    ph = placeholders(sorted(NAMED_TOOLS))
    rows = c.execute(f"""SELECT LOWER(repo_name), spec_tool,
                                MIN(file_first_commit_at)
                         FROM spec_files_all
                         WHERE spec_tool IN ({ph})
                           AND file_first_commit_at IS NOT NULL
                         GROUP BY LOWER(repo_name), spec_tool""",
                     tuple(sorted(NAMED_TOOLS))).fetchall()
    for _repo, tool, first in rows:
        m = month(first)
        if m:
            ad[tool][m] += 1
    for _repo, first in c.execute(
            """SELECT LOWER(repo_name), MIN(first_commit_at) FROM kiro_files_all
               WHERE first_commit_at IS NOT NULL GROUP BY LOWER(repo_name)"""):
        m = month(first)
        if m:
            ad["kiro"][m] += 1
    return {k: dict(v) for k, v in ad.items()}


def sample(c):
    """Adoptions and specs per tool per month within the analysis sample."""
    repos, _ = load(c)
    keep = [r["repo"] for r in repos]
    ph, rp = placeholders(sorted(NAMED_TOOLS)), placeholders(keep)
    par = tuple(sorted(NAMED_TOOLS)) + tuple(keep)

    files = collections.defaultdict(collections.Counter)
    first = collections.defaultdict(dict)
    for repo, tool, fc in c.execute(
            f"""SELECT s.repo_name, s.spec_tool, s.file_first_commit_at
                FROM spec_files s
                WHERE {SQL_WHERE} AND s.spec_tool IN ({ph})
                  AND s.repo_name IN ({rp})""", par):
        m = month(fc)
        if not m:
            continue
        files[tool][m] += 1
        k = repo.lower()
        if m < first[tool].get(k, "9999"):
            first[tool][k] = m

    for repo, fc in c.execute(
            """SELECT kf.repo_name, MIN(kc.authored_at)
               FROM kiro_files kf JOIN kiro_file_commits kc ON kc.kiro_file_id = kf.id
               GROUP BY kf.id"""):
        m = month(fc)
        if not m:
            continue
        files["kiro"][m] += 1
        k = repo.lower()
        if m < first["kiro"].get(k, "9999"):
            first["kiro"][k] = m

    ad = collections.defaultdict(collections.Counter)
    for tool, per in first.items():
        for _repo, m in per.items():
            ad[tool][m] += 1
    return {"files_per_month": {k: dict(v) for k, v in files.items()},
            "adoptions": {k: dict(v) for k, v in ad.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "build"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    c = connect()

    s = sample(c)
    json.dump(s, open(os.path.join(a.out, "timeline_sample.json"), "w"))
    na = sum(sum(v.values()) for v in s["adoptions"].values())
    nf = sum(sum(v.values()) for v in s["files_per_month"].values())
    print(f"timeline_sample.json   {na:,} repository-tool adoptions, {nf:,} specs")

    t = census(c)
    json.dump(t, open(os.path.join(a.out, "timeline_census.json"), "w"))
    print(f"timeline_census.json   {sum(sum(v.values()) for v in t.values()):,} "
          f"repository-tool adoptions across {len(t)} tools")
    c.close()


if __name__ == "__main__":
    main()
