#!/usr/bin/env python3
"""Export the analysis sample from the SpecMine MySQL database into one
portable SQLite file.

    python3 build_dataset.py --out data/specmine-sample.sqlite

This is the only script in the package that needs the original MySQL server.
Everything else reads the SQLite file it produces, so a replicator never
installs a database.

WHAT IS IN THE FILE

  spec_files_all      every kept spec file in the whole census (not just the
                      sample), with only the columns the Table-4 cascade
                      filters on. Without this the cascade cannot be
                      recomputed, only asserted: it starts at 503,767 files
                      and the sample is what survives it.
  spec_file_commits_tier
                      commits for the licensed-tier repositories, so the final
                      cascade step (>= 10 distinct spec commits) is recomputed
                      rather than taken on trust.
  spec_files          the sample's files, with document text.
  spec_file_commits   the sample's commit history.
  kiro_files,
  kiro_file_commits   the Kiro half of the sample, which lives in its own
                      tables because Kiro's layout is invisible to a spec.md
                      census.
  spec_content_features
                      the Tier-1 deterministic features per sample file.
  cascade_expected    the per-stage counts the manuscript reports, so
                      verification can diff against them offline.

PERSONAL DATA

The manuscript's ethics statement says the release keeps author and committer
logins and numeric ids, which are public and needed for authorship analysis,
and drops commit emails, avatar URLs and remaining profile fields. This script
implements exactly that, with one addition.

Author names and emails are never written. They are replaced by
`author_name_hash` and `author_email_hash`: HMAC-SHA256 under a random salt
that is generated per run and then discarded. The authorship analysis needs
only to know whether two commits carry the SAME name or address -- that is how
an unlinked git identity is matched to a GitHub login -- and equality survives
hashing. The address itself does not, and cannot be recovered by guessing
because the salt is gone.

Columns dropped outright: every *_email, *_avatar_url, *_html_url,
*_site_admin, *_node_id, *_signature, *_signature_payload, the clone/ssh/svn
URLs, and the GPG verification fields.
"""
import argparse, hashlib, hmac, os, secrets, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))

# The salt lives for the lifetime of this process only.
_SALT = secrets.token_bytes(32)


def h(v):
    """Stable within one export, unrecoverable after it."""
    if v is None:
        return None
    v = str(v).strip().lower()
    if not v:
        return None
    return hmac.new(_SALT, v.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def identity(login, name):
    """The author identity the analysis groups by, hashed.

    The original analysis keys on LOWER(COALESCE(NULLIF(login,''), name, '')):
    ONE namespace, so a commit with no login whose author name is `alice`
    merges with a commit whose login is `alice`. Hashing login and name into
    separate columns and letting the reader combine them breaks that merge and
    splits such identities apart. So the identity is formed here, while both
    values are still in the clear, and only the result is hashed.
    """
    v = (login or "").strip().lower() or (name or "").strip().lower()
    return h(v) if v else ""


def subject(v):
    """First line of a commit message, capped.

    Bodies average 2,358 characters here because most of these commits are
    agent-written, and no analysis in this package reads them. The manuscript
    also notes that commit messages are authored prose that may carry
    identifying information. The subject line keeps the record legible at a
    fraction of the size and the exposure.
    """
    if v is None:
        return None
    return str(v).splitlines()[0][:200] if str(v).strip() else None


# ---------------------------------------------------------------- mysql side

def mysql_conn(env_path):
    for line in open(env_path):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    import mysql.connector
    return mysql.connector.connect(
        host=os.environ.get("myDB_host", "localhost"),
        port=int(os.environ.get("myDB_port", 3306)),
        user=os.environ["myDB_user"], password=os.environ["myDB_pwd"],
        database=os.environ.get("myDB_name", "specdriven"))


# Tool labels that come from a real kit's path fingerprint. The four generic
# buckets (adhoc_other, specs_generic, docs_embedded, root_bare) mean
# "spec-shaped file, no tool marker" and are excluded from the sample.
NAMED_TOOLS = {"caffeine", "openspec", "speckit", "conductor", "agent_os", "specweave",
               "moai", "claude_code", "opencode", "trae", "codex", "cursor", "kilocode",
               "gsd", "zenflow", "kitty_specs", "dot_specs"}

KEEP_WHERE = """s.not_spec_filter = 0
    AND s.repo_archived = 0 AND s.repo_fork = 0 AND s.repo_private = 0
    AND s.repo_visibility = 'public'
    AND s.repo_stars >= 10
    AND s.repo_license_spdx_id IS NOT NULL
    AND s.repo_license_spdx_id NOT IN ('', 'NOASSERTION')"""

# sample columns: everything an analysis script touches, nothing personal
SPEC_COLS = [
    "file_url_sha16", "file_url", "file_path", "file_name", "file_sha",
    "repo_id", "repo_name", "owner_login", "owner_id", "owner_type",
    "repo_description", "repo_stars", "repo_forks", "repo_watchers",
    "repo_open_issues", "repo_size_kb", "repo_language",
    "repo_license_spdx_id", "repo_default_branch", "repo_topics",
    "repo_archived", "repo_fork", "repo_private", "repo_visibility",
    "repo_created_at", "repo_updated_at", "repo_pushed_at",
    "not_spec_filter", "spec_tool", "spec_role",
    "file_first_commit_sha", "file_first_commit_at",
    "file_first_commit_author_login", "file_first_commit_author_id",
    "file_first_commit_author_type",
    "file_last_commit_sha", "file_last_commit_at",
    "file_last_commit_author_login", "file_last_commit_author_id",
    "file_last_commit_author_type",
    "file_total_commits", "commit_history_status",
    "file_content", "file_content_sha", "file_content_bytes",
    "content_fetch_status", "feature_branch",
    "n_linked_prs", "n_linked_issues", "n_sibling_docs", "n_code_links",
    "has_tasks", "has_plan", "has_proposal", "has_design",
]
# fetched so they can be hashed, never written in the clear
SPEC_HASHED = [("file_first_commit_author_email", "file_first_commit_author_email_hash"),
               ("file_last_commit_author_email", "file_last_commit_author_email_hash")]
# fetched, then reduced to their first line
SPEC_SUBJECT = [("file_last_commit_message", "file_last_commit_subject")]

COMMIT_COLS = ["file_url_sha16", "repo_name", "file_path", "commit_sha",
               "seq_from_oldest", "authored_at", "author_login", "author_id",
               "author_type", "committed_at", "committer_login"]
COMMIT_HASHED = [("author_name", "author_name_hash"), ("author_email", "author_email_hash")]
COMMIT_SUBJECT = [("message", "message_subject")]

KIRO_COLS = ["id", "repo_name", "owner_login", "repo_id", "file_path", "file_name",
             "kind", "feature", "file_sha", "file_content", "file_content_sha",
             "file_content_bytes", "content_fetch_status", "file_total_commits"]
KIRO_COMMIT_COLS = ["kiro_file_id", "repo_name", "file_path", "seq_from_oldest",
                    "commit_sha", "authored_at", "author_login", "author_id",
                    "committed_at", "committer_login"]
KIRO_COMMIT_HASHED = [("author_name", "author_name_hash"), ("author_email", "author_email_hash")]
KIRO_COMMIT_SUBJECT = [("message", "message_subject")]


def affinity(values):
    """SQLite column type inferred from the values actually seen.

    This matters more than it looks. Declaring everything TEXT gives the column
    text affinity, so `repo_stars >= 10` compares strings and '9' sorts after
    '10'. Every numeric filter in the cascade would silently misbehave.
    """
    seen = {type(v) for v in values if v is not None}
    if not seen:
        return "TEXT"
    if seen <= {bool, int}:
        return "INTEGER"
    if seen <= {bool, int, float}:
        return "REAL"
    return "TEXT"


def copy(cur, sq, name, select, cols, hashed, params=(), chunk=2000, subj=(),
         ident=None):
    """Stream one MySQL query into a SQLite table.

    `ident` is (login_col, name_col, dst): the two are combined into one
    hashed identity, because the grouping the analysis does needs them in a
    single namespace.
    """
    extra = [ident[2]] if ident else []
    out_cols = list(cols) + [dst for _, dst in hashed] + [dst for _, dst in subj] + extra
    src_cols = list(cols) + [s for s, _ in hashed] + [s for s, _ in subj]
    if ident:
        src_cols = src_cols + [ident[0], ident[1]] if ident[0] not in src_cols else src_cols
    cur.execute(select, params)

    def shape(rows):
        out = []
        for r in rows:
            d = dict(zip(src_cols, r))
            row = ([d[c] for c in cols] + [h(d[s]) for s, _ in hashed]
                   + [subject(d[s]) for s, _ in subj])
            if ident:
                row.append(identity(d.get(ident[0]), d.get(ident[1])))
            out.append(row)
        return out

    first = shape(cur.fetchmany(chunk))
    types = [affinity([row[i] for row in first]) for i in range(len(out_cols))]
    sq.execute(f"DROP TABLE IF EXISTS {name}")
    sq.execute(f"CREATE TABLE {name} ("
               + ", ".join(f"{c} {t}" for c, t in zip(out_cols, types)) + ")")

    ins = f"INSERT INTO {name} VALUES ({','.join('?' * len(out_cols))})"
    n, t0, batch = 0, time.time(), first
    while batch:
        sq.executemany(ins, batch)
        n += len(batch)
        if n % 100000 < chunk:
            print(f"    {name}: {n:,} rows ({time.time()-t0:.0f}s)", flush=True)
        batch = shape(cur.fetchmany(chunk))
    sq.commit()
    print(f"  {name:<26}{n:>9,} rows   "
          f"{sum(1 for t in types if t != 'TEXT')}/{len(types)} numeric", flush=True)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="/data2/shyamaga/AndrewSDD@JSS/.env")
    ap.add_argument("--keep", default=os.path.join(HERE, "data", "kiro_keep.txt"))
    ap.add_argument("--out", default=os.path.join(HERE, "data", "specmine-sample.sqlite"))
    a = ap.parse_args()

    my = mysql_conn(a.env); cur = my.cursor()
    # The sample is derived here rather than imported, so that this script
    # depends only on MySQL and analysis/sample.py depends only on SQLite.
    # Same definition as the manuscript's cascade: kept spec.md files, a named
    # tool, >= 10 stars, public and not a fork, a recognised SPDX licence, and
    # >= 10 DISTINCT commits touching those files.
    cur.execute(f"""SELECT s.repo_name, COUNT(DISTINCT k.commit_sha)
                    FROM spec_files s JOIN spec_file_commits k
                      ON k.file_url_sha16 = s.file_url_sha16
                    WHERE {KEEP_WHERE}
                      AND s.spec_tool IN ({','.join(['%s'] * len(NAMED_TOOLS))})
                    GROUP BY s.repo_name
                    HAVING COUNT(DISTINCT k.commit_sha) >= 10""",
                tuple(sorted(NAMED_TOOLS)))
    keep = sorted(r[0] for r in cur.fetchall())
    kiro = sorted(set(open(a.keep).read().split()))
    print(f"sample: {len(keep)} spec-file repos + {len(kiro)} Kiro repos")

    if os.path.exists(a.out):
        os.remove(a.out)
    sq = sqlite3.connect(a.out)
    sq.execute("PRAGMA journal_mode=OFF")
    sq.execute("PRAGMA synchronous=OFF")

    ph = ",".join(["%s"] * len(keep))
    kph = ",".join(["%s"] * len(kiro))

    # 1. whole census, filter columns only -- lets the cascade be recomputed.
    # Restricted to the kept set, because Table 4's base IS the kept set:
    # 470,795 kept spec files + 32,972 Kiro requirements = 503,767.
    cols_all = ["file_url_sha16", "repo_name", "file_path", "spec_tool", "spec_role",
                "repo_stars", "repo_license_spdx_id", "repo_archived", "repo_fork",
                "repo_private", "repo_visibility", "not_spec_filter",
                "file_first_commit_at"]
    copy(cur, sq, "spec_files_all",
         f"SELECT {','.join(cols_all)} FROM spec_files WHERE not_spec_filter = 0",
         cols_all, [])

    # The other half of that base: the whole Kiro census, filter columns only.
    # Kiro keeps no first-commit column, so it is derived here: the adoption
    # figure dates a repository's uptake to its earliest spec commit.
    kall = ["repo_name", "owner_login", "file_path", "kind", "feature",
            "first_commit_at"]
    copy(cur, sq, "kiro_files_all",
         """SELECT kf.repo_name, kf.owner_login, kf.file_path, kf.kind, kf.feature,
                   LEFT(MIN(kc.authored_at), 10)
            FROM kiro_files kf
            LEFT JOIN kiro_file_commits kc ON kc.kiro_file_id = kf.id
            WHERE kf.kind='requirements' GROUP BY kf.id""",
         kall, [])
    krall = ["repo_name", "repo_stars", "repo_license_spdx_id", "owner_login",
             "repo_archived", "repo_fork", "repo_visibility"]
    copy(cur, sq, "kiro_repos_all",
         f"SELECT {','.join(krall)} FROM kiro_repos", krall, [])

    # 2. commits for the licensed tier, for the >= 10 distinct commits step
    copy(cur, sq, "spec_file_commits_tier",
         f"""SELECT DISTINCT s.repo_name, k.commit_sha, s.spec_tool
             FROM spec_files s JOIN spec_file_commits k
               ON k.file_url_sha16 = s.file_url_sha16
             WHERE {KEEP_WHERE}""",
         ["repo_name", "commit_sha", "spec_tool"], [])

    # 3. the sample itself
    copy(cur, sq, "spec_files",
         f"""SELECT {','.join(SPEC_COLS + [s for s, _ in SPEC_HASHED]
                              + [s for s, _ in SPEC_SUBJECT])}
             FROM spec_files
             WHERE not_spec_filter = 0 AND repo_name IN ({ph})""",
         SPEC_COLS, SPEC_HASHED, tuple(keep), subj=SPEC_SUBJECT)

    copy(cur, sq, "spec_file_commits",
         f"""SELECT {','.join('k.'+c for c in COMMIT_COLS)},
                    {','.join('k.'+s for s, _ in COMMIT_HASHED)},
                    {','.join('k.'+s for s, _ in COMMIT_SUBJECT)}
             FROM spec_file_commits k JOIN spec_files s
               ON s.file_url_sha16 = k.file_url_sha16
             WHERE s.not_spec_filter=0 AND s.repo_name IN ({ph})""",
         COMMIT_COLS, COMMIT_HASHED, tuple(keep), subj=COMMIT_SUBJECT,
         ident=("author_login", "author_name", "author_identity_hash"))

    # 4. the Kiro half
    copy(cur, sq, "kiro_files",
         f"SELECT {','.join(KIRO_COLS)} FROM kiro_files "
         f"WHERE kind='requirements' AND repo_name IN ({kph})",
         KIRO_COLS, [], tuple(kiro))

    copy(cur, sq, "kiro_file_commits",
         f"""SELECT {','.join('kc.'+c for c in KIRO_COMMIT_COLS)},
                    {','.join('kc.'+s for s, _ in KIRO_COMMIT_HASHED)},
                    {','.join('kc.'+s for s, _ in KIRO_COMMIT_SUBJECT)}
             FROM kiro_file_commits kc JOIN kiro_files kf ON kf.id = kc.kiro_file_id
             WHERE kf.kind='requirements' AND kf.repo_name IN ({kph})""",
         KIRO_COMMIT_COLS, KIRO_COMMIT_HASHED, tuple(kiro), subj=KIRO_COMMIT_SUBJECT,
         ident=("author_login", "author_name", "author_identity_hash"))

    # kiro repo metadata, for owner_login and stars
    copy(cur, sq, "kiro_repos",
         f"""SELECT {','.join(krall)} FROM kiro_repos WHERE repo_name IN ({kph})""",
         krall, [], tuple(kiro))

    # 5. Tier-1 content features for the sample
    cur.execute("SHOW COLUMNS FROM spec_content_features")
    fcols = [r[0] for r in cur.fetchall()]
    copy(cur, sq, "spec_content_features",
         f"""SELECT {','.join('f.'+c for c in fcols)} FROM spec_content_features f
             JOIN spec_files s ON s.file_url_sha16 = f.file_url_sha16
             WHERE s.not_spec_filter=0 AND s.repo_name IN ({ph})""",
         fcols, [], tuple(keep))

    for stmt in ("CREATE INDEX ix_sf_repo   ON spec_files(repo_name)",
                 "CREATE INDEX ix_sf_sha    ON spec_files(file_url_sha16)",
                 "CREATE INDEX ix_sf_tool   ON spec_files(spec_tool)",
                 "CREATE INDEX ix_sfc_sha   ON spec_file_commits(file_url_sha16)",
                 "CREATE INDEX ix_sfc_repo  ON spec_file_commits(repo_name)",
                 "CREATE INDEX ix_all_repo  ON spec_files_all(repo_name)",
                 "CREATE INDEX ix_all_tool  ON spec_files_all(spec_tool)",
                 "CREATE INDEX ix_kf_repo   ON kiro_files(repo_name)",
                 "CREATE INDEX ix_kfc_file  ON kiro_file_commits(kiro_file_id)",
                 "CREATE INDEX ix_scf_sha   ON spec_content_features(file_url_sha16)"):
        sq.execute(stmt)
    sq.commit()
    sq.execute("VACUUM")
    sq.close(); my.close()
    mb = os.path.getsize(a.out) / 1024 / 1024
    print(f"\nwrote {a.out}  ({mb:.1f} MB)")
    print("salt discarded; author names and emails are present only as hashes")


if __name__ == "__main__":
    main()
