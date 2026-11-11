#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时域差分找「静止叠加层」＝记分牌。

原理：相邻帧差分
  · 看台/球员/球场都在动 ⇒ 差分大（亮）
  · 记分牌是**静止**的转播叠加层 ⇒ 差分≈0（暗矩形）⇒ 呈现为亮区里的暗块
⇒ 对差分图做「局部均值低 + 矩形规整」的检测

用法：find_overlay_diff.py <src> <t0> <dur> [step]
"""
import os
import subprocess
import sys

import cv2
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
RAMP = " .:-=+*#%@"


def grab_seq(src, t0, t1, step, w=1920, h=1080):
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)
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


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]); dur = float(sys.argv[3])
    step = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    frs = grab_seq(src, t0, t0 + dur, step)
    print(f"抽流 {len(frs)} 帧 t0={t0} dur={dur}s step={step}s  "
          f"{frs[0].shape[1]}x{frs[0].shape[0]}")
    if len(frs) < 4:
        print("帧数不足"); sys.exit(1)

    gray = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frs]).astype(np.int16)
    diff = np.abs(np.diff(gray, axis=0)).mean(axis=0)      # 时域差分（亮=在动）
    static = 255 - np.clip(diff / max(diff.mean(), 1e-6) * 60, 0, 255).astype(np.uint8)
    print(f"差分图: 中位={np.median(diff):.2f} p5={np.percentile(diff,5):.2f} "
          f"p95={np.percentile(diff,95):.2f} max={diff.max():.2f}")

    # 静止度 = 局部 21x21 均值最低 ⇒ 记分牌候选
    k = np.ones((21, 21), np.float32) / 441
    loc = cv2.filter2D((255 - static).astype(np.float32), -1, k)
    H, W = diff.shape
    win_size = W - 20
    print("\n=== 局部运动度最低的 25 个 21x21 块（=静止叠加层候选）===")
    # loc 已是 21x21 窗口均值（filter2D），直接找最低区（=最静止）
    seen = []
    order = np.argsort(loc.ravel())
    for f in order[:600]:
        f = int(f)
        cy, cx = f // W, f % W
        if any(abs(cy - a) < 30 and abs(cx - b) < 60 for a, b in seen):
            continue
        seen.append((cy, cx))
        print(f"  中心=({cx},{cy}) 局部运动度={loc.ravel()[f]:.2f}  "
              f"区域均值差分={diff[max(0,cy-10):cy+10, max(0,cx-30):cx+30].mean():.2f}")
        if len(seen) >= 25:
            break
    print(f"\n去重后 {len(seen)} 个候选")

    # 静态图输出
    out = os.path.join(SCRATCH, "static.png")
    cv2.imwrite(out, static)
    print(f"静止度图已存 {out}")
    print("ASCII 预览（顶部 y=0..120，200字宽）：")
    for y in range(0, 120, 6):
        row = diff[y, :]
        s = "".join(RAMP[min(9, int(v / max(diff.max(), 1) * 9.99))] for v in row)
        print(f"y{y:<4d}diff|{s}|")
    print("\n判读：在这条差分剖面里找**暗段（静止）** —— 记分牌=亮区中的暗矩形")
