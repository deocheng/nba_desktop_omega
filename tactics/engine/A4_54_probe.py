#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.54 调研探针(只读, 不改动任何管线产物).

目的: 量化「球被遮挡/检测丢失」的 live 段, 并核对 PBP + 球员轨迹能否支撑
      「遮挡段吸附持球者」(holder-attachment, 非位置插值) 方案.

输出(供老程裁定设计方案):
  - live 帧球无检测 gap 段数/长度/占比
  - 每个 gap 的 PBP possession(队)是否稳定 / 是否中段易主(steal/TO)
  - 每个 gap 起止帧的 event 文本(last_confirmed)
  - 每个 gap 内「持球队稳定 + 有连续球员轨迹」的候选持球者个数
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
CLIP = "sas_det"
TH = 0.30
DIAG_MAX = 60
POSS_RADIUS = 0.04
N = 400

SCORES = AW / "validate" / f"ball_cand_scores_dense_a442_{CLIP}_joint.json"
OLD_TRACKS = AW / f"{CLIP}_poss_tile_stab" / "ball_tracks.json"
STATES = AW / "validate" / f"{CLIP}_frame_states.json"
T3A = AW / "validate" / f"{CLIP}_t3a_semantic.json"
FR = AW / CLIP
EXCL = {31, 33, 38, 44, 64}

scores = json.loads(SCORES.read_text())[CLIP]
old = json.loads(OLD_TRACKS.read_text())
states = {r["fid"]: r for r in json.loads(STATES.read_text())["rows"]}
t3a = json.loads(T3A.read_text())
sem_of = {int(k): v["semantic"] for k, v in t3a["frame_annotations"].items()}


def top1(cands):
    best = None
    for c in cands:
        b = c["bbox"]
        diag = max(b[2] - b[0], b[3] - b[1])
        if c["prob"] >= TH and diag < DIAG_MAX:
            if best is None or c["prob"] > best["prob"]:
                best = c
    return best


# ---- 逐帧 top1 球位置 ----
ball_pos = [None] * N
for i in range(N):
    fk = i + 1
    t = top1(scores.get(f"f{fk:05d}.jpg", []))
    if t is not None:
        b = t["bbox"]
        ball_pos[i] = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)

# ---- 逐帧球员轨迹(tid -> bbox) ----
tid_bbox = [{} for _ in range(N)]
for i, fr in enumerate(old[:N]):
    for pl in fr.get("players", []):
        if pl.get("bbox") and pl.get("track_id") not in EXCL:
            tid_bbox[i][pl["track_id"]] = pl["bbox"]


# ---- 队色 Otsu(复用 t3b 口径) ----
def ctr(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


tid_vals = {}
for i in range(N):
    fk = i + 1
    if states[fk]["live_state"] != "live":
        continue
    img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
    if img is None:
        continue
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    for tid, b in tid_bbox[i].items():
        x0, y0, x1, y1 = (max(0, int(b[0])), max(0, int(b[1])),
                          min(1920, int(b[2])), min(1080, int(b[3])))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        tid_vals.setdefault(tid, []).append(float(np.median(hsv[y0:y1, x0:x1, 2])))
tid_med = {t: float(np.median(v)) for t, v in tid_vals.items() if len(v) >= 10}
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
tid_team = {t: ("SAS" if v >= thr else "DET") for t, v in tid_med.items()}

# ---- live 遮挡 gap ----
gaps = []
i = 0
while i < N:
    fk = i + 1
    if states[fk]["live_state"] == "live" and ball_pos[i] is None:
        j = i
        # 延伸: 下一帧仍 live 且下一帧也无球 -> j 停在最后无球帧
        while j + 1 < N and states[j + 2]["live_state"] == "live" and ball_pos[j + 1] is None:
            j += 1
        gaps.append((i, j))  # [i..j] 含, 均为 live+无球
        i = j + 1
    else:
        i += 1

print(f"[gap] live 帧球无检测 gap 段数={len(gaps)}")
lens = [b - a + 1 for a, b in gaps]
lens_s = sorted(lens)
print(f"[gap] 长度 p50={lens_s[len(lens_s)//2]} max={max(lens)} | "
      f">1帧={sum(1 for x in lens if x>1)} >3帧={sum(1 for x in lens if x>3)} >5帧={sum(1 for x in lens if x>5)}")
print(f"[gap] 总遮挡帧={sum(lens)} (占 live {sum(1 for k in states if states[k]['live_state']=='live')} 帧的 "
      f"{sum(lens)/sum(1 for k in states if states[k]['live_state']=='live')*100:.1f}%)")

rad = POSS_RADIUS * math.hypot(1920, 1080)
attachable = 0
row_fmt = "{:>10} {:>4} {:>5} {:>4} {:>5}  {:>8} {:>8} {:>8}  {:>4}"
print("\n" + row_fmt.format("gap[f..f]", "len", "sem", "possB", "possA",
                            "team_chg", "holders", "attaches", "verdict"))
print("-" * 78)
for a, b in gaps:
    fa, fb = a + 1, b + 1
    posb = states[fa]["possession"]; posa = states[fb]["possession"]
    # gap 内 possession 众数
    modes = Counter(states[k]["possession"] for k in range(fa, fb + 1)
                    if states[k]["possession"] in ("SAS", "DET"))
    team_mode = modes.most_common(1)[0][0] if modes else None
    team_chg = "Y" if posb != posa and posb in ("SAS", "DET") and posa in ("SAS", "DET") else "-"
    sem = "occ" if any(sem_of.get(k) == "occluded" for k in range(fa, fb + 1)) else (
          "miss" if any(sem_of.get(k) == "candidate_miss" for k in range(fa, fb + 1)) else "-")
    # 候选持球者: 在 gap 起止帧都存在且 track 连续的 持球队 球员
    holders = []
    for tid in set(tid_bbox[a]) & set(tid_bbox[b]):
        if tid_team.get(tid) != team_mode:
            continue
        # 连续: gap 内每帧都有该 tid
        if all(tid in tid_bbox[k - 1] for k in range(fa, fb + 1)):
            holders.append(tid)
    # 吸附可行性: 用 gap 之前最后一帧有球(prev_det) 与 gap 之后首帧有球(next_det)
    # 校验 holder 在 gap 两端是否衔接(非插值, 仅作可行性证据)
    prev_det = ball_pos[a - 1] if a > 0 else None
    next_det = ball_pos[b + 1] if b + 1 < N else None
    attaches = 0
    for tid in holders:
        ok = True
        if prev_det is not None:
            if math.hypot(ctr(tid_bbox[a][tid])[0] - prev_det[0],
                          ctr(tid_bbox[a][tid])[1] - prev_det[1]) > rad * 2.5:
                ok = False
        if next_det is not None:
            if math.hypot(ctr(tid_bbox[b][tid])[0] - next_det[0],
                          ctr(tid_bbox[b][tid])[1] - next_det[1]) > rad * 2.5:
                ok = False
        if ok:
            attaches += 1
    verdict = "ATTACH" if (team_mode and attaches >= 1) else ("HOLD?" if team_mode else "LOOSE")
    if verdict == "ATTACH":
        attachable += 1
    print(row_fmt.format(f"{fa}-{fb}", b - a + 1, sem, posb or "-", posa or "-",
                         team_chg, len(holders), attaches, verdict))

print(f"\n[summary] 可吸附(稳定队+≥1候选持球者衔接起止)={attachable}/{len(gaps)} 段")
print(f"[otsu] V阈值={thr:.1f} | SAS/dark 分界: ≥thr=SAS(white)")
