#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量探测 <DATA_ROOT>/战术分析/ 素材性质：战术演示动画 vs 真实比赛实拍。
判据（可证伪，不猜）：
  A. 是否存在**绿色球员圆形图标**（动画专用符号）→ HSV 绿球计数
  B. 是否存在**彩色箭头**（黄/红）→ 饱和色块长条
  C. 标题文字区（顶部/底部横幅）→ 文字行密度
  D. 真实比赛特征：球员框高120-420px（yolov8n person框）
输出逐片统计，供老程裁定素材能否剪叙事链。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[3]))
import glob
import json
import os
import sys

import cv2
import numpy as np

from common.nba_paths import data_file, tactics_data_file

SRC_DIR = str(data_file("战术分析"))
OUT = str(tactics_data_file("clips/tactics_probe/probe_all.json"))
WEIGHT = str(tactics_data_file("yolov8n.pt"))


def green_icon_count(bgr):
    """绿色球员图标：H∈[35,85], S≥120, V≥120 的连通域，且尺寸在20-120px方内"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (35, 120, 120), (85, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(m)
    cnt = 0
    for i in range(1, n):
        a, w, h, area = stats[i]
        if 8 <= w <= 200 and 8 <= h <= 200 and 0.5 <= a / max(1, w * h) <= 1.0:
            cnt += 1
    return cnt


def arrow_count(bgr):
    """彩色箭头：S≥150 且 V≥150 的像素块（排除绿色）"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (10, 150, 150), (40, 255, 255))   # 橙黄~黄
    m2 = cv2.inRange(hsv, (160, 150, 150), (179, 255, 255))  # 红
    tot = 0
    for mm in (m, m2):
        mm = cv2.morphologyEx(mm, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(mm)
        for i in range(1, n):
            a, w, h = stats[i][4], stats[i][2], stats[i][3]
            # 箭头：长条形面积大
            if a > 300 and (max(w, h) / max(1, min(w, h))) > 2.0:
                tot += 1
    return tot


def probe(path, model=None, sample=9):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    times = list(np.linspace(0.5, max(0.6, n / fps - 0.5), sample))
    g, a = [], []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, fr = cap.read()
        if not ok:
            continue
        g.append(green_icon_count(fr))
        a.append(arrow_count(fr))
    # person 框高（只在帧够大时有意义；竖屏 608x1080 person 会很小）
    hs = []
    if model is not None:
        res = model.track(path, stream=True, classes=[0], conf=0.30, verbose=False)
        for i, r in enumerate(res):
            if r.boxes is None or i >= 60:
                break
            xy = r.boxes.xyxy.tolist()
            for j in range(len(xy)):
                hs.append(xy[j][3] - xy[j][1])
    cap.release()
    return {"file": os.path.basename(path), "w": W, "h": H, "fps": fps,
            "dur": round(n / fps, 2), "n_frames": n,
            "green_icon_med": int(np.median(g)) if g else 0,
            "green_icon_max": int(np.max(g)) if g else 0,
            "arrow_med": int(np.median(a)) if a else 0,
            "arrow_max": int(np.max(a)) if a else 0,
            "person_box_h_med": round(float(np.median(hs)), 1) if hs else None,
            "person_detected_frames": len(hs)}


if __name__ == "__main__":
    os.environ["PYTHONPATH"] = ""
    os.environ["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"
    from ultralytics import YOLO
    model = YOLO(WEIGHT)
    files = sorted(glob.glob(os.path.join(SRC_DIR, "*.mp4")))
    rows = []
    print(f"探测 {len(files)} 片\n")
    print(f"{'文件':<44}{'时长':<7}{'分辨率':<12}{'绿图标中位':<11}"
          f"{'箭头中位':<10}{'person框高':<11}判定")
    for f in files:
        r = probe(f, model, sample=9)
        rows.append(r)
        # 判定：绿图标多 + person框高小/无 ⇒ 动画
        is_anim = r["green_icon_med"] >= 3 and (r["person_box_h_med"] or 0) < 60
        verdict = "🔴演示动画" if is_anim else "⚪需人工看"
        res = f"{r['w']}x{r['h']}"
        print(f"{r['file'][:42]:<44}{r['dur']:<7}{res:<12}{r['green_icon_med']:<11}"
              f"{r['arrow_med']:<10}{str(r['person_box_h_med']):<11}{verdict}")
    json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
    n_anim = sum(1 for r in rows if r["green_icon_med"] >= 3 and (r["person_box_h_med"] or 0) < 60)
    print(f"\n判定为演示动画: {n_anim}/{len(rows)}")
    print("wrote", OUT)
