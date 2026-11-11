#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.50: 裁判特征模板提取 + sas_det 留出分离度验证。

用户裁定(A4.48/49): sas_det tid=31/33/38/64 = 裁判。用户法理: 裁判着装固定(跨球队/跨阶段不变),
可提取特征跨转播复用。本实验:
1) 每 tid 提取上躯干带(20-50%高)与下身带(60-85%高)的 HSV V/S 中值(采样≤12帧);
2) 打印 4 个已裁定裁判 vs 全体球员的特征分布, 验证「灰上衣低S + 黑裤低V」假设是否有自然间隙;
3) 有间隙则存模板 JSON(validate/referee_template_v1.json, provenance=老程裁定 tid)。
零新模型, 特征阈值全部由实测分布导出(禁手写常量)。
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
OUT = AW / "validate" / "referee_template_v1.json"
REFEREES = [31, 33, 38, 64]  # 老程裁定 A4.48/49
MAXS = 12

tr = json.loads((AW / "sas_det_poss_tile_stab" / "ball_tracks.json").read_text())

tid_hits = {}
for fr in tr:
    fk = int(fr["file"][1:6])
    for p in fr.get("players", []):
        tid = p.get("track_id")
        if tid is not None and p.get("bbox"):
            tid_hits.setdefault(tid, []).append((fk, p["bbox"]))


def bands_stats(b, img):
    x0, y0, x1, y1 = [int(round(v)) for v in b]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(1920, x1), min(1080, y1)
    h = y1 - y0
    if h < 20 or x1 - x0 < 12:
        return None
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    up = hsv[int(0.20 * h):int(0.50 * h)]
    lo = hsv[int(0.60 * h):int(0.85 * h)]
    if up.size == 0 or lo.size == 0:
        return None
    return {"up_V": float(np.median(up[:, :, 2])), "up_S": float(np.median(up[:, :, 1])),
            "lo_V": float(np.median(lo[:, :, 2])), "lo_S": float(np.median(lo[:, :, 1]))}


feat = {}  # tid -> dict(medians)
for tid, hits in tid_hits.items():
    if len(hits) < 10:
        continue
    step = max(1, len(hits) // MAXS)
    stats = []
    for fk, b in hits[::step][:MAXS]:
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        if img is None:
            continue
        s = bands_stats(b, img)
        if s:
            stats.append(s)
    if len(stats) < 5:
        continue
    feat[tid] = {k: float(np.median([s[k] for s in stats])) for k in stats[0]}

# 分布: 裁判 vs 球员
refs = [t for t in REFEREES if t in feat]
players = [t for t in feat if t not in REFEREES]


def show(name, vals, tids_):
    arr = np.array(sorted(vals))
    print(f"{name:<12} p0={arr[0]:6.1f} p25={arr[len(arr)//4]:6.1f} p50={arr[len(arr)//2]:6.1f} "
          f"p75={arr[3*len(arr)//4]:6.1f} p100={arr[-1]:6.1f}")


print(f"n_tids={len(feat)} (裁判 {len(refs)} / 球员 {len(players)})")
for key in ("up_V", "up_S", "lo_V", "lo_S"):
    show(f"球员 {key}", [feat[t][key] for t in players], players)
    print(f"{'裁判 ' + key:<12} " + " ".join(f"t{t}={feat[t][key]:.1f}" for t in refs))

# 复合特征观察: 上身亮度-饱和度差(V-S, 灰色=V高S低) vs 下身V
print("\n[tid] up_V / up_S / lo_V  (裁判标*)")
for t in sorted(feat):
    f = feat[t]
    star = "*" if t in REFEREES else " "
    print(f" {star}t{t:<3d} up_V={f['up_V']:6.1f} up_S={f['up_S']:6.1f} lo_V={f['lo_V']:6.1f}")
