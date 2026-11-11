#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在已定位的顶部窄带内**逐行 OCR**，找出能读出 2 位数字的行 ⇒ 进攻时钟行。
逐行 = 每次一行，调用数 = 带内行数（~40 次，可接受）。
同时用「列变化率」给出行内 x 区间。

用法：scan_top_rows.py <src> <t0> <dur> [y0] [y1]
"""
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")


def ensure():
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)


def grab_seq(src, t0, t1, step, w=960, h=540):
    ensure()
    tmp = os.path.join(SCRATCH, "seq.mp4")
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {t1 - t0} -an -vf "fps={1.0/step:.6f},scale={w}:{h}" '
                   f'-c:v libx264 -preset ultrafast -crf 20 -pix_fmt yuv420p -g 1 "{tmp}"',
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
    p = os.path.join(SCRATCH, "row_ocr.png")
    cv2.imwrite(p, img)
    args = [TESS, p, "stdout", "--psm", str(psm)]
    if wl:
        args += ["-c", f"tessedit_char_whitelist={wl}"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.decode("utf-8", "ignore").strip()


def prep(g, scale=6):
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    g = cv2.createCLAHE(3.0, (8, 8)).apply(g)
    return g


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]); t1 = float(sys.argv[3])
    y0 = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    y1 = int(sys.argv[5]) if len(sys.argv) > 5 else 45
    frs = grab_seq(src, t0, t1, 0.5)
    print(f"抽流 {len(frs)} 帧 t0={t0} t1={t1} step=0.5s；扫描 y={y0}~{y1}")
    if not frs:
        print("无帧"); sys.exit(1)

    W = frs[0].shape[1]
    print(f"\n{'y带':<10}{'逐帧读数（每帧一行 OCR）'}")
    winners = []
    for ya in range(y0, y1, 3):
        yb = min(ya + 3, y1)
        seqs = []
        for fr in frs:
            g = cv2.cvtColor(fr[ya:yb, :], cv2.COLOR_BGR2GRAY)
            seqs.append(ocr(prep(g), psm=7))
        clean = [s for s in seqs if s]
        n2 = sum(1 for s in clean if len(s) == 2)
        flag = "★" if n2 >= max(3, len(clean) * 0.4) and len(clean) >= 3 else " "
        print(f"{flag} y={ya}~{yb:<6} [{len(clean)}/{len(seqs)} 有读数, 2位数 {n2}] "
              f"{clean[:14]}")
        if flag == "★":
            winners.append((ya, yb, clean))

    if winners:
        print("\n=== 命中带 ===")
        for ya, yb, clean in winners:
            # 2 位数字最多的
            two = [s for s in clean if len(s) == 2]
            print(f"  y={ya}~{yb}: 2位数字样本 {two[:20]}")
    else:
        print("\n=== 无命中。候选：放宽到 y=-5~90 / 加 x 切段 / 换 --psm ===")
    cv2.imwrite(os.path.join(SCRATCH, "row_sample.png"),
                frs[len(frs) // 2][max(0, y0 - 5):y1 + 5, :])
    print(f"样本带已存 {os.path.join(SCRATCH, 'row_sample.png')}")
