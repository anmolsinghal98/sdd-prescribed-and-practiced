#!/usr/bin/env python3
"""How projects divide their specs, as a proxy for the scope given to each.

    LD_LIBRARY_PATH=$HOME/anaconda3/lib python3 plot_scope.py

A project that scopes specs to parts of the system should hold a few long
documents, one per capability or subsystem; a project that scopes them to
changes should hold many short ones. The two panels are the two halves of that
comparison, so they belong together even though their populations differ.

OpenSpec's change records are excluded: the tool keeps a record of every change
and retains it after the change ships, so their number measures how long a
project has used OpenSpec rather than how it scopes a spec. Its capability
specs do not accumulate that way and are kept.

Both axes are logarithmic, with bins equal in log space, because the two
quantities span three and four orders of magnitude. The shaded band is the
middle half; the mean is far outside it in both panels, which is why the median
carries the claim in the text.
"""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
BUILD = _os.path.join(_ROOT, "data", "build")
DERIVED = _os.path.join(_ROOT, "data", "derived")
OUT = _os.path.join(_ROOT, "figures", "out")
_os.makedirs(OUT, exist_ok=True)

INK, MUTED, GRID = "#1f2933", "#7b8794", "#e4e7eb"
BAR, MARK = "#2a78d6", "#d95926"

d = json.load(open(_os.path.join(DERIVED, "sample_dist_scope.json")))
PANELS = [
    (np.array(d["per_repo"]), "Specifications per repository",
     "repositories", "specifications in the repository", 1),
    (np.array(d["words"]), "Length of a specification",
     "specifications", "words", 10),
]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.0,
                     "axes.edgecolor": GRID, "text.color": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.spines.left": False})
fig, axes = plt.subplots(1, 2, figsize=(5.50, 2.00))
fig.subplots_adjust(left=.082, right=.988, top=.80, bottom=.245, wspace=.26)

for ax, (v, title, ylab, xlab, lo) in zip(axes, PANELS):
    bins = np.logspace(np.log10(lo), np.log10(v.max()), 30)
    ax.hist(v, bins=bins, color=BAR, edgecolor="white", linewidth=.5, zorder=2)
    q1, med, q3 = np.percentile(v, [25, 50, 75])
    top = ax.get_ylim()[1]

    ax.axvspan(q1, q3, color=MARK, alpha=.07, lw=0, zorder=1)
    for x in (q1, med, q3):
        ax.axvline(x, color=MARK, lw=1.0, ls=(0, (3, 2)), zorder=3)
    ax.annotate(f"{med:,.0f}", (med, top), ha="center", va="bottom", fontsize=6.6,
                color=MARK, xytext=(0, 1.5), textcoords="offset points", annotation_clip=False)
    ax.annotate(f"{q1:,.0f}", (q1, top), ha="right", va="bottom", fontsize=6.0, color=MARK,
                xytext=(-2.5, 1.5), textcoords="offset points", annotation_clip=False)
    ax.annotate(f"{q3:,.0f}", (q3, top), ha="left", va="bottom", fontsize=6.0, color=MARK,
                xytext=(2.5, 1.5), textcoords="offset points", annotation_clip=False)

    ax.set_xscale("log")
    ax.set_xlim(lo, v.max() * 1.15)
    ax.set_xlabel(xlab, fontsize=6.9, color=MUTED, labelpad=3)
    ax.set_ylabel(ylab, fontsize=6.9, color=MUTED)
    ax.grid(axis="y", color=GRID, lw=.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelsize=6.4)
    ax.set_title(title, fontsize=7.4, loc="left", pad=14)

# the dashed lines and the shaded band are explained in the caption, not here:
# a key inside the figure collided with the panel titles at this height

fig.savefig(_os.path.join(OUT, "spec-scope.pdf"), facecolor="white")
fig.savefig(_os.path.join(OUT, "spec-scope.png"), dpi=220, facecolor="white")
for v, title, *_ in PANELS:
    q = np.percentile(v, [25, 50, 75])
    print(f"  {title:<32}q1 {q[0]:>6,.0f}  median {q[1]:>6,.0f}  q3 {q[2]:>6,.0f}  "
          f"mean {v.mean():>7,.1f}  sd {v.std(ddof=1):>7,.1f}")
