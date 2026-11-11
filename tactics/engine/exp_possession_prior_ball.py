#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 A4.46: 占有权先验(PBP)能否辅助球检测(球追踪的球层)。

设计纪律(防循环论证):
  - PBP 占有权队伍(SAS/DET)只作「球候选挑选先验」, 不参与 teamID 交叉验证打分。
  - 球层精度用 INDEP 人工 GT(sas_det_human_ball_events.json, 154 帧 present)评 FPR/recall。
  - 不报告「teamID 因 PBP 选队而变高」——那是同义反复, 非有效交叉验证。

两种先验模式:
  A 严格: PBP 队伍未知(死球/未标) -> 判无球(最大修剪, 测召回损失上限)。
  B 软:   PBP 未知 -> 退回 top1(不压制); 已知 -> 重排(偏好靠近控球队球员的候选, 无一致候选不压制)。
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
RAD = 0.04 * math.hypot(1920, 1080)   # 与 t3b poss_radius 一致
MATCH = 60.0                          # 球中心匹配半径(px)

# ---- 人工 GT ----
gt = json.loads((AW / "validate" / "sas_det_human_ball_events.json").read_text())
gt_frames, gt_center = set(), {}
for ev in gt:
    for fr, c in zip(ev["frames"], ev["centers"]):
        gt_frames.add(fr)
        gt_center[fr] = tuple(c)
absent = set(range(1, N + 1)) - gt_frames

# ---- PBP 占有权 ----
states = json.loads((AW / "validate" / "sas_det_frame_states.json").read_text())
poss_of = {r["fid"]: r.get("possession") for r in states["rows"]}

# ---- dense 候选 ----
scores = json.loads((AW / "validate" / "ball_cand_scores_dense_a442_sas_det_joint.json").read_text())
fr_scores = scores["sas_det"] if "sas_det" in scores else scores

# ---- 球员(稳定轨迹 stab1) + 逐 tid Otsu 队色(复刻 t3b) ----
tr = json.loads((AW / "sas_det_poss_tile_stab" / "ball_tracks.json").read_text())
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
        b = p["bbox"]
        tid = p.get("track_id")
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
w0 = np.cumsum(hist)
w1 = w0[-1] - w0
s0 = np.cumsum(hist * centers)
s1 = s0[-1] - s0
valid = (w0 > 0) & (w1 > 0)
mu0 = np.where(valid, s0 / np.maximum(w0, 1), 0)
mu1 = np.where(valid, s1 / np.maximum(w1, 1), 0)
between = np.where(valid, w0 * w1 * (mu0 - mu1) ** 2, -1)
ot = float(centers[int(np.argmax(between))])
tid_team = {tid: ("SAS" if v >= ot else "DET") for tid, v in tid_med.items()}


def nearest_team(fk, cx, cy):
    nd, pt = 1e18, None
    for b, tid in players_by_fk.get(fk, []):
        t = tid_team.get(tid)
        if t is None:
            continue
        d = math.hypot((b[0] + b[2]) / 2 - cx, (b[1] + b[3]) / 2 - cy)
        if d < nd:
            nd, pt = d, t
    return pt, nd


def top1():
    det = {}
    for i in range(1, N + 1):
        best = None
        for c in fr_scores.get(f"f{i:05d}.jpg", []):
            b = c.get("bbox")
            if b is None:
                continue
            diag = max(b[2] - b[0], b[3] - b[1])
            p = c.get("prob", 0)
            if p >= TH and diag < DIAG_MAX and (best is None or p > best[1]):
                best = (c, p)
        if best is not None:
            b = best[0]["bbox"]
            det[i] = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    return det


def prior(mode):
    """mode='A' 严格(未知->无球); 'B' 软(未知->top1, 已知->重排但不压制)。"""
    det = {}
    for i in range(1, N + 1):
        pool = [c for c in fr_scores.get(f"f{i:05d}.jpg", [])
                if c.get("bbox") and max(c["bbox"][2] - c["bbox"][0], c["bbox"][3] - c["bbox"][1]) < DIAG_MAX
                and c.get("prob", 0) >= TH]
        if not pool:
            continue
        P = poss_of.get(i)
        if P not in ("SAS", "DET"):
            if mode == "A":
                continue
            # mode B: 退回 top1
            b = max(pool, key=lambda c: c["prob"])["bbox"]
            det[i] = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            continue
        best, bscore = None, -1e9
        for c in pool:
            b = c["bbox"]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            pt, nd = nearest_team(i, cx, cy)
            consistent = (pt == P) and (nd <= RAD)
            score = c["prob"] + (10.0 if consistent else 0.0)
            if score > bscore:
                bscore, best = score, (cx, cy)
        if best is None:
            continue
        if mode == "A":
            # 严格: 仅当一致才保留
            cx, cy = best
            pt, nd = nearest_team(i, cx, cy)
            if not ((pt == P) and (nd <= RAD)):
                continue
        det[i] = best
    return det


def evaluate(det):
    tp = fp = fn = 0
    for fr in gt_frames:
        if fr in det:
            cx, cy = det[fr]
            gx, gy = gt_center[fr]
            if math.hypot(cx - gx, cy - gy) < MATCH:
                tp += 1
            else:
                fp += 1
        else:
            fn += 1
    for fr in absent:
        if fr in det:
            fp += 1
    cov = len(det)
    recall = tp / len(gt_frames) * 100 if gt_frames else 0
    prec = tp / (tp + fp) * 100 if (tp + fp) else 0
    fpr = fp / len(absent) * 100 if absent else 0
    return cov, recall, prec, fpr


print(f"[setup] Otsu V={ot:.1f}; GT present={len(gt_frames)} absent={len(absent)}")
known = sum(1 for i in range(1, N + 1) if poss_of.get(i) in ("SAS", "DET"))
print(f"[setup] PBP 占有权已知帧: {known}/{N}")
base = top1()
print(f"[base ] top1 th={TH}: cov={base and len(base)} recall={evaluate(base)[1]:.1f}% "
      f"prec={evaluate(base)[2]:.1f}% fpr={evaluate(base)[3]:.1f}%")
for m in ("B", "A"):
    d = prior(m)
    cov, rc, pc, fp = evaluate(d)
    print(f"[prior {m}] cov={cov} recall={rc:.1f}% prec={pc:.1f}% fpr={fp:.1f}%  "
          f"(Δrecall={rc - evaluate(base)[1]:+.1f} Δfpr={fp - evaluate(base)[3]:+.1f})")
