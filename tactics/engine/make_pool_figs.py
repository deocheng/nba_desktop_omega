#!/usr/bin/env python3
"""扩样本可视化：逐窗口时间线 + 池化 null 直方图 + 参数扫描显著性网格。

输入：
  action_work/w{1,2,3,4}/pose_motion.json
  action_work/pooled.json
输出（深色主题，便于嵌入 HTML 报告）：
  action_work/fig_windows.png          2×2 逐窗口时间线
  action_work/fig_pooled.png           左：池化 null 直方图+observed；右：扫描 p 值网格
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import glob
import json
import os

import matplotlib

from common.nba_paths import tactics_data_file

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

# 注册含 CJK 的字体，避免中文标题变成方框
for _fp in ("/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"):
    if os.path.exists(_fp):
        fm.fontManager.addfont(_fp)
        plt.rcParams["font.family"] = fm.FontProperties(
            fname=_fp).get_name()
        break

import matplotlib.pyplot as plt  # noqa: E402  (re-import 应用 font.family)
from matplotlib.patches import Patch

AW = str(tactics_data_file("action_work"))

# ---------- 深色主题 ----------
plt.rcParams.update({
    "figure.facecolor": "#0e1117",
    "axes.facecolor": "#0e1117",
    "axes.edgecolor": "#3a4250",
    "axes.labelcolor": "#c9d1d9",
    "axes.titlecolor": "#e6edf3",
    "xtick.color": "#8b949e",
    "ytick.color": "#8b949e",
    "text.color": "#c9d1d9",
    "grid.color": "#21262d",
    "font.size": 10,
})

KIND_COLOR = {
    "Missed Shot": "#f85149", "Made Shot": "#3fb950", "Rebound": "#58a6ff",
    "Turnover": "#d29922", "Foul": "#bc8cff", "Block": "#39c5cf",
    "Free Throw": "#db61a2", "Jump Ball": "#a371f7", "Violation": "#e3b341",
}


def load_win(path):
    d = json.load(open(path))
    return d


def fig_windows():
    wins = sorted(glob.glob(f"{AW}/w?/pose_motion.json"))
    names = [w.split("/")[-2] for w in wins]
    fig, axes = plt.subplots(2, 2, figsize=(14, 8.5), sharex=False)
    axes = axes.ravel()
    for ax, path, name in zip(axes, wins, names):
        d = load_win(path)
        series = d["series"]
        ts = [s["t"] for s in series]
        air = [s["max_air"] if s["max_air"] is not None else 0.0 for s in series]
        ax.plot(ts, air, color="#39d0d8", lw=1.0, alpha=0.85,
                label="max air_dyn (去趋势)")
        # 跳跃峰
        for j in d["jumps"]:
            ax.scatter([j["t"]], [j["air_dyn"]], color="#f85149", s=26,
                       zorder=5, edgecolor="white", lw=0.3)
        # PBP 事件
        for e in d["events"]:
            c = KIND_COLOR.get(e["kind"], "#8b949e")
            ax.axvline(e["t"], color=c, lw=1.3, alpha=0.85, zorder=3)
            ax.text(e["t"], 0.42, f"{e['clock']:.0f}", rotation=90,
                    color=c, fontsize=7, va="bottom", ha="right")
        # 命中标注
        for wd in d.get("alignment", {}):
            pass
        # 统计文本
        al = d["alignment"]["jumps"]
        ax.set_title(f"{name}  t {ts[0]:.0f}–{ts[-1]:.0f}s  "
                     f"跳跃 {d['counts']['n_jumps']}  "
                     f"对齐 {al['observed_hits']}/{len(d['events'])}  p={al['p_value']:.3f}",
                     fontsize=10)
        ax.set_xlabel("影片时间 t (s)")
        ax.set_ylabel("air_dyn")
        ax.set_ylim(0, max(0.5, max(air) * 1.1))
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=7, framealpha=0.6)
    # 全局图例（事件类型）
    handles = [Patch(facecolor=c, label=k) for k, c in KIND_COLOR.items()]
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=8,
               frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("扩样本四窗口：姿态 air_dyn 曲线 vs PBP 事件时刻（红线=跳跃峰，竖线=PBP 事件）",
                 fontsize=13, color="#e6edf3")
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])
    out = f"{AW}/fig_windows.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"[out] {out}")
    return out


def fig_pooled():
    pooled = json.load(open(f"{AW}/pooled.json"))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # ---- 左：池化 null 直方图 + observed ----
    # 重算 null 分布（从 pooled 没有存 null 数组，这里用 pooled_perm 复现）
    import random
    import statistics
    wins = [json.load(open(p)) for p in
            sorted(glob.glob(f"{AW}/w?/pose_motion.json"))]
    # 重新载入为 load_window 结构
    from pose_pool_align import hit_stat, load_window, pooled_perm
    ww = [load_window(p) for p in sorted(glob.glob(f"{AW}/w?/pose_motion.json"))]
    hw = pooled["half_win"]
    r = pooled_perm(ww, "jumps", hw, pooled["n_perm"], seed=20260924)
    null = []
    rnd = random.Random(20260924)
    for _ in range(pooled["n_perm"]):
        tot = 0
        for w in ww:
            W = w["t1"] - w["t0"]
            d = rnd.uniform(-W / 2, W / 2)
            js = [(j["t"] - w["t0"] + d) % W + w["t0"] for j in w["jumps"]]
            tot += hit_stat(w["events"], js, hw)
        null.append(tot)
    ax1.hist(null, bins=30, color="#30527a", edgecolor="#58a6ff", alpha=0.8)
    ax1.axvline(r["observed_hits"], color="#f85149", lw=2.2,
                label=f"observed = {r['observed_hits']}")
    ax1.axvline(r["null_mean"], color="#e3b341", lw=1.6, ls="--",
                label=f"null 均值 = {r['null_mean']}")
    ax1.set_title(f"池化置换检验（跳跃，±{hw}s）\nobserved {r['observed_hits']}/{r['n_events']}  "
                  f"p={r['p_value']:.4f}  {'显著' if r['p_value']<0.05 else '不显著'}",
                  fontsize=11)
    ax1.set_xlabel("命中数（16 个 PBP 事件中，±1.5s 内存在跳跃的事件数）")
    ax1.set_ylabel("置换次数")
    ax1.legend(fontsize=9)

    # ---- 右：参数扫描 p 值网格 ----
    sweep = pooled.get("sweep", {})
    cells = sweep.get("cells", [])
    if cells:
        hws = sorted({c["half_win"] for c in cells})
        airs = sorted({c["air"] for c in cells})
        grid = [[None] * len(airs) for _ in hws]
        for c in cells:
            i = hws.index(c["half_win"]); j = airs.index(c["air"])
            grid[i][j] = c["p_value"]
        import numpy as np
        g = np.array([[0 if v is None else v for v in row] for row in grid])
        im = ax2.imshow(g, cmap="RdYlGn_r", vmin=0, vmax=0.5, aspect="auto")
        ax2.set_xticks(range(len(airs))); ax2.set_xticklabels([f"air≥{a}" for a in airs])
        ax2.set_yticks(range(len(hws))); ax2.set_yticklabels([f"±{h}s" for h in hws])
        for i in range(len(hws)):
            for j in range(len(airs)):
                v = g[i, j]
                ax2.text(j, i, f"{v:.3f}", ha="center", va="center",
                         color="white" if v < 0.25 else "#0e1117", fontsize=9)
        ax2.set_title(f"参数扫描 p 值网格\n{sweep.get('n_significant',0)}/{sweep.get('n_cells',0)} 格显著"
                      f"（比例 {sweep.get('significant_share',0):.3f}）", fontsize=11)
        ax2.set_xlabel("air 阈值"); ax2.set_ylabel("half-win")
        fig.colorbar(im, ax=ax2, fraction=0.046, pad=0.04, label="p")
    else:
        ax2.text(0.5, 0.5, "无扫描数据", ha="center", va="center")

    fig.suptitle("跨窗口池化对齐检验 + 参数扫描稳健性（reach 固定 0.10）",
                 fontsize=13, color="#e6edf3")
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    out = f"{AW}/fig_pooled.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"[out] {out}")
    return out


if __name__ == "__main__":
    fig_windows()
    fig_pooled()
    print("done")
