#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判决性检验：链式累积的单应对不对？

做法：取帧 1 上一块**静态纹理区**（看台，纹理丰富）作为模板，
在帧 433 的**全图范围**内搜索它的落点（尺度固定 1.0）。
· 若链式 H 正确 → 搜索到的落点应与 H 预测一致；
· 若链式 H 的尺度被系统性带偏 → 模板在帧 433 里会被缩放，固定尺度搜索的 NCC 会掉，
  且预测落点会偏离实际落点。

用法: python engine/probe_pan.py --win w1 --a 1 --b 433
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
OVERLAY = (60, 880, 580, 1020)   # 比分板（检测前涂黑）


def load(win, i, sc=0.5):
    fs = sorted((AW / win).glob("f*.jpg"))
    g = cv2.imread(str(fs[i - 1]), cv2.IMREAD_GRAYSCALE)
    x0, y0, x1, y1 = OVERLAY
    g[y0:y1, x0:x1] = 0
    return cv2.resize(g, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", default="w1")
    ap.add_argument("--a", type=int, default=1)
    ap.add_argument("--b", type=int, default=433)
    ap.add_argument("--r", type=int, default=60)
    ap.add_argument("--scales", default="1.0",
                    help="逗号分隔的尺度候选；给多个则逐尺度全图搜索取最佳")
    a = ap.parse_args()
    sc = 0.5
    A = load(a.win, a.a, sc)
    B = load(a.win, a.b, sc)
    scales = [float(x) for x in a.scales.split(",")]
    pts = [(1240, 240, "stand-right"), (300, 190, "stand-upper-left"),
           (1500, 430, "stand-right-mid"), (960, 150, "stand-upper-mid")]
    print(f"帧 {a.a} 的静态纹理块 → 在帧 {a.b} 全图范围内的落点（尺度候选 {scales}）")
    for (cx, cy, name) in pts:
        x0 = int(cx * sc) - int(a.r * sc)
        y0 = int(cy * sc) - int(a.r * sc)
        w = int(2 * a.r * sc)
        base = A[y0:y0 + w, x0:x0 + w]
        if base.size == 0:
            continue
        best = None
        for s in scales:
            tpl = base if abs(s - 1.0) < 1e-6 else cv2.resize(
                base, None, fx=s, fy=s,
                interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
            if tpl.shape[0] < 8 or tpl.shape[1] >= B.shape[1] or tpl.shape[0] >= B.shape[0]:
                continue
            res = cv2.matchTemplate(B, tpl, cv2.TM_CCOEFF_NORMED)
            _, mx, _, ml = cv2.minMaxLoc(res)
            if best is None or mx > best[0]:
                best = (mx, s, (ml[0] + tpl.shape[1] / 2) / sc, (ml[1] + tpl.shape[0] / 2) / sc)
        if best:
            mx, s, fx, fy = best
            print(f"  {name:16s} 帧{a.a} 中心=({cx},{cy}) → 帧{a.b} 最佳=({fx:.0f},{fy:.0f})  "
                  f"位移=({fx - cx:+.0f},{fy - cy:+.0f})  尺度={s:.2f}  NCC={mx:.3f}")


if __name__ == "__main__":
    main()
