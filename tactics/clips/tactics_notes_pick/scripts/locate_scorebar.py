#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全画面扫描定位「比分条」水平带（不目视）。
思路：比分条 = 一条**水平文本带**，特征是
  ① 该行带的边缘（Canny）密度显著高于全画面平均
  ② 该行带内存在规则的**垂直短线段**（数字笔画）
做法：
 ① 取若干秒的多帧（避免单帧噪声）
 ② 每帧 Canny → 行方向边缘密度曲线（对行求和）
 ③ 多帧取中位 → 找峰值行带
 ④ 输出候选行带（top-k），再用 OCR 校验能否读出 2 位数字
"""
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
SB = "/tmp/_sb3.png"


def grab(src, t0, dur, tmp="/tmp/_bandloc.mp4"):
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {dur} -an -vf "fps=1,scale=960:540" -c:v libx264 '
                   f'-preset ultrafast -crf 26 -pix_fmt yuv420p {tmp}', shell=True)
    cap = cv2.VideoCapture(tmp)
    frs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frs.append(fr)
    cap.release()
    return frs


def row_band_density(frs):
    H, W = frs[0].shape[:2]
    acc = np.zeros(H)
    for fr in frs:
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        e = cv2.Canny(g, 60, 180)
        # 垂直方向的笔画：水平差分
        v = np.abs(np.diff(g.astype(np.int16), axis=1)).mean(axis=1)
        acc += (e > 0).mean(axis=1) + v / 255.0 * 0.5
    return acc / len(frs)


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
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    frs = grab(src, t0, dur)
    H, W = frs[0].shape[:2]
    print(f"采样{len(frs)}帧 {W}x{H}")
    acc = row_band_density(frs)
    base = np.median(acc)
    print(f"行带密度: 中位={base:.2f} max={acc.max():.2f}")

    # 找连续高密度行带
    hi = acc > max(base * 1.6, acc.max() * 0.45)
    bands, cur = [], None
    for y in range(H):
        if hi[y]:
            cur = [y, y] if cur is None else [cur[0], y]
        else:
            if cur is not None and (cur[1] - cur[0]) >= 6:
                bands.append(cur)
            cur = None
    if cur and (cur[1] - cur[0]) >= 6:
        bands.append(cur)
    bands.sort(key=lambda b: -(acc[b[0]:b[1] + 1].mean()))
    print(f"\n候选水平带 {len(bands)} 条（按密度排序，取前 6）：")
    print(f"{'y0':<6}{'y1':<6}{'高度':<7}{'密度':<8}OCR 整条读数")
    stack = frs
    for y0, y1 in bands[:6]:
        strip = np.median(np.stack([f[y0:y1 + 1, :] for f in stack]), axis=0).astype(np.uint8)
        txt = ocr_num(strip, psm=6)
        print(f"{y0:<6}{y1:<6}{y1-y0+1:<7}{acc[y0:y1+1].mean():<8.2f}{txt}")

    # 保存最佳带的图供人工核对（老程能看图）
    if bands:
        y0, y1 = bands[0]
        for k, f in enumerate(frs[:3]):
            cv2.imwrite(f"/tmp/_band_{k}.png", f[max(0, y0 - 6):y1 + 7, :])
        print(f"\n已导出最佳带前3帧到 /tmp/_band_0..2.png (y={y0}~{y1})")
        print("请老程确认这条带里**进攻时钟**的 x 位置（像素范围），我据此精确裁剪。")
