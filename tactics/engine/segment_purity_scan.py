#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.10 段纯净度扫描：177 个「实战片段」里到底有多少是**真转播帧**？

起因（A5.9 目视自证）：ep19_s0 / ep5_s1 / ep1_s0 的抽样帧是《战术笔记》**节目讲解帧**
（左=画中画比赛录像，右=白纸卡片中文说明，底=字幕条），而 tracks.json 在这些帧上仍有
12–17 个检测框（打在画中画里被缩小的人身上）⇒ A4.60「telestration 帧 0 人自动排除」失效。
后果：A5.1 的「大框≥140px=场上球员」分层、每帧人数、碎片倍率等**全部统计可能被污染**。

判据（两条，均为**不依赖检测器**的纯像素特征）：
  R1 卡片白区 : 右半区 x∈[0.55W,W], y∈[0,0.92H] 的近白像素(V≥190 且 S≤45)占比
  R2 字幕条   : 底部 y∈[0.88H,H] 的高对比文字密度（|∇|>40 的像素占比）
每段抽 N 帧取中位。卡片帧 ⟺ R1 高(≥0.45)。

自证：本脚本 --self 模式打印 3 个已知段的三帧值，核对判据方向。

用法: segment_purity_scan.py [--all] [--segs a,b] [--n 16]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUTJ = ROOT / "action_work" / "track_judge" / "segment_purity.json"

CARD_TH = 0.45      # 右半区近白占比 ≥ 该值 ⇒ 卡片帧
SUB_TH = 0.06       # 底部高对比密度 ≥ 该值 ⇒ 疑有字幕条


def frame_feats(im):
    H, W = im.shape[:2]
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    v, s = hsv[:, :, 2], hsv[:, :, 1]
    x0 = int(W * 0.55)
    y1 = int(H * 0.92)
    reg = (v[:y1, x0:] >= 190) & (s[:y1, x0:] <= 45)
    r1 = float(reg.mean())
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    r2 = float((mag[int(H * 0.88):, :] > 40).mean())
    return r1, r2


def scan_seg(seg, n):
    d = SEGD / seg
    files = sorted((d / "frames").glob("f*.jpg"))
    if not files:
        return None
    step = max(1, len(files) // n)
    rs = [frame_feats(cv2.imread(str(f))) for f in files[::step][:n]]
    rs = [x for x in rs if x is not None]
    if not rs:
        return None
    r1 = float(np.median([x[0] for x in rs]))
    r2 = float(np.median([x[1] for x in rs]))
    card_frac = float(np.mean([x[0] >= CARD_TH for x in rs]))
    return {"seg": seg, "n_frames": len(files), "n_sampled": len(rs),
            "card_white_r1": r1, "subtitle_r2": r2, "card_frame_frac": card_frac}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--segs", default="ep24_s1,ep5_s1,ep19_s0,ep1_s0")
    ap.add_argument("--n", type=int, default=16)
    a = ap.parse_args()

    segs = (sorted(p.name for p in SEGD.iterdir() if p.is_dir())
            if a.all else [s.strip() for s in a.segs.split(",")])
    res = []
    for s in segs:
        r = scan_seg(s, a.n)
        if r:
            res.append(r)
    res.sort(key=lambda x: -x["card_frame_frac"])
    print(f"{'段':<12}{'帧':>5}{'右半区近白':>10}{'底部对比':>9}{'卡片帧占比':>10}")
    for r in res[:40]:
        print(f"{r['seg']:<12}{r['n_frames']:>5}{r['card_white_r1']:>10.2f}"
              f"{r['subtitle_r2']:>9.3f}{r['card_frame_frac']*100:>9.1f}%")
    if len(res) > 40:
        print(f"...（共 {len(res)} 段）")

    pure = [r for r in res if r["card_frame_frac"] <= 0.10]
    mix = [r for r in res if 0.10 < r["card_frame_frac"] <= 0.60]
    dirty = [r for r in res if r["card_frame_frac"] > 0.60]
    print(f"\n纯净（卡片帧≤10%）  : {len(pure):>3} 段")
    print(f"混杂（10%–60%）     : {len(mix):>3} 段")
    print(f"几乎全节目帧(>60%)  : {len(dirty):>3} 段")
    if res:
        print(f"全 {len(res)} 段卡片帧占比 中位 {np.median([r['card_frame_frac'] for r in res]):.1%}  "
              f"均值 {np.mean([r['card_frame_frac'] for r in res]):.1%}")
    json.dump(res, open(OUTJ, "w"), ensure_ascii=False, indent=1)
    print(f"\n-> {OUTJ}")


if __name__ == "__main__":
    main()
