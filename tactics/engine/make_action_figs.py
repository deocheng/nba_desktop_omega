#!/usr/bin/env python3
"""姿态动作层图：① 骨架起跳信号 vs PBP 事件　② 参数扫描的 p 值全景。

第一张图的目的不是"展示成果"，而是让读者一眼看出：
    起跳信号确实在出手/篮板/上篮封盖附近抬起来（物理上说得通），
    但整段基线也在动，**单看曲线无法判定这是不是巧合**。
第二张图是决定性的：15 个参数格只有 1 格 p<0.05。

用法: make_action_figs.py <pose_motion.json> <sweep.json> <clock_table.json> <outdir>
"""
from __future__ import annotations

import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

BG = "#12151c"
PANEL = "#1a1f29"
FG = "#e6e9ef"
DIM = "#8b93a3"
RED = "#e5484d"
GREEN = "#3fb950"
BLUE = "#4c8dff"
AMBER = "#e3b341"
GREY = "#6e7681"
PURPLE = "#a371f7"
PAL = [RED, BLUE, AMBER, GREEN, PURPLE]


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


def fig_timeline(pm, out):
    ser = pm["series"]
    ts = [z["t"] for z in ser]
    air = [z["max_air"] for z in ser]
    evs = pm["events"]
    jumps = pm["jumps"]
    al = pm["alignment"]["jumps"]

    fig, ax = plt.subplots(figsize=(10.2, 4.3), dpi=150)
    fig.patch.set_facecolor(BG)
    _style(ax)
    ax.plot(ts, air, color=BLUE, lw=0.9, alpha=0.75,
            label="逐帧最大 air_dyn（骨架相对近期姿态的抬脚量）")
    ax.axhline(0, color=GREY, lw=0.8, ls="-", alpha=0.6)
    for j in jumps:
        ax.plot([j["t"]], [j["air_dyn"]], "v", color=RED, ms=11, zorder=5)
    ax.plot([], [], "v", color=RED, ms=11, label=f"检出的起跳事件（{len(jumps)} 次）")
    ymax = 1.05
    for i, e in enumerate(evs):
        col = PAL[i % len(PAL)]
        ax.axvline(e["t"], color=col, ls=":", lw=1.5, alpha=0.95)
        ax.text(e["t"], ymax, f"{i + 1}", ha="center", va="bottom", color=col,
                fontsize=11, fontweight="bold")
    lines = "\n".join(f"{i + 1}. {e['player']} {e['kind']}   t={e['t']}s"
                      for i, e in enumerate(evs))
    ax.text(0.985, 0.05, lines, transform=ax.transAxes, ha="right", va="bottom",
            color=FG, fontsize=8.2, linespacing=1.5,
            bbox=dict(boxstyle="round,pad=0.5", fc="#0f1319", ec="#2b323f", lw=0.9))
    ax.set_ylim(-0.45, 1.30)
    ax.set_xlim(min(ts), max(ts))
    ax.set_xlabel("窗口内时间 t / s  (seg_hi @10fps, 435 帧)")
    ax.set_ylabel("air_dyn（除以框高，无量纲）")
    ax.set_title(
        "YOLO11n-pose 骨架起跳信号 vs PBP 事件（事件时间由读秒表推导）\n"
        f"命中 {al['observed_hits']}/5 个事件邻域，循环平移 null 均值 {al['null_mean']}，"
        f"p={al['p_value']:.4f} —— 但见下一张图：参数扫描后不稳健",
        fontsize=10.5, pad=26)
    lg = ax.legend(frameon=False, fontsize=8.8, loc="upper left")
    for t in lg.get_texts():
        t.set_color(FG)
    fig.tight_layout()
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"[fig] {out}")


def fig_sweep(sw, out):
    rows = sw["rows"]
    hws = sorted({r["half_win"] for r in rows})
    airs = sorted({r["air_thr"] for r in rows})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 4.0), dpi=150,
                                   gridspec_kw={"width_ratios": [1.5, 1]})
    fig.patch.set_facecolor(BG)
    for ax in (ax1, ax2):
        _style(ax)

    w = 0.26
    for k, air in enumerate(airs):
        ys = [next(r["p_jumps"] for r in rows
                   if r["half_win"] == hw and r["air_thr"] == air) for hw in hws]
        ns = [next(r["n_jumps"] for r in rows
                   if r["half_win"] == hw and r["air_thr"] == air) for hw in hws]
        xs = [i + (k - 1) * w for i in range(len(hws))]
        bars = ax1.bar(xs, ys, w, color=PAL[k], zorder=3,
                       label=f"air 阈值 {air}")
        for i, (b, v, n) in enumerate(zip(bars, ys, ns)):
            off = 0.015 + (0.075 if k == 2 else 0.0) + (0.038 if k == 1 else 0.0)
            ax1.text(b.get_x() + b.get_width() / 2, v + off, f"{v:.3f}\nn={n}",
                     ha="center", va="bottom", color=FG, fontsize=7.6)
    ax1.axhline(0.05, color=RED, ls="--", lw=1.3, zorder=2)
    ax1.text(len(hws) - 0.45, 0.062, "α = 0.05", color=RED, fontsize=9)
    ax1.set_xticks(range(len(hws)))
    ax1.set_xticklabels([f"±{h}s" for h in hws], color=FG, fontsize=9.5)
    ax1.set_ylim(0, 0.92)
    ax1.set_ylabel("对齐检验 p 值")
    ax1.set_xlabel("事件邻域半宽")
    s = sw["summary"]
    ax1.set_title(f"15 个参数格里只有 1 格 p<0.05\n"
                  f"（{s['n_significant']}/{s['n_cells']} = {s['significant_share']:.3f}，"
                  f"α=0.05 下期望 {s['expected_share_under_alpha0.05']}）",
                  fontsize=10.3)
    lg = ax1.legend(frameon=False, fontsize=8.8, loc="upper left")
    for t in lg.get_texts():
        t.set_color(FG)

    cats = ["显著格数", "α=0.05 期望格数"]
    vals = [s["n_significant"], s["n_cells"] * s["expected_share_under_alpha0.05"]]
    bars = ax2.bar(cats, vals, 0.5, color=[AMBER, GREY], zorder=3)
    for b, v in zip(bars, vals):
        ax2.text(b.get_x() + b.get_width() / 2, v + 0.05, f"{v:.2f}", ha="center",
                 va="bottom", color=FG, fontsize=11)
    ax2.set_ylim(0, max(3, max(vals) * 1.5))
    ax2.set_ylabel("格数 / 共 15 格")
    ax2.set_title("观测显著数 ≈ 偶然期望数\n→ 不能宣称「骨架动作能解释战术事件」",
                  fontsize=10.3)
    fig.tight_layout()
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"[fig] {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pose_motion_json")
    ap.add_argument("sweep_json")
    ap.add_argument("outdir")
    a = ap.parse_args()
    pm = json.load(open(a.pose_motion_json))
    sw = json.load(open(a.sweep_json))
    os.makedirs(a.outdir, exist_ok=True)
    fig_timeline(pm, os.path.join(a.outdir, "fig_pose_timeline.png"))
    fig_sweep(sw, os.path.join(a.outdir, "fig_pose_sweep.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
