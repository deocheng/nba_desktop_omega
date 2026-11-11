#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多时刻粗 ASCII 拼图 —— 让 AI「看见」转播风格并定位记分牌。

用法：ascii_multi.py <src> <t1> <t2> ... [--w 60]
输出：每时刻一张粗 ASCII，横向拼成一张对照图（含 y/x 刻度）
"""
import os
import subprocess
import sys

import cv2
import numpy as np

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
RAMP = " .:-=+*#%@"


def frame_at(src, t, w=1920, h=1080):
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "f.png")
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t} -i "{src}" '
                   f'-frames:v 1 -vf "scale={w}:{h}" "{out}"',
                   shell=True, capture_output=True)
    return cv2.imread(out)   # 注意：必须存 .png，存 .mp4 读不出（坑②）


def grid(fr, W):
    H = fr.shape[0]
    h = max(1, int(round(W * H / fr.shape[1] / 2.1)))
    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (W, h), interpolation=cv2.INTER_AREA)
    return g


def ascii_of(g):
    return ["".join(RAMP[min(9, int(v / 25.6))] for v in row) for row in g]


if __name__ == "__main__":
    argv = sys.argv[1:]
    W = 60
    if "--w" in argv:
        i = argv.index("--w")
        W = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]
    src = args[0]
    ts = [float(x) for x in args[1:]]
    print(f"共 {len(ts)} 时刻，每格≈{1920//W}px(1920宽基准)")
    blocks = []
    for t in ts:
        fr = frame_at(src, t)
        if fr is None:
            print(f"t={t} 读帧失败"); continue
        g = grid(fr, W)
        blocks.append((t, ascii_of(g)))
    if not blocks:
        sys.exit(1)
    n = len(blocks)
    H = blocks[0][1].__len__()
    print("时刻   " + "".join(f"t={int(t):<{W-4}}" for t, _ in blocks))
    for r in range(H):
        y0 = r * 1080 // H
        line = "".join(f"y{y0:<3d} " + blocks[i][1][r] + "  " for i in range(n))
        print(line)
    print("\n时刻: " + "  ".join(f"{t}s" for t, _ in blocks))
    print("\n判读：记分牌 = 暗色/亮色矩形块内含小字；字幕条 = 底部横向亮带")
