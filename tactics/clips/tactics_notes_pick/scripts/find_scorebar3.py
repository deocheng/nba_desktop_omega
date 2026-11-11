#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两条正交路径找记分牌：
  A) 整帧 OCR（多 psm / 多预处理）—— 记分牌在画面里就有机会读出数字
  B) 长水平直线检测（Canny + 水平线投影）—— 记分牌矩形边框会形成长水平线

用法：find_scorebar3.py <src> <t> [<t2> ...]
"""
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"


def frame_at(path, t, w=1920, h=1080):
    out = "/tmp/_fb3.png"
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t} -i "{path}" '
                   f'-frames:v 1 -vf "scale={w}:{h}" {out}', shell=True)
    return cv2.imread(out)


def ocr(img, psm, wl=None, tag=""):
    p = "/tmp/_fb3_ocr.png"
    cv2.imwrite(p, img)
    args = [TESS, p, "stdout", "--psm", str(psm)]
    if wl:
        args += ["-c", f"tessedit_char_whitelist={wl}"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=25)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.decode("utf-8", errors="ignore").strip()


def full_ocr(fr, tag):
    """整帧 OCR，多种预处理。"""
    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    res = {}
    # 1) 原图灰度
    res["gray_psm11"] = ocr(g, 11)
    # 2) 二值化（亮底黑字）
    _, b1 = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    res["otsu_psm11"] = ocr(b1, 11)
    res["otsu_psm11_num"] = ocr(b1, 11, wl="0123456789")
    # 3) 反相（二值化黑底白字）
    res["inv_psm11"] = ocr(255 - b1, 11)
    # 4) CLAHE 增强
    cl = cv2.createCLAHE(3.0, (8, 8)).apply(g)
    res["clahe_psm11"] = ocr(cl, 11)
    print(f"\n[{tag}] 整帧 OCR:")
    any_hit = False
    for k, v in res.items():
        if v:
            any_hit = True
            print(f"  {k:<16}: {v[:120]!r}")
    if not any_hit:
        print("  （全部为空）→ 该帧画面里没有可读的文本叠加层，或记分牌不在此帧")
    return res


def long_hlines(fr, min_ratio=0.35, tag=""):
    """长水平线检测：Hough 找 len > min_ratio*W 的水平线段。"""
    H, W = fr.shape[:2]
    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    e = cv2.Canny(g, 50, 150)
    lines = cv2.HoughLinesP(e, 1, np.pi / 360, threshold=120,
                            minLineLength=int(W * min_ratio), maxLineGap=3)
    print(f"\n[{tag}] 长水平线 (>{min_ratio:.0%}W) 共 {0 if lines is None else len(lines)} 条:")
    segs = []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            segs.append((int(y1), int(x1), int(x2), int(x2 - x1)))
    for y, x1, x2, ln in sorted(segs):
        print(f"  y={y:<5d} x={x1}..{x2}  len={ln}")

    # 投影法补充：Canny 像素的水平游程
    rowmax = np.zeros(H, int)
    for y in range(H):
        xs = np.where(e[y] > 0)[0]
        if len(xs) >= 2:
            # 最长连续段
            best = run = 1
            for i in range(1, len(xs)):
                run = run + 1 if xs[i] - xs[i - 1] <= 2 else 1
                best = max(best, run)
            rowmax[y] = best
    thr = W * min_ratio
    ys = np.where(rowmax >= thr)[0]
    print(f"  投影法（行内最长连续边 ≥ {thr:.0f}px）命中行: {ys.tolist()[:40]}")
    return segs, rowmax, ys


if __name__ == "__main__":
    src = sys.argv[1]
    ts = [float(x) for x in sys.argv[2:]] or [456.0]
    for t in ts:
        fr = frame_at(src, t)
        if fr is None:
            print("读帧失败", t); continue
        H, W = fr.shape[:2]
        print(f"\n{'='*70}\nt={t}s  {W}x{H}")
        full_ocr(fr, f"t={t}")
        long_hlines(fr, 0.30, f"t={t}")
