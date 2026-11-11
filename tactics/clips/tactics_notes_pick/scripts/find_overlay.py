#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨时间中位帧 → 凸显转播叠加层（记分牌/台标/logo）。

原理：画面内容在动（相机运动+球员运动），但**转播叠加层固定不动**
      ⇒ 多帧逐像素中位数会把动的部分糊掉/抹平，静止的叠加层保留下来
然后在叠加层上做「暗底亮字」检测，得到记分牌矩形候选。

用法：
  find_overlay.py <src> <t0> <dur> [nframes] [out_png]
"""
import os
import subprocess
import sys

import cv2
import numpy as np

TMP = "/tmp/_ov.mp4"


def grab_far(src, t0, dur, w=960, h=540, fps=1):
    subprocess.run(
        f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" -t {dur} -an '
        f'-vf "fps={fps},scale={w}:{h}" -c:v libx264 -preset ultrafast -crf 22 '
        f'-pix_fmt yuv420p -g 1 {TMP}', shell=True)
    cap = cv2.VideoCapture(TMP)
    frs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frs.append(fr)
    cap.release()
    return frs


def ascii_row(g, y0, y1, x0=0, x1=None):
    x1 = x1 or g.shape[1]
    out = []
    for y in range(y0, y1):
        row = g[y, x0:x1]
        out.append(f"y{y:<4d}|" + "".join(' .:-=+*#%@'[min(9, int(v / 25.6))] for v in row) + "|")
    return "\n".join(out)


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
    out = sys.argv[4] if len(sys.argv) > 4 else "/tmp/overlay.png"

    frs = grab_far(src, t0, dur, fps=1)
    print(f"抽流 {len(frs)} 帧  t0={t0} dur={dur}s  {frs[0].shape[1]}x{frs[0].shape[0]}")
    if len(frs) < 5:
        print("帧数不足"); sys.exit(1)

    stack = np.stack(frs)
    med = np.median(stack, axis=0).astype(np.uint8)
    std = stack.astype(np.float32).std(axis=0).mean(axis=2)  # 时域标准差
    print(f"中位帧已生成；时域std: 中位={np.median(std):.1f} p10={np.percentile(std,10):.1f} "
          f"p90={np.percentile(std,90):.1f}")
    cv2.imwrite(out, med)

    g = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    # 叠加层候选：低时域方差（静止） + 高局部对比（文字）
    print("\n=== 时域方差最低的 30 行（静止叠加层候选）===")
    rs = std.mean(axis=1)
    for y in np.argsort(rs)[:30]:
        print(f"  y={y:<4d} std={rs[y]:.2f}")

    print("\n=== 中位帧 顶部 y=0..70（ASCII，192字宽）===")
    print(ascii_row(g, 0, 70))

    print("\n=== 中位帧 底部 y=470..540 ===")
    print(ascii_row(g, 470, 540))

    print(f"\n中位帧已存 {out}")
    print("→ 在 ASCII 里找「暗底 + 亮小字」的矩形带，即记分牌候选")
