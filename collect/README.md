# How SpecMine was collected

The fifteen scripts that built the corpus from nothing, in the order they ran.
They are here to be **read**, not re-run: see "Why you cannot reproduce this"
below. Nothing elsewhere in the package depends on them — the analyses and the
claim checks all run from `data/specmine-sample.sqlite`.

## Order

```
fetch_spec_files.py        GitHub code search for spec.md / specs.md, plus repo
                           and last-commit metadata          -> spec_files
classify_specs.py          flags non-SDD files               -> not_spec_filter
classify_tooling.py        attributes each kept file to a tool by path
                           fingerprint                       -> spec_tool, spec_role
  |
  +-- fetch_commit_history.py   full path history per file   -> spec_file_commits
  +-- fetch_spec_content.py     raw markdown at the last commit -> file_content
        |
        +-- analyze_content.py  ~40 deterministic features   -> spec_content_features
        +-- traceability.py     links parsed from text and commit messages -> spec_links
              +-- fetch_repo_trees.py   sibling and code edges -> repo_trees

OpenSpec deep dive (needs classify_tooling)
  fetch_openspec_full.py        the whole openspec/ tree for curated repos
  fetch_openspec_artifacts.py   proposal/design/tasks siblings, parsed task links
  resolve_code_links.py         version-pins those links to a commit

Pull requests (needs fetch_commit_history and a <tool>_repos table)
  fetch_spec_prs.py --tool T --seed --discover --rollup

Kiro, a separate census (its layout is invisible to a spec.md search)
  fetch_kiro.py --schema --plan     -> kiro_files
  kiro_enrich.py --phase repos|content|commits|features

Reporting
  spec_descriptives.py
```

Two ordering constraints are easy to miss. `classify_specs.py` gates every
later stage through `not_spec_filter = 0`, so running anything before it
silently includes files the corpus excludes. And `kiro_enrich.py --phase
features` imports `analyze_content.py` as a module rather than merely
depending on it conceptually.

## Configuration

`fetch_spec_files.py` is the shared helper: token rotation, the database
connection, and the stable file id. The others import it, so they expect to
sit in the same directory as it.

Credentials are read from a `.env`, by default beside these scripts, or
wherever `SPECMINE_ENV` points:

```
GITHUB_TOKENS=tok1,tok2,...      # rotated; the census used about 19
myDB_user=...
myDB_pwd=...
myDB_name=specdriven
```

No credentials are in this repository, and `.env` is ignored by git.

## Why you cannot reproduce this

Re-running these would not rebuild the corpus we analysed, for reasons that
have nothing to do with the code:

- **GitHub code search is not stable.** Its index changes continuously, caps
  any query at 1,000 results (which is why the census partitions queries by
  file size and recursively halves any range that comes back full), and
  returns only what it has indexed, which need not be every matching file.
- **The population moved.** Repositories have been deleted, renamed, made
  private, and starred since July 2026. Star counts, licences and archived
  flags are as-of-crawl snapshots, so the cascade's thresholds would select a
  different set today.
- **It is expensive.** 85,300 repositories, 503,767 files, and several million
  API calls across a rotating token pool, over days.

The corpus as analysed is frozen in `data/` and on Zenodo
(**ZENODO_DOI_PLACEHOLDER**). These scripts document how it was built.

## Not included

Deliberately excluded, so there is no question which code produced the paper:

- earlier drafts superseded by the scripts above — `fetch_sdd_md_original.py`,
  `_original2.py`, `_intermediate.py`, `spec_kit_identifier_original.py`
  (about 3,300 lines)
- a legacy CSV-era pipeline that targets a different database entirely
  (about 4,200 lines)
