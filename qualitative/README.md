# Reddit and interview materials

The materials behind the paper's Reddit and interview analyses. The paper's appendices
summarize them: the High-Level Codes appendix gives the codebook's top level, and
the Codes and Participants appendix lists which participants carry each code
used in the findings.

| | |
|---|---|
| `interview_protocol.md` | the semi-structured protocol used for all 21 interviews: 17 main questions in four sections, with follow-up probes and interviewer notes |
| `joint_codebook.md` | the merged Reddit and interview codebook: 427 low-level codes under 15 high-level codes, with the participants (P1–P21) and Reddit records (R1–R99) assigned each code |
| `joint_codebook.csv` | the same codebook, one row per code, for analysis |
| `reddit_keywords.txt` | the 70 keywords used to filter the Reddit corpus, one per line. A record was retained if it matched at least one. |

The codebook lists only code labels and pseudonymous IDs. The interview
transcripts and coder notes are not released, because several participants
build publicly known SDD tools and could be identified from them.

The code and data that produce the paper's quantitative results are in the rest
of this package: `verify/claims.py` recomputes them, and `figures/` redraws the
figures.
