#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证记分牌 ROI 并读进攻时钟。

已定位（2026-10-07 实测）：静止叠加层在 1920x1080 下
    x≈978~1186, y≈943~986  （区域差分 0.3~1.0 vs 全画面中位 36.7）
⇒ 960x540 下 = x≈489~593, y≈471~493
之前扫「顶部 y=0~48」全错方向（那是看台噪声）。

本脚本：ROI 多尺度 OCR + 逐秒读数，检查是否出现「2 位递减序列」。

用法：verify_clock_roi.py <src> <t0> <dur> [step]
"""
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")

# 1920x1080 实测 ROI（留余量）
ROI_1080 = (955, 925, 1215, 1005)


def ensure():
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)


def grab_seq(src, t0, t1, step, w=1920, h=1080):
    ensure()
    tmp = os.path.join(SCRATCH, "seq.mp4")
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {t1 - t0} -an -vf "fps={1.0/step:.6f},scale={w}:{h}" '
                   f'-c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -g 1 "{tmp}"',
                   shell=True, capture_output=True)
    cap = cv2.VideoCapture(tmp)
    frs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frs.append(fr)
    cap.release()
    return frs


def ocr(img, psm, wl=None):
    ensure()
    p = os.path.join(SCRATCH, "roi_ocr.png")
    cv2.imwrite(p, img)
    args = [TESS, p, "stdout", "--psm", str(psm)]
    if wl:
        args += ["-c", f"tessedit_char_whitelist={wl}"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.decode("utf-8", "ignore").strip()


def variants(roi):
    """同一 ROI 的多种预处理，交给 OCR。"""
    g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    out = {}
    up = cv2.resize(g, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
    out["gray5"] = up
    out["otsu5"] = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    out["inv5"] = 255 - out["otsu5"]
    out["clahe5"] = cv2.createCLAHE(3.0, (8, 8)).apply(up)
    # 局部自适应：记分牌是暗底白字，用大核阈值分离
    out["adapt5"] = cv2.adaptiveThreshold(up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                          cv2.THRESH_BINARY, 31, 5)
    return out


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]); dur = float(sys.argv[3])
    step = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    x0, y0, x1, y1 = ROI_1080
    if len(sys.argv) > 8:
        x0, y0, x1, y1 = [int(v) for v in sys.argv[5:9]]

    frs = grab_seq(src, t0, t0 + dur, step)
    print(f"抽流 {len(frs)} 帧  t0={t0} dur={dur}s step={step}s")
    print(f"ROI = x{x0}~{x1}, y{y0}~{y1}  (1920x1080)")
    if not frs:
        print("无帧"); sys.exit(1)

    ensure()
    # 保存 ROI 放大图（供结构分析）
    big = cv2.resize(frs[0][y0:y1, x0:x1], None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(os.path.join(SCRATCH, "roi_big.png"), big)

    print("\n=== 各预处理 × 各 psm 的读数（取第 1 帧）===")
    for name, v in variants(frs[0][y0:y1, x0:x1]).items():
        for psm in (7, 6, 8, 11, 13):
            t = ocr(v, psm, "0123456789")
            if t:
                print(f"  {name:<8} psm={psm:<3} → {t!r}")
    print("\n=== 不限字符（全字）===")
    for name, v in variants(frs[0][y0:y1, x0:x1]).items():
        t = ocr(v, 7)
        if t:
            print(f"  {name:<8} psm=7 → {t!r}")

    print(f"\n=== 逐帧读数（{len(frs)} 帧，间隔 {step}s）===")
    seq = []
    for i, fr in enumerate(frs):
        roi = fr[y0:y1, x0:x1]
        best = None
        for name, v in variants(roi).items():
            t = ocr(v, 7, "0123456789")
            if t and (best is None or len(t) > len(best[1])):
                best = (name, t)
        t = round(t0 + i * step, 1)
        seq.append((t, best))
        print(f"  t={t:<8} {best[0] if best else '-':<8} {best[1] if best else '(空)'!r}")

    print(f"\nROI 放大图已存 {os.path.join(SCRATCH, 'roi_big.png')}")
    print("判读：找 2 位**递减**序列（24,23,22,…）⇒ 进攻时钟；起点≈24 ⇒ 回合开始")
