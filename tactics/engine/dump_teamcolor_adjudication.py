#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.48 裁定证据: 为反复错分 tid(31/33/44/36) 导出球衣裁切拼图, 供老程人工裁定队色。

零标注零新模型: 只从既有帧图裁切, 拼一张对照图。
每行一个 tid: 上=整bbox裁切, 下=球衣区(30%~65%), 标注帧号+Otsu V中值。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
FR = AW / "sas_det"
OUT = AW / "validate" / "a4_48_teamcolor_adjudication.png"

TIDS = [31, 33, 44, 36]
MAXC = 6  # 每 tid 最多采样帧数

tr = json.loads((AW / "sas_det_poss_tile_stab" / "ball_tracks.json").read_text())

# 收集每 tid 的 (frame, bbox)
tid_hits = {}
for fr in tr:
    fk = int(fr["file"][1:6])
    for p in fr.get("players", []):
        tid = p.get("track_id")
        if tid in TIDS and p.get("bbox"):
            tid_hits.setdefault(tid, []).append((fk, p["bbox"]))

# Otsu V 中值(与 exp 脚本同法, 仅这几 tid 的实测值展示用)
tid_v = {}
for tid, hits in tid_hits.items():
    vs = []
    for fk, b in hits:
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        if img is None:
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in b]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(1920, x1), min(1080, y1)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        vs.append(float(np.median(hsv[y0:y1, x0:x1, 2])))
    tid_v[tid] = float(np.median(vs)) if vs else float("nan")

CW, CH = 240, 300  # 每格: 两行(整bbox / 球衣区)
cols = MAXC
rows = len(TIDS)
sheet = np.full((rows * CH + 40, cols * CW + 20, 3), 245, np.uint8)

def put(img, r, c, crop, label):
    if crop is None or crop.size == 0:
        return
    h, w = crop.shape[:2]
    s = min((CW - 10) / w, (CH // 2 - 30) / h)
    crop = cv2.resize(crop, (max(1, int(w * s)), max(1, int(h * s))))
    y0 = r * CH + 40 + (0 if label.endswith("full") else CH // 2 - 20)
    x0 = c * CW + 10
    hh, ww = crop.shape[:2]
    sheet[y0:y0 + hh, x0:x0 + ww] = crop
    if label.endswith("full"):
        cv2.putText(sheet, label[:-5], (x0, y0 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1)

for r, tid in enumerate(TIDS):
    hits = tid_hits.get(tid, [])
    step = max(1, len(hits) // MAXC)
    sel = hits[::step][:MAXC]
    for c, (fk, b) in enumerate(sel):
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        if img is None:
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in b]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(1920, x1), min(1080, y1)
        full = img[y0:y1, x0:x1]
        h = y1 - y0
        jer = img[y0 + int(0.30 * h):y0 + int(0.65 * h), x0:x1] if h >= 8 else None
        put(img, r, c, full, f"tid{tid} f{fk:05d} full")
        put(img, r, c, jer, f"tid{tid} f{fk:05d} jer")
    info = f"tid={tid}  n={len(hits)}  OtsuV_med={tid_v.get(tid, float('nan')):.1f}"
    cv2.putText(sheet, info, (10, r * CH + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 200), 2)

# 底部说明
foot = "row=top:full bbox crop / bottom:jersey band(30-65%).  RULE: SAS=white jersey, DET=dark jersey."
cv2.putText(sheet, foot, (10, sheet.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)
cv2.imwrite(str(OUT), sheet)
print(f"saved {OUT}")
for tid in TIDS:
    print(f"tid={tid}: n_hits={len(tid_hits.get(tid, []))} frames={sorted(f for f, _ in tid_hits.get(tid, []))[:12]} OtsuV_med={tid_v.get(tid, float('nan')):.1f}")
