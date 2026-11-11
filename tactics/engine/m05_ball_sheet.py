#!/usr/bin/env python3
"""球检测目视验收：逐帧裁出球框周围 160x160（2x 放大）拼成接触表。
每格左上写 frame / interp；用于人眼直接判「真球 / 假阳性」。
用法: m05_ball_sheet.py <window> <out.jpg> [--n 40] [--cell 150]
"""
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

AW = Path(str(tactics_data_file("action_work")))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("window"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--cols", type=int, default=10)
    ap.add_argument("--cell", type=int, default=150)
    ap.add_argument("--half", type=int, default=80)
    a = ap.parse_args()
    tr = json.loads((AW / f"{a.window}_poss" / "ball_tracks.json").read_text())
    fdir = AW / a.window
    hasball = [i for i, f in enumerate(tr) if f.get("ball") and "bbox" in f["ball"]]
    print(f"总帧 {len(tr)}  有球帧 {len(hasball)} ({len(hasball)/len(tr)*100:.1f}%)")
    idx = np.linspace(0, len(hasball) - 1, a.n).astype(int)
    tiles = []
    for j in idx:
        i = hasball[j]; fr = tr[i]
        img = cv2.imread(str(fdir / fr["file"]))
        bx1, by1, bx2, by2 = fr["ball"]["bbox"]
        cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
        h = a.half
        x1, y1 = int(cx - h), int(cy - h)
        x2, y2 = x1 + 2 * h, y1 + 2 * h
        pad = np.zeros((2 * h, 2 * h, 3), np.uint8)
        sx1, sy1 = max(0, x1), max(0, y1)
        sx2, sy2 = min(img.shape[1], x2), min(img.shape[0], y2)
        if sx2 > sx1 and sy2 > sy1:
            pad[sy1 - y1:sy2 - y1, sx1 - x1:sx2 - x1] = img[sy1:sy2, sx1:sx2]
        t = cv2.resize(pad, (a.cell, a.cell), interpolation=cv2.INTER_CUBIC)
        # 球框在裁图里的位置
        cv2.rectangle(t, (int(bx1 - x1), int(by1 - y1)), (int(bx2 - x1), int(by2 - y1)),
                      (0, 255, 0), 2)
        cv2.putText(t, f"{fr['frame']}", (3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.putText(t, f"w{int(bx2-bx1)}x{int(by2-by1)}", (3, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        if fr["ball"].get("interp"):
            cv2.putText(t, "INTERP", (3, a.cell - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        tiles.append(t)
    rows = []
    for i in range(0, len(tiles), a.cols):
        r = tiles[i:i + a.cols]
        while len(r) < a.cols:
            r.append(np.zeros_like(tiles[0]))
        rows.append(np.hstack(r))
    cv2.imwrite(a.out, np.vstack(rows))
    print("[图]", a.out)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
