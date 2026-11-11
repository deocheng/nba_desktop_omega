#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整条底部条带渲染（静止度增强）—— 一次性看清转播叠加层的完整布局。

关键判据：记分牌 = 静止叠加层 ⇒ 用「时域中位」或「时域差分低」来提亮，
        画面内容（动的）会被压暗，从而只留下叠加层结构。

用法：strip_ascii.py <src> <t0> <dur> [y0 y1] [xstep]
"""
import os
import subprocess
import sys

import cv2
import numpy as np

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
RAMP = " .:-=+*#%@"


def grab_seq(src, t0, t1, step, w=1920, h=1080):
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)
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


def show(g2d, xstep, title):
    H, W = g2d.shape
    n = len(range(0, W, xstep))
    # 刻度：每 160px 一个标记
    t1 = "     " + "".join("|" if (i * xstep) % 160 < xstep else " " for i in range(n))
    t2 = "     " + "".join(str(((i * xstep) // 160) % 10) if (i * xstep) % 160 < xstep else " "
                           for i in range(n))
    lines = [title, t2, t1]
    for y in range(H):
        lines.append(f"{y:>4d}|" + "".join(RAMP[min(9, int(v / 25.6))]
                                           for v in g2d[y, ::xstep]) + "|")
    return "\n".join(lines)


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]); dur = float(sys.argv[3])
    y0, y1 = (880, 1020)
    xstep = 4
    a = sys.argv[4:]
    if len(a) >= 1 and a[0].isdigit():
        y0 = int(a[0])
    if len(a) >= 2 and a[1].isdigit():
        y1 = int(a[1])
    if len(a) >= 3 and a[2].isdigit():
        xstep = max(1, int(a[2]))
    frs = grab_seq(src, t0, t0 + dur, 1.0)
    print(f"抽流 {len(frs)} 帧  条带 y={y0}~{y1}  xstep={xstep}px/字符  "
          f"（列号 ×160px）")
    if not frs:
        print("无帧"); sys.exit(1)

    stack = np.stack([cv2.cvtColor(f[y0:y1, :], cv2.COLOR_BGR2GRAY) for f in frs])
    med = np.median(stack, axis=0).astype(np.uint8)
    diff = np.abs(np.diff(stack.astype(np.int16), axis=0)).mean(axis=0)
    stat = np.clip(255 - diff * 4, 0, 255).astype(np.uint8)   # 静止=亮

    # 静止度局部均值（21x21），压掉孤立噪点
    loc = cv2.filter2D(stat, -1, np.ones((15, 15), np.float32) / 225)

    print(f"\n########## A. 时域中位（灰度）y={y0}~{y1} ##########")
    print(show(med, xstep, "中位帧"))

    print("\n########## B. 静止度（差分低=亮）##########")
    print(f"差分: 中位={np.median(diff):.1f} p10={np.percentile(diff,10):.1f}")
    print(show(loc.astype(np.uint8), xstep, "静止度图：亮=静止叠加层"))
    cv2.imwrite(os.path.join(SCRATCH, "strip_median.png"), med)
    cv2.imwrite(os.path.join(SCRATCH, "strip_static.png"), loc.astype(np.uint8))
    print(f"\n图已存 {SCRATCH}/strip_median.png, strip_static.png")
