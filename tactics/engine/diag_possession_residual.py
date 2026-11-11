#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.53 诊断 —— 拆解 canonical 口径1 的 13 个 disagree 帧, 判定 hold-prev / tracklet 能否修复。

纪律: 先调研再下结论。本脚本只读取与统计, 不改写任何产物。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
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
import tactical_events as te

TH, DIAG_MAX, POSS_RADIUS, HOLD_MAX, N_FRAMES = 0.30, 60, 0.04, 250.0, 400
CLIP = sys.argv[1] if len(sys.argv) > 1 else "sas_det"
EXCL = {31, 33, 38, 44, 64} if CLIP == "sas_det" else {7, 8, 38}

SCORES = AW / "validate" / f"ball_cand_scores_dense_a442_{CLIP}_joint.json"
OLD = AW / f"{CLIP}_poss_tile_stab" / "ball_tracks.json"
STATES = AW / "validate" / f"{CLIP}_frame_states.json"
T3A = AW / "validate" / f"{CLIP}_t3a_semantic.json"
TK = AW / "validate" / f"{CLIP}_ball_tracklets.json"
FR = AW / CLIP

scores = json.loads(SCORES.read_text()); fr_scores = scores[CLIP] if CLIP in scores else scores
old = json.loads(OLD.read_text())
states = json.loads(STATES.read_text())
live_of = {r["fid"]: r["live_state"] for r in states["rows"]}
poss_of = {r["fid"]: r["possession"] for r in states["rows"]}
t3a = json.loads(T3A.read_text())
sem_of = {int(k): v["semantic"] for k, v in t3a["frame_annotations"].items()}


def top1(cands):
    best = None
    for c in cands:
        diag = max(c["bbox"][2] - c["bbox"][0], c["bbox"][3] - c["bbox"][1])
        if c["prob"] >= TH and diag < DIAG_MAX:
            if best is None or c["prob"] > best["prob"]:
                best = c
    return best


# top1 球位置
bc = [None] * N_FRAMES
for i in range(N_FRAMES):
    t = top1(fr_scores.get(f"f{i+1:05d}.jpg", []))
    if t:
        b = t["bbox"]; bc[i] = ((b[0]+b[2])/2, (b[1]+b[3])/2)

# tracklet 球位置
tk = json.loads(TK.read_text())
tbest = {}
for tr in tk["tracklets"]:
    for fk, pt in zip(tr["frames"], tr["pts"]):
        if fk not in tbest or tr.get("mean_prob", 0) > tbest[fk][2]:
            tbest[fk] = (pt[0], pt[1], tr.get("mean_prob", 0))
tkpos = [(tbest[i+1][0], tbest[i+1][1]) if i+1 in tbest else None for i in range(N_FRAMES)]

# players per frame (剔除裁判)
players = []
for i, fr in enumerate(old[:N_FRAMES]):
    players.append([{"tid": p.get("track_id"), "c": te.ctr(p["bbox"]), "bbox": p["bbox"]}
                    for p in fr.get("players", []) if p.get("bbox") and p.get("track_id") not in EXCL])

# teamID Otsu (与 canonical 同)
tid_vals = {}
for i in range(N_FRAMES):
    fk = i + 1
    if live_of.get(fk) != "live":
        continue
    img = cv2.imread(str(FR / f"f{fk:05d}.jpg")); hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    for p in players[i]:
        b = [int(round(v)) for v in p["bbox"]]
        x0, y0, x1, y1 = max(0, b[0]), max(0, b[1]), min(1920, b[2]), min(1080, b[3])
        if x1-x0 < 8 or y1-y0 < 8:
            continue
        tid_vals.setdefault(p["tid"], []).append(float(np.median(hsv[y0:y1, x0:x1, 2])))
tid_med = {t: float(np.median(v)) for t, v in tid_vals.items() if len(v) >= 10}
vals = np.array(sorted(tid_med.values()), np.float32)
hist, edges = np.histogram(vals, bins=64, range=(vals.min(), vals.max()+1e-6))
centers = (edges[:-1]+edges[1:])/2
w0 = np.cumsum(hist); w1 = w0[-1]-w0; s0 = np.cumsum(hist*centers); s1 = s0[-1]-s0
valid = (w0 > 0) & (w1 > 0)
mu0 = np.where(valid, s0/np.maximum(w0, 1), 0); mu1 = np.where(valid, s1/np.maximum(w1, 1), 0)
between = np.where(valid, w0*w1*(mu0-mu1)**2, -1)
thr = float(centers[int(np.argmax(between))])
tid_team = {t: ("SAS" if v >= thr else "DET") for t, v in tid_med.items()}

rad = POSS_RADIUS * math.hypot(1920, 1080)


def assign(ballpos, hold):
    """canonical nearest 规则; hold=True 时自由球保留上一帧。返回 taf[]。"""
    taf = [None]*N_FRAMES; prev = None
    for i in range(N_FRAMES):
        bcx = ballpos[i]
        if bcx is None:
            prev = None; continue
        inside, nearest, nd = None, None, 1e18
        for p in players[i]:
            pb = p["bbox"]
            if pb[0] <= bcx[0] <= pb[2] and pb[1] <= bcx[1] <= pb[3] and inside is None:
                inside = p["tid"]
            d = math.hypot(p["c"][0]-bcx[0], p["c"][1]-bcx[1])
            if d < nd:
                nd, nearest = d, p["tid"]
        if inside is not None:
            taf[i] = inside
        elif nearest is not None and nd <= rad:
            taf[i] = nearest
        else:
            taf[i] = prev if hold else None
        prev = taf[i]
    return taf


def spd_arr(ballpos):
    sp = [None]*N_FRAMES
    for i in range(1, N_FRAMES):
        if ballpos[i] and ballpos[i-1]:
            sp[i] = math.hypot(ballpos[i][0]-ballpos[i-1][0], ballpos[i][1]-ballpos[i-1][1])*10
    return sp


def xval(taf, ballpos):
    sp = spd_arr(ballpos)
    a1 = d1 = a2 = d2 = na = 0
    for i in range(N_FRAMES):
        fk = i+1
        if live_of.get(fk) != "live":
            continue
        tid = taf[i]; pbp = poss_of.get(fk)
        if tid is None or pbp not in ("SAS", "DET"):
            na += 1; continue
        team = tid_team.get(tid)
        if team is None:
            na += 1; continue
        ok = team == pbp
        if ok: a1 += 1
        else: d1 += 1
        if sp[i] is not None and sp[i] < HOLD_MAX:
            if ok: a2 += 1
            else: d2 += 1
    tot1, tot2 = a1+d1, a2+d2
    return dict(a1=a1, d1=d1, na=na, r1=a1/tot1*100 if tot1 else None,
                a2=a2, d2=d2, r2=a2/tot2*100 if tot2 else None)


def assign_gated(bp, hold, gate_frames):
    """在 assign 基础上: 仅当 fk 属于 gate_frames(如 tracklet 覆盖帧)才指派, 否则 None/hold。"""
    taf = [None]*N_FRAMES; prev = None
    for i in range(N_FRAMES):
        fk = i+1
        bcx = bp[i]
        if bcx is None or fk not in gate_frames:
            prev = None if not hold else prev
            taf[i] = prev if (hold and fk in gate_frames) else None
            # 简化: 非 gate 帧 → 不指派(等价 nearest 的 None)
            taf[i] = None
            continue
        inside, nearest, nd = None, None, 1e18
        for p in players[i]:
            pb = p["bbox"]
            if pb[0] <= bcx[0] <= pb[2] and pb[1] <= bcx[1] <= pb[3] and inside is None:
                inside = p["tid"]
            d = math.hypot(p["c"][0]-bcx[0], p["c"][1]-bcx[1])
            if d < nd:
                nd, nearest = d, p["tid"]
        if inside is not None:
            taf[i] = inside
        elif nearest is not None and nd <= rad:
            taf[i] = nearest
        else:
            taf[i] = prev if hold else None
        prev = taf[i]
    return taf


print("=== 占有权方案对比 (sas_det) ===")
gate = set(tbest.keys())
for name, bp, hold, gated in [("top1+nearest", bc, False, False),
                               ("top1+hold", bc, True, False),
                               ("tracklet+nearest", tkpos, False, False),
                               ("tracklet+hold", tkpos, True, False),
                               ("top1+tracklet-gate", bc, False, True)]:
    taf = assign_gated(bp, hold, gate) if gated else assign(bp, hold)
    x = xval(taf, bp)
    print(f"  {name:18s} 口径1 {x['a1']}/{x['a1']+x['d1']}={x['r1']:.1f}%  "
          f"口径2 {x['a2']}/{x['a2']+x['d2']}={x['r2']:.1f}%  na={x['na']}")

# 拆解 canonical top1+nearest 的 disagree 帧
taf_c = assign(bc, False)
sp = spd_arr(bc)
print(f"\n=== canonical 口径1 disagree 帧明细 (共 {sum(1 for i in range(N_FRAMES) if live_of.get(i+1)=='live' and taf_c[i] and tid_team.get(taf_c[i]) and poss_of.get(i+1) in ('SAS','DET') and tid_team[taf_c[i]]!=poss_of.get(i+1))}) ===")
prev_tid = None
for i in range(N_FRAMES):
    fk = i+1
    if live_of.get(fk) != "live" or taf_c[i] is None:
        continue
    tid = taf_c[i]; pbp = poss_of.get(fk)
    if pbp not in ("SAS", "DET") or tid_team.get(tid) is None:
        continue
    if tid_team[tid] == pbp:
        prev_tid = tid; continue
    # disagree
    # 该帧球是否在某人框内 / 最近球员
    in_box = any(pb[0] <= bc[i][0] <= pb[2] and pb[1] <= bc[i][1] <= pb[3]
                 for p in players[i] if (pb := p["bbox"]))
    nd = min((math.hypot(p["c"][0]-bc[i][0], p["c"][1]-bc[i][1]) for p in players[i]), default=1e18)
    prev_team = tid_team.get(prev_tid, "?") if prev_tid else "?"
    print(f"  f{fk:03d} 指派 tid={tid}({tid_team[tid]}) PBP={pbp} "
          f"ball_in_box={in_box} 最近球员d={nd:.0f}px 球速={sp[i] if sp[i] else 0:.0f}px/s "
          f"上一持球={prev_tid}({prev_team}) sem={sem_of.get(fk)} "
          f"tracklet覆盖={'Y' if fk in tbest else 'N'}")
    prev_tid = tid
