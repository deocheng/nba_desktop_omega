#!/usr/bin/env python3
"""A5.8h 落地可行性：按「动/不动」逐帧过滤后，**每帧候选池还剩多少检测**？

期望：场上 10 名球员 + 3 名裁判 ≈ 13。若过滤后仍 25+ ⇒ 判据不够狠。
同时输出：被剔除的框的**位置/尺寸特征**（验证剔掉的确实是场边/小框）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
TH = 12
SHRINK = 0.12
RATIO_MIN = 3.0
SEGS = ["ep24_s1", "ep1_s0", "ep10_s0", "ep12_s0", "ep46_s0"]


def load_gray(files, i):
    img = cv2.imread(str(files[i]))
    if img is None:
        return None
    return cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)


def main():
    for seg in SEGS:
        d = SEGD / seg
        tr = json.load(open(d / "tracks.json"))
        files = sorted((d / "frames").glob("f*.jpg"))
        keep_n, all_n = [], []
        kept_h, drop_h = [], []
        kept_y2, drop_y2 = [], []
        prev = None
        for fr in tr["frames"]:
            idx = fr["idx"]
            if idx == 0 or idx >= len(files):
                continue
            g = load_gray(files, idx)
            if g is None:
                continue
            if prev is None or prev[0] != idx - 1:
                pg = load_gray(files, idx - 1)
            else:
                pg = prev[1]
            if pg is None:
                continue
            da = cv2.absdiff(g, pg)
            base = float((da > TH).mean())
            k = 0
            for p in fr.get("players", []):
                all_n.append(1)
                x1, y1, x2, y2 = [int(v) for v in p["box"]]
                dx = int((x2 - x1) * SHRINK); dy = int((y2 - y1) * SHRINK)
                a1, b1 = max(0, x1 + dx), max(0, y1 + dy)
                a2, b2 = min(g.shape[1], x2 - dx), min(g.shape[0], y2 - dy)
                if a2 - a1 < 3 or b2 - b1 < 3:
                    r = 0.0
                else:
                    r = float((da[b1:b2, a1:a2] > TH).mean())
                ratio = r / base if base > 1e-6 else (99.0 if r > 0.02 else 1.0)
                if ratio > RATIO_MIN:
                    k += 1
                    kept_h.append(y2 - y1); kept_y2.append(y2)
                else:
                    drop_h.append(y2 - y1); drop_y2.append(y2)
            keep_n.append(k)
            prev = (idx, g)
        kn = np.array(keep_n)
        print(f"{seg}: 每帧候选 {kn.mean():.1f} ± {kn.std():.1f} "
              f"(中位 {np.median(kn):.0f}, min {kn.min()}, max {kn.max()})  "
              f"原每帧检测 {len(all_n)/len(keep_n):.1f}")
        print(f"    保留框 高中位 {np.median(kept_h):.0f}px  脚点y中位 {np.median(kept_y2):.0f} | "
              f"剔除框 高中位 {np.median(drop_h):.0f}px  脚点y中位 {np.median(drop_y2):.0f}")


if __name__ == "__main__":
    main()
