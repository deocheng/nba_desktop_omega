#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用「行变化率」定位记分牌（比分条/进攻时钟）。

新判据（与 Canny 密度正交）：
  记分牌上的**数字每秒都在变**，看台/球场/球员基本不变
  ⇒ 对每一行 y 计算该行像素随时间的**平均绝对变化量**
  ⇒ 记分牌所在行的变化率显著高于全画面中位，而静态看台行≈0

用法：
  locate_scorebar_v2.py <src> <t0> <dur> [out_json]
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
TMP = "/tmp/_sbv2.mp4"


def grab(src, t0, dur, w=960, h=540, fps=4):
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
    return frs, fps


def row_change(frs):
    """每行的平均绝对变化量（对相邻帧）。"""
    H = frs[0].shape[0]
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.int16) for f in frs]
    acc = np.zeros(H)
    for i in range(1, len(gray)):
        d = np.abs(gray[i] - gray[i - 1]).mean(axis=1)
        acc += d
    return acc / max(1, len(gray) - 1)


def row_bright_row_change(frs):
    """只统计「亮→暗」跳变（白色数字在暗底记分牌上 ⇒ 背景变暗时数字更跳）。
    用 max-min 包络差近似：每行在该时间窗内的极差。"""
    H = frs[0].shape[0]
    gray = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frs]).astype(np.int16)
    rng = (gray.max(axis=0) - gray.min(axis=0)).mean(axis=1)
    return rng


def bands_from(acc, H, base_mult=1.8, min_h=5):
    base = np.median(acc)
    hi = acc > max(base * base_mult, acc.max() * 0.35)
    bands, cur = [], None
    for y in range(H):
        if hi[y]:
            cur = [y, y] if cur is None else [cur[0], y]
        else:
            if cur is not None and (cur[1] - cur[0] + 1) >= min_h:
                bands.append(cur)
            cur = None
    if cur and (cur[1] - cur[0] + 1) >= min_h:
        bands.append(cur)
    bands.sort(key=lambda b: -(acc[b[0]:b[1] + 1].mean()))
    return bands, base


def prep(strip, scale=5):
    g = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    g = cv2.bilateralFilter(g, 5, 40, 40)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return b


def ocr_text(img, psm=7, whitelist="0123456789:"):
    cv2.imwrite("/tmp/_sbv2_ocr.png", img)
    try:
        r = subprocess.run([TESS, "/tmp/_sbv2_ocr.png", "stdout", "--psm", str(psm),
                            "-c", f"tessedit_char_whitelist={whitelist}"],
                           capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        return None
    t = r.stdout.decode("utf-8", errors="ignore").strip()
    return t or None


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 452.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
    out = sys.argv[4] if len(sys.argv) > 4 else "/tmp/sbv2.json"

    frs, fps = grab(src, t0, dur)
    H, W = frs[0].shape[:2]
    print(f"抽流 {len(frs)} 帧 @{fps}fps  {W}x{H}  t0={t0}s dur={dur}s")

    rc = row_change(frs)
    rb = row_bright_row_change(frs)
    for name, acc in (("行变化率", rc), ("行极差", rb)):
        print(f"\n[{name}] 中位={np.median(acc):.2f} max={acc.max():.2f} "
              f"max/中位={acc.max()/max(np.median(acc),1e-6):.2f}")
        order = np.argsort(-acc)[:14]
        print("  top14 行: " + ", ".join(f"y={y}({acc[y]:.2f})" for y in sorted(order)))

    bands, base = bands_from(rb, H)
    print(f"\n候选变化带(极差判据) {len(bands)} 条，取前 5：")
    for y0, y1 in bands[:5]:
        print(f"  y={y0}~{y1} (h={y1-y0+1}) 极差={rb[y0:y1+1].mean():.2f} 变化率={rc[y0:y1+1].mean():.2f}")

    result = {"src": os.path.basename(src), "t0": t0, "dur": dur, "fps": fps,
              "W": W, "H": H,
              "row_change": [round(float(v), 3) for v in rc],
              "row_range": [round(float(v), 3) for v in rb],
              "cands": []}

    for y0, y1 in bands[:5]:
        h = y1 - y0 + 1
        # 取该带的「时间中位帧」→ 数字不会互相糊
        strip = np.median(np.stack([f[y0:y1 + 1, :] for f in frs]), axis=0).astype(np.uint8)
        big = prep(strip, 5)
        txt = ocr_text(big, psm=7)
        txt6 = ocr_text(big, psm=6)
        # 逐帧读（3 帧采样即可看是否递减）
        seq = []
        for k in range(0, len(frs), max(1, len(frs) // 6)):
            s = frs[k][y0:y1 + 1, :]
            seq.append(ocr_text(prep(s, 5), psm=7))
        print(f"\n--- 带 y={y0}~{y1} (h={h})")
        print(f"    psm7={txt!r}  psm6={txt6!r}")
        print(f"    逐帧: {seq}")
        cv2.imwrite(f"/tmp/_sbv2_{y0}.png", frs[0][max(0, y0 - 10):y1 + 11, :])
        result["cands"].append({"y0": y0, "y1": y1, "h": h,
                                "psm7": txt, "psm6": txt6, "seq": seq})

    json.dump(result, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {out}")
    print("导出带图: /tmp/_sbv2_<y0>.png")
    print("判定标准：seq 里出现 2 位**递减**序列(如 24,23,22…)且起点≈24 ⇒ 进攻时钟")
