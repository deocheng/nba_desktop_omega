#!/usr/bin/env python3
"""court_pm_white_overlay.py — 把「真实紫漆掩膜」与「白线掩膜」同时叠到原始帧上，用于人眼判定
油漆区四边 & 白线（罚球线/罚球圈/限制区弧）各自的真实位置。
产出 _pmw_{seg}_f{idx}.png
"""
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
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--v", type=int, default=150)
    ap.add_argument("--s", type=int, default=75)
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    raw = cv2.inRange(hsv, np.array([110, 60, 70]), np.array([170, 255, 255]))
    m = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((31, 31), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    b = 1 + int(np.argmax(st[1:, 4]))
    pm = np.where(lab == b, 255, 0).astype(np.uint8)
    print("purple CC bbox:", st[b].tolist())

    wm = ((hsv[..., 2] > a.v) & (hsv[..., 1] < a.s)).astype(np.uint8) * 255
    # 白线只保留"细"结构: 水平开运算后回原掩膜
    thin = cv2.morphologyEx(wm, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1)))

    vis = img.copy().astype(float)
    # 紫漆: 染蓝
    vis[pm > 0] = 0.55 * vis[pm > 0] + 0.45 * np.array([255, 60, 0])
    # 白线: 染绿
    vis[thin > 0] = 0.25 * vis[thin > 0] + 0.75 * np.array([0, 255, 0])
    vis = vis.astype(np.uint8)

    cs, _ = cv2.findContours(pm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, cs, -1, (0, 215, 255), 2)
    cv2.imwrite(str(OUT / f"_pmw_{a.seg}_f{a.idx}.png"), vis)
    print(f"wrote _pmw_{a.seg}_f{a.idx}.png")


if __name__ == "__main__":
    main()
