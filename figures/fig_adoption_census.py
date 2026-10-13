#!/usr/bin/env python3
"""Cumulative repository adoptions per tool, across the whole SpecMine census.

Paper format: acmsmall, \\textwidth = 5.5in, same type sizes, palette, legend
and tick treatment as Figure 1. No title -- the LaTeX caption carries it.

The axis is LINEAR, and that is the point. An earlier draft used a log axis,
where every cumulative series becomes the same concave plateau: it hid that
OpenSpec's curve is convex and still steepening while Kiro's and Spec Kit's
have gone straight, and it spent half the height on the opening months, when
the counts are single digits and mean nothing.

One thing this view cannot show: cumulative counts only ever rise, so a tool
that has stalled still reads as a tall line. On the monthly rate (not plotted)
OpenSpec passes both leaders in 2026-03 and Conductor peaks in 2026-01 and
falls away -- neither is visible here.

A repository adopts a tool in the month of the first commit of its earliest
file attributed to that tool. A repository using two tools contributes to both
curves, so the series are not a partition and do not sum to a repository count.

caffeine.ai is excluded: the largest tool in the census by repository count
(13,749), but one generator account emitting a repository per generated app,
so its curve is a step function rather than an adoption curve and it
contributes nothing to the analysis sample.

    python3 plot_timeline_full.py
"""
import json, itertools, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
BUILD = _os.path.join(_ROOT, "data", "build")
DERIVED = _os.path.join(_ROOT, "data", "derived")
OUT = _os.path.join(_ROOT, "figures", "out")
_os.makedirs(OUT, exist_ok=True)

INK, MUTED, GRID = "#1f2933", "#7b8794", "#e4e7eb"

# Colours follow the tool, not its rank, so a tool keeps its colour between
# this figure and Figure 1.
#   validate_palette.js --mode light -> ok: true
#   lightness band all within L 0.43-0.77 | chroma floor all >= 0.1
#   worst adjacent CVD dE 18.8 protan     | contrast all >= 3:1
SERIES = [("openspec", "OpenSpec", "#d95926"),
          ("kiro", "Kiro", "#a0439c"),
          ("speckit", "Spec Kit", "#2a78d6"),
          ("conductor", "Conductor", "#4a3aa7"),
          ("__other__", "Other tools", "#7b8794")]
NAMED = {k for k, _, _ in SERIES} - {"__other__"}
EXCLUDE = {"caffeine"}

# Collection ended 2026-07-03, so the partial month would read as a collapse.
DROP = "2026-07"
# Adoption starts in earnest in 2025-06. Two repositories carry an earlier
# first-commit date (one 2023-12, one 2025-03); starting there would spend half
# the width on 15 empty months. They are folded into the opening cumulative
# value rather than dropped, so the cumulative totals are exact.
START = "2025-06"


def month_range(lo, hi):
    """Every month from lo to hi inclusive. The data skips months; the axis
    must not, or an unequal gap would read as equal time."""
    out, y, m = [], int(lo[:4]), int(lo[5:])
    while f"{y:04d}-{m:02d}" <= hi:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


ad = json.load(open(_os.path.join(BUILD, "timeline_census.json")))
months = month_range(START, max(m for t in ad.values() for m in t if m < DROP))

blocks = {k: ad.get(k, {}) for k in NAMED}
other = collections.Counter()
for k, v in ad.items():
    if k not in NAMED and k not in EXCLUDE:
        other.update(v)
blocks["__other__"] = other

new = {k: [b.get(m, 0) for m in months] for k, b in blocks.items()}
cum = {k: list(itertools.accumulate(new[k],
                initial=sum(n for m, n in blocks[k].items() if m < START)))[1:]
       for k in blocks}
x = list(range(len(months)))

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.0,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK, "text.color": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False})
fig, ax = plt.subplots(figsize=(2.42, 1.92))
fig.subplots_adjust(left=.175, right=.985, top=.985, bottom=.205)

thousands = FuncFormatter(lambda v, p: f"{v/1000:g}k" if v >= 1000 else f"{v:.0f}")

for key, label, col in SERIES:
    v = cum[key]
    first = next(i for i, n in enumerate(v) if n > 0)
    ax.plot(x[first:], v[first:], color=col, lw=1.3, marker="o", ms=1.9,
            mec="white", mew=.35, zorder=4 if key == "openspec" else 3)

ax.set_ylim(0, max(max(v) for v in cum.values()) * 1.04)
ax.set_xlim(-.6, len(months) - .4)
ax.yaxis.set_major_formatter(thousands)
ax.set_ylabel("repositories", fontsize=7.0)

ax.grid(axis="y", color=GRID, linewidth=.6)
ax.set_axisbelow(True)
tick = [i for i, m in enumerate(months) if m.endswith(("-01", "-07"))]
# The quarterly rule leaves the final month unlabelled, which hides where the
# series actually end; collection stopped 2026-07-03, so the last point is the
# edge of the data, not an arbitrary cut.
if tick[-1] != len(months) - 1:
    tick.append(len(months) - 1)
ax.set_xticks(tick)
ax.set_xticklabels([months[i] for i in tick], rotation=45, ha="right", fontsize=6.4)


ax.legend(handles=[plt.Line2D([], [], color=c, lw=1.6, marker="o", ms=3.0,
                              mec="white", mew=.4) for _, _, c in SERIES],
          labels=[l for _, l, _ in SERIES], loc="upper left",
          bbox_to_anchor=(-.005, 1.015), frameon=False, fontsize=6.5, ncol=1,
          handlelength=1.1, labelspacing=.22, handletextpad=.4)

fig.savefig(_os.path.join(OUT, "spec-adoption-census.png"), dpi=220, facecolor="white")
fig.savefig(_os.path.join(OUT, "spec-adoption-census.pdf"), facecolor="white")
print(f"wrote spec-timeline-full.{{png,pdf}}  range {months[0]}..{months[-1]}")
print(f"  {'tool':<18}{'total':>9}{'last 3 mo/month':>18}")
for key, label, _ in SERIES:
    print(f"  {label:<18}{cum[key][-1]:>9,}{sum(new[key][-3:]) / 3:>18,.0f}")
