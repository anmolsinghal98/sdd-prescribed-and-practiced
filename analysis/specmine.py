"""Access to the packaged dataset.

    from specmine import connect
    conn = connect()

Replaces the `import fetch_spec_files` / MySQL connection that the original
analysis used. There is no server and no configuration: one SQLite file,
unpacked on first use.

Two things to know when reading the queries in this package.

REPOSITORIES ARE COUNTED CASE-INSENSITIVELY. GitHub treats repository names
that way and so did the MySQL collation the original analysis ran under.
Exactly one repository in the census is recorded under two spellings
(`JaZeR-444/FL-Studio-Master-Hub` and `JaZeR-444/fl-studio-master-hub`), so a
case-sensitive count returns 85,301 where the paper says 85,300. Use
`COUNT(DISTINCT LOWER(repo_name))`, or the `n_repos()` helper below.

THE SAMPLE IS THE NAMED-TOOL FILES. `spec_files` holds every kept file in the
266 sample repositories, 300 of which carry no tool fingerprint. Filter with
`NAMED_TOOLS`, which `sample.load()` does for you.
"""
import os, sqlite3, lzma, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
DB = os.path.join(DATA, "specmine-sample.sqlite")
XZ = DB + ".xz"

# Tool labels that come from a real kit's path fingerprint. The four generic
# buckets (adhoc_other, specs_generic, docs_embedded, root_bare) mean
# "spec-shaped file, no tool marker" and are not evidence of self-invention.
NAMED_TOOLS = {"caffeine", "openspec", "speckit", "conductor", "agent_os", "specweave",
               "moai", "claude_code", "opencode", "trae", "codex", "cursor", "kilocode",
               "gsd", "zenflow", "kitty_specs", "dot_specs"}
GENERIC_BUCKETS = {"adhoc_other", "specs_generic", "docs_embedded", "root_bare"}

MIN_STARS, MIN_COMMITS = 10, 10

# Predicate over the sample tables, aliased `s`. Same text as the original
# analysis so the two can be diffed by eye.
SQL_WHERE = f"""s.not_spec_filter = 0
    AND s.repo_archived = 0 AND s.repo_fork = 0 AND s.repo_private = 0
    AND s.repo_visibility = 'public'
    AND s.repo_stars >= {MIN_STARS}
    AND s.repo_license_spdx_id IS NOT NULL
    AND s.repo_license_spdx_id NOT IN ('', 'NOASSERTION')"""


def unpack(force=False):
    """Decompress the dataset if it is not already there."""
    if os.path.exists(DB) and not force:
        return DB
    if not os.path.exists(XZ):
        raise SystemExit(
            f"neither {DB} nor {XZ} found.\n"
            "The dataset ships compressed; run `make data` or\n"
            f"  xz -dk {XZ}")
    print(f"unpacking {os.path.basename(XZ)} (once) ...", flush=True)
    with lzma.open(XZ) as src, open(DB + ".part", "wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 22)
    os.replace(DB + ".part", DB)
    return DB


def connect():
    conn = sqlite3.connect(unpack())
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")
    return conn


def placeholders(xs):
    return ",".join("?" * len(xs))


def n_repos(rows, idx=0):
    """Distinct repositories, counted the way GitHub counts them."""
    return len({(r[idx] or "").lower() for r in rows})
