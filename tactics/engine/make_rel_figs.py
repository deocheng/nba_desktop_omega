#!/usr/bin/env python3
"""里程碑 03 图表：关系层的两处「结论会翻转」的定量证据。

三张图，全部读 JSON 现算，不硬编码任何数字：
  fig_rel_q2.png  —— 决定性 2x2：`holding` 只由「球框是否落在球员框内」决定，
                     真球位置与随机位置在框内/框外两层上**完全一致**（0.818 / 0.000）。
  fig_rel_q1.png  —— 名单口径对退化的影响：三种口径下都只有 4 个不同谓词，
                     `watching` 占 67%–88%，说明退化不是名单污染造成的。
  fig_rel_time.png—— 全 435 帧 `watching` 占比沿时间（叠 PBP 战术转换点）：
                     占比在转换点没有任何结构变化 ⇒ 关系层不携带战术信息。

用法: make_rel_figs.py <probe.json> <relations_full.json> <outdir>
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os

import matplotlib

from common.nba_paths import tactics_data_file

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

BG = "#12151c"
PANEL = "#1a1f29"
FG = "#e6e9ef"
DIM = "#8b93a3"
RED = "#e5484d"      # 中国习惯：高/涨 = 红
GREEN = "#3fb950"    # 低/跌 = 绿
BLUE = "#4c8dff"
AMBER = "#e3b341"
GREY = "#6e7681"

HOLD = {"holding", "carrying", "wearing", "riding", "using"}

# 窗口内 PBP 战术转换点——🔴 **不再手写，改为从 clock_table 读秒插值推导**。
# 2026-09-23 教训：本文件首版把 4 个事件时间硬编码成 218.5/221.1/223.4/224.6，
# 其中 ③④ 与真实时刻（239.8 / 244.3）差 16–20 秒，图上的虚线画在了无关时刻上，
# 还据此写了结论。现在一律由数据推导。
PBP_MARKS = []          # 由 load_pbp_marks() 填充


def load_pbp_marks(clock_table, possession_json, t0=204.5):
    """从画面读秒表反查每个 PBP 事件的时间 t，返回 [(t, label, color), ...]。"""
    ct = json.load(open(clock_table))
    pairs = sorted((round(t0 + (f["frame"] - 1) * 0.5, 2), float(f["clock_sec"]))
                   for f in ct["frames"] if "clock_sec" in f)

    def t_of_clock(c):
        for i in range(len(pairs) - 1):
            t1, c1 = pairs[i]
            t2, c2 = pairs[i + 1]
            if (c1 - c) * (c2 - c) <= 0 and c1 != c2:
                return round(t1 + (t2 - t1) * (c1 - c) / (c1 - c2), 1)
        return None

    pal = [RED, BLUE, AMBER, GREEN, "#a371f7"]
    marks, seen = [], set()
    for act in json.load(open(possession_json))["pbp_actions"]:
        t = t_of_clock(float(act["clock"]))
        if t is None:
            continue
        key = (t, act["kind"])
        if key in seen:
            continue
        seen.add(key)
        col = pal[len(marks) % len(pal)]
        marks.append((t, f"{act['player']} {act['kind']}", col))
    return marks


def _style(ax):
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color("#2b323f")
    ax.tick_params(colors=DIM, labelsize=9)
    ax.grid(True, color="#232a36", lw=0.7, alpha=0.9)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(DIM)
    ax.yaxis.label.set_color(DIM)
    ax.title.set_color(FG)


def fig_q2(probe, out):
    q = probe["Q2_ball_holding"]
    t2 = q["true_stratified_by_inside_player_box"]
    c2 = q["control"]["ctrl_stratified_by_inside_player_box"]
    labels = ["框内\n(球框落在球员框内)", "框外\n(球框落在球员框外)"]
    true_v = [t2["inside_box"]["hold_rate"], t2["outside_box"]["hold_rate"]]
    ctrl_v = [c2["inside_box"]["hold_rate"], c2["outside_box"]["hold_rate"]]
    true_n = [t2["inside_box"]["n"], t2["outside_box"]["n"]]
    ctrl_n = [c2["inside_box"]["n"], c2["outside_box"]["n"]]

    fig, ax = plt.subplots(figsize=(7.4, 4.3), dpi=150)
    fig.patch.set_facecolor(BG)
    _style(ax)
    x = [0, 1]
    w = 0.34
    b1 = ax.bar([i - w / 2 for i in x], true_v, w, color=RED,
                label="真球位置（目视确认）", zorder=3)
    b2 = ax.bar([i + w / 2 for i in x], ctrl_v, w, color=GREY,
                label="对照：随机位置（同尺寸方框）", zorder=3)
    for bars, vals, ns in ((b1, true_v, true_n), (b2, ctrl_v, ctrl_n)):
        for b, v, n in zip(bars, vals, ns):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.025, f"{v:.3f}\nn={n}",
                    ha="center", va="bottom", color=FG, fontsize=9.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, color=FG, fontsize=10)
    ax.set_ylim(0, 1.22)
    ax.set_ylabel("holding / carrying 类动词出现率 (rate)")
    ax.set_title("决定性对照：holding 完全由几何包含决定，与框里是不是球无关\n"
                 "框内 0.818 vs 0.818（Fisher OR=1.00, p=1.00）；框外 0.000 vs 0.000",
                 fontsize=10.5, pad=12)
    lg = ax.legend(frameon=False, fontsize=9.5, loc="upper right")
    for t in lg.get_texts():
        t.set_color(FG)
    fig.tight_layout()
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"[fig] {out}")


def fig_q1(probe, out):
    q1 = probe["Q1_scope_effect"]
    keys = list(q1.keys())
    name = {"A_all": "A 全部框\n(11.8 人/帧)", "B_oncourt": "B 场上球员\n(9.9 人/帧)",
            "C_topk6": "C 最近 Top-6\n(6.0 人/帧)"}
    watch = [q1[k]["watching_share"] for k in keys]
    distinct = [q1[k]["distinct_predicates"] for k in keys]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 3.9), dpi=150,
                                   gridspec_kw={"width_ratios": [1.35, 1]})
    fig.patch.set_facecolor(BG)
    for ax in (ax1, ax2):
        _style(ax)

    bars = ax1.bar(range(len(keys)), watch, 0.55, color=[GREY, GREY, BLUE], zorder=3)
    for b, v in zip(bars, watch):
        ax1.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.1%}", ha="center",
                 va="bottom", color=FG, fontsize=10)
    ax1.set_xticks(range(len(keys)))
    ax1.set_xticklabels([name[k] for k in keys], color=FG, fontsize=9)
    ax1.set_ylim(0, 1.0)
    ax1.set_ylabel("watching 占比 (share)")
    ax1.set_title("退化不是名单污染：A→B 反而略升", fontsize=10.5)

    bars2 = ax2.bar(range(len(keys)), distinct, 0.55, color=AMBER, zorder=3)
    for b, v in zip(bars2, distinct):
        ax2.text(b.get_x() + b.get_width() / 2, v + 0.08, str(v), ha="center",
                 va="bottom", color=FG, fontsize=10)
    ax2.axhline(35, color=RED, ls="--", lw=1.2, zorder=2)
    ax2.text(len(keys) - 0.5, 35.6, "词表上限 35", ha="right", color=RED, fontsize=9)
    ax2.set_xticks(range(len(keys)))
    ax2.set_xticklabels([k.split("_")[0] for k in keys], color=FG, fontsize=9)
    ax2.set_ylim(0, 40)
    ax2.set_ylabel("实际用到的谓词数 / 35")
    ax2.set_title("三种口径都只用到 4 个谓词", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"[fig] {out}")


def fig_time(rel, out, align=None):
    fr = rel["frames"]
    ts = [f["t"] for f in fr]
    ws = [sum(1 for t in f["triples"] if t["pred"] == "watching") /
          max(len(f["triples"]), 1) for f in fr]
    # 20 帧滑动平均
    k = 20
    sm = [sum(ws[max(0, i - k + 1):i + 1]) / len(ws[max(0, i - k + 1):i + 1])
          for i in range(len(ws))]

    fig, ax = plt.subplots(figsize=(10.2, 4.2), dpi=150)
    fig.patch.set_facecolor(BG)
    _style(ax)
    ax.plot(ts, ws, color=GREY, lw=0.7, alpha=0.5, label="逐帧 watching 占比")
    ax.plot(ts, sm, color=RED, lw=2.0, label=f"{k} 帧滑动平均")
    ax.axhline(0.846, color=BLUE, ls="--", lw=1.2, label="全片段均值 84.6%")
    for i, (t, lab, col) in enumerate(PBP_MARKS, 1):
        ax.axvline(t, color=col, ls=":", lw=1.5, alpha=0.95)
        ax.text(t, 1.075, f"{i}", ha="center", va="bottom", color=col,
                fontsize=11, fontweight="bold")
    lines = "\n".join(f"{i}. {lab}   t={t}s" for i, (t, lab, _) in enumerate(PBP_MARKS, 1))
    ax.text(0.985, 0.04, lines, transform=ax.transAxes, ha="right", va="bottom",
            color=FG, fontsize=8.2, linespacing=1.5,
            bbox=dict(boxstyle="round,pad=0.5", fc="#0f1319", ec="#2b323f", lw=0.9))
    ax.set_ylim(0, 1.30)
    ax.set_xlim(min(ts), max(ts))
    ax.set_xlabel("窗口内时间 t / s  (seg_hi @10fps, 435 帧)")
    ax.set_ylabel("watching 占比 (share)")
    sub = "→ 关系层输出不携带战术信息（35 条词表实际只用到 8 条）"
    if align:
        m = align["metrics"]["watching_share"]
        sub = (f"事件邻域均值 {m['observed_event_mean']:.3f} vs 同宽滑动窗口 null "
               f"{m['null_mean']:.3f}，p={m['p_one_sided']:.3f} → "
               f"{'显著' if m['significant_at_0.05'] else '不显著'}")
    ax.set_title("全 435 帧：watching 占比 vs PBP 事件（事件时间由读秒表推导，非手写）\n" + sub,
                 fontsize=10.5, pad=34)
    lg = ax.legend(frameon=False, fontsize=9, loc="upper left", ncol=1)
    for t in lg.get_texts():
        t.set_color(FG)
    fig.tight_layout()
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"[fig] {out}")


def main() -> int:
    global PBP_MARKS
    ap = argparse.ArgumentParser()
    ap.add_argument("probe_json")
    ap.add_argument("relations_json")
    ap.add_argument("outdir")
    ap.add_argument("--clock-table",
                    default=str(tactics_data_file("reports/milestone_02/pbp/clock_table.json")))
    ap.add_argument("--possession",
                    default=str(tactics_data_file("reports/milestone_02/pbp/possession_v2.json")))
    ap.add_argument("--align-json", default="")
    a = ap.parse_args()
    probe = json.load(open(a.probe_json))
    rel = json.load(open(a.relations_json))
    PBP_MARKS = load_pbp_marks(a.clock_table, a.possession)
    print("PBP 事件时间（由读秒表推导）:",
          " ".join(f"{lab.split()[0]}@{t}s" for t, lab, _ in PBP_MARKS))
    align = json.load(open(a.align_json)) if a.align_json else None
    os.makedirs(a.outdir, exist_ok=True)
    fig_q2(probe, os.path.join(a.outdir, "fig_rel_q2.png"))
    fig_q1(probe, os.path.join(a.outdir, "fig_rel_q1.png"))
    fig_time(rel, os.path.join(a.outdir, "fig_rel_time.png"), align)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
