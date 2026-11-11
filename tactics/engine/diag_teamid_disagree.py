#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.48 诊断: 把 teamID 球在手中不一致的帧归因。

区分两类根因(决定 90% 杠杆):
  (a) 持球者 tid 指错 -> 跟踪/占有权错 -> 需真 ReID / 更好占有权
  (b) 正确持球者但队色判错 -> Otsu 二分弱 -> 需更强队色分类器

只读分析: 复用 canonical 配置(stab1 + dense_a442 + Otsu), 不写任何产物。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
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

# Otsu per-tid team (复刻 t3b)
tid_vals = {}
players_by_fk = {}
for fr in tr:
    fk = int(fr["file"][1:6])
    players_by_fk[fk] = [(p["bbox"], p.get("track_id")) for p in fr.get("players", []) if p.get("bbox")]
    img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
    if img is None:
        continue
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    for p in fr.get("players", []):
        b = p["bbox"]; tid = p.get("track_id")
        x0, y0, x1, y1 = max(0, int(round(b[0]))), max(0, int(round(b[1]))), \
                        min(1920, int(round(b[2]))), min(1080, int(round(b[3])))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        v = float(np.median(hsv[y0:y1, x0:x1, 2]))
        tid_vals.setdefault(tid, []).append(v)
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
ot = float(centers[int(np.argmax(between))])
tid_team = {tid: ("SAS" if v >= ot else "DET") for tid, v in tid_med.items()}


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


def nearest_player(fk, cx, cy):
    nd, res = 1e18, None
    for b, tid in players_by_fk.get(fk, []):
        d = math.hypot((b[0] + b[2]) / 2 - cx, (b[1] + b[3]) / 2 - cy)
        if d < nd:
            nd, res = d, (tid, tid_team.get(tid))
    return res, nd


print(f"[setup] Otsu V={ot:.1f}; 白tid={sum(1 for v in tid_med.values() if v>=ot)} 深tid={sum(1 for v in tid_med.values() if v<ot)}")

rows = []
prev = None
for i in range(1, N + 1):
    if live_of.get(i) != "live":
        continue
    bc = ball_of(i)
    if bc is None:
        prev = None
        continue
    (tid, tteam), nd = nearest_player(i, bc[0], bc[1])
    P = poss_of.get(i)
    spd = None
    if prev is not None:
        spd = math.hypot(bc[0] - prev[0], bc[1] - prev[1]) * 10
    prev = bc
    if P not in ("SAS", "DET") or tid is None or tteam is None or spd is None or spd >= HOLD_MAX:
        continue
    agree = tteam.startswith(P)
    rows.append((i, tid, tteam, P, nd, spd, agree))

dis = [r for r in rows if not r[6]]
print(f"[ball-in-hand] 总 {len(rows)} 帧, 一致 {sum(1 for r in rows if r[6])}, 不一致 {len(dis)}")

# 归因: 不一致帧是否有 PBP 同队球员在球附近(持球者指错 vs 队色判错)
flip_poss = 0
flip_team = 0
print("\n=== 不一致帧明细 ===")
for i, tid, tteam, P, nd, spd, _ in dis:
    # 是否有 PBP 同队球员离球更近
    pb_team_near = None
    best_nd = 1e18
    for b, t in players_by_fk.get(i, []):
        if tid_team.get(t) == P:
            d = math.hypot((b[0] + b[2]) / 2 - ball_of(i)[0], (b[1] + b[3]) / 2 - ball_of(i)[1])
            if d < best_nd:
                best_nd = d
    # 若把球指派给"最近的 PBP 同队球员", 其队色必=P => 一致 -> 说明是持球者指错
    if best_nd <= RAD:
        flip_poss += 1
    else:
        # 没有 PBP 同队球员在半径内 -> 即便重指派也难; 看是否队色判错(正确持球者被错分)
        flip_team += 1
    print(f"  f{i:03d} tid={tid} Otsu={tteam} PBP={P} nd={nd:.0f}px spd={spd:.0f} "
          f"| PBP同队最近球员距={best_nd:.0f}px({'可重指派' if best_nd<=RAD else '无同队在半径内'})")

print(f"\n[归因] 疑似持球者指错(半径内有PBP同队球员, 重指派即一致): {flip_poss}/{len(dis)}")
print(f"[归因] 疑似队色判错(无PBP同队球员在半径内): {flip_team}/{len(dis)}")
