#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场线提取（用户思路：涂装是变量，边线/中线/三分线是常量）。

预处理链
--------
  ① ROI：用 court_gate 的上包络（RANSAC 二次）取「地板及以下」区域，去掉观众席
     —— 观众席是亮像素最多的地方，不先剔除无法做线检测。
  ② 亮细线增强：白 top-hat（大核）—— 球场线永远比其邻域**亮且细**；
     木地板/涂装/球员身体都是「块状」，top-hat 只保留比核更细的亮结构。
  ③ 归一化 + 阈值 → 二值线像素图。
  ④ LSD 直线段检测（退化时回退 HoughLinesP）。
  ⑤ 目视验收：叠加渲染。

用法:
  python engine/court_lines.py --window w1 --frame f00010.jpg
  python engine/court_lines.py --window w1 --frame f00010.jpg --kernel 21 --thr 0.18
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


def floor_roi(img, dilate=25):
    """地板 ROI：上包络以下 ∩ 地板色掩膜（膨胀，容忍人物遮挡）⇒ 剔除观众席与场边。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from court_gate import env_at, floor_mask, top_envelope
    m, sc = floor_mask(img)
    if m is None:
        return np.full(img.shape[:2], 255, np.uint8), None
    env = top_envelope(m)
    roi = np.zeros(img.shape[:2], np.uint8)
    if env is not None:
        for x in range(img.shape[1]):
            t = int(np.clip(env_at(env, float(x)), 0, img.shape[0] - 1))
            roi[t:, x] = 255
    mf = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate | 1, dilate | 1))
    mf = cv2.morphologyEx(mf, cv2.MORPH_CLOSE, k)
    mf = cv2.dilate(mf, k)
    return cv2.bitwise_and(roi, mf), env


def line_response(gray, kernel=21):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
    th = cv2.GaussianBlur(th, (3, 3), 0)
    return th


def binarize(resp, roi, thr=0.18):
    r = resp.astype(np.float32)
    v = np.percentile(r[roi > 0], 99.0) if (roi > 0).any() else 1.0
    b = ((r >= thr * max(v, 1.0)) & (roi > 0)).astype(np.uint8) * 255
    b = cv2.morphologyEx(b, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return b


def segments(binary, min_len=60):
    try:
        lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        lines = lsd.detect(binary)[0]
        if lines is None:
            return []
        segs = [(l[0][0], l[0][1], l[0][2], l[0][3]) for l in lines]
    except Exception:
        segs = []
    if not segs:
        ls = cv2.HoughLinesP(binary, 1, np.pi / 360, 40, minLineLength=min_len, maxLineGap=8)
        if ls is None:
            return []
        segs = [tuple(v) for v in np.asarray(ls).reshape(-1, 4).astype(float)]
    out = []
    for x1, y1, x2, y2 in segs:
        if np.hypot(x2 - x1, y2 - y1) >= min_len:
            out.append((float(x1), float(y1), float(x2), float(y2)))
    return out


def angle_hist(segs, bins=36):
    a = np.array([np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180 for x1, y1, x2, y2 in segs])
    if len(a) == 0:
        return a, np.zeros(bins)
    h, _ = np.histogram(a, bins=bins, range=(0, 180),
                        weights=[np.hypot(x2 - x1, y2 - y1) for x1, y1, x2, y2 in segs])
    return a, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default=None)
    ap.add_argument("--frame", default=None)
    ap.add_argument("--img", default=None, help="直接给图像路径（如稳定化时间中值底板）")
    ap.add_argument("--kernel", type=int, default=21)
    ap.add_argument("--thr", type=float, default=0.18)
    ap.add_argument("--min-len", type=int, default=60)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.img:
        img = cv2.imread(a.img)
        tag = Path(a.img).stem
    else:
        img = cv2.imread(str(AW / a.window / a.frame))
        tag = f"{a.window}_{Path(a.frame).stem}"
    if img is None:
        raise SystemExit("读不到图像")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    roi, env = floor_roi(img)
    resp = line_response(gray, a.kernel)
    b = binarize(resp, roi, a.thr)
    segs = segments(b, a.min_len)

    ov = img.copy()
    ov[b > 0] = (0, 255, 255)
    for x1, y1, x2, y2 in segs:
        L = np.hypot(x2 - x1, y2 - y1)
        col = (0, 255, 0) if L > 200 else ((0, 165, 255) if L > 120 else (255, 0, 255))
        cv2.line(ov, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
    if env is not None:
        sys_pts = []
        for x in range(0, img.shape[1], 8):
            from court_gate import env_at
            t = env_at(env, float(x))
            if t is not None and -100 < t < img.shape[0] + 100:
                sys_pts.append((x, int(t)))
        if len(sys_pts) > 1:
            cv2.polylines(ov, [np.array(sys_pts).reshape(-1, 1, 2)], False, (255, 0, 255), 3)

    _, ah = angle_hist(segs)
    txt = f"{tag} segs={len(segs)}  linepx={b.mean()/255*100:.2f}%"
    cv2.putText(ov, txt, (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2, cv2.LINE_AA)
    out = a.out or str(MS / f"courtlines_{tag}.jpg")
    cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}  {txt}")
    dom = np.argsort(ah)[::-1][:6]
    print("  主导方向（度:权重）: " + ", ".join(f"{int(i*5)}°:{ah[i]:.0f}" for i in dom if ah[i] > 0))
    np.save(MS / f"lineseg_{tag}.npy", np.array(segs))


if __name__ == "__main__":
    main()
