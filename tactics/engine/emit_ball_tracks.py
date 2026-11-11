#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emit_ball_tracks.py — 路径 A 产品演示：把校准后的宽景球信号抽成「球事件轨迹」并可视化。

对指定 clip，在 gate_calibrated.json 的 operating_th（或 --th）下，取宽景(<60px) 高置信球心，
连成连续片段(episodes)，输出 JSON 轨迹 + 一页轨迹叠加 montage（每片段用同色线连球心）。

用法:
  python engine/emit_ball_tracks.py --clip sas_hou [--th 0.85] [--min-len 1]
  --min-len N: 只保留连续帧数 ≥ N 的片段（产品级过滤，默认 1=不过滤）。
               N=2 即报告里声明的「片段≥2帧」过滤，剔除单帧孤立 claim（含 FP 与可能的真单帧）。
产物:
  action_work/validate/<clip>_ball_tracks.json
  action_work/validate/<clip>_ball_tracks_overview.jpg
  [--min-len 2 时另写 <clip>_ball_tracks_clean.json / _clean_overview.jpg]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import random
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MAX_PX = 60.0
GAP_TOL = 3
SMOOTH_PX = 80.0


def frame_claims_wide(frames, th):
    present = {}
    for fn, cs in frames.items():
        hs = [c for c in cs if c["prob"] > th]
        if not hs:
            continue
        best = max(hs, key=lambda c: c["prob"])
        b = best["bbox"]
        if math.hypot(b[2] - b[0], b[3] - b[1]) >= MAX_PX:
            continue
        num = int(fn[1:6])
        present[num] = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, float(best["prob"]), fn)
    return present


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--th", type=float, default=None)
    ap.add_argument("--min-len", type=int, default=1,
                    help="只保留连续帧数≥N的片段（产品级过滤；2=剔除所有单帧claim）")
    a = ap.parse_args()
    cal = json.loads((AW / "validate" / "gate_calibrated.json").read_text())
    th = a.th if a.th is not None else cal[a.clip]["operating_th"]
    assert th is not None, f"{a.clip} 无 operating_th（gate FAIL），无法抽轨迹"
    d = json.loads((AW / "validate" / f"{a.clip}_scores.json").read_text())[a.clip]
    present = frame_claims_wide(d, th)
    nums = sorted(present)
    eps, cur, last = [], [], None
    for f in nums:
        if last is not None and f - last > GAP_TOL + 1 and cur:
            eps.append(cur)
            cur = []
        cur.append(f)
        last = f
    if cur:
        eps.append(cur)
    if a.min_len > 1:                       # 产品级过滤：只留持续片段
        eps = [e for e in eps if len(e) >= a.min_len]
    tracks = [{"episode": i + 1, "frames": [int(n) for n in e],
              "centers": [[round(present[n][0], 1), round(present[n][1], 1)] for n in e],
              "probs": [round(present[n][2], 3) for n in e]} for i, e in enumerate(eps)]
    suf = "_clean" if a.min_len > 1 else ""
    (AW / "validate" / f"{a.clip}_ball_tracks{suf}.json").write_text(json.dumps(tracks, ensure_ascii=False, indent=1))
    print(f"[{a.clip}] th={th} min-len={a.min_len}  {len(tracks)} 条球事件轨迹，"
          f"覆盖帧 {len(present)}/{len(d)} ({len(present)/len(d)*100:.1f}%)")

    # montage：每片段取首帧作底图，叠球心连线和数字
    palette = [(0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 255, 0), (255, 128, 0)]
    cells = []
    for i, e in enumerate(tracks):
        fn = present[e["frames"][0]][3]
        img = cv2.imread(str(AW / a.clip / fn))
        if img is None:
            continue
        small = cv2.resize(img, (480, 270))
        col = palette[i % len(palette)]
        pts = [(int((c[0] / 1920) * 480), int((c[1] / 1080) * 270)) for c in e["centers"]]
        for j in range(len(pts) - 1):
            cv2.line(small, pts[j], pts[j + 1], col, 2)
        for p in pts:
            cv2.circle(small, p, 4, col, -1)
        cv2.putText(small, f"#{i+1}:{e['frames'][0]}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
        cells.append(small)
    cols = 4
    rows = max(1, math.ceil(len(cells) / cols))
    grid = np.zeros((rows * 270, cols * 480, 3), np.uint8)
    for i, c in enumerate(cells):
        r, c0 = divmod(i, cols)
        grid[r * 270:(r + 1) * 270, c0 * 480:(c0 + 1) * 480] = c
    out = AW / "validate" / f"{a.clip}_ball_tracks{suf}_overview.jpg"
    cv2.imwrite(str(out), grid)
    print(f"→ {out.name}  ({len(cells)} 条轨迹可视化)")


if __name__ == "__main__":
    main()
