#!/usr/bin/env python3
"""Which sections cross a document-type boundary, and between which types.

    LD_LIBRARY_PATH=$HOME/anaconda3/lib python3 headings_matrix.py

Rows are the ten sections that reach a majority in more than one document type;
columns are the 13 types. Every cell carries its share, because leaving the
sub-threshold cells blank would hide real differences -- only 32 of them are
zero, and two sit at 50% and 47%. Cells at or above the majority threshold are
outlined. The other 30 majority sections appear in exactly one type and are left
out, which is what the figure shows: the shared vocabulary is this thin.
"""
import csv, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
BUILD = _os.path.join(_ROOT, "data", "build")
DERIVED = _os.path.join(_ROOT, "data", "derived")
OUT = _os.path.join(_ROOT, "figures", "out")
_os.makedirs(OUT, exist_ok=True)

csv.field_size_limit(10**9)
INK, MUTED, GRID = "#1f2933", "#7b8794", "#e4e7eb"
RAMP = LinearSegmentedColormap.from_list("blue", ["#ffffff", "#cde2fb", "#5598e7", "#1c5cab"])

f=collections.defaultdict(set); hf=collections.defaultdict(set)
for r in csv.DictReader(open(_os.path.join(BUILD, "headings_all.csv"), newline="")):
    k=(r["spec_tool"], r["spec_role"] or "na")
    f[k].add(r["file_sha16"]); hf[(k,r["heading_norm"])].add(r["file_sha16"])
K=sorted([k for k in f if len(f[k])>=90], key=lambda x:-len(f[x]))
share={(k,h): len(v)/len(f[k]) for (k,h),v in hf.items() if k in f}
core={k:{h for (kk,h),v in hf.items() if kk==k and len(v)/len(f[k])>=.5} for k in K}
own=collections.Counter(h for k in K for h in core[k])
rows=sorted([h for h,c in own.items() if c>1], key=lambda h:(-own[h], h))

NAME={("openspec","archived"):"OpenSpec archived",
      ("openspec","living"):"OpenSpec capability",
      ("openspec","change_proposal"):"OpenSpec change",
      ("openspec","na"):"OpenSpec other",
      ("speckit","feature"):"Spec Kit specs/",
      ("speckit","config"):"Spec Kit .specify/",
      ("opencode","config"):"OpenCode",
      ("kiro","requirements"):"Kiro",
      ("moai","na"):"MoAI-ADK",
      ("codex","config"):"Codex",
      ("kitty_specs","na"):"kitty-specs",
      ("conductor","na"):"Conductor",
      ("dot_specs","na"):".specs"}
def lab(k): return NAME.get(k, f"{k[0]}/{k[1]}")

plt.rcParams.update({"font.family":"DejaVu Sans","font.size":7.0,
                     "axes.edgecolor":GRID,"text.color":INK,
                     "xtick.color":INK,"ytick.color":INK})
fig,ax=plt.subplots(figsize=(5.50,2.55))
fig.subplots_adjust(left=.265,right=.995,top=.635,bottom=.035)
for i,h in enumerate(rows):
    for j,k in enumerate(K):
        v=share.get((k,h),0); maj = h in core[k]
        ax.add_patch(plt.Rectangle((j-.45,i-.45),.90,.90, facecolor=RAMP(v),
                     edgecolor=INK if maj else "white", lw=.9 if maj else .5,
                     zorder=3 if maj else 2))
        ax.annotate(f"{v*100:.0f}",(j,i),ha="center",va="center",fontsize=5.2,
                    zorder=4, color="white" if v>.60 else INK,
                    fontweight="bold" if maj else "normal")
ax.set_xlim(-.6,len(K)-.4); ax.set_ylim(len(rows)-.5,-.5)
ax.set_xticks(range(len(K))); ax.set_xticklabels([lab(k) for k in K],fontsize=5.9,rotation=38,ha="left",rotation_mode="anchor")
ax.xaxis.set_ticks_position("top"); ax.xaxis.set_label_position("top")
ax.set_yticks(range(len(rows))); ax.set_yticklabels(rows,fontsize=6.3)
ax.tick_params(length=0)
for s in ax.spines.values(): s.set_visible(False)
ax.set_xlabel("")
fig.savefig(_os.path.join(OUT, "spec-headings-matrix.png"),dpi=220,facecolor="white")
fig.savefig(_os.path.join(OUT, "spec-headings-matrix.pdf"),facecolor="white")
print(f"rows (sections in >1 type): {len(rows)}   cols (types): {len(K)}")
print(f"filled cells {sum(1 for h in rows for k in K if h in core[k])} of {len(rows)*len(K)}")
print(f"sections in exactly one type: {sum(1 for h,c in own.items() if c==1)} of {len(own)}")
