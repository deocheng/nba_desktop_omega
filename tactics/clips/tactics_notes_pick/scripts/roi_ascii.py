#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精细 ASCII 渲染记分牌 ROI 内部结构 —— 看清有几个数字块、各在哪个 x。
用时域中位 + 阈值增强，让笔画凸显（AI 读不了图，靠这个「看」）。

用法：roi_ascii.py <src> <t0> <dur> [x0 y0 x1 y1]
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


def render(g2d, xstep=2, title=""):
    """g2d: 灰度二维数组。x 方向每 xstep px 一字符，y 方向 1px 一行（可用 ystep 抽）。"""
    H, W = g2d.shape
    lines = []
    for y in range(H):
        row = "".join(RAMP[min(9, int(v / 25.6))]
                      for v in g2d[y, ::xstep])
        lines.append(f"{y:>3d}|{row}|")
    # x 刻度
    tick = "   " + "".join(str((i * xstep) // 100 % 10) if (i * xstep) % 100 < xstep else " "
                           for i in range(len(g2d[0, ::xstep])))
    tick2 = "   " + "".join(str(((i * xstep) // 10) % 10) if (i * xstep) % 10 < xstep else " "
                            for i in range(len(g2d[0, ::xstep])))
    return f"{title}\n{tick2}\n{tick}\n" + "\n".join(lines)


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]); dur = float(sys.argv[3])
    x0, y0, x1, y1 = (955, 925, 1215, 1005)
    if len(sys.argv) > 7:
        x0, y0, x1, y1 = [int(v) for v in sys.argv[4:8]]

    frs = grab_seq(src, t0, t0 + dur, 1.0)
    print(f"抽流 {len(frs)} 帧  ROI=x{x0}~{x1},y{y0}~{y1} (1920x1080 原生)")
    if not frs:
        print("无帧"); sys.exit(1)

    stack = np.stack([cv2.cvtColor(f[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY) for f in frs])
    med = np.median(stack, axis=0).astype(np.uint8)
    print(f"ROI 尺寸 {med.shape[1]}x{med.shape[0]}")

    print("\n########## A. 时域中位（原始灰度）##########")
    print(render(med, 2, f"x 方向每字符 = 2px；总宽 {med.shape[1]}px"))

    print("\n########## B. Otsu 阈值（笔画凸显）##########")
    _, b = cv2.threshold(cv2.resize(med, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC),
                         0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    print(render(b, 2, "3x 上采样后 Otsu"))
