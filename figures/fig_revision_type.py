#!/usr/bin/env python3
"""How often each document type's specifications are revised.

    LD_LIBRARY_PATH=$HOME/anaconda3/lib python3 revision_by_type.py

Revision is the number of distinct commits touching a file; one commit means the
file was written and never changed. Types are the tool-and-role groups used for
the heading analysis, so the two findings are comparable.

The three bands are ordered, so the fill is a sequential ramp (blue steps 200,
400 and 700, monotone in lightness) rather than three categorical hues, with the
darkest step on the most-revised band. Rows are sorted by the first band, which
turns the boundary between light and dark into a single readable contour.
"""
import json
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
BANDS = [("1 commit", "#9ec5f4"), ("2 commits", "#3987e5"), ("3 or more", "#104281")]
NAME = {"openspec/living":"OpenSpec capability","openspec/change_proposal":"OpenSpec change",
        "openspec/archived":"OpenSpec archived","openspec/na":"OpenSpec other",
        "speckit/feature":"Spec Kit specs/","speckit/config":"Spec Kit .specify/",
        "opencode/config":"OpenCode","kiro/requirements":"Kiro","moai/na":"MoAI-ADK",
        "codex/config":"Codex","kitty_specs/na":"kitty-specs","conductor/na":"Conductor",
        "dot_specs/na":".specs"}

d = json.load(open(_os.path.join(DERIVED, "revision_dist.json")))
order = sorted(d, key=lambda k: d[k]["one"])

plt.rcParams.update({"font.family":"DejaVu Sans","font.size":7.0,
                     "axes.edgecolor":GRID,"text.color":INK,
                     "xtick.color":MUTED,"ytick.color":INK,
                     "axes.spines.top":False,"axes.spines.right":False,
                     "axes.spines.left":False,"axes.spines.bottom":False})
fig, ax = plt.subplots(figsize=(5.50, 2.70))
fig.subplots_adjust(left=.225, right=.995, top=.885, bottom=.185)

# grid first, behind everything
for x in (25, 50, 75, 100):
    ax.axvline(x, color=GRID, lw=.6, zorder=0)

y = list(range(len(order)))[::-1]
for i, k in zip(y, order):
    left = 0
    for (lab, col), key in zip(BANDS, ["one", "two", "three_plus"]):
        v = d[k][key]
        ax.barh(i, v, .66, left=left, color=col, edgecolor="white", linewidth=.7, zorder=2)
        if v >= 9:
            ax.annotate(f"{v:.0f}", (left + v / 2, i), ha="center", va="center", fontsize=6.0,
                        zorder=3, color=INK if col == "#9ec5f4" else "white")
        left += v
    ax.annotate(f"{d[k]['n']:,}", (104, i), ha="left", va="center",
                fontsize=6.0, color=MUTED, zorder=3)

ax.set_yticks(y); ax.set_yticklabels([NAME.get(k, k) for k in order], fontsize=6.6)
ax.set_xlim(0, 118); ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xticklabels(["0", "25", "50", "75", "100%"], fontsize=6.3)
ax.set_ylim(-.75, len(order) - .25)
ax.tick_params(length=0)
ax.annotate("files", (104, len(order) - .35), ha="left", va="center",
            fontsize=6.2, color=MUTED, annotation_clip=False)
ax.set_xlabel("")
ax.annotate("share of the type's files", (50, -2.15), ha="center",
            va="center", fontsize=6.9, color=MUTED, annotation_clip=False)

h = [plt.Rectangle((0, 0), 1, 1, fc=c, ec="white", lw=.5) for _, c in BANDS]
leg = ax.legend(h, [b for b, _ in BANDS], loc="lower left",
                bbox_to_anchor=(0, 1.012, 1, .12), mode=None, borderaxespad=0,
                frameon=False, fontsize=6.4, ncol=3, handlelength=1.1,
                handleheight=.8, columnspacing=1.1, handletextpad=.4)
fig.savefig(_os.path.join(OUT, "spec-revision-type.png"), dpi=220, facecolor="white")
fig.savefig(_os.path.join(OUT, "spec-revision-type.pdf"), facecolor="white")
print("wrote spec-revision-type.{png,pdf}")
