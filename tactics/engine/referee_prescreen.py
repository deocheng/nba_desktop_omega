#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.50: 跨转播裁判预筛 + 裁定图(sas_lal 实测)。

背景: 裁判着装固定可复用(用户 2026-09-28)。但 sas_det 留出验证(A4.50)证明裸 HSV 带特征
**不能自动分类裁判**(up_V/lo_V 与球员完全重叠), 只能做**弱排序预筛**: 裁判 lo_V(黑裤)整体
低于球员中位。本脚本对新转播(sas_lal):
1) 提取每 tid 上/下身带 HSV + 寿命;
2) 按预筛分排序(深裤倾向 + 长寿命优先), 取 top-K 候选;
3) 出裁定图: top-K 候选各一行(整bbox + 球衣带裁切), 供老程目视裁定哪些是裁判。
预筛只做排序不裁最终结果, 裁定权归老程。
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
CLIP = sys.argv[1] if len(sys.argv) > 1 else "sas_lal"
FR = AW / CLIP
TRK = AW / f"{CLIP}_poss_tile_stab" / "ball_tracks.json"
OUT_PNG = AW / "validate" / f"a4_50_{CLIP}_referee_prescreen.png"
OUT_JSON = AW / "validate" / f"a4_50_{CLIP}_referee_prescreen.json"
TOPK = 8

tr = json.loads(TRK.read_text())
tid_hits = {}
for fr in tr:
    fk = int(fr["file"][1:6])
    for p in fr.get("players", []):
        tid = p.get("track_id")
        if tid is not None and p.get("bbox"):
            tid_hits.setdefault(tid, []).append((fk, p["bbox"]))


def bands(b, img):
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


feat, life = {}, {}
for tid, hits in tid_hits.items():
    if len(hits) < 15:   # 裁判 = 长寿命轨迹, 与 stabilize --min-track 口径一致
        continue
    step = max(1, len(hits) // 12)
    stats = []
    for fk, b in hits[::step][:12]:
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        if img is None:
            continue
        s = bands(b, img)
        if s:
            stats.append(s)
    if len(stats) < 5:
        continue
    feat[tid] = {k: float(np.median([s[k] for s in stats])) for k in stats[0]}
    life[tid] = len(hits)

# 预筛分: 深裤(lo_V 低) + 长寿命。sas_det 裁判实测 lo_V 9.5~70 vs 球员 p50=94 —— 用作排序权重。
# 分数 = z(lo_V 取负)*1.0 + z(life)*0.5; 只排序, 不下裁定。
lo_arr = np.array([f["lo_V"] for f in feat.values()])
life_arr = np.array([life[t] for t in feat], float)
z_lo = (lo_arr - lo_arr.mean()) / (lo_arr.std() + 1e-9)
z_life = (life_arr - life_arr.mean()) / (life_arr.std() + 1e-9)
score = {t: -zl + 0.5 * zl2 for t, zl, zl2 in zip(feat, z_lo, z_life)}
rank = sorted(feat, key=lambda t: score[t], reverse=True)  # 分数高 = lo_V 低(深裤) + 寿命长 → 更疑似裁判
top = rank[:TOPK]

print(f"[{CLIP}] n_tids(≥15帧)={len(feat)}, 预筛 top{TOPK}: {top}")
for t in top:
    f = feat[t]
    print(f"  t{t}: lo_V={f['lo_V']:.1f} up_V={f['up_V']:.1f} life={life[t]}")

# 裁定图: 每行一个候选, 每行 4 格(整bbox) + 4 格(球衣带)
rows = len(top)
COLS = 4
CW, CH = 250, 560
sheet = np.full((rows * CH + 50, COLS * CW + 20, 3), 245, np.uint8)
for r, tid in enumerate(top):
    hits = tid_hits[tid]
    step = max(1, len(hits) // COLS)
    sel = hits[::step][:COLS]
    for c, (fk, b) in enumerate(sel):
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        if img is None:
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in b]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(1920, x1), min(1080, y1)
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        h, w = crop.shape[:2]
        s = min((CW - 10) / w, (CH // 2 - 40) / h)
        crop = cv2.resize(crop, (max(1, int(w * s)), max(1, int(h * s))))
        ch, cw2 = crop.shape[:2]
        yy = r * CH + 40 + c % 2 * (CH // 2)  # 交错两行
        xx = c * CW + 10
        sheet[yy:yy + ch, xx:xx + cw2] = crop
        cv2.putText(sheet, f"f{fk:05d}", (xx, yy - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    f = feat[tid]
    cv2.putText(sheet, f"tid={tid} life={life[tid]} lo_V={f['lo_V']:.0f} up_V={f['up_V']:.0f}",
                (10, r * CH + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 200), 2)
cv2.putText(sheet, "PRESCREEN ONLY (ranked candidates, not verdicts). RULE: referee=grey shirt+black pants, stays on court all game.",
            (10, sheet.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 1)
cv2.imwrite(str(OUT_PNG), sheet)
json.dump({"clip": CLIP, "ranked_tids": rank, "top": top,
           "features": {str(t): feat[t] for t in feat},
           "life": life}, open(OUT_JSON, "w"), indent=1)
print(f"saved {OUT_PNG}\nsaved {OUT_JSON}")
