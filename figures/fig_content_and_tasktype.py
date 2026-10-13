#!/usr/bin/env python3
"""E7 figures: spec content (Finding 1) and task type (Finding 3).

    LD_LIBRARY_PATH=$HOME/anaconda3/lib python3 plot_e7.py

Both are drawn at the paper's text width so nothing is scaled down on the page,
and both order document types the same way the revision figure does, so a reader
moving between Findings 1, 3, 6 and 7 meets the same rows in the same order.

Panel titles state what is plotted, not what it means; the interpretation lives
in the text, where a reader can weigh it.
"""
import json, collections, csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.colors import LinearSegmentedColormap
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
BUILD = _os.path.join(_ROOT, "data", "build")
DERIVED = _os.path.join(_ROOT, "data", "derived")
OUT = _os.path.join(_ROOT, "figures", "out")
_os.makedirs(OUT, exist_ok=True)

for _p in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",):
    try: fm.fontManager.addfont(_p)
    except Exception: pass

INK, MUTED, GRID = "#1f2933", "#7b8794", "#e4e7eb"
# sequential, monotone in lightness; the four extents are ordered
EXTENT = [("none", "#eef3fa"), ("incidental", "#9ec5f4"),
          ("substantial", "#3987e5"), ("dominant", "#104281")]
RAMP = LinearSegmentedColormap.from_list("b", ["#ffffff", "#cde2fb", "#5598e7", "#1c5cab"])
NAME = {"openspec/living":"OpenSpec capability","openspec/change_proposal":"OpenSpec change",
        "openspec/archived":"OpenSpec archived","openspec/na":"OpenSpec other",
        "speckit/feature":"Spec Kit specs/","speckit/config":"Spec Kit .specify/",
        "opencode/config":"OpenCode","kiro/requirements":"Kiro","moai/na":"MoAI-ADK",
        "codex/config":"Codex","kitty_specs/na":"kitty-specs","conductor/na":"Conductor",
        "dot_specs/na":".specs"}
PURPOSE = ["feat", "fix", "refactor", "perf", "style"]
OBJECT = ["test", "docs", "build", "chore", "ci"]

plt.rcParams.update({"font.family":["DejaVu Sans","WenQuanYi Zen Hei"],"font.size":7.0,
                     "axes.edgecolor":GRID,"text.color":INK,
                     "xtick.color":MUTED,"ytick.color":INK,
                     "axes.spines.top":False,"axes.spines.right":False,
                     "axes.spines.left":False,"axes.spines.bottom":False})


def load(path, key):
    return [r for r in map(json.loads, open(path)) if r.get("parsed") and key in r["parsed"]]


W = load(_os.path.join(DERIVED, "e7_content.jsonl"), "requirements")
T = load(_os.path.join(DERIVED, "e7_tasktype.jsonl"), "purpose")
size = {r["type"]: int(r["type_files"]) for r in csv.DictReader(open(_os.path.join(DERIVED, "e7_sample.csv")))}
bw = collections.defaultdict(list)
for r in W: bw[r["type"]].append(r["parsed"])
order = sorted(bw, key=lambda t: -sum(p["implementation_extent"] in ("substantial", "dominant")
                                      for p in bw[t]) / len(bw[t]))

# ---------------------------------------------------------------- Finding 1
fig, ax = plt.subplots(figsize=(5.50, 2.70))
fig.subplots_adjust(left=.225, right=.995, top=.885, bottom=.185)
for x in (25, 50, 75, 100):
    ax.axvline(x, color=GRID, lw=.6, zorder=0)
y = list(range(len(order)))[::-1]
for i, t in zip(y, order):
    c = collections.Counter(p["implementation_extent"] for p in bw[t]); n = len(bw[t]); left = 0
    for lab, col in EXTENT:
        v = c[lab] / n * 100
        ax.barh(i, v, .66, left=left, color=col, edgecolor="white", linewidth=.7, zorder=2)
        if v >= 9:
            ax.annotate(f"{v:.0f}", (left + v / 2, i), ha="center", va="center", fontsize=6.0,
                        zorder=3, color="white" if col in ("#3987e5", "#104281") else INK)
        left += v
    ax.annotate(f"{size[t]:,}", (104, i), ha="left", va="center", fontsize=6.0, color=MUTED)
ax.set_yticks(y); ax.set_yticklabels([NAME.get(t, t) for t in order], fontsize=6.6)
ax.set_xlim(0, 118); ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xticklabels(["0", "25", "50", "75", "100%"], fontsize=6.3)
ax.set_ylim(-.75, len(order) - .25); ax.tick_params(length=0)
ax.annotate("files", (104, len(order) - .35), ha="left", va="center", fontsize=6.2,
            color=MUTED, annotation_clip=False)
ax.annotate("share of the type's judged specs", (50, -2.15), ha="center", va="center",
            fontsize=6.9, color=MUTED, annotation_clip=False)
h = [plt.Rectangle((0, 0), 1, 1, fc=c, ec="white", lw=.5) for _, c in EXTENT]
ax.legend(h, [b for b, _ in EXTENT], loc="lower left", bbox_to_anchor=(0, 1.012, 1, .12),
          borderaxespad=0, frameon=False, fontsize=6.4, ncol=4, handlelength=1.1,
          handleheight=.8, columnspacing=1.1, handletextpad=.4)
fig.savefig(_os.path.join(OUT, "spec-content.pdf"), facecolor="white"); fig.savefig(_os.path.join(OUT, "spec-content.png"), dpi=220, facecolor="white")

# ---------------------------------------------------------------- Finding 3
bt = collections.defaultdict(list)
for r in T: bt[r["type"]].append(r["parsed"])
fig, axes = plt.subplots(1, 2, figsize=(5.50, 3.05), gridspec_kw={"width_ratios": [1, 1.5]})
fig.subplots_adjust(left=.115, right=.995, top=.735, bottom=.07, wspace=.62)

ax = axes[0]
labs = PURPOSE + OBJECT
# The judge sample is a fixed draw per type, so the pooled share would count
# each type equally. Weight each type by its number of files instead, as the
# text and verify/claims.py do.
_tot = sum(size[t] for t in bt)
share = [sum(size[t] * sum(l in p["purpose"] or l in p["object"] for p in v) / len(v)
             for t, v in bt.items()) / _tot * 100 for l in labs]
yy = list(range(len(labs)))[::-1]
for i, l, v in zip(yy, labs, share):
    ax.barh(i, v, .66, color="#2a78d6" if l in PURPOSE else "#d95926",
            edgecolor="white", linewidth=.6, zorder=2)
    ax.annotate(f"{v:.0f}", (v + 1.5, i), va="center", fontsize=6.1, color=MUTED)
for x in (25, 50, 75):
    ax.axvline(x, color=GRID, lw=.6, zorder=0)
ax.set_yticks(yy); ax.set_yticklabels(labs, fontsize=6.5)
ax.set_xlim(0, 108); ax.set_xticks([0, 50, 100]); ax.set_xticklabels(["0", "50", "100%"], fontsize=6.3)
ax.tick_params(length=0)
ax.set_title("all judged specs, file-weighted", fontsize=7.0, loc="left", pad=13)
ax.legend([plt.Rectangle((0,0),1,1,fc=c,ec="white",lw=.5) for c in ("#2a78d6","#d95926")],
          ["purpose", "object"], loc="lower left", bbox_to_anchor=(0, 1.005, 1, .1),
          borderaxespad=0, frameon=False, fontsize=6.3, ncol=2, handlelength=1.1,
          handleheight=.8, columnspacing=1.2, handletextpad=.4)

ax = axes[1]
for j, t in enumerate(order):
    for i, l in enumerate(labs):
        v = sum(l in p["purpose"] or l in p["object"] for p in bt[t]) / len(bt[t]) * 100
        ax.add_patch(plt.Rectangle((i - .5, j - .5), 1, 1, facecolor=RAMP(v / 100),
                                   edgecolor="white", lw=.6))
        ax.annotate(f"{v:.0f}", (i, j), ha="center", va="center", fontsize=5.3,
                    color="white" if v > 62 else INK)
ax.set_xlim(-.5, len(labs) - .5); ax.set_ylim(len(order) - .5, -.5)
ax.set_xticks(range(len(labs))); ax.set_xticklabels(labs, fontsize=5.9, rotation=38,
                                                    ha="left", rotation_mode="anchor")
ax.xaxis.set_ticks_position("top")
ax.set_yticks(range(len(order))); ax.set_yticklabels([NAME.get(t, t) for t in order], fontsize=5.9)
ax.tick_params(length=0)
ax.set_title("by document type", fontsize=7.0, loc="left", pad=20)
fig.savefig(_os.path.join(OUT, "spec-tasktype.pdf"), facecolor="white"); fig.savefig(_os.path.join(OUT, "spec-tasktype.png"), dpi=220, facecolor="white")
print("wrote e7_content.{pdf,png} and e7_tasktype.{pdf,png}")
