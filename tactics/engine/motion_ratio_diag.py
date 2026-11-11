#!/usr/bin/env python3
"""A5.8e 帧差判据诊断：**框内运动 vs 全帧基线**。

疑点：#21(观众) 的框内 motion_ratio 中位 0.543 却与球员 #269(0.585) 接近。
假设：该帧**画面整体在变**（切镜/摇镜/转播图形）⇒ 框内比值被背景抬高。
判据应为「框内显著高于全帧基线」而不是绝对比值。
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

TARGETS = [
    ("ep24_s1", 21, "tracks.json", "观众(老程)"),
    ("ep24_s1", 190, "tracks.json", "替补席+观众(老程)"),
    ("ep24_s1", 269, "tracks.json", "球员(老程)"),
    ("ep24_s1", 309, "tracks.json", "教练(老程)"),
    ("ep1_s0", 116, "tracks.json", "球员→观众A→邻座B"),
]


def load_gray(files, i):
    img = cv2.imread(str(files[i]))
    if img is None:
        return None
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (5, 5), 0)


def main():
    for seg, tid, src, tag in TARGETS:
        d = SEGD / seg
        tr = json.load(open(d / src))
        files = sorted((d / "frames").glob("f*.jpg"))
        print(f"\n=== {seg}#{tid}  {tag} ===")
        print(f"{'帧':>5}{'框内':>8}{'全帧基线':>10}{'差值':>8}  判")
        rows = []
        for fr in tr["frames"]:
            idx = fr["idx"]
            hits = [p for p in fr.get("players", []) if p["id"] == tid]
            if not hits or idx == 0 or idx >= len(files):
                continue
            g = load_gray(files, idx)
            pg = load_gray(files, idx - 1)
            if g is None or pg is None:
                continue
            d_all = cv2.absdiff(g, pg)
            base = float((d_all > TH).mean())
            for p in hits:
                x1, y1, x2, y2 = [int(v) for v in p["box"]]
                dx = int((x2 - x1) * SHRINK); dy = int((y2 - y1) * SHRINK)
                x1, y1 = max(0, x1 + dx), max(0, y1 + dy)
                x2, y2 = min(g.shape[1], x2 - dx), min(g.shape[0], y2 - dy)
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                r = float((d_all[y1:y2, x1:x2] > TH).mean())
                rows.append((idx, r, base, r - base))
        for idx, r, b, diff in rows:
            flag = "动" if diff > 0.10 else "静"
            print(f"{idx:>5}{r:>8.3f}{b:>10.3f}{diff:>8.3f}  {flag}")
        if rows:
            rs = [x[1] for x in rows]; bs = [x[2] for x in rows]; ds = [x[3] for x in rows]
            print(f"  框内中位={np.median(rs):.3f}  全帧基线中位={np.median(bs):.3f}  "
                  f"差值中位={np.median(ds):+.3f}  动帧(差>0.1)占比={np.mean([d>0.1 for d in ds]):.2f}")


if __name__ == "__main__":
    main()
