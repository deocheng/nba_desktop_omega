#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精确定位「进攻时钟」在比分条上的 x 像素坐标（单次 tesseract 调用 + TSV bbox）。

思路（替代滑窗扫描，避免 SIGTERM）：
  ① 比分条整条读一次数字：放大 4x + psm 7（单行），tesseract 输出 **TSV**
     ⇒ 每个字符自带 x 坐标，一次调用就知道所有数字位置
  ② 多帧连续读，验证「数字随时间递减」且从 24 起 ⇒ 确认是进攻时钟而非节/比分
  ③ 若整条读不出，退化为「等宽切段」：按 24px 一格拼成一行再读（仍只需 1~2 次调用）

用法：
  locate_clock_x.py <src> <t0> <dur> [out_json]
"""
import json
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
TSV = "/tmp/_clock_tsv.png"
TMP = "/tmp/_clockgrab.mp4"


def grab(src, t0, dur, w=1280, h=720, fps=2):
    """低规格抽流：先降规格，避免长 GOP seek 超时。"""
    subprocess.run(
        f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" -t {dur} -an '
        f'-vf "fps={fps},scale={w}:{h}" -c:v libx264 -preset ultrafast -crf 24 '
        f'-pix_fmt yuv420p -g 1 {TMP}', shell=True)
    cap = cv2.VideoCapture(TMP)
    frs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frs.append(fr)
    cap.release()
    return frs, fps


def find_band(frs):
    """行带密度找比分条 y 区间（多帧中位，抗单帧噪声）。"""
    H = frs[0].shape[0]
    acc = np.zeros(H)
    for fr in frs:
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        e = cv2.Canny(g, 60, 180)
        v = np.abs(np.diff(g.astype(np.int16), axis=1)).mean(axis=1)
        acc += (e > 0).mean(axis=1) + v / 255.0 * 0.5
    acc /= len(frs)
    base = np.median(acc)
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
    return bands, acc


def prep(strip, scale=5):
    """比分条 → 便于 OCR 的白底黑字大图。"""
    g = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    g = cv2.bilateralFilter(g, 5, 40, 40)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return b


def tsv_run(img, psm=7):
    """跑一次 tesseract，返回 (全文, [(char, x_left, x_width, x_center), ...])。"""
    cv2.imwrite(TSV, img)
    try:
        r = subprocess.run([TESS, TSV, "stdout", "--psm", str(psm), "tsv",
                            "-c", "tessedit_char_whitelist=0123456789:"],
                           capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return None, []
    lines = r.stdout.decode("utf-8", errors="ignore").splitlines()
    if len(lines) < 2:
        return None, []
    hdr = lines[0].split("\t")
    ix = {k: i for i, k in enumerate(hdr)}
    txt, items = [], []
    for ln in lines[1:]:
        p = ln.split("\t")
        if len(p) < len(hdr):
            continue
        ch = p[ix["text"]].strip()
        if not ch:
            continue
        conf = float(p[ix["conf"]])
        if conf < 30:
            continue
        x, w = int(p[ix["left"]]), int(p[ix["width"]])
        txt.append(ch)
        items.append((ch, x, w, x + w // 2))
    return "".join(txt), items


def strip_cells(strip, cell=26, ypad=2):
    """退化方案：等宽切段横向拼成一条带（每段下方贴一条黑分隔线做视觉分隔）。"""
    H, W = strip.shape[:2]
    cells = []
    for x0 in range(0, W - cell + 1, cell):
        c = strip[ypad:H - ypad, x0:x0 + cell]
        cells.append(c)
        cells.append(np.full((2, cell, 3), 0, np.uint8))  # 分隔线
    return np.hstack(cells)


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 452.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
    out = sys.argv[4] if len(sys.argv) > 4 else "/tmp/clock_x.json"

    frs, fps = grab(src, t0, dur)
    print(f"抽流 {len(frs)} 帧 @ {fps}fps  t0={t0}s  dur={dur}s  "
          f"分辨率 {frs[0].shape[1]}x{frs[0].shape[0]}")

    bands, acc = find_band(frs)
    H = frs[0].shape[0]
    base = np.median(acc)
    print(f"行带密度: 中位={base:.2f} max={acc.max():.2f} (max/base={acc.max()/base:.2f})")
    # 打印 top-12 密度行，供人工核对（不目视，靠数值）
    order = np.argsort(-acc)[:12]
    print("密度 top12 行: " + ", ".join(f"y={y}({acc[y]:.2f})" for y in sorted(order)))
    # 放宽阈值：base*1.25
    hi = acc > max(base * 1.25, acc.max() * 0.30)
    bands, cur = [], None
    for y in range(H):
        if hi[y]:
            cur = [y, y] if cur is None else [cur[0], y]
        else:
            if cur is not None and (cur[1] - cur[0]) >= 5:
                bands.append(cur)
            cur = None
    if cur and (cur[1] - cur[0]) >= 5:
        bands.append(cur)
    bands.sort(key=lambda b: -(acc[b[0]:b[1] + 1].mean()))
    print(f"候选行带 {len(bands)} 条，取前 4：")
    for y0, y1 in bands[:4]:
        print(f"  y={y0}~{y1} (h={y1-y0+1}) 密度={acc[y0:y1+1].mean():.2f}")

    result = {"src": os.path.basename(src), "t0": t0, "dur": dur,
              "fps": fps, "W": frs[0].shape[1], "H": frs[0].shape[0], "bands": []}

    for y0, y1 in bands[:3]:
        strip = np.median(np.stack([f[y0:y1 + 1, :] for f in frs]), axis=0).astype(np.uint8)
        big = prep(strip, 5)
        txt, items = tsv_run(big, psm=7)
        print(f"\n--- 带 y={y0}~{y1} 整条读数 psm7: {txt!r}")
        if txt:
            cells = [(c, round(x / 5.0), round(w / 5.0)) for c, x, w, _ in items]
            print(f"    字符位（原图像素）: {cells}")

        # 逐帧读，验证递减序列
        seq = []
        for k, f in enumerate(frs):
            s = np.median(np.stack([f[y0:y1 + 1, :] for f in frs[max(0, k - 1):k + 2]]),
                          axis=0).astype(np.uint8)
            t2, _ = tsv_run(prep(s, 5), psm=7)
            seq.append(t2)
        print(f"    逐帧读数: {seq}")
        result["bands"].append({
            "y0": y0, "y1": y1,
            "text": txt,
            "cells": [[c, round(x / 5.0), round(w / 5.0)] for c, x, w, _ in items],
            "seq": seq,
        })

        # 导出带图供老程目视核对（我读不了图，只能请老程看）
        for k in range(min(3, len(frs))):
            cv2.imwrite(f"/tmp/_clockband_{y0}_{k}.png", frs[k][max(0, y0 - 8):y1 + 9, :])

    json.dump(result, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {out}")
    if bands:
        print(f"已导出比分条帧: /tmp/_clockband_{bands[0][0]}_0..2.png")
        print("→ 若整条读数含 2 位递减数字，即为进攻时钟；字符位可换算出 x 像素范围。")
    else:
        print("→ 仍未找到行带。下一轮对策：")
        print("   1) 改用多帧差分定位「有记分牌 vs 无记分牌」的帧段")
        print("   2) 对 top12 密度行逐行单独 OCR（每行 1 次调用，总共 12 次）")
