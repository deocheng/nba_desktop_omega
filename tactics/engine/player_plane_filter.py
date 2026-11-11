#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""player_plane_filter.py — R4 污染过滤（核心 = 球场平面透视一致性）。

为什么是这个判据（前三个候选的实测否证记录）
--------------------------------------------
- ❌ **球场 footprint 颜色掩膜**（`geom_floor_poly` / `geom_floor_region`）：
  TOR 主场调参 → HOU 球场是黑+红+木三色，掩膜只剩木色（floor 30.1%），
  实测 w1 f00001 在 x=186 处"上边线"=631 而真实远端边线≈409（**低估 220px**）
  ⇒ 用它做"越界剔除"在 sas_hou f00001 上**误删 3 名场内球员**（t3/t9/t11，放大图已证）。
- ❌ **纯身高阈值**：w1 近端场边观众离镜头近 ⇒ 框高可达 **216~241px**，与远场球员同量级；
  各域 foot_y∈[900,1080] 全区间都混着 h∈[150,380] 的框（实测无间隙）⇒ 不可分。
- ❌ **静态性**（track 位移）：ball_tracks 的 track_id 在观众区频繁跳号 ⇒ 观众 span 可达 947px，
  信号被 ID 跳变吃掉。
- ❌ **镜动残差**（换算全局光流后的框内残差）：**持球站定的球员残差仅 1.69px**，
  而某观众 5.60px ⇒ 混叠（站着不动的人与坐着的人在"自主动作"上无区别）。
- ✅ **球场平面透视一致性**：地面平面上身高固定者满足 `h = A·y_foot + B`（见下推导），
  **比同行平面预期矮很多** ⇒ 该人比球场更远 ⇒ 看台/场边后排。

推导（为什么是仿射）
--------------------
针孔投影：`y_foot = c + k/Z`（Z=人所在距离），`y_head = c + k(h_cam-H)/Z`，
故 `h = y_foot - y_head = k·H/Z = (H/h_cam)·(y_foot - c)` ⇒ **h 对 y_foot 严格仿射**。

锚点（如何拿到"一定在场上"的样本）
----------------------------------
球被 7/7 门禁验证过（`gate_tracked_recalib.json`），且 A4.18 已验 `poss_track_id`（几何最近球员）
与真持球者一致。故**取「距球框 ≤ anchor_radius 的框」+ 持球者框为锚点**（必在场上）。
逐帧窗口内（默认 ±45 帧，近似同一机位）用**迭代最小二乘 + 残差裁剪**稳健拟合 A、B。

判据
----
`rel = (h - (A·y_foot + B)) / (A·y_foot + B)`。
**单边**剔除：仅当 `rel < -thr`（人明显比平面预期矮=更远）才剔除；
`rel > 0`（比平面更近，如站在近端边线外/更靠镜头）**一律保留**——该方向天然保守。
`A <= A_MIN`（拟合退化）或锚点不足 ⇒ 该帧 **plane_ok=0，不做任何剔除**（宁漏不误杀）。

硬保护（P0）
------------
① 持球者：任一帧为 `poss_track_id` ⇒ **整条轨迹全程保护**；
② 近球框：与球框距离 ≤ `POSS_RADIUS`(88.1px) ⇒ 保护。

用法
    python engine/player_plane_filter.py --all-clips
    python engine/player_plane_filter.py --clip w1 --thr 0.30 --win 45
    python engine/player_plane_filter.py --report          # 打印已目视确认的标签子集
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
OUT = AW / "validate"
DIAG = (1920.0 ** 2 + 1080.0 ** 2) ** 0.5
POSS_RADIUS = round(0.04 * DIAG, 1)      # 88.1px
P0_GUARD = -0.55         # P0 豁免闸门：轨迹/框 rel 低于此值 ⇒ 「持球者/近球」标签本身不可信，不豁免
#   ↑ 数值取自 P3 的 strict 阈值，一致口径；实测被它拦下的框 rel 中位 −0.57…−0.70，
#     其中 >99% 是近端看台成排坐着的观众（目视验收 band_w1_y80_h170.jpg 20/20）。
ANCHOR_RADIUS = 200.0
ANCHOR_HMIN = 100.0
A_MIN = 0.02
MIN_ANCHORS = 8
THR_DEFAULT = 0.30
HI_THR = 0.30            # 看台上界（轨迹级 rel 中位）
HI_HMAX_FRAC = 0.20      # P4 身高上界：>0.20*H(=216px) 的框一律不受 P4 约束
#   ↑ 实测依据：被抬高的看台观众 h≈177~206px；而**并框放大的场内球员** h≥321px
#     （w1 f00098 t811 = 白球衣 #30，框覆盖两人，h=321，rel=+0.38）。
#     加此上界后 w1 仍能删掉 t9/t14/t25/t1587，而并框球员与 sas_hou 的 h≥398 巨框不再被删。
DBALL_HI_GUARD = 150.0   # P4 附加保护：轨迹全程离球 < 该值则不动
WIN_DEFAULT = 45
HMIN = {"w1": 70.0, "w2": 70.0, "w3": 70.0, "w4": 70.0,
        "sas_hou": 120.0, "sas_nop": 120.0, "sas_det": 120.0}
HMIN_DEFAULT = 80.0


def rect_dist(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def robust_fit(fy, h, rounds=3, clip_frac=1.5):
    """迭代最小二乘 + 残差裁剪（鲁棒仿射）。返回 (A, B, n_used, rms)。"""
    fy = np.asarray(fy, float)
    h = np.asarray(h, float)
    m = np.ones(len(fy), bool)
    A = B = 0.0
    for _ in range(rounds):
        if m.sum() < 4:
            break
        A, B = np.polyfit(fy[m], h[m], 1)
        r = h - (A * fy + B)
        s = np.median(np.abs(r[m])) * 1.4826 + 1e-6
        m = np.abs(r) < clip_frac * max(s, 6.0)
    r = h - (A * fy + B)
    return float(A), float(B), int(m.sum()), float(np.sqrt(np.mean(r[m] ** 2))) if m.sum() else float("nan")


# ── 拟合可靠度闸门（本轮关键修正） ──────────────────────────────────────
# 实测教训：`sas_*` 有 92% 的帧**锚点数为 0**（球只在 ~8% 帧被解出），
# `sas_nop` 全片仅 74 个锚点、足点跨度 261px ⇒ ±45 帧窗口凑够 8 点就宣布"可用"，
# 但**杠杆臂太短** ⇒ 拟合出 A=0.371（对比 w1 的 0.234）⇒ 系统性高估 pred ⇒
# 34.1% 的框被删（含 h 中位 298、111 框的疑似真球员轨迹）。
# 故新增三重闸门：① 锚点数；② 足点跨度（杠杆臂）；③ **留出验证**（半训半测，
# 直接检验"这组锚点推出来的平面能不能预测没见过的锚点"）。
MIN_SPAN = 200.0        # 锚点足点 p95-p5 下限
HOLDOUT_MAX = 0.25      # 留出集 |rel| 中位上限
MIN_ANCHORS_CLIP = 30


def load_recs(clip, suffix="_poss_tile"):
    p = AW / f"{clip}{suffix}" / "ball_tracks.json"
    return json.loads(p.read_text()) if p.exists() else None


def fit_with_holdout(fy, h, fidx=None, min_n=12, min_span=MIN_SPAN, holdout_max=HOLDOUT_MAX):
    """半训半测的鲁棒仿射拟合。返回 dict。

    切分按**帧序**而非点序，避免同帧锚点跨集导致的信息泄漏。
    """
    fy = np.asarray(fy, float)
    h = np.asarray(h, float)
    n = len(fy)
    if n < min_n:
        return {"ok": 0, "why": f"n<{min_n}"}
    span = float(np.percentile(fy, 95) - np.percentile(fy, 5))
    if span < min_span:
        return {"ok": 0, "why": f"span<{min_span:.0f}({span:.0f})"}
    if fidx is None:
        m1 = np.arange(n) % 2 == 0
    else:
        fidx = np.asarray(fidx)
        m1 = fidx % 2 == 0
    if m1.sum() < 5 or (~m1).sum() < 5:
        return {"ok": 0, "why": "holdout_split_too_small"}
    A1, B1, _, _ = robust_fit(fy[m1], h[m1])
    if A1 < A_MIN:
        return {"ok": 0, "why": f"A1<{A_MIN}"}
    p = A1 * fy[~m1] + B1
    ok_ = p > 1
    if ok_.sum() < 4:
        return {"ok": 0, "why": "holdout_pred_invalid"}
    err = float(np.median(np.abs((h[~m1][ok_] - p[ok_]) / p[ok_])))
    if err > holdout_max:
        return {"ok": 0, "why": f"holdout_err={err:.3f}", "err": round(err, 3)}
    A, B, nu, rms = robust_fit(fy, h)
    if A < A_MIN:
        return {"ok": 0, "why": f"A<{A_MIN}"}
    return {"ok": 1, "A": A, "B": B, "n": nu, "rms": round(rms, 1),
            "span": round(span, 0), "holdout": round(err, 3), "src": None}


def anchors_of(recs, radius=ANCHOR_RADIUS, hmin=ANCHOR_HMIN):
    """逐帧锚点：距球框 ≤ radius 的框（必在场上）+ 持球者框。"""
    per = []
    for r in recs:
        ball = r.get("ball")
        bb = ball.get("bbox") if ball else None
        a = []
        for pl in r.get("players", []):
            x1, y1, x2, y2 = pl["bbox"]
            h = y2 - y1
            if h < hmin:
                continue
            if bb is not None and rect_dist(pl["bbox"], bb) <= radius:
                a.append((y2, h))
            elif r.get("poss_track_id") is not None and pl["track_id"] == r.get("poss_track_id"):
                a.append((y2, h))
        per.append(a)
    return per


def plane_for_windows(recs, win=WIN_DEFAULT, win_min_n=12, allow_clip_fallback=True):
    """逐帧平面：优先**窗口拟合**（近似同机位），不可靠则回退**片段级拟合**，再不可靠则 plane_ok=0。

    返回 list of dict：{ok, A, B, n, rms, span, holdout, src}
    """
    n = len(recs)
    per = anchors_of(recs)
    allfy = [p[0] for a in per for p in a]
    allhh = [p[1] for a in per for p in a]
    allfi = [i for i, a in enumerate(per) for _ in a]
    clipfit = fit_with_holdout(allfy, allhh, allfi, min_n=MIN_ANCHORS_CLIP) \
        if (allow_clip_fallback and len(allfy) >= MIN_ANCHORS_CLIP) else {"ok": 0, "why": "clip_n<30"}
    if clipfit.get("ok"):
        clipfit = dict(clipfit, src="clip")

    out = []
    for i in range(n):
        lo, hi = max(0, i - win), min(n, i + win + 1)
        fy, hh, fi = [], [], []
        for j in range(lo, hi):
            for p in per[j]:
                fy.append(p[0])
                hh.append(p[1])
                fi.append(j)
        wf = fit_with_holdout(fy, hh, fi, min_n=win_min_n)
        if wf.get("ok"):
            out.append(dict(wf, src="win"))
        elif clipfit.get("ok"):
            out.append(dict(clipfit))
        else:
            out.append({"ok": 0, "why": wf.get("why", "no_fit"), "src": "none"})
    return out



def analyze(clip, suffix="_poss_tile", thr=THR_DEFAULT, win=WIN_DEFAULT,
            hmin=None, use_hmin=True, strict=-0.55, min_track_boxes=3,
            use_stands=True, hi_thr=HI_THR, min_stands_boxes=5,
            dball_hi_guard=DBALL_HI_GUARD, hi_hmax_frac=HI_HMAX_FRAC):
    recs = load_recs(clip, suffix)
    if recs is None:
        raise SystemExit(f"[缺数据] {clip}{suffix}/ball_tracks.json")
    hmin = HMIN.get(clip, HMIN_DEFAULT) if hmin is None else hmin
    planes = plane_for_windows(recs, win)

    # 持球者轨迹全程保护
    prot_tracks = set()
    for r in recs:
        if r.get("poss_track_id") is not None:
            prot_tracks.add(r["poss_track_id"])

    rows = []
    for i, r in enumerate(recs):
        pl_ = planes[i]
        A, B, ok = pl_.get("A", 0.0), pl_.get("B", 0.0), pl_.get("ok", 0)
        na, rms = pl_.get("n", 0), pl_.get("rms", float("nan"))
        ball = r.get("ball")
        bb = ball.get("bbox") if ball else None
        for pl in r.get("players", []):
            x1, y1, x2, y2 = pl["bbox"]
            h = y2 - y1
            d = {"file": str(r["file"]), "track_id": pl["track_id"],
                 "bbox": [round(v, 1) for v in pl["bbox"]],
                 "h": round(h, 1), "foot_y": round(y2, 1),
                 "cx": round((x1 + x2) / 2, 1), "cy": round((y1 + y2) / 2, 1),
                 "conf": round(float(pl.get("conf", 0)), 4),
                 "plane_ok": ok, "plane_src": pl_.get("src"), "plane_why": pl_.get("why"),
                 "A": round(A, 4), "B": round(B, 1),
                 "n_anchor": na, "plane_rms": None if rms is None or rms != rms else round(rms, 1),
                 "pred_h": None, "rel": None,
                 "d_ball": None if bb is None else round(rect_dist(pl["bbox"], bb), 1),
                 "d_ball_min": None,
                 "is_poss": bool(r.get("poss_track_id") == pl["track_id"]),
                 "prot_track": pl["track_id"] in prot_tracks}
            if ok:
                pred = A * y2 + B
                d["pred_h"] = round(pred, 1)
                d["rel"] = round((h - pred) / pred, 4) if pred > 1 else None
            rows.append(d)

    # ── 轨迹级聚合（关键：把判据从"框级"升到"轨迹级"） ────────────────────
    # 动机（实测）：被遮挡的球员框会被**截断**⇒ h 偏小 ⇒ 与"更远"混淆。
    # sas_hou f00001 的 t11（场内白球衣 #34，h=155）因此被框级判据误删（rel=-0.34）。
    # 真实球员只在**少数帧**异常、多数帧正常；观众/替补则**帧帧**异常。
    # 故用轨迹 rel 的**中位数**做判定（对被遮挡帧天然鲁棒）。
    agg = {}
    for d in rows:
        if d["rel"] is None:
            continue
        agg.setdefault(d["track_id"], []).append(d["rel"])
    tstat = {}
    for t, v in agg.items():
        v = np.asarray(v, float)
        tstat[t] = {"n": len(v), "rel_med": round(float(np.median(v)), 4),
                    "rel_p25": round(float(np.percentile(v, 25)), 4),
                    "rel_min": round(float(v.min()), 4)}

    tstat_dball = {}
    for d in rows:
        v = d.get("d_ball")
        if v is None:
            continue
        cur = tstat_dball.get(d["track_id"])
        tstat_dball[d["track_id"]] = v if cur is None else min(cur, v)

    for d in rows:
        st = tstat.get(d["track_id"])
        # ---- P0 保护（A4.21 修正）-------------------------------------------------
        # 原实现：`prot_track or is_poss` ⇒ **片段级**保护：凡曾被赋过持球者的 track 全程放行。
        # 而持球者 =「几何最近球」，球一旦误检到近端看台，某个观众 track 就被永久豁免。
        # 实测 w1 有 64% 的保留框由 P0 放行，且底部带(foot_y≥0.80H) 97 个小框里 84 个是
        # P0 放行的**成排坐着的观众**（目视 20/20，rel −0.57…−0.84）。
        # 改为：① 只保护**当帧**持球框/近球框；② 加**平面可行性闸门**——平面模型判定该框
        # 比"站在此处的人"矮 ≥55% 时它不可能是持球球员，此时"持球者"标签本身是
        # 最近球启发式的产物，不得用它来豁免该框。
        g_med = st["rel_med"] if (st and st["n"] >= min_track_boxes) \
            else (d["rel"] if d["rel"] is not None else 0.0)
        plausible = g_med >= P0_GUARD
        near_ball = d["d_ball"] is not None and d["d_ball"] <= POSS_RADIUS
        if plausible and (d["is_poss"] or near_ball):
            keep, why = True, ("P0_poss_frame" if d["is_poss"] else "P0_near_ball")
        elif use_hmin and d["h"] < hmin:
            keep, why = False, f"P1_micro(h<{hmin:g})"
        elif st and st["n"] >= min_track_boxes and st["rel_med"] < -thr:
            keep, why = False, f"P2_track_far(med{st['rel_med']:+.2f})"
        elif d["rel"] is not None and d["rel"] < strict:
            keep, why = False, f"P3_box_extreme(rel{d['rel']:+.2f})"
        elif (use_stands and d["h"] < hi_hmax_frac * 1080
              and st and st["n"] >= min_stands_boxes
              and st["rel_med"] > hi_thr
              and (tstat_dball.get(d["track_id"]) is None
                   or tstat_dball[d["track_id"]] > dball_hi_guard)):
            keep, why = False, f"P4_stands(med{st['rel_med']:+.2f})"
        else:
            keep, why = True, "keep"
        d["keep"] = keep
        d["reason"] = why
        d["rel_med_track"] = None if not st else st["rel_med"]
        d["rel_n_track"] = None if not st else st["n"]
    nf = len(recs)
    nok = sum(1 for p in planes if p.get("ok"))
    res = {"clip": clip, "n_frames": nf, "hmin": hmin, "thr": thr, "win": win,
           "strict": strict, "plane_frames_ok": nok, "n_boxes": len(rows),
           "n_kept": sum(r["keep"] for r in rows),
           "_shadow_planes_removed": True,
           "planes": planes,
           "track_stats": tstat,
           "prot_tracks": sorted(prot_tracks),
           "n_prot_track_boxes": sum(1 for r in rows if r["prot_track"]),
           "rows": rows}
    return res


def summarize(res):
    nb, nk = res["n_boxes"], res["n_kept"]
    why = {}
    for r in res["rows"]:
        if not r["keep"]:
            why[r["reason"].split("(")[0]] = why.get(r["reason"].split("(")[0], 0) + 1
    A = [p["A"] for p in res["planes"] if p.get("ok")]
    rms = [p["rms"] for p in res["planes"] if p.get("ok") and p.get("rms") is not None]
    srcs = {}
    for p in res["planes"]:
        if p.get("ok"):
            srcs[p.get("src")] = srcs.get(p.get("src"), 0) + 1
    print(f"[{res['clip']}] 平面可用帧 {res['plane_frames_ok']}/{res['n_frames']}"
          f"  A 中位={np.median(A):.4f}" if A else f"[{res['clip']}] 平面不可用")
    if rms:
        print(f"      平面拟合 rms 中位={np.median(rms):.1f}px", end="")
    print(f"  框 {nb} → {nk}（剔除 {nb-nk}，{100*(nb-nk)/max(1,nb):.1f}%）"
          f"  每帧 {nb/res['n_frames']:.2f} → {nk/res['n_frames']:.2f}")
    print(f"      规则: {why}   保护轨迹 {len(res['prot_tracks'])} 条 / {res['n_prot_track_boxes']} 框")
    print(f"      平面来源: {srcs}")
    return res


LABELS = {
    ("w1", 421): {"off": [2768, 3019, 3048, 3062, 3135, 3030, 3159, 3160, 2693,
                          2946, 2874, 2980, 3157, 3004, 2641],
                  "on": [2900, 2218, 3049, 1892, 2912, 3068, 2552, 2991, 3026, 2888]},
    ("sas_hou", 1): {"on": [1, 2, 3, 4, 5, 6, 7, 8, 11], "off": [12, 13, 14], "ref": [10]},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all-clips", action="store_true")
    ap.add_argument("--suffix", default="_poss_tile")
    ap.add_argument("--thr", type=float, default=THR_DEFAULT)
    ap.add_argument("--win", type=int, default=WIN_DEFAULT)
    ap.add_argument("--no-hmin", action="store_true")
    ap.add_argument("--dump", default=None)
    a = ap.parse_args()
    clips = ["w1", "w2", "w3", "w4", "sas_hou", "sas_nop", "sas_det"] if a.all_clips else [a.clip or "w1"]
    allres = {}
    print("=" * 92)
    for c in clips:
        r = analyze(c, a.suffix, a.thr, a.win, use_hmin=not a.no_hmin)
        summarize(r)
        allres[c] = r
    p = Path(a.dump) if a.dump else OUT / "player_plane_filter.json"
    p.write_text(json.dumps(allres, ensure_ascii=False))
    print(f"\n[out] {p}")

    if allres:
        print("\n" + "=" * 92)
        print("目视确认标签子集上的 rel 分布（单边判据；保护/微框规则不影响下表读数）")
        print(f"{'clip':>8} {'frame':>6} {'label':>5} {'track':>6} {'h':>5} {'foot_y':>7} "
              f"{'pred_h':>7} {'rel':>8} {'plane_ok':>8} {'判定':<26}")
        for (clip, fr), lab in LABELS.items():
            if clip not in allres:
                continue
            rows = {r["track_id"]: r for r in allres[clip]["rows"]
                    if r["file"] == f"f{fr:05d}.jpg"}
            for kind in ("on", "ref", "off"):
                for t in lab.get(kind, []):
                    r = rows.get(t)
                    if not r:
                        continue
                    print(f"{clip:>8} {fr:>6} {kind:>5} {t:>6} {r['h']:>5.0f} {r['foot_y']:>7.0f} "
                          f"{str(r['pred_h']):>7} {str(r['rel']):>8} {r['plane_ok']:>8} {r['reason']:<26}")


if __name__ == "__main__":
    main()
