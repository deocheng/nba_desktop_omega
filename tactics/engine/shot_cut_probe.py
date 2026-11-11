#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.15 切镜探针：验证「段内是否含切镜」。

背景：A5.15 直线探针发现 ep24_s1 的 f70 与 f145 是**两个不同机位**
（记分牌 1:37→3:50、字幕不同、球场视角完全不同）。
⇒ 推翻「段=单一静止镜头」假设；A5.14 累积掩膜可能混了两台相机的帧。
⇒ 直线推断必须**按镜头（shot）做**，不能按段做。

方法：相邻帧灰度差（320×180 下采样）+ 16-bin 直方图相关。双指标峰值=切镜。
用法: shot_cut_probe.py --seg ep24_s1 [--th 18]
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

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--th", type=float, default=18.0)
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    print(f"=== {a.seg} 切镜探针（{len(files)} 帧）===")
    prev = None
    cuts = []
    for i, fp in enumerate(files):
        img = cv2.imread(str(fp))
        g = cv2.cvtColor(cv2.resize(img, (320, 180)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            d = float(np.abs(g - prev).mean())
            h1 = cv2.calcHist([prev], [0], None, [16], [0, 256]); h1 /= h1.sum()
            h2 = cv2.calcHist([g], [0], None, [16], [0, 256]); h2 /= h2.sum()
            hc = float(cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL))
            mark = ""
            if d > a.th:
                mark = " <<< 疑似切镜"
                cuts.append(i)
            print(f"f{i:>3} diff={d:6.2f} histcorr={hc:+.3f}{mark}")
        prev = g
    print(f"\n疑似切镜帧（diff>{a.th}）: {cuts}")
    # 分组：每组一个镜头
    if cuts:
        bounds = [0] + cuts + [len(files)]
        for s, e in zip(bounds[:-1], bounds[1:]):
            print(f"  镜头: f{s}..f{e-1}（{e-s} 帧）")


if __name__ == "__main__":
    main()
