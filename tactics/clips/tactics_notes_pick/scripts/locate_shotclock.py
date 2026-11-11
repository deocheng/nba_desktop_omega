#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动定位比分条上「进攻时钟」的位置（不目视）。
思路：进攻时钟是**每秒减1**的两位数 ⇒ 在正确 ROI 上，
     相邻秒的像素变化极小且规律；比分/队名是静态或跳变。
做法：
 ① 取一段已知含比赛的帧序列（1fps 采样，覆盖若干秒）
 ② 把比分条高度方向压成一条"列签名"：每列在该区间内的**变化频次/方差**
 ③ 时钟列的特征 = 每秒都在变（方差高）但**变化量小**（数字局部变化）
    静态队名/比分 = 变化量≈0（除了得分瞬间）
 ④ 输出候选列区间，再由 OCR 校验读出的数字是否是合法时钟值(0-24)
"""
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
SB = "/tmp/_sb2.png"


def grab(src, t0, dur, tmp="/tmp/_clockloc.mp4"):
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {dur} -an -vf "fps=1,scale=960:540" -c:v libx264 '
                   f'-preset ultrafast -crf 26 -pix_fmt yuv420p {tmp}', shell=True)
    cap = cv2.VideoCapture(tmp)
    frs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        h = fr.shape[0]
        frs.append(fr[int(h * 0.85):int(h * 0.995), :])
    cap.release()
    return frs


def column_signature(frs):
    """返回 每列的 平均绝对帧间差（按时钟每秒变→中低且规律）"""
    arr = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in frs])
    d = np.abs(np.diff(arr, axis=0)).mean(axis=(0, 2))     # 每列的平均帧间差
    return d


def ocr_num(img, psm=7):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    g = cv2.bilateralFilter(g, 5, 50, 50)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cv2.imwrite(SB, b)
    try:
        r = subprocess.run([TESS, SB, "stdout", "--psm", str(psm),
                            "-c", "tessedit_char_whitelist=0123456789"],
                           capture_output=True, timeout=8)
    except subprocess.TimeoutExpired:
        return None
    t = re.sub(r"[^0-9]", "", r.stdout.decode("utf-8", errors="ignore").strip())
    return t or None


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 400.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 40.0
    frs = grab(src, t0, dur)
    print(f"采样 {len(frs)} 秒  比分条尺寸 {frs[0].shape}")
    d = column_signature(frs)
    w = len(d)
    print(f"列变化率: min={d.min():.2f} 中位={np.median(d):.2f} max={d.max():.2f}")

    # 滑窗：找长度≈2-3位数字宽度的区间，变化率中低但>0（时钟在动）
    # 比分条宽度 960，对应 1920 实际 → 1个数字约 12-18px@960
    best = []
    for width in range(14, 40, 2):
        for s in range(0, w - width, 2):
            seg = d[s:s + width]
            m = seg.mean()
            if 0.05 <= m <= 3.0:            # 在动但不是剧烈变化
                # 内部一致性：变化率较均匀（数字局部变，不是整块换）
                cv_ = seg.std() / (m + 1e-6)
                if cv_ < 1.6:
                    best.append((m, s, width, cv_))
    best.sort(key=lambda x: (-x[3], x[0]))
    print(f"\n候选时钟区间 {len(best)} 个，取前 12 个用 OCR 校验：")
    seen = []
    for m, s, width, cv_ in best[:60]:
        if any(abs(s - ss) < 20 for ss in seen):
            continue
        seen.append(s)
        # 用多数帧的并集做 OCR（取该区间在多帧上的中值图）
        stack = np.stack([cv2.cvtColor(f[:, s:s + width], cv2.COLOR_BGR2GRAY)
                          for f in frs])
        med = np.median(stack, axis=0).astype(np.uint8)
        vals = [ocr_num(med)] * 3
        print(f"  x={s:<5} 宽={width:<4} 变化率={m:.2f} 均匀度={cv_:.2f} "
              f"OCR(多帧中值)={vals[0]}")
        if len(seen) >= 12:
            break
