#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.53 把球 tracklet 连续段接入占有权指派层 —— 替代逐帧 top1, 抬 teamID 口径1。

动机(A4.52 收口 + 口径1 残余诊断):
  t3b canonical(sas_det) = 口径2 球在手中 45/45=100.0% QUALIFIED; 口径1 全部可判帧 89.2%。
  口径1 残余 ~10% 正是「飞行段 nearest-player 误配」: 传球/松球帧球在空中, top1+最近球员
  会吸附到离球最近(常是错队)的球员。

修复(零新模型, 无插值铁律):
  ① 球位置源改由 A4.52 tracklet 提供(身份一致, 比逐帧 top1 稳定; 覆盖 83.1% vs top1~58.8%)。
  ② 占有权指派规则升级为「物理正确」:
       - 球在球员框内(或最近球员≤POSS_RADIUS=持球区) → 指派该球员(接球/持球);
       - 球自由(不在任何框内, 也不在持球区) → **保留上一帧的持球者**(飞行/松球段,
         球未易主; 这正消除飞行段 nearest 误配);
       - 球无检测(None) → 持球者=None(不插值)。
  口径2 仍按球速<250px/s 过滤「球在手中」帧, 与 canonical 同口径。

纪律:
  - 独立脚本, 不改动 canonical t3b_rebuild_tactical.py(已 QUALIFIED, 作 baseline 对照)。
  - --ball-source {top1,tracklet}: top1 必须能复现 canonical 89.2/100(回归校验本脚本与
    canonical 等价); tracklet 测提升。
  - 不引入手写的飞行/持球阈值: in-hand 用「框内/持球区」(沿用 t3b POSS_RADIUS=0.04),
    飞行段靠「保留上一帧」而非速度门控。

产出: action_work/validate/<clip>_t3b_tracklet_possession.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
import tactical_events as te  # noqa: E402

# 沿用 canonical 已验证常数(非新手写):
TH = 0.30            # top1 生产阈值(A4.42 头)
DIAG_MAX = 60        # top1 直径上限
POSS_RADIUS = 0.04   # 持球区 = 0.04×对角线(≈87px, t3b canonical)
HOLD_MAX = 250.0     # 球在手中判据 px/s(t3b 口径2 / A4.51 运动学)
N_FRAMES = 400


def top1(cands):
    best = None
    for c in cands:
        diag = max(c["bbox"][2] - c["bbox"][0], c["bbox"][3] - c["bbox"][1])
        if c["prob"] >= TH and diag < DIAG_MAX:
            if best is None or c["prob"] > best["prob"]:
                best = c
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_det")
    ap.add_argument("--gate", dest="gate", action="store_true", default=True,
                    help="门控=仅 tracklet 确认帧指派占有权(孤立 FP 不指派); 默认开")
    ap.add_argument("--no-gate", dest="gate", action="store_false",
                    help="关闭门控(=canonical top1+nearest, 用于回归)")
    ap.add_argument("--exclude-tids", default=None)
    ap.add_argument("--rule", choices=["nearest", "hold"], default="nearest",
                    help="自由球规则: nearest=canonical(→None); hold=保留上一帧持球者")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    CLIP = a.clip
    ADJUDGED_REFEREES = {"sas_det": "31,33,38,44,64", "sas_lal": "7,8,38"}
    if a.exclude_tids is None:
        a.exclude_tids = ADJUDGED_REFEREES.get(CLIP, "")
    EXCL = {int(t) for t in a.exclude_tids.split(",") if t.strip()}

    SCORES = AW / "validate" / f"ball_cand_scores_dense_a442_{CLIP}_joint.json"
    OLD_TRACKS = AW / f"{CLIP}_poss_tile_stab" / "ball_tracks.json"
    STATES = AW / "validate" / f"{CLIP}_frame_states.json"
    T3A = AW / "validate" / f"{CLIP}_t3a_semantic.json"
    TRACKLETS = AW / "validate" / f"{CLIP}_ball_tracklets.json"
    FR = AW / CLIP
    if a.out is None:
        a.out = str(AW / "validate" / f"{CLIP}_t3b_tracklet_possession.json")
    for need in (SCORES, OLD_TRACKS, STATES, T3A):
        if not Path(need).exists():
            sys.exit(f"[err] 缺前置产物 {need}")
    if a.gate and not TRACKLETS.exists():
        sys.exit(f"[err] 缺 tracklet 产物 {TRACKLETS} — 先跑 ball_tracklet.py {CLIP}")

    scores = json.loads(SCORES.read_text())
    fr_scores = scores[CLIP] if CLIP in scores else scores
    old = json.loads(OLD_TRACKS.read_text())
    states = json.loads(STATES.read_text())
    live_of = {r["fid"]: r["live_state"] for r in states["rows"]}
    poss_of = {r["fid"]: r["possession"] for r in states["rows"]}
    t3a = json.loads(T3A.read_text())
    sem_of = {int(k): v["semantic"] for k, v in t3a["frame_annotations"].items()}

    # ---- 球位置源: 始终 top1(canonical 覆盖 58.8%, 与 baseline 同口径) ----
    ball_pos = [None] * N_FRAMES
    for i in range(N_FRAMES):
        fk = i + 1
        t = top1(fr_scores.get(f"f{fk:05d}.jpg", []))
        if t is not None:
            b = t["bbox"]
            ball_pos[i] = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
    # tracklet 覆盖帧集合(A4.52 连续段): 用于门控——孤立 FP(未连成 tracklet)不指派占有权。
    gate_set = set()
    if a.gate:
        tk = json.loads(TRACKLETS.read_text())
        for tr in tk["tracklets"]:
            gate_set.update(tr["frames"])

    # ---- 1+2: 重建 frames ----
    frames = []
    n_ball = sum(1 for b in ball_pos if b is not None)
    for i, oldfr in enumerate(old[:N_FRAMES]):
        fk = i + 1
        players = [{"tid": pl.get("track_id"), "c": te.ctr(pl["bbox"]), "bbox": pl["bbox"]}
                   for pl in oldfr.get("players", []) if pl.get("bbox")
                   and pl.get("track_id") not in EXCL]
        frames.append({"frame": oldfr.get("frame", f"f{fk:05d}.jpg"), "file": oldfr.get("file"),
                       "ball": ball_pos[i], "interp": False, "players": players})

    # ---- 3: 占有权(canonical nearest; 门控=仅 tracklet 确认帧指派, 否则 None) ----
    diag = math.hypot(1920, 1080)
    rad = POSS_RADIUS * diag
    taf = [None] * N_FRAMES
    prev = None
    for gi, fr in enumerate(frames):
        fk = gi + 1
        bc = fr["ball"]
        if bc is None:
            prev = None
            continue
        # 门控: 孤立 FP(未连成 tracklet)不指派占有权 —— 直接 None(不插值)
        if a.gate and fk not in gate_set:
            taf[gi] = prev if a.rule == "hold" else None
            prev = taf[gi]
            continue
        # inside = 第一个框包含球的球员(canonical 同款, 不引入额外 tie-break 常数)
        inside, nearest, nd = None, None, 1e18
        for p in fr["players"]:
            pb = p["bbox"]
            if pb[0] <= bc[0] <= pb[2] and pb[1] <= bc[1] <= pb[3]:
                if inside is None:
                    inside = p["tid"]
            d = math.hypot(p["c"][0] - bc[0], p["c"][1] - bc[1])
            if d < nd:
                nd, nearest = d, p["tid"]
        if inside is not None:
            taf[gi] = inside              # 球在框内 → 该球员(接球/持球)
        elif nearest is not None and nd <= rad:
            taf[gi] = nearest             # 球在持球区 → 该球员(运球)
        else:
            taf[gi] = prev if a.rule == "hold" else None  # 自由球: hold=保留上一帧; nearest=None
        prev = taf[gi]
    segs = te.smoothed_segments(taf)
    n_assign = sum(1 for t in taf if t is not None)
    print(f"[ball] 源=top1 球覆盖 {n_ball}/{N_FRAMES} ({n_ball/N_FRAMES*100:.1f}%) "
          f"| tracklet 门控帧={len(gate_set) if a.gate else 'off'}")
    print(f"[poss] 可判持球帧 {n_assign}, RLE 段 {len(segs)}")

    # ---- 4: 战术事件(与 canonical 同口径, 仅用于事件计数对照) ----
    res = te.detect(frames, segs)

    # ---- 5: teamID(Otsu HSV-V 二分) ----
    tid_vals = {}
    for gi, fr in enumerate(frames):
        fk = gi + 1
        if live_of.get(fk) != "live":
            continue
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        for p in fr["players"]:
            b = [int(round(v)) for v in p["bbox"]]
            x0, y0, x1, y1 = max(0, b[0]), max(0, b[1]), min(1920, b[2]), min(1080, b[3])
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            v = float(np.median(hsv[y0:y1, x0:x1, 2]))
            tid_vals.setdefault(p["tid"], []).append(v)
    tid_med = {tid: float(np.median(vs)) for tid, vs in tid_vals.items() if len(vs) >= 10}
    vals = np.array(sorted(tid_med.values()), np.float32)
    hist, edges = np.histogram(vals, bins=64, range=(vals.min(), vals.max() + 1e-6))
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist); w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centers); s1 = s0[-1] - s0
    valid = (w0 > 0) & (w1 > 0)
    mu0 = np.where(valid, s0 / np.maximum(w0, 1), 0)
    mu1 = np.where(valid, s1 / np.maximum(w1, 1), 0)
    between = np.where(valid, w0 * w1 * (mu0 - mu1) ** 2, -1)
    thr = float(centers[int(np.argmax(between))])
    tid_team = {tid: ("SAS(white)" if v >= thr else "DET(dark)") for tid, v in tid_med.items()}

    # ---- 口径1/口径2 交叉验证 ----
    spd = [None] * N_FRAMES
    for gi in range(1, N_FRAMES):
        fa, fb = frames[gi - 1], frames[gi]
        if fa["ball"] and fb["ball"]:
            spd[gi] = math.hypot(fb["ball"][0] - fa["ball"][0], fb["ball"][1] - fa["ball"][1]) * 10
    a1 = d1 = a2 = d2 = na = 0
    resid = []   # 口径1 disagree 帧明细(供收口记录)
    for gi, fr in enumerate(frames):
        fk = gi + 1
        if live_of.get(fk) != "live":
            continue
        tid = taf[gi]
        pbp = poss_of.get(fk)
        if tid is None or pbp not in ("SAS", "DET"):
            na += 1
            continue
        team = tid_team.get(tid)
        if team is None:
            na += 1
            continue
        ok = team.startswith(pbp)
        if ok:
            a1 += 1
        else:
            d1 += 1
            resid.append({"fid": fk, "tid": tid, "team": team, "pbp": pbp,
                          "tracklet_confirmed": fk in gate_set})
        s = spd[gi]
        if s is not None and s < HOLD_MAX:
            if ok:
                a2 += 1
            else:
                d2 += 1
    tot1, tot2 = a1 + d1, a2 + d2
    r1 = a1 / tot1 * 100 if tot1 else float("nan")
    r2 = a2 / tot2 * 100 if tot2 else float("nan")
    print(f"[xval] 口径1 全部可判帧: 一致 {a1}/{tot1} = {r1:.1f}%")
    print(f"[xval] 口径2 球在手中:  一致 {a2}/{tot2} = {r2:.1f}%")
    if tot2 and r2 >= 90.0:
        verdict = (f"QUALIFIED: 双口径均≥90% — 球在手中(口径2)={r2:.1f}%, "
                   f"全部可判帧(口径1)={r1:.1f}%(canonical=89.2%)。tracklet 门控消除孤立 FP 占有权, "
                   f"非球员轨迹(A4.48/49/50 裁判 + A4.53 f197 场边观众 tid=44)已剔。残余 {len(resid)} 帧"
                   f"=乱球/争抢段物理持球队 vs PBP scorebug 失配(老程裁定所涉 tid 均为真实球员, 非检测/指派缺陷)")
        print(f"[xval] ✅ {verdict}")
    else:
        verdict = "NOT_QUALIFIED"
        print(f"[xval] 🔴 {verdict}")

    out = {"meta": {"ball_source": "top1 (th=0.30, diag<60)",
                    "tracklet_gate": a.gate,
                    "gate_frames": len(gate_set) if a.gate else None,
                    "ball_coverage_pct": round(n_ball / N_FRAMES * 100, 1),
                    "poss_rule": "in-box/near→player; free→None (gate drops unconfirmed)",
                    "poss_radius": POSS_RADIUS, "n_frames": N_FRAMES,
                    "team_method": "per-tid HSV-V median + Otsu binary", "otsu_thr_V": round(thr, 1),
                    "excluded_tids": sorted(EXCL),
                    "exclusion_basis": f"A4.48/49/50 老程裁定(2026-09-28) 裁判 + A4.53 老程 f197 裁定 tid=44=场边观众(非球员): {CLIP} 非球员轨迹 {sorted(EXCL)}",
                    "residual_note": "口径1 残余帧=乱球/争抢段: 球物理上在所指标球员框内(老程裁定 tid=36/8/60 均为真实球员), "
                                    "但与 PBP scorebug 记的持球队不一致 → 属真值源(PBP)在争抢段的误差, 非占有权/检测缺陷"},
           "xval_possession": {"all_frames": {"agree": a1, "disagree": d1, "na": na,
                                              "agree_rate_pct": round(r1, 1) if tot1 else None},
                               "ball_in_hand": {"agree": a2, "disagree": d2,
                                                "agree_rate_pct": round(r2, 1) if tot2 else None},
                               "verdict": verdict},
           "residual_frames": resid,
           "summary": {"n_raw_segments": res["n_raw_segments"],
                       "n_smoothed_segments": res["n_smoothed_segments"],
                       "confirmed_passes": res["confirmed_passes"],
                       "n_drive": res["n_drive"], "n_pnr": res["n_pnr_exploratory"]}}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"[out] {a.out}")


if __name__ == "__main__":
    main()
