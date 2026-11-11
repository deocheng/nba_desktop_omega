#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整比赛候选体检：不目视，只测三项可算指标，判断哪场**适合自动定位回合**。
① 比分条强度：底部条带内"高亮文字像素"占比（有比分条才好定位回合）
② 分辨率/帧率一致性
③ 中段采样：画面是否为真比赛（运动活跃度 > 阈值），排除黑屏/静止/广告
取样：全片均匀 12 点，每点取 1 帧。
"""
import glob
import os
import sys

import cv2
import numpy as np


def band_score(fr, y0f=0.80, y1f=0.96):
    """底部条带内亮像素(文字/图形)占比 + 边缘密度"""
    h, w = fr.shape[:2]
    band = fr[int(h * y0f):int(h * y1f), :]
    g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    bright = float(np.mean(g > 200))
    edges = float(np.mean(cv2.Canny(g, 80, 200) > 0))
    return bright, edges


def probe(path, n_sample=12):
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if n <= 0 or fps <= 0:
        cap.release()
        return None
    idxs = [int(n * (i + 0.5) / n_sample) for i in range(n_sample)]
    br, ed, act = [], [], []
    prev = None
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            continue
        b, e = band_score(fr)
        br.append(b); ed.append(e)
        g = cv2.cvtColor(cv2.resize(fr, None, fx=0.25, fy=0.25), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            act.append(float(np.mean(cv2.absdiff(g, prev))))
        prev = g
    cap.release()
    return {"file": os.path.basename(path), "w": W, "h": H, "fps": fps,
            "dur_min": round(n / fps / 60, 1),
            "band_bright": round(float(np.mean(br)), 4),
            "band_edge": round(float(np.mean(ed)), 4),
            "act_med": round(float(np.median(act)), 2) if act else None}


if __name__ == "__main__":
    pats = sys.argv[1:] if len(sys.argv) > 1 else []
    files = []
    for p in pats:
        files += sorted(glob.glob(p))
    print(f"{'时长':<7}{'分辨率':<11}{'fps':<5}{'比分条亮':<10}{'比分条边':<10}{'活跃中位':<9}文件")
    print("-" * 110)
    rows = []
    for f in files:
        r = probe(f)
        if not r:
            print("  ❌ 读取失败:", os.path.basename(f)[:50]); continue
        rows.append(r)
        res = f"{r['w']}x{r['h']}"
        print(f"{r['dur_min']:<7}{res:<11}{r['fps']:<5.0f}"
              f"{r['band_bright']:<10}{r['band_edge']:<10}{str(r['act_med']):<9}"
              f"{r['file'][:44]}")
    print("\n=== 适配度排序（比分条越清晰越好定位回合）===")
    for r in sorted(rows, key=lambda x: -(x["band_edge"] * 2 + x["band_bright"])):
        score = r["band_edge"] * 2 + r["band_bright"]
        print(f"  {score:<7.4f} {r['file'][:44]:<46} 活跃={r['act_med']}")
