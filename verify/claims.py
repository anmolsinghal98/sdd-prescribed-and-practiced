#!/usr/bin/env python3
"""Recompute every quantitative claim in the manuscript from this package.

    python3 verify/claims.py            # all groups
    python3 verify/claims.py --group authorship
    python3 verify/claims.py --quiet    # failures only

Each claim records the value as it is printed in the paper next to a function
that recomputes it from `data/specmine-sample.sqlite` and `data/derived/`.
Nothing here reads the original MySQL server, so a reader can run it.

Exit status is 1 if any claim fails, so this can gate a build.

Percentages are compared at the precision the paper prints them: a paper
figure of 98.3 must round-trip to 98.3, not merely to within a point. Counts
must match exactly.

Two traps are encoded here because both have produced wrong numbers before.
Repositories are counted case-insensitively, since one repository appears
under two spellings and GitHub treats the names as the same. And a comment is
on a spec file when its `match` field says so -- the spec-file crawl writes
`exact`/`basename` while the Kiro crawl writes `path`/`none`, so testing one
vocabulary silently drops the other half.
"""
import argparse, json, os, sys, collections, gzip, csv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from specmine import connect, NAMED_TOOLS, SQL_WHERE          # noqa: E402

DERIVED = os.path.join(ROOT, "data", "derived")
RESULTS = []


def claim(group, name, paper, got, note="", dp=1):
    """Record one comparison. `paper` is the value as printed.

    `dp` is how many decimals the manuscript shows: a paper that prints 79%
    is satisfied by 79.4, one that prints 98.3% is not satisfied by 98.2.
    """
    if isinstance(paper, float):
        ok = abs(round(got, dp) - round(paper, dp)) < 1e-9
        shown = f"{got:,.{max(dp,1)}f}"
    else:
        ok = int(got) == int(paper)
        shown = f"{got:,}"
    RESULTS.append((group, name, f"{paper:,}" if not isinstance(paper, float)
                    else f"{paper:.1f}", shown, ok, note))


def jsonl(name):
    p = os.path.join(DERIVED, name)
    with (gzip.open(p, "rt") if p.endswith(".gz") else open(p)) as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def lower_set(rows, idx=0):
    return {(r[idx] or "").lower() for r in rows}


# --------------------------------------------------------------- the cascade

def g_cascade(c):
    """Table 2/4: the five filter steps, repositories and files."""
    ph = ",".join("?" * len(NAMED_TOOLS))
    named = f"spec_tool IN ({ph})"
    stars = named + " AND repo_stars>=10"
    clean = stars + (" AND repo_archived=0 AND repo_fork=0 AND repo_private=0"
                     " AND repo_visibility='public'")
    lic = clean + (" AND repo_license_spdx_id IS NOT NULL"
                   " AND repo_license_spdx_id NOT IN ('','NOASSERTION')")
    # Kiro's predicates mirror these minus the two columns its tables lack:
    # spec_tool (every Kiro requirements document is Kiro's by definition) and
    # repo_private.
    ksteps = {"base": "1=1", "named": "1=1",
              "stars": "p.repo_stars>=10",
              "clean": "p.repo_stars>=10 AND p.repo_archived=0 AND p.repo_fork=0"
                       " AND p.repo_visibility='public'",
              "lic": "p.repo_stars>=10 AND p.repo_archived=0 AND p.repo_fork=0"
                     " AND p.repo_visibility='public'"
                     " AND p.repo_license_spdx_id IS NOT NULL"
                     " AND p.repo_license_spdx_id NOT IN ('','NOASSERTION')"}
    steps = {"base": "1=1", "named": named, "stars": stars, "clean": clean, "lic": lic}
    exp = {"base": (85300, 503767), "named": (48732, 396818), "stars": (1446, 50858),
           "clean": (1444, 50836), "lic": (1031, 42813)}
    for step, (er, ef) in exp.items():
        par = tuple(NAMED_TOOLS) if "?" in steps[step] else ()
        sr = lower_set(c.execute(
            f"SELECT DISTINCT repo_name FROM spec_files_all WHERE {steps[step]}", par).fetchall())
        sf = c.execute(f"SELECT COUNT(*) FROM spec_files_all WHERE {steps[step]}",
                       par).fetchone()[0]
        kr = lower_set(c.execute(
            f"""SELECT DISTINCT k.repo_name FROM kiro_files_all k
                JOIN kiro_repos_all p ON p.repo_name=k.repo_name
                WHERE {ksteps[step]}""").fetchall())
        kf = c.execute(f"""SELECT COUNT(*) FROM kiro_files_all k
                           JOIN kiro_repos_all p ON p.repo_name=k.repo_name
                           WHERE {ksteps[step]}""").fetchone()[0]
        claim("cascade", f"{step}: repositories", er, len(sr | kr))
        claim("cascade", f"{step}: files", ef, sf + kf)


def g_sample(c):
    """The analysis sample as the paper reports it."""
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    from sample import load, kiro_repos
    repos, nf = load(c)
    kiro = kiro_repos()
    claim("sample", "spec-file repositories", 253, len(repos))
    claim("sample", "Kiro repositories", 13, len(kiro))
    claim("sample", "repositories", 266, len(repos) + len(kiro))
    kf = c.execute("SELECT COUNT(*) FROM kiro_files").fetchone()[0]
    claim("sample", "files", 36890, nf + kf)
    kc = c.execute("SELECT COUNT(DISTINCT commit_sha) FROM kiro_file_commits").fetchone()[0]
    claim("sample", "spec commits", 13640,
          sum(r["commits"] for r in repos) + kc)
    claim("sample", "Kiro requirements documents kept", 654, kf)
    # tools surviving the filter
    ph = ",".join("?" * len(NAMED_TOOLS))
    keep = [r["repo"] for r in repos]
    rp = ",".join("?" * len(keep))
    n = c.execute(f"""SELECT COUNT(DISTINCT s.spec_tool) FROM spec_files s
                      WHERE {SQL_WHERE} AND s.spec_tool IN ({ph})
                        AND s.repo_name IN ({rp})""",
                  tuple(NAMED_TOOLS) + tuple(keep)).fetchone()[0]
    claim("sample", "tools surviving (incl. Kiro)", 12, n + 1)


# ------------------------------------------------------------- authorship

BOTPAT = ("[bot]", "-bot", "bot-", "dependabot", "renovate", "github-actions")


def is_bot(login, flag=None):
    if flag:
        return True
    l = (login or "").lower()
    # Copilot's account type is Bot but its login carries no [bot] suffix,
    # which once put 388 of its comments on the human side of the ledger.
    return l == "copilot" or any(p in l for p in BOTPAT)


def g_authorship(c):
    """Finding 6 and the authorship half of Finding 3."""
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    from sample import load, kiro_repos
    repos, _ = load(c)
    keep = [r["repo"] for r in repos]
    rp = ",".join("?" * len(keep))
    ph = ",".join("?" * len(NAMED_TOOLS))

    rows = c.execute(f"""SELECT s.repo_name, s.file_url_sha16,
                                k.author_identity_hash
                         FROM spec_files s
                         JOIN spec_file_commits k ON k.file_url_sha16 = s.file_url_sha16
                         WHERE {SQL_WHERE} AND s.spec_tool IN ({ph})
                           AND s.repo_name IN ({rp})""",
                     tuple(NAMED_TOOLS) + tuple(keep)).fetchall()
    per_file = collections.defaultdict(set)
    per_repo = collections.defaultdict(set)
    # Identity is the login where there is one, otherwise the author name.
    # Names are stored only as hashes, which preserves the equality this
    # grouping needs without releasing them.
    # author_identity_hash is LOWER(COALESCE(NULLIF(login,''), name, ''))
    # formed in the exporter and hashed there, so logins and names share one
    # namespace. A commit with neither keeps the empty identity rather than
    # being skipped.
    for repo, fsha, ident in rows:
        per_file[fsha].add(ident or "")
        per_repo[repo].add(ident or "")
    krows = c.execute("""SELECT kf.repo_name, kf.id, kc.author_identity_hash
                         FROM kiro_files kf JOIN kiro_file_commits kc
                           ON kc.kiro_file_id = kf.id""").fetchall()
    for repo, fid, ident in krows:
        per_file[f"kiro:{fid}"].add(ident or "")
        per_repo[repo].add(ident or "")

    one = sum(1 for v in per_file.values() if len(v) == 1)
    claim("authorship", "files with a recorded history", 36888, len(per_file))
    claim("authorship", "single-author files (%)", 98.3, one / len(per_file) * 100)
    solo = sum(1 for v in per_repo.values() if len(v) == 1)
    claim("authorship", "repositories with one spec author (%)", 63.0,
          solo / len(per_repo) * 100, dp=0)


# ----------------------------------------------------------------- review

def spec_comments():
    """Every inline comment anchored to a spec file, both halves."""
    out = []
    for r in jsonl("spec_comments.jsonl"):
        for x in r.get("comments") or []:
            if x.get("match") in ("exact", "basename"):
                out.append(dict(repo=x["repo_name"], user=x.get("user"),
                                assoc=x.get("author_association"),
                                reply=x.get("in_reply_to") is not None, bot=None))
    for r in jsonl("kiro_spec_comments.jsonl"):
        for x in r.get("comments") or []:
            if x.get("match") == "path":
                out.append(dict(repo=r["repo"], user=x.get("user"), assoc=x.get("assoc"),
                                reply=bool(x.get("in_reply")), bot=x.get("bot")))
    return out


def g_review(c):
    """The review half of Finding 3."""
    C = spec_comments()
    claim("review", "inline comments on a spec", 1731, len(C))
    bots = [x for x in C if is_bot(x["user"], x["bot"])]
    claim("review", "written by bots (%)", 68.5, len(bots) / len(C) * 100)
    silent = 266 - len({x["repo"] for x in C})
    claim("review", "repositories with no such comment", 210, silent)
    hum = [x for x in C if not is_bot(x["user"], x["bot"])]
    claim("review", "human comments", 545, len(hum))
    nr = sum(1 for x in hum if x["reply"])
    claim("review", "human comments that are replies (%)", 79.0,
          nr / len(hum) * 100, dp=0)
    claim("review", "human comments opening a thread", 112, len(hum) - nr)
    claim("review", "repositories with a human spec comment", 31,
          len({x["repo"] for x in hum}))
    first = sum(1 for r in jsonl("commit_prs.jsonl")
                if r.get("author_association") in ("FIRST_TIMER", "FIRST_TIME_CONTRIBUTOR"))
    claim("review", "first-time-contributor spec commits", 0, first)




# --------------------------------------------------------------- retention

def commits_per_file(c, where, params=()):
    """Distinct commits touching each file, for files matching `where`."""
    rows = c.execute(f"""SELECT s.file_url_sha16, COUNT(DISTINCT k.commit_sha)
                         FROM spec_files s
                         JOIN spec_file_commits k ON k.file_url_sha16 = s.file_url_sha16
                         WHERE {where} GROUP BY s.file_url_sha16""", params).fetchall()
    return [n for _, n in rows]


def g_retention(c):
    """Finding 4: how often a spec is revised after it is written."""
    from sample import load
    repos, _ = load(c)
    keep = [r["repo"] for r in repos]
    rp = ",".join("?" * len(keep))
    ph = ",".join("?" * len(NAMED_TOOLS))
    base = f"{SQL_WHERE} AND s.spec_tool IN ({ph}) AND s.repo_name IN ({rp})"
    par = tuple(NAMED_TOOLS) + tuple(keep)

    # Kiro lives in its own tables and belongs in the overall rate.
    allc = commits_per_file(c, base, par)
    kc = [n for _, n in c.execute(
        """SELECT kf.id, COUNT(DISTINCT kc.commit_sha)
           FROM kiro_files kf JOIN kiro_file_commits kc ON kc.kiro_file_id = kf.id
           GROUP BY kf.id""").fetchall()]
    both = allc + kc
    claim("retention", "specs with a single commit (%)", 81.5,
          sum(1 for n in both if n == 1) / len(both) * 100)

    def pct_one(extra, extra_par=()):
        v = commits_per_file(c, base + " AND " + extra, par + extra_par)
        return sum(1 for n in v if n == 1) / len(v) * 100, v

    p_arch, _ = pct_one("s.spec_role='archived'")
    claim("retention", "OpenSpec archived, one commit (%)", 95.4, p_arch)
    p_prop, _ = pct_one("s.spec_role='change_proposal'")
    claim("retention", "OpenSpec proposals, one commit (%)", 84.2, p_prop)
    p_cap, cap = pct_one("s.spec_role='living'")
    claim("retention", "OpenSpec capability specs, one commit (%)", 47.4, p_cap)
    claim("retention", "capability specs with 3+ commits (%)", 30.2,
          sum(1 for n in cap if n >= 3) / len(cap) * 100)

    p_cfg, _ = pct_one("s.spec_tool='speckit' AND s.spec_role='config'")
    claim("retention", "Spec Kit .specify/, one commit (%)", 97.7, p_cfg)
    p_feat, _ = pct_one("s.spec_tool='speckit' AND s.spec_role='feature'")
    claim("retention", "Spec Kit specs/, one commit (%)", 73.9, p_feat)
    # The manuscript currently has this sentence commented out. An earlier
    # draft said 74.5, which came from 100 - two - three_plus: that arithmetic
    # counts the two Kiro files with no commit history at all as single-commit
    # files. The correct figure over all 654 is 74.2, recorded here so the
    # right number is to hand if the sentence returns.
    ktot = c.execute("SELECT COUNT(*) FROM kiro_files").fetchone()[0]
    claim("retention", "Kiro, one commit (%)", 74.2,
          sum(1 for n in kc if n == 1) / ktot * 100,
          note="not currently stated in the paper")

    p_moai, moai = pct_one("s.spec_tool='moai'")
    claim("retention", "MoAI-ADK, one commit (%)", 22.3, p_moai)
    claim("retention", "MoAI-ADK, 3+ commits (%)", 60.3,
          sum(1 for n in moai if n >= 3) / len(moai) * 100)
    claim("retention", "MoAI-ADK files", 647, len(moai))

    # file counts, the other side of the same division
    for role, exp, name in (("archived", 19067, "OpenSpec archived changes"),
                            ("living", 6644, "OpenSpec capability specs")):
        n = c.execute(f"""SELECT COUNT(*) FROM spec_files s
                          WHERE {base} AND s.spec_role=?""",
                      par + (role,)).fetchone()[0]
        claim("retention", f"{name} (files)", exp, n)


# ------------------------------------------------------------- tool shares

def g_tools(c):
    """The concentration numbers in the sampling discussion."""
    from sample import load
    repos, nf = load(c)
    keep = [r["repo"] for r in repos]
    rp = ",".join("?" * len(keep))
    ph = ",".join("?" * len(NAMED_TOOLS))
    rows = c.execute(f"""SELECT s.spec_tool, COUNT(*) FROM spec_files s
                         WHERE {SQL_WHERE} AND s.spec_tool IN ({ph})
                           AND s.repo_name IN ({rp}) GROUP BY s.spec_tool""",
                     tuple(NAMED_TOOLS) + tuple(keep)).fetchall()
    per = dict(rows)
    kf = c.execute("SELECT COUNT(*) FROM kiro_files").fetchone()[0]
    per["kiro"] = kf
    total = sum(per.values())
    claim("tools", "sample files", 36890, total)
    claim("tools", "OpenSpec + Spec Kit share of files (%)", 89.0,
          (per["openspec"] + per["speckit"]) / total * 100)
    claim("tools", "OpenSpec share of files (%)", 78.4, per["openspec"] / total * 100)
    claim("tools", "tools contributing under 300 files", 7,
          sum(1 for v in per.values() if v < 300))


# ----------------------------------------------------------------- judges

def weighted(sample_csv, labels, hit):
    """Population-weighted share.

    The judge sample is stratified: 77 documents from each of 13 document
    types, so the raw share over the sample is not an estimate of the corpus.
    Each type is weighted by its size in the sample (`type_files`). Unweighted,
    the implementation share reads 87.7% rather than 77.6%, because the small
    types that carry the most implementation detail are massively
    over-represented by a fixed per-type draw.
    """
    rows = list(csv.DictReader(open(os.path.join(DERIVED, sample_csv))))
    pop, num, den = {}, collections.Counter(), collections.Counter()
    for r in rows:
        t = r["type"]
        pop[t] = float(r["type_files"])
        lab = labels.get(r["id"])
        if not lab:
            continue
        den[t] += 1
        if hit(lab):
            num[t] += 1
    total = sum(pop.values())
    return sum(pop[t] * num[t] / den[t] for t in den) / total * 100, sum(den.values())


def g_judges(c):
    """The LLM-judge results behind Findings 1 and 3."""
    content = {r["id"]: r["parsed"] for r in jsonl("e7_content.jsonl") if r.get("parsed")}
    rows = list(csv.DictReader(open(os.path.join(DERIVED, "e7_sample.csv"))))
    claim("judges", "documents sampled for content", 1000, len(rows))
    claim("judges", "of those, parsed by the judge", 997, len(content))

    impl, n = weighted("e7_sample.csv", content,
                       lambda p: p.get("implementation") == 1)
    claim("judges", "state how to build it (%)", 77.6, impl)
    sub, _ = weighted("e7_sample.csv", content,
                      lambda p: p.get("implementation_extent") in ("substantial", "dominant"))
    claim("judges", "where that fills a section or more (%)", 58.2, sub)

    work = {r["id"]: r["parsed"] for r in jsonl("e7_tasktype.jsonl") if r.get("parsed")}
    claim("judges", "documents judged for work type", 1000, len(work))




# ---------------------------------------------------------------- headings

HEADINGS = os.path.join(ROOT, "data", "build", "headings_all.csv")


def g_headings(c):
    """The heading analysis: extraction totals and Finding 7.

    Reads data/build/headings_all.csv, which `make data` regenerates from the
    packaged database. It is 155 MB, so it is built rather than shipped.
    """
    if not os.path.exists(HEADINGS):
        RESULTS.append(("headings", "headings_all.csv missing", "-",
                        "run analysis/extract_headings.py --kiro", False, ""))
        return
    import csv as _csv
    files = collections.defaultdict(set)
    hf = collections.defaultdict(set)
    nh = kiro_h = 0
    with open(HEADINGS, newline="") as fh:
        for r in _csv.DictReader(fh):
            k = (r["spec_tool"], r["spec_role"] or "na")
            files[k].add(r["file_sha16"])
            hf[(k, r["heading_norm"])].add(r["file_sha16"])
            nh += 1
            if r["spec_tool"] == "kiro":
                kiro_h += 1

    claim("headings", "headings extracted", 527981, nh)
    claim("headings", "files carrying at least one heading", 36881,
          sum(len(v) for v in files.values()))
    claim("headings", "files with none", 9, 36890 - sum(len(v) for v in files.values()))
    claim("headings", "headings contributed by Kiro", 12916, kiro_h)
    claim("headings", "tool x role combinations present", 16, len(files))

    # A document type needs 90 files to be reported; three combinations fall
    # under it (Trae 70, Claude Code 12, Cursor 1).
    K = [k for k in files if len(files[k]) >= 90]
    claim("headings", "document types at >= 90 files", 13, len(K))
    claim("headings", "files in the dropped types", 83,
          sum(len(files[k]) for k in files if len(files[k]) < 90))
    claim("headings", "OpenSpec files matching no role", 135,
          len(files[("openspec", "na")]))

    core = {k: {h for (kk, h), v in hf.items()
                if kk == k and len(v) / len(files[k]) >= .5} for k in K}
    own = collections.Counter(h for k in K for h in core[k])
    rows = [h for h, n in own.items() if n > 1]
    claim("headings", "sections heading a majority somewhere", 40, len(own))
    claim("headings", "of those, in exactly one type", 30,
          sum(1 for n in own.values() if n == 1))
    claim("headings", "recurring in more than one type", 10, len(rows))
    cross = [h for h in rows if len({k[0] for k in K if h in core[k]}) > 1]
    claim("headings", "crossing a tool boundary", 9, len(cross))

    v = sorted(len(hf.get((k, h), ())) / len(files[k]) * 100 for h in own for k in K)
    claim("headings", "type-section pairs plotted against", 520, len(v))
    claim("headings", "pairs exactly zero (%)", 52.0,
          sum(1 for x in v if x == 0) / len(v) * 100, dp=0)
    claim("headings", "pairs below a tenth (%)", 82.0,
          sum(1 for x in v if x < 10) / len(v) * 100, dp=0)
    half = [x for x in v if x >= 50]
    mid = (half[len(half) // 2] if len(half) % 2
           else (half[len(half) // 2 - 1] + half[len(half) // 2]) / 2)
    claim("headings", "median of pairs at half or more (%)", 66.0, mid, dp=0)

    def share(tool, role, h):
        return len(hf.get(((tool, role), h), ())) / len(files[(tool, role)]) * 100

    claim("headings", "OpenSpec capability specs heading requirements (%)", 81.0,
          share("openspec", "living", "requirements"), dp=0)
    claim("headings", "OpenSpec change proposals heading added requirements (%)", 83.0,
          share("openspec", "change_proposal", "added requirements"), dp=0)




# ---------------------------------------------------------------- PR layer

def g_prs(c):
    """Finding 2's pull-request layer.

    Built from data/derived/pr_layer.json, a snapshot of the per-tool PR
    tables, which are the one part of the corpus the SQLite export does not
    carry. Rebuild it with build_pr_layer.py if you have the MySQL corpus.
    """
    d = json.load(open(os.path.join(DERIVED, "pr_layer.json")))
    pr = d["prs"]
    claim("prs", "repositories crawled", 949, len(d["repositories"]))
    claim("prs", "spec commits queried", 15726, d["commits_queued"])
    # A repository that ships two tools appears in both tool tables, so the
    # row count double-counts 13 PRs. The paper reports distinct PRs.
    claim("prs", "rows across the per-tool tables", 5992, d["rows"])
    claim("prs", "distinct spec-modifying PRs", 5979, len(pr))
    claim("prs", "repositories yielding a PR", 581,
          len({k.rsplit("#", 1)[0] for k in pr}))
    code = sum(1 for v in pr.values() if v["code"])
    claim("prs", "PRs that also modify code (%)", 81.2, code / len(pr) * 100)


GROUPS = {"headings": g_headings, "prs": g_prs,
          "cascade": g_cascade, "sample": g_sample,
          "authorship": g_authorship, "review": g_review,
          "retention": g_retention, "tools": g_tools, "judges": g_judges}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=sorted(GROUPS), action="append")
    ap.add_argument("--quiet", action="store_true", help="show failures only")
    a = ap.parse_args()

    c = connect()
    for g in (a.group or sorted(GROUPS)):
        try:
            GROUPS[g](c)
        except Exception as e:
            RESULTS.append((g, f"GROUP RAISED {type(e).__name__}", "-", str(e)[:48], False, ""))
    c.close()

    width = max(len(n) for _, n, *_ in RESULTS) + 2
    last = None
    bad = 0
    for group, name, paper, got, ok, note in RESULTS:
        if not ok:
            bad += 1
        if a.quiet and ok:
            continue
        if group != last:
            print(f"\n{group.upper()}")
            last = group
        flag = "ok  " if ok else "FAIL"
        print(f"  [{flag}] {name:<{width}} paper {paper:>12}   recomputed {got:>12}"
              + (f"   {note}" if note else ""))
    print(f"\n{len(RESULTS)} claims, {len(RESULTS) - bad} reproduced, {bad} failed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
