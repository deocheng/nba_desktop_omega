#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读比分条上的**进攻时钟**（老程 2026-10-07 方法：往前找到"24"= 回合开始）。
不用 pytesseract（未装），直接调 tesseract CLI。
流程：
① 从帧中裁出比分条 ROI，放大+二值化预处理
② tesseract --psm 7 白名单数字，读出 2 位时钟
③ 也读球队名+比分（作为校验：时钟倒退时比分应不变或增加）
输出：逐采样点的 时钟/比分 序列，可用于找"时钟重置为24"的回合起点。
"""
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
SB = "/tmp/_sb.png"


def crop_sb(fr, y0f=0.855, y1f=0.995):
    h = fr.shape[0]
    return fr[int(h * y0f):int(h * y1f), :]


def ocr(img, psm=7, whitelist="0123456789"):
    cv2.imwrite(SB, img)
    cmd = [TESS, SB, "stdout", "--psm", str(psm),
           "-c", f"tessedit_char_whitelist={whitelist}"]
    try:
        # 🔴 tesseract 会输出非 UTF-8 字节(WARNING)，必须用二进制再解码
        r = subprocess.run(cmd, capture_output=True, timeout=8)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    t = re.sub(r"[^0-9]", "", r.stdout.decode("utf-8", errors="ignore").strip())
    return t if t else None


def preprocess_clock(sb):
    """时钟区域预处理：灰度→放大→自适应二值"""
    g = cv2.cvtColor(sb, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return b


def probe_frame(fr, sb_split=0.62):
    """返回 (clock_str, score_str)。时钟在中偏右，比分在两侧。"""
    sb = crop_sb(fr)
    h, w = sb.shape[:2]
    b = preprocess_clock(sb)
    # 时钟：比分条中部（大致 55%~72% 宽）
    cw = int(w * 0.72) - int(w * 0.52)
    clock_img = b[:, int(w * 0.52):int(w * 0.72)]
    clock = ocr(clock_img, psm=7)
    # 比分：左半 + 右半
    left = ocr(b[:, int(w * 0.02):int(w * 0.50)], psm=7)
    right = ocr(b[:, int(w * 0.74):int(w * 0.98)], psm=7)
    return clock, left, right


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    n_samp = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"fps={fps} frames={n}")
    idxs = [int(n * (i + 0.5) / n_samp) for i in range(n_samp)]
    print(f"{'源t':<9}{'clock':<8}{'左比分':<10}{'右比分':<8}")
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            continue
        c, l, r = probe_frame(fr)
        print(f"{i/fps:<9.1f}{str(c):<8}{str(l):<10}{str(r):<8}")
    cap.release()
