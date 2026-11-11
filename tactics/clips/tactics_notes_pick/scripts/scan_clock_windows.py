#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在比分条上滑窗 OCR，自动找出「进攻时钟」窗口。
老程 2026-10-07 方法：从中近景关键镜头往前推，找到记分牌上的 24 秒 = 回合起点。
前提：能读出时钟数字。比分条 y 已定位，本脚本自动找 x。
做法：
 ① 取该时段**多帧中值图**（去掉瞬时噪声/球员遮挡）
 ② 沿 x 滑窗（窄窗），每窗 OCR 一次
 ③ 收集所有能读出 1~2 位数字的窗口，按位置归并
 ④ 用「数字随时间递减」二次确认（真时钟每���减1）
输出：候选时钟窗口列表 + 每窗在多个时刻的读数。
"""
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
SB = "/tmp/_cw.png"


def ocr(img, psm=7):
    if img.size == 0 or img.shape[0] < 4 or img.shape[1] < 4:
        return None
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.resize(g, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
    g = cv2.bilateralFilter(g, 5, 50, 50)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cv2.imwrite(SB, b)
    try:
        r = subprocess.run([TESS, SB, "stdout", "--psm", str(psm),
                            "-c", "tessedit_char_whitelist=0123456789"],
                           capture_output=True, timeout=6)
    except subprocess.TimeoutExpired:
        return None
    t = re.sub(r"[^0-9]", "", r.stdout.decode("utf-8", errors="ignore").strip())
    return t or None


def grab_seq(src, t0, dur, tmp="/tmp/_cwseq.mp4", fps=4, scale=(960, 540)):
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {dur} -an -vf "fps={fps},scale={scale[0]}:{scale[1]}" '
                   f'-c:v libx264 -preset ultrafast -crf 24 -pix_fmt yuv420p {tmp}',
                   shell=True)
    cap = cv2.VideoCapture(tmp)
    frs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frs.append(fr)
    cap.release()
    return frs, fps


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 430.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
    Y0, Y1 = 127, 191            # 已在 960x540 上定位的比分条行带

    frs, fps = grab_seq(src, t0, dur)
    print(f"采样 {len(frs)} 帧 (fps={fps}) 源t={t0}~{t0+dur}s")
    strips = [f[Y0:Y1, :] for f in frs]
    W = strips[0].shape[1]

    # 滑窗宽度：两位数字在 960 宽下约 20-34px
    results = []
    for w in (26, 34, 44):
        for x in range(0, W - w, 4):
            vals = [ocr(s[:, x:x + w]) for s in strips]
            digits = [v for v in vals if v and len(v) <= 2]
            if len(digits) >= max(3, len(vals) * 0.5):
                # 递减检验：相邻读数差为 -1 的比例
                seq = [int(v) for v in digits]
                dec = sum(1 for i in range(1, len(seq)) if seq[i] == seq[i - 1] - 1)
                results.append({"w": w, "x": x, "vals": seq,
                                "dec_ratio": round(dec / max(1, len(seq) - 1), 2),
                                "n_ok": len(digits)})

    print(f"\n能读出数字的窗口 {len(results)} 个，按(递减率×读出率)排序：")
    print(f"{'x':<6}{'窗宽':<6}{'读出':<6}{'递减率':<8}读数序列（前20）")
    for r in sorted(results, key=lambda z: (-z["dec_ratio"], -z["n_ok"]))[:25]:
        print(f"{r['x']:<6}{r['w']:<6}{r['n_ok']:<6}{r['dec_ratio']:<8}{r['vals'][:20]}")

    json_out = sys.argv[4] if len(sys.argv) > 4 else "/tmp/clock_windows.json"
    import json
    json.dump(results, open(json_out, "w"), ensure_ascii=False, indent=1)
    print("\nwrote", json_out)
