#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.48 实验: 用 DINOv2 jersey 嵌入替换 Otsu 亮度二分做队色分类, 重测 teamID。

动机(诊断结论): 15 个不一致里 14 个是「同一批 tid 被 Otsu 系统性错分 DET, PBP 说 SAS」-> 队色判错,
非跟踪/占有权错。A4.44 证伪的是「外观做人重识别(跨帧关联)」, 与「外观判单人所属球队(队色分类)」是两任务。
本实验测: DINOv2 jersey 嵌入能否把队色判对 -> 抬 teamID 向 90%。

不引入新模型(facebook/dinov2-small 本地缓存, 复用 stabilize_tracks_v2.embed_crops)。
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

sys.path.insert(0, str(Path(str(tactics_data_file("engine")))))
from stabilize_tracks_v2 import embed_crops  # noqa: E402

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

# ---- Otsu 基线 per-tid 队色 ----
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


ot = otsu_thr(list(tid_med.values()))
otsu_team = {tid: ("SAS" if v >= ot else "DET") for tid, v in tid_med.items()}


# ---- DINOv2 jersey 嵌入 per-tid ----
def jersey_crop(b, img):
    x0, y0, x1, y1 = [int(round(v)) for v in b]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(1920, x1), min(1080, y1)
    h = y1 - y0
    if h < 8:
        return None
    # 上 30%~65%: 去头去短裤, 聚焦球衣
    jy0 = y0 + int(0.30 * h)
    jy1 = y0 + int(0.65 * h)
    if jy1 - jy0 < 6:
        return None
    return img[jy0:jy1, x0:x1]


tid_crops = {}
for fr in tr:
    fk = int(fr["file"][1:6])
    img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
    if img is None:
        continue
    for p in fr.get("players", []):
        tid = p.get("track_id")
        if tid not in tid_med:
            continue
        c = jersey_crop(p["bbox"], img)
        if c is None or c.size == 0:
            continue
        tid_crops.setdefault(tid, []).append(c)

# 每 tid 采样 <=6 帧
emb_tid = {}
for tid, crops in tid_crops.items():
    sel = crops[::max(1, len(crops) // 6)][:6]
    e = embed_crops(sel).mean(axis=0)
    emb_tid[tid] = e

# ---- 修正: 仅球衣区(去短裤/皮肤)的 V 中值 再 Otsu ----
tid_jv = {}
for tid, crops in tid_crops.items():
    vs = []
    for c in crops:
        hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
        vs.append(float(np.median(hsv[:, :, 2])))
    if vs:
        tid_jv[tid] = float(np.median(vs))
otj = otsu_thr(list(tid_jv.values()))
jersey_team = {tid: ("SAS" if v >= otj else "DET") for tid, v in tid_jv.items()}

# kmeans-2 on 嵌入
X = np.stack([emb_tid[t] for t in emb_tid])
rng = np.random.default_rng(0)
c0 = X[rng.integers(0, len(X))]; c1 = X[rng.integers(0, len(X))]
for _ in range(20):
    d0 = np.linalg.norm(X - c0, axis=1); d1 = np.linalg.norm(X - c1, axis=1)
    l0 = d0 < d1
    if l0.sum() == 0 or l0.sum() == len(X):
        break
    c0 = X[l0].mean(0); c1 = X[~l0].mean(0)
l0 = np.linalg.norm(X - c0, axis=1) < np.linalg.norm(X - c1, axis=1)
# 映射到 SAS/DET: 高亮度(V)簇 = SAS
cl_mean_v = [np.mean([tid_med[t] for t, ll in zip(emb_tid, l0) if ll]),
             np.mean([tid_med[t] for t, ll in zip(emb_tid, ~l0) if not ll])]
sas_is_l0 = cl_mean_v[0] >= cl_mean_v[1]
dino_team = {}
for t, ll in zip(emb_tid, l0):
    dino_team[t] = "SAS" if (ll == sas_is_l0) else "DET"


# ---- possession + teamID xval (复用 t3b 逻辑) ----
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


def teamid_xval(team_map):
    a2 = d2 = 0
    prev = None
    for i in range(1, N + 1):
        if live_of.get(i) != "live":
            continue
        bc = ball_of(i)
        if bc is None:
            prev = None
            continue
        nd, tid = 1e18, None
        for b, t in players_by_fk.get(i, []):
            d = math.hypot((b[0] + b[2]) / 2 - bc[0], (b[1] + b[3]) / 2 - bc[1])
            if d < nd:
                nd, tid = d, t
        if nd > RAD:   # 与 t3b 一致: 球须在某球员半径内才算持球者
            prev = bc
            continue
        P = poss_of.get(i)
        if tid is None or P not in ("SAS", "DET"):
            prev = bc
            continue
        tm = team_map.get(tid)
        if tm is None:
            prev = bc
            continue
        spd = None
        if prev is not None:
            spd = math.hypot(bc[0] - prev[0], bc[1] - prev[1]) * 10
        prev = bc
        if spd is None or spd >= HOLD_MAX:
            continue
        if tm.startswith(P):
            a2 += 1
        else:
            d2 += 1
    tot = a2 + d2
    return a2, d2, (a2 / tot * 100 if tot else 0.0)


a_o, d_o, r_o = teamid_xval(otsu_team)
a_d, d_d, r_d = teamid_xval(dino_team)
a_j, d_j, r_j = teamid_xval(jersey_team)


def teamid_xval_t3b(team_map):
    """复刻 t3b: 球在框内优先, 否则最近球员且 nd<=RAD。"""
    a2 = d2 = 0
    prev = None
    for i in range(1, N + 1):
        if live_of.get(i) != "live":
            continue
        bc = ball_of(i)
        if bc is None:
            prev = None
            continue
        inside, nearest, nd = None, None, 1e18
        for b, t in players_by_fk.get(i, []):
            if b[0] <= bc[0] <= b[2] and b[1] <= bc[1] <= b[3]:
                if inside is None:
                    inside = t
            d = math.hypot((b[0] + b[2]) / 2 - bc[0], (b[1] + b[3]) / 2 - bc[1])
            if d < nd:
                nd, nearest = d, t
        tid = inside if inside is not None else (nearest if nd <= RAD else None)
        if tid is None:
            prev = bc
            continue
        P = poss_of.get(i)
        if P not in ("SAS", "DET"):
            prev = bc
            continue
        tm = team_map.get(tid)
        if tm is None:
            prev = bc
            continue
        spd = None
        if prev is not None:
            spd = math.hypot(bc[0] - prev[0], bc[1] - prev[1]) * 10
        prev = bc
        if spd is None or spd >= HOLD_MAX:
            continue
        if tm.startswith(P):
            a2 += 1
        else:
            d2 += 1
    tot = a2 + d2
    return a2, d2, (a2 / tot * 100 if tot else 0.0)


# 天花板估计: 把反复错分 tid 翻为 SAS(基于 jersey/DINOv2 证据)
corrected = dict(otsu_team)
for t in (31, 44):
    corrected[t] = "SAS"

print(f"{'方法':<14}{'严格(半径内)':>14}{'t3b(框内优先)':>16}")
for name, m in [("Otsu全bbox", otsu_team), ("Otsu球衣区", jersey_team),
                ("DINOv2 km", dino_team), ("修正天花板", corrected)]:
    ra, rd, rr = teamid_xval(m)
    ta, td, tr = teamid_xval_t3b(m)
    print(f"{name:<14}{rr:>11.1f}% ({ra}/{ra+rd}){tr:>13.1f}% ({ta}/{ta+td})")
# 翻转的 tid
flip = [t for t in set(list(otsu_team) + list(dino_team)) if otsu_team.get(t) != dino_team.get(t)]
print(f"[DINOv2] 与 Otsu 不同的 tid: {len(flip)} -> {flip}")
print(f"[note] 诊断中反复错分 tid=31/33/44/36 的队色: "
      f"Otsu全bbox=31={otsu_team.get(31)} 33={otsu_team.get(33)} 44={otsu_team.get(44)} 36={otsu_team.get(36)} | "
      f"Otsu球衣区=31={jersey_team.get(31)} 33={jersey_team.get(33)} 44={jersey_team.get(44)} 36={jersey_team.get(36)} | "
      f"DINOv2=31={dino_team.get(31)} 33={dino_team.get(33)} 44={dino_team.get(44)} 36={dino_team.get(36)}")
