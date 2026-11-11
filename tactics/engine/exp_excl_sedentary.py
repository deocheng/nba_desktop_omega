#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.48b: 污染轨迹剔除实验。

视觉自证发现(A4.48裁定图): tid=44=坐着的教练(非球员); tid=33/36=身份合并(前后期球衣不同);
tid=31=待裁定。本实验:
1) 量化每 tid 的逐帧脚点位移中位数(运动性), 看坐着的人是否可用位移判据分离;
2) 量化 tid=33/36 前后期球衣 V 中值(验证身份合并);
3) 把「久坐 tid」从持球者候选剔除后重测 teamID 两口径 (剔除判据=运动性, 不用 PBP, 无循环论证)。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
FR = AW / "sas_det"
N = 400
DIAG_MAX = 60
TH = 0.30
RAD = 0.04 * math.hypot(1920, 1080)
HOLD_MAX = 250.0

scores = json.loads((AW / "validate" / "ball_cand_scores_dense_a442_sas_det_joint.json").read_text())
fr_scores = scores["sas_det"] if "sas_det" in scores else scores
states = json.loads((AW / "validate" / "sas_det_frame_states.json").read_text())
live_of = {r["fid"]: r["live_state"] for r in states["rows"]}
poss_of = {r["fid"]: r.get("possession") for r in states["rows"]}
tr = json.loads((AW / "sas_det_poss_tile_stab" / "ball_tracks.json").read_text())

# ---- per-tid 数据 ----
tid_frames = defaultdict(dict)   # tid -> fk -> (foot_x, foot_y, bbox)
for fr in tr:
    fk = int(fr["file"][1:6])
    for p in fr.get("players", []):
        tid = p.get("track_id")
        b = p.get("bbox")
        if tid is None or not b:
            continue
        tid_frames[tid][fk] = ((b[0] + b[2]) / 2, b[3], b)

tid_disp = {}   # tid -> 中位逐帧脚点位移
tid_v = {}      # tid -> V 中值
tid_v_split = {}  # tid -> (前半 V 中值, 后半 V 中值)
for tid, fkm in tid_frames.items():
    fks = sorted(fkm)
    if len(fks) < 10:
        continue
    ds = []
    for a, b in zip(fks, fks[1:]):
        if b - a != 1:
            continue
        (x0, y0, _), (x1, y1, _) = fkm[a], fkm[b]
        ds.append(math.hypot(x1 - x0, y1 - y0))
    if not ds:
        continue
    tid_disp[tid] = float(np.median(ds))
    vs = []
    for fk in fks:
        _, _, bb = fkm[fk]
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        if img is None:
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in bb]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(1920, x1), min(1080, y1)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        vs.append((fk, float(np.median(hsv[y0:y1, x0:x1, 2]))))
    if len(vs) >= 10:
        tid_v[tid] = float(np.median([v for _, v in vs]))
        half = len(vs) // 2
        tid_v_split[tid] = (float(np.median([v for _, v in vs[:half]])),
                            float(np.median([v for _, v in vs[half:]])))


def otsu_thr(vals):
    vals = np.array(sorted(vals), np.float32)
    hist, edges = np.histogram(vals, bins=64, range=(vals.min(), vals.max() + 1e-6))
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist); w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centers); s1 = s0[-1] - s0
    valid = (w0 > 0) & (w1 > 0)
    mu0 = np.where(valid, s0 / np.maximum(w0, 1), 0)
    mu1 = np.where(valid, s1 / np.maximum(w1, 1), 0)
    between = np.where(valid, w0 * w1 * (mu0 - mu1) ** 2, -1)
    return float(centers[int(np.argmax(between))])


ot = otsu_thr(list(tid_v.values()))
otsu_team = {tid: ("SAS" if v >= ot else "DET") for tid, v in tid_v.items()}

# ---- 运动性分布 ----
disps = sorted(tid_disp.values())
print("== per-tid 逐帧脚点位移中位数 分布(px) ==")
for q in (0, 10, 25, 50, 75, 90, 100):
    v = disps[int(q / 100 * (len(disps) - 1))]
    print(f"  p{q:>3}: {v:.1f}")
print("争议 tid 位移:", {t: round(tid_disp.get(t, float('nan')), 1) for t in (31, 33, 44, 36)})
print("争议 tid V前/后半:", {t: (round(tid_v_split[t][0], 1), round(tid_v_split[t][1], 1))
                            for t in (31, 33, 44, 36) if t in tid_v_split})
sed_all = sorted([t for t, d in tid_disp.items() if d < 20], key=lambda t: tid_disp[t])
print(f"位移<20px 的 tid(共{len(sed_all)}): {sed_all}")


# ---- xval (同 exp_teamcolor_dinov2, 增加候选剔除) ----
players_by_fk = {}
for fr in tr:
    fk = int(fr["file"][1:6])
    players_by_fk[fk] = [(p["bbox"], p.get("track_id")) for p in fr.get("players", []) if p.get("bbox")]


def ball_of(fk):
    best = None
    for c in fr_scores.get(f"f{fk:05d}.jpg", []):
        b = c.get("bbox")
        if b is None:
            continue
        diag = max(b[2] - b[0], b[3] - b[1])
        p = c.get("prob", 0)
        if p >= TH and diag < DIAG_MAX and (best is None or p > best[1]):
            best = (c, p)
    if best is None:
        return None
    b = best[0]["bbox"]
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def xval(team_map, exclude=frozenset(), t3b_rule=False):
    a2 = d2 = 0
    prev = None
    for i in range(1, N + 1):
        if live_of.get(i) != "live":
            continue
        bc = ball_of(i)
        if bc is None:
            prev = None
            continue
        if t3b_rule:
            inside, nearest, nd = None, None, 1e18
            for b, t in players_by_fk.get(i, []):
                if t in exclude or team_map.get(t) is None:
                    continue
                if b[0] <= bc[0] <= b[2] and b[1] <= bc[1] <= b[3] and inside is None:
                    inside = t
                d = math.hypot((b[0] + b[2]) / 2 - bc[0], (b[1] + b[3]) / 2 - bc[1])
                if d < nd:
                    nd, nearest = d, t
            tid = inside if inside is not None else (nearest if nd <= RAD else None)
        else:
            nd, tid = 1e18, None
            for b, t in players_by_fk.get(i, []):
                if t in exclude or team_map.get(t) is None:
                    continue
                d = math.hypot((b[0] + b[2]) / 2 - bc[0], (b[1] + b[3]) / 2 - bc[1])
                if d < nd:
                    nd, tid = d, t
            if nd > RAD:
                tid = None
        if tid is None:
            prev = bc
            continue
        P = poss_of.get(i)
        if P not in ("SAS", "DET"):
            prev = bc
            continue
        spd = None
        if prev is not None:
            spd = math.hypot(bc[0] - prev[0], bc[1] - prev[1]) * 10
        prev = bc
        if spd is None or spd >= HOLD_MAX:
            continue
        if team_map[tid].startswith(P):
            a2 += 1
        else:
            d2 += 1
    tot = a2 + d2
    return (a2 / tot * 100 if tot else 0.0), tot


print("\n== 污染轨迹剔除实验 (Otsu 队色, 剔除判据=位移<阈值, 与 PBP 无关) ==")
print(f"{'配置':<28}{'严格(半径内)':>14}{'t3b(框内优先)':>14}")
for name, excl in [
    ("基线(不剔除)", set()),
    ("剔除位移<10px tid", {t for t, d in tid_disp.items() if d < 10}),
    ("剔除位移<20px tid", {t for t, d in tid_disp.items() if d < 20}),
    ("剔除位移<40px tid", {t for t, d in tid_disp.items() if d < 40}),
    ("仅剔除 tid=44(目视教练)", {44}),
    ("仅剔除 tid=33/44(混合+教练)", {33, 44}),
]:
    r1, n1 = xval(otsu_team, exclude=excl)
    r2, n2 = xval(otsu_team, exclude=excl, t3b_rule=True)
    print(f"{name:<26}{r1:>11.1f}% ({n1}){r2:>11.1f}% ({n2})")
