#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整帧分块 OCR —— 一次性定位画面里任何位置的可读数字（记分牌/时钟）。

不猜位置：把画面切成网格，每块单独 OCR；用「多帧读数一致 + 含 2 位数字」
作为真记分牌判据（噪声块读数会跳变，真数字块会稳定或规律递减）。

用法：grid_ocr.py <src> <t0> <dur> [nx] [ny]
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


def ocr(img, psm=6, wl="0123456789"):
    ensure()
    p = os.path.join(SCRATCH, "grid_ocr.png")
    cv2.imwrite(p, img)
    args = [TESS, p, "stdout", "--psm", str(psm)]
    if wl:
        args += ["-c", f"tessedit_char_whitelist={wl}"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.decode("utf-8", "ignore").strip()


def block_enhance(b):
    """块预处理：3x 上采样 + CLAHE + Otsu（含原图，三取一）。"""
    g = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if b.ndim == 3 else b
    up = cv2.resize(g, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    cl = cv2.createCLAHE(3.0, (8, 8)).apply(up)
    _, ot = cv2.threshold(cl, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return [up, cl, ot]


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]); dur = float(sys.argv[3])
    nx = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    ny = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    frs = grab_seq(src, t0, t0 + dur, 1.0)
    H, W = frs[0].shape[:2]
    print(f"抽流 {len(frs)} 帧  {W}x{H}  切 {nx}x{ny}={nx*ny} 块")
    if not frs:
        print("无帧"); sys.exit(1)
    bw, bh = W // nx, H // ny
    print(f"每块 {bw}x{bh}")

    rows = []
    for j in range(ny):
        for i in range(nx):
            x0, x1 = i * bw, (i + 1) * bw
            y0, y1 = j * bh, (j + 1) * bh
            reads = []
            for fr in frs:
                b = fr[y0:y1, x0:x1]
                best = ""
                for v in block_enhance(b):
                    for psm in (6, 7):
                        t = ocr(v, psm)
                        if t and len(t) > len(best):
                            best = t
                reads.append(best)
            clean = [r for r in reads if r]
            two = [r for r in clean if len(r) == 2 and r.isdigit()]
            cnt = Counter(clean).most_common(3)
            stab = len(cnt) > 0 and cnt[0][1] >= max(3, len(clean) * 0.35)
            flag = "★★" if (len(two) >= 2 and stab) else ("★" if two else " ")
            rows.append({"i": i, "j": j, "x0": x0, "y0": y0,
                         "reads": reads, "two": two, "top": cnt})
            print(f"{flag} blk(i={i},j={j}) x{x0}~{x1} y{y0}~{y1}: "
                  f"2位读数={len(two)}/{len(clean)} 常见={cnt[:2]}")

    print("\n=== ★★ 命中块（2位数字且读数稳定）===")
    hit = [r for r in rows if len(r["two"]) >= 2]
    for r in hit:
        print(f"  blk(i={r['i']},j={r['j']}) x{r['x0']}~{r['x0']+bw} "
              f"y{r['y0']}~{r['y0']+bh}")
        print(f"     2位序列: {r['two']}")
        print(f"     全部读数: {r['reads']}")

    import json
    json.dump({"src": os.path.basename(src), "bw": bw, "bh": bh, "rows": rows},
              open("/tmp/grid_ocr.json", "w"), ensure_ascii=False, indent=1)
    print("\nwrote /tmp/grid_ocr.json")
