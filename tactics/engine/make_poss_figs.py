#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1.5 图件：球权段时间线 / 有符号偏移 / 参数扫描热力图。

为什么必须有时间线图
--------------------
p 值只能说"整体是否对齐"，说不出**错在哪**。时间线图把每个窗口的
「检测到的持球者 track_id（色带）」与「PBP 事件（竖线）」画在同一条时间轴上，
一眼可见：切换点是落在事件上，还是落在两次事件之间的空档（= 检测器把
传球/贴身抖动误当换手）。

用法: make_poss_figs.py <poss_align.json> <outdir>
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import matplotlib

from common.nba_paths import tactics_data_file

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

sys.path.insert(0, str(Path(__file__).parent))
from poss_align import load_window, nearest  # noqa: E402

AW = Path(str(tactics_data_file("action_work")))

KIND_COLOR = {
    "Missed Shot": "#c0392b", "Made Shot": "#27ae60",
    "Rebound": "#2980b9", "Turnover": "#8e44ad",
    "Foul": "#e67e22", "Steal": "#16a085",
}


def setup_font():
    for name in ("Arial Unicode", "PingFang", "STHeiti"):
        for f in fm.findSystemFonts():
            if name in f:
                fm.fontManager.addfont(f)
                plt.rcParams["font.family"] = fm.FontProperties(fname=f).get_name()
                return name
    return None


def fig_timeline(wins, out):
    n = len(wins)
    fig, axes = plt.subplots(n, 1, figsize=(15, 2.5 * n), sharex=False)
    if n == 1:
        axes = [axes]
    for ax, w in zip(axes, wins):
        t0, dt = w["t0"], (w["t1"] - w["t0"]) / (w["n_frames"] - 1)
        ids = sorted({s["track_id"] for s in w["segments"]})
        cmap = plt.get_cmap("tab20")
        col = {tid: cmap(i % 20) for i, tid in enumerate(ids)}
        for s in w["segments"]:
            a = t0 + s["start"] * dt
            b = t0 + (s["end"] + 1) * dt
            ax.axvspan(a, b, color=col[s["track_id"]], alpha=0.85, lw=0)
        ax.set_ylim(0, 1)
        ax.set_yticks([])
        for e in w["events"]:
            c = KIND_COLOR.get(e["kind"], "#555")
            ax.axvline(e["t"], color=c, ls="--", lw=1.6)
            ax.text(e["t"], 1.02, f"{e['kind']}", rotation=90, fontsize=7,
                    va="bottom", ha="center", color=c)
        for cpt in w["changes"]:
            ax.plot(cpt, 0.5, marker="v", ms=9, color="k",
                    mec="w", mew=1.2, zorder=5)
        ax.set_xlim(w["t0"], w["t1"])
        ax.set_title(f"{w['name']}  t {w['t0']:.1f}–{w['t1']:.1f}s   "
                     f"球权段 {len(w['segments'])}  切换点 {len(w['changes'])}  "
                     f"覆盖 {w['coverage']*100:.0f}%  PBP {len(w['events'])}",
                     fontsize=10)
        ax.set_xlabel("影片时间 t (s)", fontsize=9)
    handles = [Line2D([0], [0], marker="v", color="k", ls="", ms=8,
                      label="检测到的换手点")]
    for k, c in KIND_COLOR.items():
        handles.append(Line2D([0], [0], color=c, ls="--", lw=1.6, label=k))
    fig.legend(handles=handles, loc="lower center", ncol=7, fontsize=8,
               frameon=False)
    fig.suptitle("球权段（色带=持球者 track_id） vs PBP 事件（竖线）  "
                 "▼=检测到的换手点", fontsize=12)
    fig.tight_layout(rect=(0, 0.06, 1, 0.97))
    p = out / "fig_poss_timeline.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def fig_offset(wins, hw, out):
    rows = []
    for w in wins:
        for e in w["events"]:
            if not w["changes"]:
                continue
            c = min(w["changes"], key=lambda z: abs(z - e["t"]))
            rows.append({"w": w["name"], "t": e["t"], "kind": e["kind"],
                         "signed": c - e["t"], "abs": abs(c - e["t"])})
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.2))
    ax[0].axvspan(-hw, hw, color="#27ae60", alpha=0.15)
    ax[0].axvline(0, color="k", lw=1)
    for r in rows:
        ax[0].plot(r["signed"], r["w"], marker="o", ms=7,
                   color=KIND_COLOR.get(r["kind"], "#555"), ls="")
    ax[0].set_xlabel("有符号偏移（换手点 − PBP 事件，s）", fontsize=9)
    ax[0].set_title(f"正=换手晚于事件；绿带=±{hw}s 命中窗", fontsize=10)
    ax[0].invert_yaxis()
    ax[0].grid(axis="x", alpha=0.3)

    ax[1].hist([r["abs"] for r in rows], bins=12, color="#34495e", alpha=.85)
    ax[1].axvline(hw, color="#c0392b", ls="--", label=f"half-win {hw}s")
    ax[1].set_xlabel("|Δt| (s)", fontsize=9)
    ax[1].set_ylabel("事件数", fontsize=9)
    ax[1].set_title("绝对距离分布", fontsize=10)
    ax[1].legend(fontsize=8)
    fig.suptitle(f"逐事件偏移（n={len(rows)}）", fontsize=12)
    fig.tight_layout()
    p = out / "fig_poss_offset.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p, rows


def fig_sweep(sweep, out):
    hws = sorted({c["half_win"] for c in sweep})
    hys = sorted({c["hyst"] for c in sweep})
    grid = {(c["half_win"], c["hyst"]): c for c in sweep}
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
    for a, key, title in ((ax[0], "p_hits", "p（命中数）"),
                          (ax[1], "p_dist", "p（平均距离）")):
        import numpy as np
        M = np.array([[grid[(h, y)][key] for h in hws] for y in hys])
        im = a.imshow(M, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
        a.set_xticks(range(len(hws)), [str(h) for h in hws])
        a.set_yticks(range(len(hys)), [str(y) for y in hys])
        a.set_xlabel("half-win (s)", fontsize=9)
        a.set_ylabel("hysteresis (帧)", fontsize=9)
        a.set_title(title + "　🟢<0.05 显著", fontsize=10)
        for i in range(len(hys)):
            for j in range(len(hws)):
                a.text(j, i, f"{M[i, j]:.3f}", ha="center", va="center",
                       fontsize=8)
        plt.colorbar(im, ax=a, fraction=.046)
    fig.suptitle("参数扫描：12 格全部 p>0.05 ⇒ 阴性对参数不敏感", fontsize=12)
    fig.tight_layout()
    p = out / "fig_poss_sweep.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def fig_support(diag_json, out):
    """判据 4：迟滞「冻结」诊断 —— 平滑段内有观测支撑的帧占比。"""
    d = json.loads(Path(diag_json).read_text())
    wins = list(d)
    hysts = sorted({int(h) for w in d.values() for h in w["per_hyst"]})
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.4))
    import numpy as np
    xs = np.arange(len(wins))
    wdt = 0.26
    cols = ["#c0392b", "#e67e22", "#2980b9"]
    for i, h in enumerate(hysts):
        v = [d[w]["per_hyst"][str(h)]["support_share"] for w in wins]
        b = ax[0].bar(xs + (i - 1) * wdt, v, wdt, label=f"hyst={h}",
                      color=cols[i % 3])
        ax[0].bar_label(b, fmt="%.2f", fontsize=7, padding=1)
    ax[0].axhline(0.8, color="k", ls=":", lw=1)
    ax[0].text(len(wins) - 0.5, 0.815, "可接受下界 0.8", fontsize=7, ha="right")
    ax[0].set_xticks(xs, wins)
    ax[0].set_ylim(0, 1.05)
    ax[0].set_ylabel("有观测支撑帧占比", fontsize=9)
    ax[0].set_title("判据4：平滑段内 raw==该 ID 的帧占比", fontsize=10)
    ax[0].legend(fontsize=8)
    ax[0].grid(axis="y", alpha=0.3)

    # 右图：w1 最长段（hyst=10, id=206, 20.2s）的支撑日历
    import sys as _s
    _s.path.insert(0, str(Path(__file__).parent))
    from poss_align import assign as _asg
    from poss_align import hysteresis, rle
    tr = json.loads((AW / "w1_poss" / "ball_tracks.json").read_text())
    diag = (1920 ** 2 + 1080 ** 2) ** 0.5
    raw = [_asg(fr["ball"]["bbox"], fr.get("players", []), 0.035, diag)
           if (fr.get("ball") and "bbox" in fr["ball"]) else None for fr in tr]
    sm = hysteresis(raw, 10)
    segs = rle(sm)
    lg = max(segs, key=lambda s: s["n"])
    t0 = 204.5
    sup = [1 if raw[i] == lg["track_id"] else 0
           for i in range(lg["start"], lg["end"] + 1)]
    ax[1].imshow([sup], aspect="auto", cmap="RdYlGn",
                 extent=[t0 + lg["start"] * 0.1, t0 + (lg["end"] + 1) * 0.1, 0, 1])
    ax[1].set_yticks([])
    ax[1].set_xlabel("影片时间 t (s)", fontsize=9)
    n_sup = sum(sup)
    ax[1].set_title(f"w1 最长段 id={lg['track_id']}  {lg['n']*0.1:.1f}s："
                    f"仅 {n_sup}/{lg['n']} 帧({100*n_sup/lg['n']:.0f}%)有支撑\t"
                    f"🟩=raw 确为该 ID　🟥=冻结", fontsize=9)
    fig.suptitle("迟滞不是平滑，而是冻结：hyst 越大，「球权段」越是凭空延长",
                 fontsize=12)
    fig.tight_layout()
    p = out / "fig_poss_support.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("align_json")
    ap.add_argument("outdir")
    ap.add_argument("--diag", default="action_work/poss_diag.json")
    a = ap.parse_args()
    setup_font()
    d = json.loads(Path(a.align_json).read_text())
    diag = (1920 ** 2 + 1080 ** 2) ** 0.5
    wins = [load_window(n, d["radius"], d["hyst"], diag) for n in d["windows"]]
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    p1 = fig_timeline(wins, out)
    p2, rows = fig_offset(wins, d["main"]["half_win"], out)
    p3 = fig_sweep(d["sweep"], out) if d.get("sweep") else None
    p4 = fig_support(a.diag, out) if Path(a.diag).exists() else None
    (out / "offsets.json").write_text(json.dumps(rows, indent=1,
                                                 ensure_ascii=False))
    print("[图]", p1)
    print("[图]", p2)
    if p3:
        print("[图]", p3)
    if p4:
        print("[图]", p4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
