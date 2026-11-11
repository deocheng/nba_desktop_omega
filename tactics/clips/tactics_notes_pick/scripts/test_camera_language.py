#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证「镜头语言」判据：完整进攻须含**远景段落**（过半场）。
老程 2026-10-07 批评：poss_a 只有一次传球+一次上篮，缺过半场，其余是出手镜头/出手以后。
假说：过半场 = 远景(player框高小) ⇒ 完整进攻= 远景段 + 终结段 都要有。
测法：分段统计 yolov8n person 框高中位（= camera_scale_h），只算相对高低。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import os
import statistics
import subprocess
import sys

import cv2
import numpy as np

from common.nba_paths import data_file, tactics_data_file

os.environ["PYTHONPATH"] = ""
os.environ["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"
os.environ["HF_HUB_OFFLINE"] = "1"

SRC = str(data_file("比赛录像/2025-26/25-26常规赛/2025.12/2025.12.17 NBA杯决赛 马刺 vs 尼克斯/2025.12.17 NBA杯 马刺 vs 尼克斯 上半场.mp4"))
WEIGHT = str(tactics_data_file("yolov8n.pt"))

SEGMENTS = [
    ("A候选 451.6-459.4", 451.6, 7.8),
    ("前段 435.0-441.0", 435.0, 6.0),
    ("前段 441.0-447.0", 441.0, 6.0),
    ("后段 448.0-454.0", 448.0, 6.0),
    ("后段 454.0-460.0", 454.0, 6.0),
    ("对照 430.0-436.0", 430.0, 6.0),
]


def probe(src, t0, dur, tmp="/tmp/_seg.mp4"):
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {dur} -an -c:v libx264 -preset veryfast -crf 20 '
                   f'-pix_fmt yuv420p {tmp}', shell=True)
    from ultralytics import YOLO
    m = YOLO(WEIGHT)
    hs, npf = [], []
    res = m.track(tmp, stream=True, classes=[0], conf=0.30, verbose=False)
    for r in res:
        if r.boxes is None:
            continue
        xy = r.boxes.xyxy.tolist()
        npf.append(len(xy))
        for j in range(len(xy)):
            hs.append(xy[j][3] - xy[j][1])
    if not hs:
        return None
    hs_sorted = sorted(hs)
    return {"h_med": round(statistics.median(hs), 1),
            "h_p25": round(hs_sorted[len(hs_sorted) // 4], 1),
            "h_p75": round(hs_sorted[3 * len(hs_sorted) // 4], 1),
            "people_med": round(statistics.median(npf), 1),
            "people_min": min(npf), "n": len(hs)}


if __name__ == "__main__":
    print(f"{'段':<22}{'框高中位':<10}{'p25':<8}{'p75':<8}{'人/帧中位':<11}{'最少':<6}{'样本':<7}镜头判断")
    rows = []
    for name, t0, dur in SEGMENTS:
        r = probe(SRC, t0, dur)
        if not r:
            print(f"{name:<22}❌ 未检出 person"); continue
        rows.append((name, r))
        # 判据：框高中位 < 150 视为远景(过半场)；> 200 视为特写(篮下)
        tag = "🔴特写/篮下" if r["h_med"] >= 200 else (
              "🟡中景" if r["h_med"] >= 150 else "🟢远景/过半场")
        print(f"{name:<22}{r['h_med']:<10}{r['h_p25']:<8}{r['h_p75']:<8}"
              f"{r['people_med']:<11}{r['people_min']:<6}{r['n']:<7}{tag}")
    if rows:
        print("\n=== 结论 ===")
        a = [r for n, r in rows if n.startswith("A候选")]
        pre = [r for n, r in rows if n.startswith("前段") or n.startswith("对照")]
        if a and pre:
            am = statistics.mean(x["h_med"] for x in a)
            pm = statistics.mean(x["h_med"] for x in pre)
            print(f"  A候选(被老程判缺过半场) 框高均值 = {am:.1f}")
            print(f"  前段/对照            框高均值 = {pm:.1f}")
            print(f"  ⇒ {'前段更远景(框高更小)，A更特写' if am > pm else 'A并不更特写，假设不成立'}")
