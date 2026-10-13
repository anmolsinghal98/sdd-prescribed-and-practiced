#!/usr/bin/env python3
"""
Descriptive statistics + figures for the spec_files dataset (fetch_spec_files.py).

Re-runnable: reads the current `specdriven.spec_files` snapshot (safe while
collection is ongoing) and regenerates:
  - analysis/figures/*.png   (charts)
  - analysis/descriptive_stats.md   (findings doc that embeds the charts + tables)

Usage:  python3 spec_descriptives.py

NOTE: we currently store each file's LAST-commit date (not first-commit), so the
temporal view reflects most-recent activity, not creation. A first-commit /
creation timeline is a planned follow-up once collection completes.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spec_files as f

POP_STARS = 500  # "popular" cut (mirrors AIDev-pop's >500 stars)

# Analysis runs on the CLEANED dataset: rows excluded by classify_specs.py
# (not_spec_filter=1 — spack package-cache, vendored deps) are dropped; kept-but-
# tagged rows (e.g. caffeinepub AI-generator specs, filter=0) remain in-scope.
KEEP = "not_spec_filter = 0"

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "analysis")
FIG_DIR = os.path.join(OUT_DIR, "figures")

# --- validated palette (dataviz skill, light surface) ---
BLUE = "#2a78d6"      # sequential/magnitude single hue
ORANGE = "#e8710a"    # 2nd categorical hue; blue/orange is the CVD-safe pair
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e6e6e3"
SURFACE = "#ffffff"


def setup_mpl():
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": "#cfcfca",
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "text.color": INK,
        "axes.labelcolor": INK2,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "figure.dpi": 130,
    })


def _thousands(x, _pos=None):
    return f"{int(x):,}"


def style_axes(ax, xgrid=False):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("#cfcfca")
    ax.spines["bottom"].set_color("#cfcfca")
    ax.grid(axis="x" if xgrid else "y", color=GRID, linewidth=0.8)
    ax.grid(axis="y" if xgrid else "x", visible=False)


def q(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def q1(cur, sql, params=None):
    cur.execute(sql, params or ())
    r = cur.fetchone()
    return r[0] if r else None


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------

def fig_monthly(months, counts, repo_counts, title, ylabel, fname):
    """Monthly bar chart; each bar labelled (vertical) with the distinct-repo count
    that month, so a tall bar from a few monorepos is distinguishable from broad
    adoption. Used for both the creation timeline and the activity timeline."""
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.bar(range(len(months)), counts, color=BLUE, width=0.82)
    style_axes(ax)
    ax.set_ylabel(ylabel)
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    step = max(1, len(months) // 12)
    ax.set_xticks(range(0, len(months), step))
    ax.set_xticklabels([months[i] for i in range(0, len(months), step)], rotation=45, ha="right")
    ax.set_title(title)
    ax.set_xlim(-0.6, len(months) - 0.4)
    vmax = max(counts) if counts else 1
    ax.set_ylim(0, vmax * 1.12)
    for i, (c, r) in enumerate(zip(counts, repo_counts)):
        if c <= 0:
            continue
        ax.text(i, c + vmax * 0.012, f"{r:,}", ha="center", va="bottom",
                rotation=90, fontsize=7, color=INK2)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, fname))
    plt.close(fig)


def fig_vbars(labels, values, title, ylabel, xlabel, fname):
    """Simple labelled vertical-bar chart (single hue) for ordered categories."""
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    ax.bar(range(len(labels)), values, color=BLUE, width=0.7)
    style_axes(ax)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylabel(ylabel)
    ax.set_xlabel(xlabel)
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    vmax = max(values) if values else 1
    for i, v in enumerate(values):
        ax.text(i, v + vmax * 0.01, f"{v:,}", ha="center", va="bottom", fontsize=9, color=INK2)
    ax.set_ylim(0, vmax * 1.14)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, fname))
    plt.close(fig)


def _hbar(labels, values, title, xlabel, fname, fmt_pct_of=None):
    labels = labels[::-1]
    values = values[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(labels) + 1.2))
    ax.barh(range(len(labels)), values, color=BLUE, height=0.72)
    style_axes(ax, xgrid=True)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    vmax = max(values) if values else 1
    for i, v in enumerate(values):
        lbl = f"{v:,}"
        if fmt_pct_of:
            lbl += f"  ({100*v/fmt_pct_of:.1f}%)"
        ax.text(v + vmax * 0.01, i, lbl, va="center", ha="left", fontsize=9, color=INK2)
    ax.set_xlim(0, vmax * 1.18)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, fname))
    plt.close(fig)


def fig_style_by_tool(labels, ears, gherkin, fname):
    """Two-series horizontal bars: EARS vs Gherkin prevalence per tool. Legend +
    direct value labels, so identity is never color-alone (blue/orange CVD-safe)."""
    labels, ears, gherkin = labels[::-1], ears[::-1], gherkin[::-1]
    fig, ax = plt.subplots(figsize=(8.4, 0.62 * len(labels) + 1.4))
    h = 0.38
    ys = list(range(len(labels)))
    ax.barh([y + h / 2 for y in ys], ears, height=h, color=BLUE, label="EARS “shall”")
    ax.barh([y - h / 2 for y in ys], gherkin, height=h, color=ORANGE, label="Gherkin WHEN/THEN")
    style_axes(ax, xgrid=True)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels)
    ax.set_xlabel("% of the tool's specs")
    ax.set_xlim(0, 108)
    ax.set_title("Two requirement dialects, one per kit (EARS vs Gherkin)")
    for y, v in zip(ys, ears):
        ax.text(v + 1, y + h / 2, f"{v:.0f}", va="center", ha="left", fontsize=8, color=INK2)
    for y, v in zip(ys, gherkin):
        ax.text(v + 1, y - h / 2, f"{v:.0f}", va="center", ha="left", fontsize=8, color=INK2)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, fname))
    plt.close(fig)


def fig_small_multiples(panels, months, fname, ncols=3):
    """Grid of mini creation-timelines — one panel per (tool, role) rulebook row.
    Shared x (all months), independent y per panel (so shapes compare even when
    magnitudes differ 100x); each panel titled with its total. x labels only on
    the bottom panel of each column to stay legible."""
    n = len(panels)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 3.2, nrows * 1.55), squeeze=False)
    xr = range(len(months))
    tick_idx = [i for i, m in enumerate(months) if m.endswith("-01")] or [0, len(months) - 1]
    for k, (title, counts) in enumerate(panels):
        r, c = divmod(k, ncols)
        ax = axes[r][c]
        ax.bar(xr, counts, color=BLUE, width=1.0)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.spines["left"].set_color("#cfcfca"); ax.spines["bottom"].set_color("#cfcfca")
        ax.set_title(title, fontsize=8, fontweight="bold", color=INK)
        ax.set_xlim(-0.5, len(months) - 0.5)
        ax.set_ylim(0, (max(counts) if counts else 1) * 1.18)
        ax.margins(y=0)
        ax.tick_params(labelsize=6, length=2, color="#cfcfca")
        ax.grid(axis="y", color=GRID, linewidth=0.6); ax.grid(axis="x", visible=False)
        ax.set_axisbelow(True)
        ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
        ax.locator_params(axis="y", nbins=3)
        is_bottom = (k + ncols >= n)   # bottom-most populated panel in its column
        ax.set_xticks(tick_idx)
        if is_bottom:
            ax.set_xticklabels([months[i] for i in tick_idx], rotation=45, ha="right", fontsize=6)
        else:
            ax.set_xticklabels([])
    for k in range(n, nrows * ncols):     # blank the unused cells
        r, c = divmod(k, ncols)
        axes[r][c].axis("off")
    fig.suptitle("Spec creation over time, per tool & role (first commit / month)",
                 fontsize=12, fontweight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.99])
    fig.savefig(os.path.join(FIG_DIR, fname))
    plt.close(fig)


def fig_stars(buckets, values):
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    ax.bar(range(len(buckets)), values, color=BLUE, width=0.7)
    style_axes(ax)
    ax.set_xticks(range(len(buckets)))
    ax.set_xticklabels(buckets)
    ax.set_ylabel("repositories")
    ax.set_xlabel("stars")
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    vmax = max(values) if values else 1
    for i, v in enumerate(values):
        ax.text(i, v + vmax * 0.01, f"{v:,}", ha="center", va="bottom", fontsize=9, color=INK2)
    ax.set_ylim(0, vmax * 1.12)
    ax.set_title("Repositories by star count (the long tail)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "stars_distribution.png"))
    plt.close(fig)


# --------------------------------------------------------------------------
# Markdown helpers
# --------------------------------------------------------------------------

def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "-"


def build_pdf():
    """Render descriptive_stats.md -> descriptive_stats.pdf via pandoc, if the
    toolchain is present. Runs from OUT_DIR so figure paths resolve; images are
    capped to page width so wide charts don't overflow. A missing toolchain is a
    warning, not an error (md + figures are the primary outputs)."""
    if not shutil.which("pandoc"):
        print("PDF skipped: pandoc not found.")
        return
    engine = next((e for e in ("xelatex", "pdflatex", "lualatex") if shutil.which(e)), None)
    if engine is None:
        print("PDF skipped: no LaTeX engine (xelatex/pdflatex) found.")
        return
    header = (r"\usepackage{graphicx}" "\n"
              r"\setkeys{Gin}{width=0.85\linewidth,keepaspectratio}" "\n")
    hpath = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".tex", delete=False) as fh:
            fh.write(header)
            hpath = fh.name
        subprocess.run(
            ["pandoc", "descriptive_stats.md", "-o", "descriptive_stats.pdf",
             f"--pdf-engine={engine}", "-V", "geometry:margin=1in",
             "-V", "fontsize=11pt", "-V", "linkcolor:blue", "-H", hpath],
            cwd=OUT_DIR, check=True, capture_output=True, text=True)
        print(f"Wrote {os.path.join(OUT_DIR, 'descriptive_stats.pdf')} (via pandoc/{engine}).")
    except subprocess.CalledProcessError as e:
        print("PDF generation failed (md + figures are still fine):\n", (e.stderr or "")[-400:])
    finally:
        if hpath and os.path.exists(hpath):
            os.unlink(hpath)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    setup_mpl()
    conn = f.get_db_connection("specdriven")
    cur = conn.cursor()

    total = q1(cur, f"SELECT COUNT(*) FROM spec_files WHERE {KEEP}")
    repos = q1(cur, f"SELECT COUNT(DISTINCT repo_name) FROM spec_files WHERE {KEEP}")
    owners = q1(cur, f"SELECT COUNT(DISTINCT owner_login) FROM spec_files WHERE {KEEP}")
    raw_total = q1(cur, "SELECT COUNT(*) FROM spec_files")
    excluded = q1(cur, "SELECT COUNT(*) FROM spec_files WHERE not_spec_filter = 1")
    tagged = q(cur, "SELECT not_spec_notes, COUNT(*) n FROM spec_files WHERE not_spec_filter = 1 "
                    "GROUP BY not_spec_notes ORDER BY n DESC")
    done = q1(cur, "SELECT SUM(status='done') FROM spec_files_plan")
    totp = q1(cur, "SELECT COUNT(*) FROM spec_files_plan")
    est = q1(cur, "SELECT plan_total_est FROM spec_files_run_meta LIMIT 1")

    # Filename split
    fn_rows = q(cur, f"SELECT LOWER(file_name) fn, COUNT(*) n FROM spec_files WHERE {KEEP} GROUP BY fn ORDER BY n DESC")
    # Owner type
    ot_rows = q(cur, f"SELECT COALESCE(owner_type,'(null)'), COUNT(*), COUNT(DISTINCT repo_name) "
                     f"FROM spec_files WHERE {KEEP} GROUP BY owner_type ORDER BY 2 DESC")
    # Stars (repo-level, less skewed by monorepos)
    star_rows = q(cur, f"""SELECT bucket, COUNT(*) FROM (
        SELECT repo_name, CASE
          WHEN MAX(repo_stars)=0 THEN '0'
          WHEN MAX(repo_stars) BETWEEN 1 AND 10 THEN '1-10'
          WHEN MAX(repo_stars) BETWEEN 11 AND 100 THEN '11-100'
          WHEN MAX(repo_stars) BETWEEN 101 AND 1000 THEN '101-1000'
          ELSE '1000+' END AS bucket
        FROM spec_files WHERE {KEEP} GROUP BY repo_name) t GROUP BY bucket""")
    star_order = {"0": 0, "1-10": 1, "11-100": 2, "101-1000": 3, "1000+": 4}
    star_rows = sorted(star_rows, key=lambda r: star_order.get(r[0], 9))
    pop_repos = q1(cur, f"SELECT COUNT(DISTINCT repo_name) FROM spec_files WHERE {KEEP} AND repo_stars > {POP_STARS}")
    pop_files = q1(cur, f"SELECT COUNT(*) FROM spec_files WHERE {KEEP} AND repo_stars > {POP_STARS}")
    max_stars = q1(cur, f"SELECT MAX(repo_stars) FROM spec_files WHERE {KEEP}")

    # Languages (repo-level)
    lang_rows = q(cur, f"SELECT COALESCE(repo_language,'(none)'), COUNT(DISTINCT repo_name) r "
                       f"FROM spec_files WHERE {KEEP} GROUP BY repo_language ORDER BY r DESC LIMIT 12")
    # Licenses (repo-level)
    lic_rows = q(cur, f"SELECT COALESCE(repo_license_spdx_id,'(none)'), COUNT(DISTINCT repo_name) r "
                      f"FROM spec_files WHERE {KEEP} GROUP BY repo_license_spdx_id ORDER BY r DESC LIMIT 10")
    # Path conventions
    conv_rows = q(cur, f"""SELECT conv, COUNT(*) FROM (
        SELECT CASE
          WHEN file_path LIKE '%.specify/%' THEN 'Spec Kit (.specify/)'
          WHEN file_path LIKE '%specs/%' THEN 'specs/ dir'
          WHEN file_path LIKE '%spec/%' THEN 'spec/ dir'
          WHEN file_path LIKE '%docs/%' THEN 'docs/'
          WHEN file_path LIKE '%.github/%' THEN '.github/'
          WHEN file_path NOT LIKE '%/%' THEN 'repo root'
          ELSE 'other' END AS conv
        FROM spec_files WHERE {KEEP}) t GROUP BY conv ORDER BY COUNT(*) DESC""")
    # Tooling attribution (classify_tooling.py): which SDD kit produced each spec.
    tool_rows = q(cur, f"SELECT spec_tool, COUNT(*) n, COUNT(DISTINCT repo_name) r "
                       f"FROM spec_files WHERE {KEEP} AND spec_tool IS NOT NULL "
                       f"GROUP BY spec_tool ORDER BY n DESC")
    # OpenSpec lifecycle split (living vs proposed vs archived).
    osrole_rows = q(cur, f"SELECT spec_role, COUNT(*) FROM spec_files "
                         f"WHERE {KEEP} AND spec_tool='openspec' AND spec_role<>'na' "
                         f"GROUP BY spec_role ORDER BY 2 DESC")
    # Per-rule counts, keyed by (tool, role) — each classify_tooling.py rule maps to
    # a unique (tool, role) pair, so this reproduces the rulebook's file counts.
    taxo_pairs = q(cur, f"SELECT spec_tool, spec_role, COUNT(*) FROM spec_files "
                        f"WHERE {KEEP} AND spec_tool IS NOT NULL GROUP BY spec_tool, spec_role")
    taxo_cnt = {(t, r): n for t, r, n in taxo_pairs}

    # ---- Content features (analyze_content.py -> spec_content_features) ----
    # Everything here is over files we actually fetched + parsed (join to the flag).
    CF = ("FROM spec_content_features t JOIN spec_files s "
          "ON s.file_url_sha16 = t.file_url_sha16 WHERE s.not_spec_filter = 0")
    cf_n = q1(cur, f"SELECT COUNT(*) {CF}") or 0
    if cf_n:
        cf_avg_words = q1(cur, "SELECT ROUND(AVG(n_words)) FROM spec_content_features")
        # By-tool content profile (the bimodal dialect story). Top tools by volume.
        style_rows = q(cur, f"""SELECT s.spec_tool, COUNT(*) n, ROUND(AVG(t.n_words)) w,
              ROUND(AVG(t.has_ears)*100,1) ears, ROUND(AVG(t.has_gherkin)*100,1) ghk,
              ROUND(AVG(t.has_unfilled_placeholder)*100,1) plc
            {CF} GROUP BY s.spec_tool ORDER BY n DESC LIMIT 8""")
        # Section presence (share of parsed files).
        SEC = [("has_requirements", "Requirements"), ("has_purpose", "Purpose"),
               ("has_success_criteria", "Success Criteria"), ("has_user_scenarios", "User Scenarios/Stories"),
               ("has_edge_cases", "Edge Cases"), ("has_out_of_scope", "Out of Scope"),
               ("has_dependencies", "Dependencies"), ("has_overview", "Overview"),
               ("has_acceptance_criteria", "Acceptance Criteria"), ("has_open_questions", "Open Questions")]
        sec_sel = ", ".join(f"ROUND(AVG({c})*100,1)" for c, _ in SEC)
        sec_vals = q(cur, f"SELECT {sec_sel} FROM spec_content_features")[0]
        sec_rows = sorted(zip([lbl for _, lbl in SEC], [float(v) for v in sec_vals]),
                          key=lambda kv: kv[1], reverse=True)
        # Markdown richness (share with >=1).
        RICH = [("n_code_fences", "code blocks"), ("n_tables", "tables"),
                ("n_checkboxes", "task checkboxes"), ("n_mermaid", "mermaid diagrams"),
                ("n_images", "images")]
        rich_sel = ", ".join(f"ROUND(AVG({c}>0)*100,1)" for c, _ in RICH)
        rich_vals = [float(v) for v in q(cur, f"SELECT {rich_sel} FROM spec_content_features")[0]]
        rich_rows = list(zip([lbl for _, lbl in RICH], rich_vals))
        # Quality.
        tiny_pct = float(q1(cur, "SELECT ROUND(AVG(is_tiny)*100,1) FROM spec_content_features"))
        plc_pct = float(q1(cur, "SELECT ROUND(AVG(has_unfilled_placeholder)*100,1) FROM spec_content_features"))
        # Natural language.
        en_pct = float(q1(cur, "SELECT ROUND(AVG(lang='en')*100,1) FROM spec_content_features"))
        lang_rows_nat = q(cur, "SELECT lang, COUNT(*) c FROM spec_content_features "
                               "WHERE lang NOT IN ('na','unknown') GROUP BY lang ORDER BY c DESC LIMIT 8")
    tool_attr = q1(cur, f"SELECT COUNT(*) FROM spec_files WHERE {KEEP} AND spec_tool IS NOT NULL")
    # Authorship
    auth_rows = q(cur, f"SELECT COALESCE(file_last_commit_author_type,'(unlinked)'), COUNT(*) "
                       f"FROM spec_files WHERE {KEEP} GROUP BY file_last_commit_author_type ORDER BY 2 DESC")
    verified = q1(cur, f"SELECT COUNT(*) FROM spec_files WHERE {KEEP} AND file_last_commit_verified=1")
    # Top owners (outliers)
    owner_rows = q(cur, f"SELECT owner_login, owner_type, COUNT(*) n, COUNT(DISTINCT repo_name) r "
                        f"FROM spec_files WHERE {KEEP} AND owner_login IS NOT NULL "
                        f"GROUP BY owner_login, owner_type ORDER BY n DESC LIMIT 10")
    # ---- Commit-history-derived (Phase 2): only 'done' rows carry first-commit data ----
    HIST = f"{KEEP} AND commit_history_status = 'done'"
    hist_files = q1(cur, f"SELECT COUNT(*) FROM spec_files WHERE {HIST}")
    empty_files = q1(cur, f"SELECT COUNT(*) FROM spec_files WHERE {KEEP} AND commit_history_status = 'empty'")
    # Commit counts restricted to the KEPT set (SUM of per-file counts == kept
    # commit rows; verified needs the per-commit table joined back to the flag).
    total_commits = int(q1(cur, f"SELECT COALESCE(SUM(file_total_commits),0) FROM spec_files WHERE {HIST}") or 0)
    verified_commits = q1(cur, f"SELECT COUNT(*) FROM spec_file_commits c "
                               f"JOIN spec_files s ON s.file_url_sha16 = c.file_url_sha16 "
                               f"WHERE s.not_spec_filter = 0 AND c.verified = 1")

    # Temporal — CREATION (first commit). No hardcoded floor: pre-2024 files are
    # excluded upstream by classify_specs.py's `pre_2024` rule, so the axis
    # auto-ranges from the first month with kept data (2024-01) forward.
    crt_rows = q(cur, f"SELECT SUBSTR(file_first_commit_at,1,7) ym, COUNT(*), COUNT(DISTINCT repo_name) "
                      f"FROM spec_files WHERE {HIST} "
                      f"GROUP BY ym ORDER BY ym")
    # Creation timeline split by (spec_tool, spec_role) — one series per rulebook row.
    crt_tr_rows = q(cur, f"SELECT spec_tool, spec_role, SUBSTR(file_first_commit_at,1,7) ym, COUNT(*) "
                         f"FROM spec_files WHERE {HIST} AND spec_tool IS NOT NULL "
                         f"GROUP BY spec_tool, spec_role, ym")

    # Temporal — ACTIVITY (last commit). Same kept population as the creation
    # timeline (all created 2024+), so it auto-ranges from 2024-01 too.
    tmp_rows = q(cur, f"SELECT SUBSTR(file_last_commit_at,1,7) ym, COUNT(*), COUNT(DISTINCT repo_name) "
                      f"FROM spec_files WHERE {HIST} AND file_last_commit_at IS NOT NULL "
                      f"GROUP BY ym ORDER BY ym")

    # Commit-count distribution (how much a spec churns)
    cc_rows = q(cur, f"""SELECT bucket, COUNT(*) FROM (
        SELECT CASE
          WHEN file_total_commits = 1 THEN '1'
          WHEN file_total_commits BETWEEN 2 AND 5 THEN '2-5'
          WHEN file_total_commits BETWEEN 6 AND 20 THEN '6-20'
          WHEN file_total_commits BETWEEN 21 AND 100 THEN '21-100'
          ELSE '100+' END AS bucket
        FROM spec_files WHERE {HIST}) t GROUP BY bucket""")
    cc_order = {"1": 0, "2-5": 1, "6-20": 2, "21-100": 3, "100+": 4}
    cc_rows = sorted(cc_rows, key=lambda r: cc_order.get(r[0], 9))
    single_commit = q1(cur, f"SELECT COUNT(*) FROM spec_files WHERE {HIST} AND file_total_commits = 1")
    avg_commits = q1(cur, f"SELECT ROUND(AVG(file_total_commits), 2) FROM spec_files WHERE {HIST}")
    max_commits = q1(cur, f"SELECT MAX(file_total_commits) FROM spec_files WHERE {HIST}")

    # Lifespan (first -> last commit), in days, multi-commit files only
    life_rows = q(cur, f"""SELECT bucket, COUNT(*) FROM (
        SELECT CASE
          WHEN DATEDIFF(SUBSTR(file_last_commit_at,1,10), SUBSTR(file_first_commit_at,1,10)) = 0 THEN 'same day'
          WHEN DATEDIFF(SUBSTR(file_last_commit_at,1,10), SUBSTR(file_first_commit_at,1,10)) <= 7 THEN '1-7 days'
          WHEN DATEDIFF(SUBSTR(file_last_commit_at,1,10), SUBSTR(file_first_commit_at,1,10)) <= 30 THEN '8-30 days'
          WHEN DATEDIFF(SUBSTR(file_last_commit_at,1,10), SUBSTR(file_first_commit_at,1,10)) <= 90 THEN '31-90 days'
          ELSE '90+ days' END AS bucket
        FROM spec_files WHERE {HIST} AND file_total_commits > 1) t GROUP BY bucket""")
    life_order = {"same day": 0, "1-7 days": 1, "8-30 days": 2, "31-90 days": 3, "90+ days": 4}
    life_rows = sorted(life_rows, key=lambda r: life_order.get(r[0], 9))

    # Creator vs maintainer: is the first-commit author the same as the last?
    same_author = q1(cur, f"""SELECT COUNT(*) FROM spec_files WHERE {HIST} AND file_total_commits > 1
        AND file_first_commit_author_login IS NOT NULL AND file_last_commit_author_login IS NOT NULL
        AND file_first_commit_author_login = file_last_commit_author_login""")
    diff_author = q1(cur, f"""SELECT COUNT(*) FROM spec_files WHERE {HIST} AND file_total_commits > 1
        AND file_first_commit_author_login IS NOT NULL AND file_last_commit_author_login IS NOT NULL
        AND file_first_commit_author_login <> file_last_commit_author_login""")

    # First-commit author type (who CREATES specs — humans vs agents/bots?)
    crt_auth_rows = q(cur, f"SELECT COALESCE(file_first_commit_author_type,'(unlinked)'), COUNT(*) "
                           f"FROM spec_files WHERE {HIST} GROUP BY file_first_commit_author_type ORDER BY 2 DESC")
    conn.close()

    # ---- figures ----
    fig_monthly([r[0] for r in crt_rows], [r[1] for r in crt_rows], [r[2] for r in crt_rows],
                "Spec-file creation over time (bar = files created; label = # repos)",
                "spec files created (first commit in month)", "creation_monthly.png")
    fig_monthly([r[0] for r in tmp_rows], [r[1] for r in tmp_rows], [r[2] for r in tmp_rows],
                "Spec-file activity over time (bar = files; label = # repos)",
                "spec files (last commit in month)", "adoption_monthly.png")
    fig_vbars([r[0] for r in cc_rows], [r[1] for r in cc_rows],
              "How much specs churn (commits per file)", "spec files", "commits per file",
              "commit_counts.png")
    fig_vbars([r[0] for r in life_rows], [r[1] for r in life_rows],
              "Spec lifespan (first to last commit; multi-commit files)", "spec files",
              "first-to-last-commit span", "lifespan.png")
    fig_stars([r[0] for r in star_rows], [r[1] for r in star_rows])
    _hbar([r[0] for r in lang_rows], [r[1] for r in lang_rows],
          "Top languages of spec-containing repositories", "repositories",
          "top_languages.png", fmt_pct_of=repos)
    _hbar([r[0] for r in conv_rows], [r[1] for r in conv_rows],
          "Where spec files live (path convention)", "spec files",
          "path_conventions.png", fmt_pct_of=total)
    # Tool-family chart: pretty names, top families kept explicit (they read as a
    # who's-who of SDD kits); the tiny per-IDE config dirs are already distinct rows.
    TOOL_LABEL = {
        "openspec": "OpenSpec", "speckit": "GitHub Spec Kit", "adhoc_other": "ad-hoc / other",
        "specs_generic": "generic specs/ dir", "docs_embedded": "docs/ embedded",
        "root_bare": "root-level spec.md", "caffeine": "caffeine.ai (generator)",
        "conductor": "Conductor", "trae": ".trae/ (Trae)", "opencode": ".opencode/",
        "claude_code": ".claude/ (Claude Code)", "agent_os": "Agent OS", "moai": "MoAI-ADK",
        "specweave": "SpecWeave", "codex": ".codex/", "cursor": ".cursor/", "kilocode": ".kilocode/",
        "gsd": "GSD (.gsd/)", "zenflow": "Zenflow (.zenflow/)", "dot_specs": ".specs/ dir",
        "kitty_specs": "kitty-specs/",
    }
    tool_top = tool_rows[:12]
    _hbar([TOOL_LABEL.get(r[0], r[0]) for r in tool_top], [r[1] for r in tool_top],
          "Which SDD tool produced the spec (top families)", "spec files",
          "tool_families.png", fmt_pct_of=total)
    # Per-(tool, role) creation small-multiples — one panel per rulebook row, same order.
    RULE_TR = [("caffeine", "na"), ("openspec", "archived"), ("openspec", "change_proposal"),
               ("openspec", "living"), ("openspec", "na"), ("speckit", "config"),
               ("speckit", "feature"), ("conductor", "na"), ("agent_os", "na"),
               ("specweave", "na"), ("moai", "na"), ("claude_code", "config"),
               ("opencode", "config"), ("trae", "config"), ("codex", "config"),
               ("cursor", "config"), ("kilocode", "config"),
               ("gsd", "config"), ("zenflow", "config"), ("dot_specs", "na"), ("kitty_specs", "na"),
               ("specs_generic", "na"), ("docs_embedded", "na"), ("root_bare", "na"), ("adhoc_other", "na")]
    tr_map = {}
    tr_months = set()
    for t, r, ym, n in crt_tr_rows:
        if ym:
            tr_map.setdefault((t, r), {})[ym] = n
            tr_months.add(ym)
    sm_months = sorted(tr_months)
    sm_panels = []
    for t, r in RULE_TR:
        d = tr_map.get((t, r), {})
        counts = [d.get(m, 0) for m in sm_months]
        role_txt = "" if r == "na" else f"/{r}"
        sm_panels.append((f"{TOOL_LABEL.get(t, t)}{role_txt} · {sum(counts):,}", counts))
    fig_small_multiples(sm_panels, sm_months, "creation_by_tool_role.png")
    if cf_n:
        st_lbl = [TOOL_LABEL.get(r[0], r[0]) for r in style_rows]
        fig_style_by_tool(st_lbl, [float(r[3]) for r in style_rows],
                          [float(r[4]) for r in style_rows], "content_style_by_tool.png")
        _hbar(st_lbl, [int(r[2]) for r in style_rows],
              "Spec length by tool (avg words) — terse vs verbose", "average words",
              "content_length_by_tool.png")
        _hbar([lbl for lbl, _ in sec_rows], [v for _, v in sec_rows],
              "Which sections specs contain (% of specs)", "% of specs",
              "content_sections.png")
        _hbar([l for l, _ in lang_rows_nat], [c for _, c in lang_rows_nat],
              "Natural language of specs (top non-English + English)", "specs",
              "content_language.png")
    _hbar([r[0] for r in lic_rows], [r[1] for r in lic_rows],
          "Top licenses of spec-containing repositories", "repositories",
          "licenses.png", fmt_pct_of=repos)

    # ---- markdown ----
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = []
    md.append("# Spec-Driven Development on GitHub — Descriptive Statistics\n")
    md.append(f"*Auto-generated by `spec_descriptives.py` on {gen}.*\n")
    if totp and done >= totp:
        md.append(
            f"> **Complete collection.** All {totp:,} size-partitions done — this is the full "
            "census of `spec.md`/`specs.md` files on GitHub (no truncated partitions). "
            "Figures/tables regenerate when the script is re-run.\n")
    else:
        md.append(
            f"> **Snapshot of an in-progress collection.** {done:,}/{totp:,} size-partitions "
            f"complete (~{100*done/totp:.0f}%), so counts will grow. All figures/tables "
            "regenerate when the script is re-run.\n")
    md.append(
        f"> **Full commit history (Phase 2).** For every kept file we walked its entire "
        f"path-history: **{hist_files:,}** files carry a first (creation) commit and complete "
        f"timeline ({empty_files:,} had no retrievable history), totalling **{total_commits:,}** "
        "commits. So the temporal view below is a true **creation timeline** (first commit), "
        "with last-commit *activity* reported separately.\n")
    if cf_n:
        md.append(
            f"> **Full file content (Phase 3).** We fetched the raw markdown of every kept file that "
            f"still exists — **{cf_n:,}** specs — and parsed ~40 structural features from each "
            "(`analyze_content.py`). This unlocks the content sections §3–§5 (requirement style, "
            "structure, language) below; the ~2.5k unreachable files are deleted-since upstream.\n")
    excl_bits = ", ".join(f"{note} {n:,}" for note, n in tagged)
    md.append(
        f"> **Cleaned dataset.** Numbers below are the cleaned cut: **{excluded:,}** of "
        f"{raw_total:,} raw files ({pct(excluded, raw_total)}) are excluded as non-SDD — "
        f"structural noise plus pre-2024 files that predate the SDD tooling era "
        f"({excl_bits}) — via `classify_specs.py`. The exclusion is a reversible flag "
        "(`not_spec_filter`), not a delete. AI-generator specs (caffeinepub) are **kept** "
        "but separately tagged, so they still count here.\n")

    md.append("## 1. Dataset size\n")
    size_rows = [
        ["Spec files", f"{total:,}"],
        ["Unique repositories", f"{repos:,}"],
        ["Unique owner accounts", f"{owners:,}"],
        ["Avg spec files / repo", f"{total/repos:.2f}" if repos else "-"],
        ["Commits across all specs", f"{total_commits:,}"],
        ["Avg commits / spec file", f"{avg_commits}"],
        ["Files with commit history", f"{hist_files:,} ({pct(hist_files, total)})"],
    ]
    if cf_n:
        size_rows.append(["Files with parsed content", f"{cf_n:,} ({pct(cf_n, total)})"])
        size_rows.append(["Avg words / spec", f"{int(cf_avg_words):,}"])
    if not (totp and done >= totp):
        # Pre-count is inflated by inclusive size-range boundary overlaps; only
        # meaningful while collection is ongoing, not as a final figure.
        size_rows.append(["Estimated final size", f"~{est:,} files" if est else "-"])
    md.append(md_table(["metric", "value"], size_rows) + "\n")

    # ---- Tooling ecosystem (headline structural finding) ----
    td = {t: (n, r) for t, n, r in tool_rows}
    osd = {role: n for role, n in osrole_rows}
    def tc(name):
        return td.get(name, (0, 0))[0]
    md.append("## 2. The spec tooling ecosystem — which SDD kit produced each spec\n")
    md.append("![tool families](figures/tool_families.png)\n")
    md.append(
        "Every kept file is attributed to the tool that produced it (`classify_tooling.py`, "
        f"{pct(tool_attr, total)} coverage) by its **path fingerprint** — and a content sample "
        "confirms path and document-template agree, so these are genuinely distinct toolchains, "
        "not arbitrary folders. Two kits dominate the entire ecosystem:\n")
    md.append(
        f"- **OpenSpec** (Fission-AI) — **{tc('openspec'):,}** files ({pct(tc('openspec'), total)}). "
        "Its `openspec/` tree encodes a whole lifecycle: "
        f"**{osd.get('living',0):,} living** capability specs (`openspec/specs/…/spec.md`), "
        f"**{osd.get('change_proposal',0):,} active change proposals** and "
        f"**{osd.get('archived',0):,} archived** ones (`openspec/changes/[archive/]…`). The archive "
        "is why OpenSpec looks so large — every completed change keeps a dated copy of the spec.\n"
        f"- **GitHub Spec Kit** — **{tc('speckit'):,}** files ({pct(tc('speckit'), total)}): numbered "
        "`specs/NNN-name/spec.md` feature specs plus its `.specify/` scaffold.\n"
        f"- A **long tail of newer kits**: caffeine.ai ({tc('caffeine'):,}), Conductor "
        f"({tc('conductor'):,}), Agent OS ({tc('agent_os'):,}), MoAI-ADK ({tc('moai'):,}), "
        f"SpecWeave ({tc('specweave'):,}), and per-IDE agent dirs (`.trae/`, `.opencode/`, "
        "`.claude/`, `.codex/`, `.cursor/`). The remaining ~20% are generic `specs/` dirs, "
        "`docs/`-embedded specs, bare root `spec.md`s, and ad-hoc conventions with no tool marker.\n")
    # Full attribution rulebook: the priority-ordered path fingerprints, the tool/role
    # each writes, and the file count it claimed (first-match-wins, so counts sum to
    # the whole kept set). Static rule metadata; counts pulled live from the DB.
    RULEBOOK = [
        ("1", "`owner_login = 'caffeinepub'`", "caffeine", "na"),
        ("2", "`openspec/changes/archive/%`", "openspec", "archived"),
        ("3", "`openspec/changes/%`", "openspec", "change_proposal"),
        ("4", "`openspec/specs/%`", "openspec", "living"),
        ("5", "`openspec/%` (anything else)", "openspec", "na"),
        ("6", "`.specify/%` or `%/.specify/%`", "speckit", "config"),
        ("7", "`specs/NNN[-_]` (regexp)", "speckit", "feature"),
        ("8", "`…/conductor/…`", "conductor", "na"),
        ("9", "`…agent-os/…`", "agent_os", "na"),
        ("10", "`…/.specweave/…`", "specweave", "na"),
        ("11", "`…/.moai/…`", "moai", "na"),
        ("12", "`%.claude/%`", "claude_code", "config"),
        ("13", "`%.opencode/%`", "opencode", "config"),
        ("14", "`%.trae/%`", "trae", "config"),
        ("15", "`%.codex%`", "codex", "config"),
        ("16", "`%.cursor/%`", "cursor", "config"),
        ("17", "`%.kilocode/%`", "kilocode", "config"),
        ("18", "`.gsd/` (start or `/`)", "gsd", "config"),
        ("19", "`.zenflow/` (start or `/`)", "zenflow", "config"),
        ("20", "`.specs/` (start or `/`)", "dot_specs", "na"),
        ("21", "`kitty-specs/` (start or `/`)", "kitty_specs", "na"),
        ("22", "any `…specs/…` (regexp)", "specs_generic", "na"),
        ("23", "`docs/%` or `%/docs/%`", "docs_embedded", "na"),
        ("24", "path has no `/` (repo root)", "root_bare", "na"),
        ("25", "`1=1` (everything left)", "adhoc_other", "na"),
    ]
    rb_rows = [[num, fp, f"`{t}`", f"`{r}`", f"{taxo_cnt.get((t, r), 0):,}"]
               for num, fp, t, r in RULEBOOK]
    rb_rows.append(["—", "**Total (kept set)**", "", "", f"**{tool_attr:,}**"])
    md.append(
        "**The attribution rulebook.** Files are labelled by a priority-ordered list of path "
        "fingerprints (`classify_tooling.py`); the first rule that matches wins, so each file is "
        "counted exactly once and the file counts below sum to the whole kept set:\n")
    md.append(md_table(["#", "rule (path fingerprint)", "spec_tool", "spec_role", "files"],
                       rb_rows) + "\n")
    md.append(
        "**Creation over time, one panel per rule.** The same 21 buckets as a grid of creation "
        "timelines (first-commit month). Panels share the x-axis but each has its own y-scale, so "
        "the *shape* of adoption is comparable even where volumes differ 100×. This is where the "
        "OpenSpec archive shows its hand — `openspec/archived` ramps only as changes accumulate and "
        "get filed — while `openspec/living` and `speckit/feature` track the raw creation curve:\n")
    md.append("![creation by tool & role](figures/creation_by_tool_role.png)\n")
    md.append(
        "**Each kit emits a recognizable template.** A stratified content sample (raw file text) "
        "shows highly consistent, machine-detectable section structures — the same signal the "
        "path gives, independently confirmed in the document body:\n")
    md.append(md_table(
        ["tool", "signature template markers (from content sample)", "median lines"],
        [["OpenSpec", "`## Purpose` · `## Requirements` · `#### Scenario:` · delta headers `## ADDED/MODIFIED/REMOVED Requirements` · EARS “shall”", "~45–60"],
         ["GitHub Spec Kit", "`## User Scenarios & Testing *(mandatory)*` · `## Requirements *(mandatory)*` · `Success Criteria` · `Edge Cases` · `Key Entities` · `[NEEDS CLARIFICATION]`", "~144"],
         ["caffeine.ai", "`## Summary` · `## Specification` · `## Current State` · `## Requested Changes (diff)` · `## Implementation Plan`", "~20"],
         ["Agent OS", "`Spec Requirements Document` · `## User Stories` · `## Spec Scope` · `## Out of Scope` · `## Expected Deliverable`", "~122"],
         ["SpecWeave", "`## User Stories` · `## Acceptance Criteria` · `## Overview` · `## Dependencies` · `## Success Criteria`", "~88"],
         ["MoAI-ADK", "`## History` · `Requirements (EARS format)` · `Exclusions (what not to build)` · `@SPEC:` anchors", "~240"],
         ["Conductor", "`## Overview` · `## Functional Requirements` · `## Acceptance Criteria` · `## Out of Scope`", "~32"]]) + "\n")
    md.append(
        "Two template *dialects* run across the whole ecosystem regardless of kit: the "
        "**EARS** requirement style (“the system **shall** …”, strongest in OpenSpec & MoAI) "
        "and **Gherkin-ish** `WHEN/THEN` scenario prose. The takeaway: SDD on GitHub is not "
        "free-form prose — it is overwhelmingly **templated output from a small set of kits**, "
        "which makes the corpus unusually tractable for structured analysis.\n")

    if cf_n:
        md.append("## 3. What's inside the specs — two requirement dialects\n")
        md.append(
            f"We fetched and parsed the **full text** of every kept file that still exists "
            f"({cf_n:,} specs; `fetch_spec_content.py` + `analyze_content.py`) and extracted ~40 "
            "structural features each. The clearest finding: **requirement style is bimodal, and "
            "the tool decides which mode you're in.**\n")
        md.append("![style by tool](figures/content_style_by_tool.png)\n")
        md.append(md_table(
            ["tool", "specs", "avg words", "EARS “shall”", "Gherkin WHEN/THEN", "placeholders"],
            [[TOOL_LABEL.get(r[0], r[0]), f"{r[1]:,}", f"{int(r[2]):,}",
              f"{float(r[3]):.0f}%", f"{float(r[4]):.0f}%", f"{float(r[5]):.1f}%"]
             for r in style_rows]) + "\n")
        os_w = next((int(r[2]) for r in style_rows if r[0] == "openspec"), 0)
        sk_w = next((int(r[2]) for r in style_rows if r[0] == "speckit"), 0)
        md.append(
            f"**OpenSpec** produces *short, highly formal* specs (~{os_w:,} words; ~87% use the EARS "
            "“the system **shall** …” form and ~97% carry Gherkin-style `WHEN/THEN` scenarios). "
            f"**Spec Kit** produces *long prose* (~{sk_w:,} words — roughly 3× longer) that almost "
            "never uses EARS (~2%). So “spec-driven development” is not one writing style but at "
            "least two distinct dialects, selected by the kit — a strong signal that these specs are "
            "**templated tool output, not free-form authoring**. (Note `specs_generic`, a "
            "path-ambiguous bucket, is ~34% EARS / ~54% Gherkin — much of it is OpenSpec-style "
            "content that simply lives outside an `openspec/` folder.)\n")

        md.append("## 4. Structure, richness & quality\n")
        md.append("![sections](figures/content_sections.png)\n")
        req_p = dict(sec_rows).get("Requirements", 0)
        ac_p = dict(sec_rows).get("Acceptance Criteria", 0)
        md.append(
            f"A **Requirements** section is near-universal ({req_p:.0f}% of specs), but an explicit "
            f"**Acceptance Criteria** heading is rare ({ac_p:.0f}%) — most specs express testability "
            "through scenarios rather than a labelled criteria list. Purpose, Success Criteria, User "
            "Scenarios and Edge Cases form the next tier.\n")
        md.append("![length by tool](figures/content_length_by_tool.png)\n")
        md.append(
            "Length is just as tool-driven as style: caffeine.ai/Conductor emit terse stubs, "
            "OpenSpec is compact-and-formal, while root-level `spec.md`s are the longest, most "
            "free-form documents.\n")
        md.append("**Markdown richness** — specs are prose, not illustrated designs:\n\n" + md_table(
            ["element", "% of specs with ≥1"],
            [[lbl, f"{v:.1f}%"] for lbl, v in rich_rows]) + "\n")
        md.append(
            f"Only ~{dict(rich_rows).get('code blocks',0):.0f}% contain a code block and essentially "
            "none use diagrams (mermaid/images < 1%). On **quality**, the corpus is substantive, not "
            f"skeletons: just **{tiny_pct:.1f}%** are near-empty stubs and **{plc_pct:.1f}%** still "
            "carry an unfilled placeholder (`TODO`/`[NEEDS CLARIFICATION]`).\n")

        md.append("## 5. What language are specs written in?\n")
        md.append("![language](figures/content_language.png)\n")
        others = ", ".join(f"{l} ({c:,})" for l, c in lang_rows_nat if l != "en")
        md.append(
            f"Spec-driven development is **global**: **{en_pct:.0f}% English**, with a real "
            f"non-English tail — {others}. (Detected with `langdetect`; very short specs may be "
            "misattributed, so treat small languages as indicative.)\n")

    md.append("## 6. When specs are created (creation timeline)\n")
    md.append("![creation](figures/creation_monthly.png)\n")
    peak = max(crt_rows, key=lambda r: r[1]) if crt_rows else ("-", 0, 0)
    md.append(
        "Using each file's **first commit** — its true birth date — spec-driven development is "
        "a strikingly recent phenomenon: essentially nonexistent through 2024, then explosive "
        f"growth across 2025–2026 (peak month {peak[0]}: {peak[1]:,} files created across "
        f"{peak[2]:,} repos). Each bar's label is the number of distinct **repositories** "
        "creating specs that month, so the rising label confirms this is broad grassroots "
        "adoption, not a few monorepos.\n")
    md.append(
        "*(The axis is not hardcoded to 2024: the 6,705 files whose first commit predates "
        "2024-01 — trickling back to 2009 — are `spec.md`/`specs.md` files that predate the "
        "SDD tooling era and are excluded upstream as `pre_2024`, so the timeline naturally "
        "begins where SDD does.)*\n")

    md.append("## 7. How specs evolve (churn & lifespan)\n")
    md.append("![commit counts](figures/commit_counts.png)\n")
    md.append(
        f"Most specs are **written once and left**: {pct(single_commit, hist_files)} have exactly "
        f"**one commit**, and the average is just {avg_commits} commits/file (max {max_commits:,}). "
        "Spec-driven development, as practised, is largely a *point-in-time* artifact rather than "
        "a continuously-revised living document.\n")
    md.append("![lifespan](figures/lifespan.png)\n")
    life_total = sum(n for _, n in life_rows) or 1
    same_day = next((n for b, n in life_rows if b == "same day"), 0)
    long_lived = next((n for b, n in life_rows if b == "90+ days"), 0)
    md.append(
        f"Among the specs that *are* revised (>1 commit), {pct(same_day, life_total)} are edited "
        f"only on their **creation day**, while {pct(long_lived, life_total)} stay active for "
        "**90+ days** — a smaller cohort of genuinely maintained, evolving specs.\n")

    md.append("## 8. Creators & maintainers\n")
    ca_total = same_author + diff_author
    md.append(
        "**Who commits the first version?** (are agents *authoring* specs, or just humans?)\n\n"
        + md_table(["first-commit author type", "files", "%"],
                   [[t, f"{n:,}", pct(n, hist_files)] for t, n in crt_auth_rows]) + "\n")
    md.append(
        f"For multi-commit specs with linked authors, the **first and last commit are the same "
        f"person {pct(same_author, ca_total)}** of the time ({same_author:,} vs {diff_author:,} "
        "handed off to someone else) — spec authorship is overwhelmingly a **solo** activity. "
        f"Across *all* {total_commits:,} commits, {pct(verified_commits, total_commits)} are "
        "GPG-verified.\n")

    md.append("## 9. Maintenance activity over time (last commit)\n")
    md.append("![activity](figures/adoption_monthly.png)\n")
    md.append(
        "The same view by **last** commit reflects recent *activity* rather than creation. It "
        "tracks the creation curve closely — consistent with §7's finding that most specs are "
        "committed once and rarely touched again, so a file's last commit is usually near its first.\n")

    md.append("## 10. Repository popularity — the long tail\n")
    md.append("![stars](figures/stars_distribution.png)\n")
    zero = next((n for b, n in star_rows if b == "0"), 0)
    md.append(
        f"Spec-driven development is largely **grassroots**: {pct(zero, repos)} of "
        f"spec-containing repos have **0 stars**. Only **{pop_repos:,}** repos "
        f"(> {POP_STARS} stars; {pct(pop_files, total)} of files) form the \"popular\" cut. "
        f"Max stars observed: {max_stars:,}.\n")

    md.append("## 11. Languages & ecosystems\n")
    md.append("![languages](figures/top_languages.png)\n")
    top_lang = lang_rows[0] if lang_rows else ("-", 0)
    md.append(
        f"**{top_lang[0]}** leads by a wide margin ({pct(top_lang[1], repos)} of repos), "
        "reflecting where AI-assisted / spec-driven tooling has taken hold.\n")

    md.append("## 12. Where spec files live (path conventions)\n")
    md.append("![conventions](figures/path_conventions.png)\n")
    md.append(
        "A coarse view of how developers *organize* specs (the fine-grained tool attribution is "
        "§2). The `specs/…/spec.md` layout dominates — this is both OpenSpec's and Spec Kit's "
        "output location — with an explicit `.specify/` Spec Kit footprint; the `other` bucket is "
        "resolved into named tools and an ad-hoc tail in §2.\n")

    md.append("## 13. Licensing\n")
    md.append("![licenses](figures/licenses.png)\n")
    nolic = next((r for l, r in lic_rows if l == "(none)"), 0)
    md.append(
        f"Consistent with the long tail, **{pct(nolic, repos)}** of spec repos carry **no "
        "license**, with MIT the dominant explicit choice.\n")

    md.append("## 14. Filename, ownership & authorship\n")
    md.append("**spec.md vs specs.md**\n\n" + md_table(
        ["filename", "files", "%"],
        [[fn, f"{n:,}", pct(n, total)] for fn, n in fn_rows]) + "\n")
    md.append("**Owner type**\n\n" + md_table(
        ["owner_type", "files", "% files", "repos"],
        [[ot, f"{n:,}", pct(n, total), f"{r:,}"] for ot, n, r in ot_rows]) + "\n")
    md.append("**Last-commit author type** (are agents committing the specs?)\n\n" + md_table(
        ["author_type", "files", "%"],
        [[t, f"{n:,}", pct(n, total)] for t, n in auth_rows]) + "\n")
    md.append(
        f"At the commit level, spec files are still overwhelmingly **human-committed**; "
        f"GPG-verified last commits: {verified:,} ({pct(verified, total)}).\n")

    md.append("## 15. Data-quality notes & outliers\n")
    md.append("Top owners by file count, **after cleaning**:\n")
    md.append(md_table(
        ["owner", "type", "files", "repos"],
        [[o, t, f"{n:,}", f"{r:,}"] for o, t, n, r in owner_rows]) + "\n")
    md.append(
        "- **What was removed, and why it matters.** Two structural-noise sources dominate "
        f"the excluded {excluded:,}: `spack/cache.spack.io` (a package-build-cache mirror where "
        "\"spec\" means a Spack build spec, not SDD) and vendored-dependency copies. Both are "
        "bulk, machine-generated, and unrelated to spec-driven development.\n"
        "- **High file-count is NOT a noise signal.** After removing those two sources, the "
        "remaining heavy-hitters above are legitimate power-users of spec-driven tooling "
        "(OpenSpec `openspec/…/specs/…/spec.md`, Spec Kit numbered `specs/NNN/`). De-skewing by "
        "per-repo file count would discard the most committed adopters — so we don't.\n"
        "- **AI-generated specs are kept but tagged.** `caffeinepub` (the caffeine.ai app "
        "generator) contributes ~14k genuine-but-machine-authored specs across ~14k one-app "
        "repos; these are retained and flagged so they can be analysed separately from "
        "human-authored SDD.\n"
        "- **Forks are excluded** by GitHub code search (a deliberate scoping choice — avoids "
        "fork duplication).\n"
        "- **Unlinked commit authors** (git email not tied to a GitHub account) are expected "
        "and simply reported as `(unlinked)`.\n")

    md.append("## Reproduce\n")
    md.append("```bash\npython3 spec_descriptives.py   # regenerates figures/ and this file\n```\n")

    with open(os.path.join(OUT_DIR, "descriptive_stats.md"), "w") as fh:
        fh.write("\n".join(md))

    print(f"Wrote {os.path.join(OUT_DIR, 'descriptive_stats.md')} and {len(os.listdir(FIG_DIR))} figures.")
    build_pdf()
    print(f"Snapshot: {total:,} files / {repos:,} repos / {owners:,} owners "
          f"({done}/{totp} partitions).")


if __name__ == "__main__":
    main()
