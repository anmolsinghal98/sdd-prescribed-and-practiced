# Replication package

Supporting *Spec-Driven Development as Prescribed and as Practiced*.

Everything here runs from one SQLite file. There is no database server to
install and no credentials to configure.

```bash
make all          # unpack the data, redraw every figure, check every claim
```

Needs Python 3.9+, `xz`, and `markdown-it-py` with `mdit-py-plugins` (for
heading extraction). `make verify` alone is enough to check the numbers.

## What is here

| | |
|---|---|
| `data/` | the analysis sample as SQLite, plus the labelled and crawled artifacts the analyses read. See `data/README.md`. |
| `analysis/` | the sample definition and the analyses that run on it |
| `figures/` | one script per figure; `make figures` writes them into `figures/out/` under the names the paper includes |
| `verify/claims.py` | every quantitative claim in the manuscript, recomputed and diffed against the printed value |
| `qualitative/` | the Reddit keyword list, the interview protocol, and the joint Reddit and interview codebook |
| `collect/` | the fifteen crawlers that built the corpus, for reading rather than re-running; see `collect/README.md` |
| `build_dataset.py` | rebuilds the SQLite file from the original MySQL corpus. The only script that needs it. |

The full SpecMine corpus — every spec file the census found, not just the
266-repository analysis sample — is archived separately at
**ZENODO_DOI_PLACEHOLDER**. Nothing in this package requires it.

## Checking the numbers

```bash
make verify              # all groups
python3 verify/claims.py --group headings --quiet
```

Each claim pairs the value as printed in the paper with a function that
recomputes it from this package. Percentages are compared at the precision the
paper prints: 98.3% must round-trip to 98.3, while a paper that prints 79% is
satisfied by 79.4.

**`make verify` exits zero: all 74 claims reproduce.** Two figures in an
earlier draft did not, and the checks hold the corrected values:

- **Kiro's single-commit share is 74.2%.** The draft's 74.5% came from
  `100 − two − three_plus`, which counts the two Kiro files with no commit
  history as single-commit files. Counting directly over all 654 gives 74.2%.
- **30.2% of capability specs have three or more commits.** The draft said
  "a third."

## Three things that will bite a careless replication

Each of these has already produced a wrong number, so they are encoded in the
checks rather than left to the reader.

**Count repositories case-insensitively.** GitHub treats repository names that
way, and so did the collation the original analysis ran under. One repository
in the census is recorded under two spellings, so a case-sensitive count
returns 85,301 where the paper says 85,300.

**The judge results are population-weighted.** The sample is stratified at 77
documents from each of 13 document types, so a raw share over the sample is
not an estimate of the corpus. Unweighted, the headline implementation figure
reads 87.7% rather than 77.6%.

**Group authors by `author_identity_hash`.** The analysis keys on
`LOWER(COALESCE(NULLIF(author_login,''), author_name, ''))`, a single
namespace, so a commit with no login whose author name is `alice` merges with
a commit whose login is `alice`. Combining separate login and name columns
yourself breaks that merge and moves the single-author rate from 98.3% to
98.2%.

## Personal data

The release keeps author and committer logins and numeric identifiers, which
are public and needed for the authorship analysis, and drops commit emails,
avatar URLs and remaining profile fields. Names and addresses survive only as
unrecoverable hashes, which preserves the equality the analysis needs without
publishing the values. `data/README.md` sets this out in full.
