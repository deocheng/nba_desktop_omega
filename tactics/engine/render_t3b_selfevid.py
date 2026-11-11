#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.53 视觉自证 —— 占有权时间线(before/after) + 残余 8 帧接触表(供老程裁定)。

纪律: 视觉先自证。本报告只读取与渲染, 不改写任何产物。
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
import matplotlib
import numpy as np

from common.nba_paths import tactics_data_file

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

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


def top1_full(cands):
    best = None
    for c in cands:
        diag = max(c["bbox"][2] - c["bbox"][0], c["bbox"][3] - c["bbox"][1])
        if c["prob"] >= TH and diag < DIAG_MAX:
            if best is None or c["prob"] > best["prob"]:
                best = c
    return best


bc = [None]*N_FRAMES; bbbox = [None]*N_FRAMES
for i in range(N_FRAMES):
    t = top1_full(fr_scores.get(f"f{i+1:05d}.jpg", []))
    if t:
        b = t["bbox"]; bc[i] = ((b[0]+b[2])/2, (b[1]+b[3])/2); bbbox[i] = b

tk = json.loads(TK.read_text())
gate_set = set()
for tr in tk["tracklets"]:
    gate_set.update(tr["frames"])

players = []
for i, fr in enumerate(old[:N_FRAMES]):
    players.append([{"tid": p.get("track_id"), "c": te.ctr(p["bbox"]), "bbox": p["bbox"]}
                    for p in fr.get("players", []) if p.get("bbox") and p.get("track_id") not in EXCL])

tid_vals = {}
for i in range(N_FRAMES):
    fk = i+1
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


def assign(gate):
    taf = [None]*N_FRAMES
    for i in range(N_FRAMES):
        fk = i+1
        bx = bc[i]
        if bx is None or (gate and fk not in gate_set):
            continue
        inside, nearest, nd = None, None, 1e18
        for p in players[i]:
            pb = p["bbox"]
            if pb[0] <= bx[0] <= pb[2] and pb[1] <= bx[1] <= pb[3] and inside is None:
                inside = p["tid"]
            d = math.hypot(p["c"][0]-bx[0], p["c"][1]-bx[1])
            if d < nd:
                nd, nearest = d, p["tid"]
        if inside is not None:
            taf[i] = inside
        elif nearest is not None and nd <= rad:
            taf[i] = nearest
    return taf


taf_c = assign(False)   # canonical
taf_g = assign(True)    # gated


def tag(taf, i):
    fk = i+1
    if live_of.get(fk) != "live":
        return None
    tid = taf[i]; pbp = poss_of.get(fk)
    if tid is None or pbp not in ("SAS", "DET") or tid_team.get(tid) is None:
        return None
    return 1 if tid_team[tid] == pbp else -1  # 1=agree, -1=disagree


ag_c = [tag(taf_c, i) for i in range(N_FRAMES)]
ag_g = [tag(taf_g, i) for i in range(N_FRAMES)]
live = [1 if live_of.get(i+1) == "live" else 0 for i in range(N_FRAMES)]

# ---- 时间线 ----
fig, ax = plt.subplots(figsize=(13, 3.4))
for i in range(N_FRAMES):
    if not live[i]:
        continue
    # canonical row (y=1.0)
    if ag_c[i] == 1:
        ax.add_patch(Rectangle((i, 1.05), 1, 0.4, color="#2a7fff"))
    elif ag_c[i] == -1:
        ax.add_patch(Rectangle((i, 1.05), 1, 0.4, color="#ff3b30"))
    # gated row (y=0.5)
    if ag_g[i] == 1:
        ax.add_patch(Rectangle((i, 0.55), 1, 0.4, color="#2a7fff"))
    elif ag_g[i] == -1:
        ax.add_patch(Rectangle((i, 0.55), 1, 0.4, color="#ff3b30"))
    # PBP reference (y=0)
    pbp = poss_of.get(i+1)
    if pbp in ("SAS", "DET"):
        ax.add_patch(Rectangle((i, 0.05), 1, 0.4, color="#2a7fff" if pbp == "SAS" else "#444"))
ax.set_xlim(0, N_FRAMES); ax.set_ylim(0, 1.6)
ax.set_yticks([0.25, 0.75, 1.25]); ax.set_yticklabels(["PBP", "gated(新)", "canonical(旧)"], fontsize=9)
ax.set_xlabel("帧 (10fps, 400帧)", fontsize=9)
ax.set_title("A4.53 占有权时间线 — 蓝=SAS一致 红=不一致 灰=DET一致 (sas_det)", fontsize=10)
# 残余 disagree 标注
resid = [i+1 for i in range(N_FRAMES) if ag_g[i] == -1]
for fk in resid:
    ax.text(fk, 1.62, str(fk), color="#ff3b30", fontsize=6, ha="center")
plt.tight_layout()
OUT1 = AW / "validate" / f"{CLIP}_a4_53_possession_timeline.png"
fig.savefig(OUT1, dpi=130); plt.close(fig)
print(f"[render] 时间线 {OUT1}  残余 gated disagree 帧: {resid}")

# ---- 残余帧接触表(供老程裁定) ----
fig, axes = plt.subplots(2, 4, figsize=(16, 9))
for ax, fk in zip(axes.flat, resid[:8]):
    i = fk-1
    img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
    if img is None:
        ax.set_title(f"f{fk:03d} 缺帧"); ax.axis("off"); continue
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    ax.imshow(img)
    # 球 bbox
    if bbbox[i]:
        b = bbbox[i]; ax.add_patch(Rectangle((b[0], b[1]), b[2]-b[0], b[3]-b[1],
                              edgecolor="#ffd60a", facecolor="none", lw=2))
    # 指派球员 bbox
    tid = taf_g[i]
    for p in players[i]:
        if p["tid"] == tid:
            pb = p["bbox"]; ax.add_patch(Rectangle((pb[0], pb[1]), pb[2]-pb[0], pb[3]-pb[1],
                                  edgecolor="#ff3b30", facecolor="none", lw=2))
    pbp = poss_of.get(fk)
    ax.set_title(f"f{fk:03d} 指派tid={tid}({tid_team.get(tid,'?')}) PBP={pbp}\n"
                 f"sem={sem_of.get(fk)} tracklet={'Y' if fk in gate_set else 'N'}",
                 fontsize=8, color=("#ff3b30" if ag_g[i] == -1 else "k"))
    ax.axis("off")
plt.tight_layout()
OUT2 = AW / "validate" / f"{CLIP}_a4_53_residual_contact.png"
fig.savefig(OUT2, dpi=110); plt.close(fig)
print(f"[render] 残余接触表 {OUT2}")
