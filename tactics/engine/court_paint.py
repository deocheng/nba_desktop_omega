#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场涂装（紫色油漆区）探针 —— 为「球场识别」提供稠密、自动的位姿线索。

为什么用涂装
------------
球场线（白线）虽多，但观众席大量白/亮像素会干扰基于亮度的线拟合。
而 TOR 主场的**油漆区是紫色**（高饱和、色相独特），其形状是「球场坐标下的
刚性多边形（lane 16ft×19ft + FT 圆）」，投影到图像后是一组非常有约束力的四边形/圆锥曲线
⇒ 用「预测涂装区 vs 实测紫色掩膜」的 IoU 作目标函数，可以自动反解相机位姿。

用法:
  python engine/court_paint.py --render w1 f00001.jpg
  python engine/court_paint.py --stats
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
PUR_H = (115, 170)
PUR_S, PUR_V = 60, 40


def purple_mask(img, scale=0.25):
    s = cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)),
                   interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(s, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] >= PUR_H[0]) & (hsv[:, :, 0] <= PUR_H[1]) &
         (hsv[:, :, 1] >= PUR_S) & (hsv[:, :, 2] >= PUR_V)).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n > 1:
        i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        m = (lab == i).astype(np.uint8)
    return cv2.resize(m * 255, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)


def render(win, frame, out=None):
    img = cv2.imread(str(AW / win / frame))
    m = purple_mask(img)
    ov = img.copy()
    ov[m > 0] = (ov[m > 0] * 0.35 + np.array([0, 255, 0]) * 0.65).astype(np.uint8)
    cnt, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnt:
        if cv2.contourArea(c) < 500:
            continue
        cv2.polylines(ov, [c], True, (0, 255, 255), 2)
        ap = cv2.approxPolyDP(c, 6.0, True)
        for p in ap.reshape(-1, 2):
            cv2.circle(ov, tuple(p), 5, (0, 0, 255), -1)
            cv2.putText(ov, f"{p[0]},{p[1]}", (p[0] + 5, p[1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    cv2.putText(ov, f"{win} {frame} purple={m.mean()/255*100:.1f}%", (20, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    out = out or str(MS / f"purple_{win}_{Path(frame).stem}.jpg")
    cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}")


def stats():
    for w in ("w1", "w2", "w3", "w4"):
        fs = sorted((AW / w).glob("f*.jpg"))
        for fi in (0, len(fs) // 2, len(fs) - 1):
            img = cv2.imread(str(fs[fi]))
            m = purple_mask(img)
            print(f"  {w} {fs[fi].name} purple 占比 {m.mean()/255*100:5.1f}%  "
                  f"质心 {np.argwhere(m>0).mean(axis=0).round(0) if (m>0).any() else None}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", nargs=2, default=None, metavar=("WIN", "FRAME"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.render:
        render(a.render[0], a.render[1], a.out)
    if a.stats:
        stats()


if __name__ == "__main__":
    main()
