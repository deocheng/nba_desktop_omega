#!/usr/bin/env python3
"""court_white_probe.py — 白线/暗线探针：把球场标线（白线、暗线）从画面里分离出来。
用法: python3 court_white_probe.py --seg ep24_s1 --idx 70 [--v 150 --s 75]
产出: _wp_mask.png(白线掩膜) _wp_over.png(叠加) _wp_dark.png(暗线掩膜)
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import sys
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
    ap.add_argument("--v", type=int, default=150, help="白线 V 门")
    ap.add_argument("--s", type=int, default=75, help="白线 S 门(低饱和)")
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hh, ss, vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    # 白线：亮 + 低饱和
    wm = ((vv > a.v) & (ss < a.s)).astype(np.uint8) * 255
    # 暗线：很暗
    dm = (vv < 70).astype(np.uint8) * 255

    cv2.imwrite(str(OUT / f"_wp_{a.seg}_f{a.idx}_mask.png"), wm)
    cv2.imwrite(str(OUT / f"_wp_{a.seg}_f{a.idx}_dark.png"), dm)

    # overlay: white=green, dark=red
    ov = img.copy()
    ov[wm > 0] = (0, 255, 0)
    ov[dm > 0] = (0, 0, 255)
    over = cv2.addWeighted(img, 0.45, ov, 0.55, 0)
    cv2.imwrite(str(OUT / f"_wp_{a.seg}_f{a.idx}_over.png"), over)

    # downscaled full view of mask-only
    ms = cv2.resize(wm, (640, 360), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(OUT / f"_wp_{a.seg}_f{a.idx}_mask640.png"), ms)
    print(f"white px={int((wm>0).sum())}  dark px={int((dm>0).sum())}")
    print(f"wrote _wp_{a.seg}_f{a.idx}_{{mask,dark,over,mask640}}.png")


if __name__ == "__main__":
    main()
