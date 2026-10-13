# The data

`specmine-sample.sqlite.xz` is the analysis sample, and everything in
`analysis/`, `figures/` and `verify/` reads it. Unpack once:

```bash
xz -dk specmine-sample.sqlite.xz      # ~63 MB -> ~400 MB
```

The full SpecMine corpus — every spec file the census found, not just the
sample — is archived separately: **ZENODO_DOI_PLACEHOLDER**. You do not need it
to reproduce anything in the paper.

## Tables

| table | rows | what it is |
|---|---:|---|
| `spec_files_all` | 470,795 | every *kept* spec file in the census, filter columns only (no text) |
| `kiro_files_all` | 32,972 | every Kiro requirements document in the census, filter columns only |
| `kiro_repos_all` | 12,910 | repository metadata for the Kiro census |
| `spec_file_commits_tier` | 29,763 | distinct spec commits for licensed-tier repositories |
| `spec_files` | 36,536 | the sample's files, **with document text** |
| `spec_file_commits` | 54,164 | the sample's commit history |
| `kiro_files` | 654 | the Kiro half of the sample, with text |
| `kiro_file_commits` | 1,022 | its commit history |
| `kiro_repos` | 13 | its repository metadata |
| `spec_content_features` | 36,536 | deterministic per-file features |

The first four tables exist so the Table 4 cascade can be **recomputed rather
than asserted**. The cascade starts from 503,767 files across 85,300
repositories and the sample is what survives it; with only the sample you could
confirm the last row of that table and nothing above it.

`470,795 + 32,972 = 503,767`, which is the cascade's base.

## Two things that will bite you

**Count repositories case-insensitively.** GitHub treats repository names as
case-insensitive, and so did the MySQL collation the original analysis ran
under. Exactly one repository in the census is recorded under two spellings:

```
JaZeR-444/FL-Studio-Master-Hub
JaZeR-444/fl-studio-master-hub
```

SQLite and Python compare strings case-sensitively, so a naive port counts
85,301 repositories where the paper says 85,300. Use
`COUNT(DISTINCT LOWER(repo_name))`. The paper's figure is the correct one:
that is one repository, not two.

**`spec_files` is a superset of the sample by 300 files.** It holds every kept
file in the 266 sample repositories, including 300 whose path carries no tool
fingerprint (`specs_generic` 253, `adhoc_other` 39, `docs_embedded` 7,
`root_bare` 1). The sample proper is the named-tool files only:

```
36,236 named-tool spec files + 654 Kiro requirements = 36,890
```

Filter on `spec_tool IN (...)` — `analysis/sample.py` does this for you. The
extra rows are kept because they are real files in those repositories and
their exclusion is itself a finding.

## Personal data

The manuscript's ethics statement says the release keeps author and committer
logins and numeric identifiers, which are public and needed for authorship
analysis, and drops commit emails, avatar URLs and remaining profile fields.
That is what this file contains, with one addition.

Author **names and email addresses are never stored**. They appear only as
`author_name_hash` and `author_email_hash`: HMAC-SHA256 under a 32-byte random
salt generated per export and discarded when it finishes. The authorship
analysis needs to know only whether two commits carry the *same* name or
address — that is how an unlinked git identity is matched to a GitHub login —
and equality survives hashing while the address does not. With the salt gone
the hashes cannot be reversed by guessing common addresses.

One derived column exists for a reason worth knowing. The analysis groups
commits by `LOWER(COALESCE(NULLIF(author_login,''), author_name, ''))` — a
**single namespace**, so a commit with no login whose author name is `alice`
merges with a commit whose login is `alice`. Hashing login and name into
separate columns and leaving the reader to combine them breaks that merge and
splits such identities apart; it moves the single-author rate from 98.3% to
98.2%. So `author_identity_hash` is formed in the exporter, while both values
are still in the clear, and only the result is hashed. Group by that column,
not by `author_name_hash`.

Commit messages are reduced to their subject line, capped at 200 characters.
Bodies here average 2,358 characters because most of these commits are
agent-written, no analysis in this package reads them, and the manuscript notes
that commit messages are authored prose that may carry identifying
information.

Dropped outright: every `*_email`, `*_avatar_url`, `*_html_url`,
`*_site_admin`, `*_node_id`, `*_signature`, `*_signature_payload`, the
clone/ssh/svn URLs, and the GPG verification fields.

Each record keeps its repository's SPDX licence so redistribution terms can be
respected and licence-compatible subsets selected.

## Rebuilding it

Only needed if you have the original MySQL server; replicators do not.

```bash
python3 build_dataset.py --env /path/to/.env --out data/specmine-sample.sqlite
```

Hashes differ between runs by design — the salt is random each time — so the
file is not byte-reproducible. Every count computed from it is.
