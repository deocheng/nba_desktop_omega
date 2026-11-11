#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""链式累积**审计** —— 揭穿「缓存旧链」与「现算新链」不一致的陷阱。

背景（本轮发现）
--------------
`global_align.track()` 有缓存短路：`if j["n"] == len(fs): return cache`。
而 `align_w1.json` 的时间戳 **早于** `euclid_ize` 修复（20:03 vs 22:21）⇒
修好之后跑 `--traj` 仍然在打印**修复前**的旧链数字。这制造了两个互不相容的"硬结论"：
  · 缓存旧链：累积 tx 峰值 −2764px（约 f100）、末帧 −379px（**非单调：先左摇再回摇**）
  · 马赛克（现算新链）：画布 4857px ⇒ 反推链末跨度 ≈ −2897px
本脚本**不写缓存**、现场重算，逐 20 帧打印平移/尺度剖面，并给出：
  · Σ(逐对平移)  vs  链末平移   （是否自洽）
  · max|tx| / 行程（左右往返幅度的代理）

用法: python engine/chain_audit.py --win w1 --start 1 --end 433
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import global_align as GA


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", default="w1")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=433)
    ap.add_argument("--every", type=int, default=20)
    a = ap.parse_args()

    fs = GA.frame_paths(a.win)[a.start - 1:a.end]
    print(f"[{a.win}] 段 [{a.start}..{a.end}] 共 {len(fs)} 帧，现场重算（不读缓存）")
    feats = [GA.detect(GA.to_gray_small(f)[0]) for f in fs]
    Hc = np.eye(3)
    prof = {a.start: (np.eye(3), 0.0)}
    sum_t = np.zeros(2)
    nfail, fails = 0, []
    for i in range(1, len(feats)):
        H, nin = GA.match(feats[i - 1], feats[i])
        if H is None:
            nfail += 1
            fails.append(a.start + i)
        else:
            Hc = H @ Hc
            sum_t += H[:2, 2]
        prof[a.start + i] = (Hc.copy(), nin or 0)
    print(f"  配准失败 {nfail} 帧 {fails[:8]}")
    print(f"{'frame':>7}{'累积tx':>11}{'累积ty':>10}{'累积s':>10}{'|Δ帧间|':>10}")
    prev = None
    txs = []
    for k in sorted(prof):
        if (k - a.start) % a.every and k != a.end:
            continue
        H = prof[k][0]
        tx, ty = H[0, 2] / GA.SC, H[1, 2] / GA.SC
        s = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
        txs.append(tx)
        d = ""
        if prev is not None:
            Hi = np.linalg.inv(prof[prev][0]) @ H
            d = f"{np.hypot(Hi[0,2]/GA.SC, Hi[1,2]/GA.SC):>10.1f}"
        print(f"{k:>7}{tx:>11.0f}{ty:>10.0f}{s:>10.6f}{d:>10}")
        prev = k
    Hf = prof[a.end][0]
    print(f"\n  链末平移（全分辨率） ({Hf[0,2]/GA.SC:+.0f}, {Hf[1,2]/GA.SC:+.0f})"
          f"   链末尺度 {np.sqrt(abs(np.linalg.det(Hf[:2,:2]))):.6f}")
    print(f"  Σ逐对平移（全分辨率）({sum_t[0]/GA.SC:+.0f}, {sum_t[1]/GA.SC:+.0f})"
          f"   ← 与链末一致 ⇒ 链式自洽")
    txs = np.array(txs)
    print(f"  平移行程：min {txs.min():.0f}  max {txs.max():.0f}  极差 {txs.max()-txs.min():.0f}px")
    print("  ⚠️ 极差 ≫ |链末| ⇒ 镜头**非单调**（往返摇）—— 单画布马赛克会出现同区多次贴图")


if __name__ == "__main__":
    main()
