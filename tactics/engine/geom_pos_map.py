#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把真值库候选按窗叠到参考帧上，观察 TP/FP 的空间分布。

用法:
  python engine/geom_pos_map.py                      # 四窗各出一张
  python engine/geom_pos_map.py --window w1 --out /tmp/m.jpg
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--radius", type=int, default=9)
    a = ap.parse_args()

    bank = json.loads((MS / "labels_bank.json").read_text())
    wins = [a.window] if a.window else ["w1", "w2", "w3", "w4"]

    for w in wins:
        rows = [r for r in bank if r["window"] == w and r["label"] in ("TP", "FP")]
        frames = Counter(r["frame"] for r in rows)
        ref = frames.most_common(1)[0][0]
        img = cv2.imread(str(AW / w / ref))
        if img is None:
            print(f"[skip] {w} 读不到 {ref}")
            continue
        ov = img.copy()
        # 位置按帧号差平移补偿（镜头平移 ~3.4px/帧，方向未知 -> 仅按最近帧分组，不补偿）
        ntp = nfp = 0
        for r in rows:
            x1, y1, x2, y2 = r["bbox"]
            cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
            tp = r["label"] == "TP"
            col = (60, 240, 60) if tp else (40, 40, 240)
            ntp += tp
            nfp += (not tp)
            cv2.circle(ov, (cx, cy), a.radius, col, 2)
            if r["frame"] == ref:
                cv2.circle(ov, (cx, cy), 2, (0, 255, 255), -1)
        cv2.putText(ov, f"{w}  ref={ref}   TP={ntp}(green) FP={nfp}(red)  "
                        f"cyan dot = this frame", (24, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        out = a.out or str(MS / f"posmap_{w}.jpg")
        cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"[out] {out}  {w}  TP={ntp} FP={nfp}  ref={ref}")


if __name__ == "__main__":
    main()
