#!/usr/bin/env python3
"""A5.7c 一张图看清两件事：①71% 的轨迹不在场上 ②换人/同一人的位移区间重叠。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import matplotlib

from common.nba_paths import tactics_data_file

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(str(tactics_data_file("")))
JD = ROOT / "action_work" / "track_judge"
for fp in ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"]:
    if Path(fp).exists():
        font_manager.fontManager.addfont(fp)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

gate = json.load(open(JD / "courtgate_all38.json"))
disp = json.load(open(JD / "switch_displacement.json"))
verd = json.load(open(JD / "verdicts_ep24_s1.json"))["rows"]

fig, axes = plt.subplots(1, 3, figsize=(19, 6.2))
fig.suptitle("A5.7  跟踪错误根因：71% 的跟踪目标不在场上；换人与同一人的位移区间重叠",
             fontsize=17, fontweight="bold")

# --- A. on_frac 排序条形 ---
ax = axes[0]
g = sorted(gate, key=lambda r: r["on_frac"])
cols = ["#d62728" if r["on_frac"] < 0.5 else "#2ca02c" for r in g]
ax.bar(range(len(g)), [r["on_frac"] for r in g], color=cols, width=0.82)
ax.axhline(0.5, color="k", ls="--", lw=1.6)
ax.text(len(g) * 0.5, 0.53, "0.5 门", fontsize=11)
ax.annotate("27/38 = 71%\n基本不在场上", xy=(13, 0.12), xytext=(9, 0.72),
            fontsize=12, color="#d62728",
            arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.6))
ax.annotate("gap 仅 0.027\n(0.473 vs 0.500)", xy=(26.5, 0.49), xytext=(17.5, 0.83),
            fontsize=11, color="#8c564b",
            arrowprops=dict(arrowstyle="->", color="#8c564b", lw=1.4))
ax.set_title("① 全 38 条轨迹：脚点落在球场掩膜内的帧占比\n(on_frac)", fontsize=13)
ax.set_xlabel("轨迹（按 on_frac 升序）")
ax.set_ylabel("on_frac")
ax.set_ylim(0, 1.12)
ax.grid(axis="y", alpha=0.25)

# --- B. 位移对照 ---
ax = axes[1]
data = [disp["same"], disp["switch"]]
bp = ax.boxplot(data, tick_labels=["同一人\n(n=23)", "换人\n(n=14)"], widths=0.5,
                patch_artist=True, showfliers=True)
for p, c in zip(bp["boxes"], ["#2ca02c", "#d62728"]):
    p.set_facecolor(c)
    p.set_alpha(0.45)
for y, c, lab in [(disp["same"][-1], "#2ca02c", f"同一人最大 {disp['same'][-1]:.0f}px"),
                  (disp["switch"][0], "#d62728", f"换人最小 {disp['switch'][0]:.0f}px")]:
    ax.axhline(y, color=c, ls=":", lw=1.8)
    ax.text(2.42, y, lab, fontsize=10, color=c, va="center")
ax.axhspan(disp["switch"][0], disp["same"][-1], color="gray", alpha=0.18)
ax.text(1.5, 60, "重叠带 34–178px\n任何阈值都分不开", fontsize=11.5,
        ha="center", color="#444")
ax.set_yscale("log")
ax.set_ylabel("脚点位移 (px, 对数轴)")
ax.set_title("② 换人切换点 vs 同一人相邻帧的位移\n（300px 门只抓到 5/14 次换人）", fontsize=13)
ax.grid(axis="y", alpha=0.25)

# --- C. ep24_s1 8 条裁定命中 ---
ax = axes[2]
ax.axis("off")
rows = sorted(verd, key=lambda r: r["key"])
ax.set_title("③ ep24_s1 八条：自动预判 vs 老程裁定", fontsize=13)
ax.text(0.0, 0.965, "条目", fontsize=12, fontweight="bold", transform=ax.transAxes)
ax.text(0.32, 0.965, "自动预判", fontsize=12, fontweight="bold", transform=ax.transAxes)
ax.text(0.64, 0.965, "老程裁定", fontsize=12, fontweight="bold", transform=ax.transAxes)
ax.text(0.88, 0.965, "", fontsize=12, transform=ax.transAxes)
y = 0.895
for r in rows:
    ok = r["hit"]
    ax.text(0.0, y, r["key"].replace("ep24_s1", "…"), fontsize=10.5, transform=ax.transAxes)
    ax.text(0.30, y, r["auto"], fontsize=10.5, transform=ax.transAxes, color="#666")
    ax.text(0.64, y, r["verdict"], fontsize=10.5, transform=ax.transAxes,
            color="#2ca02c" if r["verdict"] == "同一人" else "#d62728")
    ax.text(0.88, y, "命中" if ok else "错", fontsize=13, transform=ax.transAxes)
    y -= 0.092
ax.text(0.0, y - 0.03, "命中 3/8 = 37.5%", fontsize=13, fontweight="bold",
        transform=ax.transAxes, color="#d62728")
ax.text(0.0, y - 0.115, "「无大跳 -> 同一人」 只有 1/6 -> 判据作废", fontsize=11.5,
        transform=ax.transAxes, color="#d62728")
ax.text(0.0, y - 0.21, "8 条里仅 1 条是场上球员，", fontsize=11.5, transform=ax.transAxes)
ax.text(0.0, y - 0.275, "7 条是观众 / 替补席 / 教练", fontsize=11.5, transform=ax.transAxes)

out = JD / "hires" / "A5_7_rootcause_summary.png"
fig.tight_layout(rect=[0, 0, 1, 0.93])
fig.savefig(out, dpi=130, facecolor="white")
print("saved", out)
