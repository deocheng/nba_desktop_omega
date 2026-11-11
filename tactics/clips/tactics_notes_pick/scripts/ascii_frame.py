#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把视频帧降采样成 ASCII 亮度网格 —— 让 AI「看见」画面布局（不依赖读图能力）。

用途：定位记分牌在画面中的位置（明暗块形状）、判断景别（人物大小）、
      判断是否有字幕/水印/转播条。所有判断基于像素值，不靠猜。

用法：
  ascii_frame.py <video> <t> [w_chars] [out_png]
  ascii_frame.py <video> <t0> <t1> <step>     # 多帧序列
"""
import os
import subprocess
import sys

import cv2
import numpy as np

# 亮度 → 字符（8 级）
RAMP = " .:-=+*#%@"


def ascii_grid(fr, W=64):
    """输出 W 字符宽的 ASCII 亮度图。返回 (文本, 实际网格数组)。"""
    H = fr.shape[0]
    h = max(1, int(round(W * H / fr.shape[1] / 2.1)))  # 字符高宽比 ~2.1
    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (W, h), interpolation=cv2.INTER_AREA)
    lines = []
    for row in g:
        lines.append("".join(RAMP[min(9, int(v / 25.6))] for v in row))
    return "\n".join(lines), g


def frame_at(path, t, w=960, h=540):
    out = "/tmp/_af.png"
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t} -i "{path}" '
                   f'-frames:v 1 -vf "scale={w}:{h}" {out}', shell=True)
    fr = cv2.imread(out)
    return fr


def color_ascii(fr, W=64):
    """彩色语义：R/G/B 三通道各自降采样，判断「暗背景+亮文字」区域。"""
    H = fr.shape[0]
    h = max(1, int(round(W * H / fr.shape[1] / 2.1)))
    b = cv2.resize(fr, (W, h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (W, h), interpolation=cv2.INTER_AREA)
    return b, gray


if __name__ == "__main__":
    path = sys.argv[1]
    t = float(sys.argv[2])
    W = int(sys.argv[3]) if len(sys.argv) > 3 else 96
    fr = frame_at(path, t)
    if fr is None:
        print("读帧失败", path, t)
        sys.exit(1)
    txt, g = ascii_grid(fr, W)
    H, WD = fr.shape[:2]
    print(f"=== {os.path.basename(path)}  t={t}s  {WD}x{H}  →  {W}x{g.shape[0]} ===")
    # 加 x 刻度
    tick = "".join(str((i * WD // W) // 100 % 10) if (i * WD // W) % 50 < WD // W else " "
                   for i in range(W))
    print("      " + tick + "   (每格≈%dpx, 数字=百位标记)" % (WD // W))
    for i, ln in enumerate(txt.split("\n")):
        y0 = i * H // g.shape[0]
        print(f"y{y0:<4d} {ln}")
