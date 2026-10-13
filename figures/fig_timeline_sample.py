#!/usr/bin/env python3
"""The analysis sample over time, by SDD tool.

    LD_LIBRARY_PATH=$HOME/anaconda3/lib python3 plot_timeline4.py

Left: cumulative repository adoptions of each tool. A repository adopts a tool
on the first-commit date of its earliest file attributed to that tool, so the
253 repositories contribute 266 repository-tool adoptions -- ten repositories
use more than one tool, and the curves are therefore not a partition of the
sample and do not sum to 253.

Right: specification files per month, by the tool that produced them. Every file
carries exactly one attribution, so these do partition the sample.

Six series: the five tools with the largest share plus a pooled Other. Colours
follow the tool, not its rank, so a tool keeps its colour across both panels
even though the two orderings differ (OpenCode is third by files and ninth by
adoptions). Linear axes, deliberately: OpenSpec towers over everything else and
that is the finding, not an artifact.

July 2026 is dropped -- collection ended 2026-07-03 and the partial month would
read as a decline.
"""
import json, collections
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.ticker
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
BUILD = _os.path.join(_ROOT, "data", "build")
OUT = _os.path.join(_ROOT, "figures", "out")
_os.makedirs(OUT, exist_ok=True)

INK, MUTED, GRID = "#1f2933", "#7b8794", "#e4e7eb"
# Validated categorical set, in the order the validator scored.  The default
# theme's light slots put aqua and yellow below 3:1 on a white surface, which is
# weak for a thin printed line with no direct label, so the low-contrast slots
# were swapped for their darker steps and the ordering searched over all 120
# permutations -- slot order is the CVD mechanism, not decoration.
#   validate_palette.py --mode light: ALL CHECKS PASS
#   contrast vs surface  all 5 >= 3.0:1   (was 2.11:1 at the yellow slot)
#   worst adjacent CVD   dE 72.9 deutan   (was 10.7, inside the floor band)
# Other is neutral gray at 3.57:1 -- an aggregate, not an entity, so it sits
# outside the categorical set and is excluded from the chroma-floor check.
SERIES = [("openspec", "OpenSpec", "#d95926"),
          ("speckit", "Spec Kit", "#2a78d6"),
          ("opencode", "OpenCode", "#008300"),
          ("conductor", "Conductor", "#4a3aa7"),
          ("moai", "MoAI-ADK", "#199e70"),
          ("kiro", "Kiro", "#a0439c"),
          ("__other__", "Other (6 tools)", "#7b8794")]
NAMED = {k for k, _, _ in SERIES} - {"__other__"}
DROP, START = "2026-07", "2025-08"

d = json.load(open(_os.path.join(BUILD, "timeline_sample.json")))
months = sorted({m for t in d["files_per_month"].values() for m in t}
                | {m for t in d["adoptions"].values() for m in t})
months = [m for m in months if START <= m < DROP]
x = range(len(months))


def pooled(block):
    """Per-month series for each named tool plus everything else pooled."""
    out = {k: [block.get(k, {}).get(m, 0) for m in months] for k in NAMED}
    out["__other__"] = [sum(v.get(m, 0) for k, v in block.items() if k not in NAMED)
                        for m in months]
    return out


files = pooled(d["files_per_month"])
adopt = pooled(d["adoptions"])
cum = {k: list(__import__("itertools").accumulate(v)) for k, v in adopt.items()}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.0,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK, "text.color": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False})
fig, axes = plt.subplots(1, 2, figsize=(5.50, 2.45))
fig.subplots_adjust(left=.082, right=.988, top=.805, bottom=.245, wspace=.235)

thousands = FuncFormatter(lambda v, p: f"{v/1000:.0f}k" if v >= 1000 else f"{v:.0f}")

for ax, data, title, ylab in [
        (axes[0], cum, "Repositories adopted, cumulative", "repositories"),
        (axes[1], files, "Specifications written each month", "files")]:
    for key, label, col in SERIES:
        v = data[key]
        ax.plot(x, v, color=col, lw=1.5, marker="o", ms=2.4, mec="white", mew=.4,
                zorder=4 if key == "openspec" else 3)
        # relief for the contrast WARN: the series a reader must find without
        # the legend carry a direct label.  On the left that is the endpoint of
        # the cumulative curve; on the right, the peak month.
        if key in ("openspec", "speckit") and data is cum:
            ax.annotate(f"{v[-1]:,}", (len(months) - 1, v[-1]), fontsize=6.2, color=col,
                        xytext=(-1, 3.5), textcoords="offset points", ha="right")
        if key == "openspec" and data is files:
            p = max(x, key=lambda i: v[i])
            ax.annotate(f"{v[p]:,}", (p, v[p]), fontsize=6.2, color=col,
                        xytext=(0, 3.5), textcoords="offset points", ha="center")
    # log(1+y): a tool has zero adoptions before it appears and zero files in a
    # month it was not used, and a plain log axis cannot show zero. The shift by
    # one is monotone and smooth, so unlike symlog there is no kink where the
    # scale changes behaviour. Ticks are labelled with the original counts.
    ax.set_yscale("function", functions=(lambda y: np.log1p(np.clip(y, 0, None)),
                                         lambda y: np.expm1(y)))
    top = max(max(v) for v in data.values())
    ticks = [t for t in (0, 1, 10, 100, 1000, 10000) if t <= top * 1.6]
    ax.set_yticks(ticks)
    ax.set_ylim(0, top * 1.6)
    ax.set_xlim(-.6, len(months) - .4)
    ax.yaxis.set_major_formatter(thousands)
    ax.set_ylabel(ylab, fontsize=6.8)
    ax.set_title(title, fontsize=7.4, loc="left", pad=4)
    ax.grid(axis="y", color=GRID, linewidth=.6)
    ax.set_axisbelow(True)
    tick = [i for i, m in enumerate(months) if m.endswith(("-01", "-04", "-07", "-10"))]
    ax.set_xticks(tick)
    ax.set_xticklabels([months[i] for i in tick], rotation=45, ha="right", fontsize=6.3)
    ax.set_xlabel("month of first commit", fontsize=6.8)

fig.legend(handles=[plt.Line2D([], [], color=c, lw=1.5, marker="o", ms=2.8,
                               mec="white", mew=.4) for _, _, c in SERIES],
           labels=[l for _, l, _ in SERIES], loc="upper left",
           bbox_to_anchor=(.078, 1.016), frameon=False, fontsize=6.6, ncol=7,
           handlelength=1.3, columnspacing=1.0, handletextpad=.4)

fig.savefig(_os.path.join(OUT, "spec-timeline.png"), dpi=220, facecolor="white")
fig.savefig(_os.path.join(OUT, "spec-timeline.pdf"), facecolor="white")
print(f"wrote spec-timeline7.{{png,pdf}}  range {months[0]}..{months[-1]}")
for key, label, _ in SERIES:
    print(f"  {label:<16} adoptions {cum[key][-1]:>4}   files {sum(files[key]):>7,}")
print(f"  TOTAL            adoptions {sum(c[-1] for c in cum.values()):>4}"
      f"   files {sum(sum(v) for v in files.values()):>7,}")
print(f"  (266 repository-tool adoptions in all; one Spec Kit adoption falls in "
      f"the dropped month {DROP})")
