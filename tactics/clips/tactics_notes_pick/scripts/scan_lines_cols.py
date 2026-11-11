#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行+列双向窄条扫描：在给定区域内精确定位「2 位数字」的行列坐标。

判据：某行/列的 OCR 在多帧中读出**稳定**的 2 位数字 ⇒ 记分牌字段
     （噪声块读数每帧都变，稳定率≈0）

用法：scan_lines_cols.py <src> <t0> <dur> <x0> <y0> <x1> <y1> [row_step] [col_step]
"""
import os
import re
import subprocess
import sys
from collections import Counter

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")


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


def ocr(img, psm=7, wl="0123456789"):
    ensure()
    p = os.path.join(SCRATCH, "lc_ocr.png")
    cv2.imwrite(p, img)
    args = [TESS, p, "stdout", "--psm", str(psm)]
    if wl:
        args += ["-c", f"tessedit_char_whitelist={wl}"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=12)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.decode("utf-8", "ignore").strip()


def enh(b):
    g = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if b.ndim == 3 else b
    up = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    cl = cv2.createCLAHE(3.0, (8, 8)).apply(up)
    _, ot = cv2.threshold(cl, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return [up, ot, 255 - ot]


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]); dur = float(sys.argv[3])
    x0, y0, x1, y1 = [int(v) for v in sys.argv[4:8]]
    rstep = int(sys.argv[8]) if len(sys.argv) > 8 else 6
    cstep = int(sys.argv[9]) if len(sys.argv) > 9 else 30
    frs = grab_seq(src, t0, t0 + dur, 1.0)
    print(f"抽流 {len(frs)} 帧  区域 x{x0}~{x1} y{y0}~{y1}  行步长={rstep} 列步长={cstep}")
    if not frs:
        print("无帧"); sys.exit(1)

    def read_all(b):
        best = ""
        for v in enh(b):
            for psm in (7, 6, 8):
                t = ocr(v, psm)
                if t and len(t) > len(best):
                    best = t
        return best

    print("\n=== 行扫描（每行是一条横向窄条）===")
    row_hits = []
    for ya in range(y0, y1, rstep):
        yb = min(ya + rstep, y1)
        reads = [read_all(fr[ya:yb, x0:x1]) for fr in frs]
        clean = [r for r in reads if r]
        two = [r for r in clean if len(r) == 2 and r.isdigit()]
        c = Counter(clean).most_common(2)
        top_rate = (c[0][1] / len(clean)) if clean else 0
        flag = "★★" if len(two) >= 2 and top_rate >= 0.5 else ("★" if two else " ")
        print(f"{flag} y={ya}~{yb:<5} 2位={len(two)}/{len(clean)} 稳定率={top_rate:.2f} "
              f"常见={c[:2]} 全部={reads[:6]}")
        if two:
            row_hits.append((ya, yb, two, reads))

    print("\n=== 列扫描（每列是一条纵向窄条）===")
    col_hits = []
    for xa in range(x0, x1, cstep):
        xb = min(xa + cstep, x1)
        reads = [read_all(fr[y0:y1, xa:xb]) for fr in frs]
        clean = [r for r in reads if r]
        two = [r for r in clean if len(r) == 2 and r.isdigit()]
        c = Counter(clean).most_common(2)
        top_rate = (c[0][1] / len(clean)) if clean else 0
        flag = "★★" if len(two) >= 2 and top_rate >= 0.5 else ("★" if two else " ")
        print(f"{flag} x={xa}~{xb:<5} 2位={len(two)}/{len(clean)} 稳定率={top_rate:.2f} "
              f"常见={c[:2]} 全部={reads[:6]}")
        if two:
            col_hits.append((xa, xb, two, reads))

    print("\n=== 汇总 ===")
    for ya, yb, two, reads in row_hits:
        print(f"  行 y={ya}~{yb}: 2位 {two[:10]}  全部 {reads[:8]}")
    for xa, xb, two, reads in col_hits:
        print(f"  列 x={xa}~{xb}: 2位 {two[:10]}  全部 {reads[:8]}")
    if not row_hits and not col_hits:
        print("  无 2 位数字命中 ⇒ 该区域无记分牌数字")
