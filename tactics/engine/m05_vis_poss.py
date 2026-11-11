#!/usr/bin/env python3
"""目视验收：把「球 + 全部检测人 + 被判定的持球者」画出来，供人眼直接判读。
不引入任何新判据，只做可视化，避免"看数字自洽"。
用法: m05_vis_poss.py <window> <out.jpg> [--frames 20,100,...]
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
    ap.add_argument("window")
    ap.add_argument("out")
    ap.add_argument("--frames", default="20,100,200,240,300,330")
    ap.add_argument("--scale", type=float, default=0.62)
    a = ap.parse_args()
    tr = json.loads((AW / f"{a.window}_poss" / "ball_tracks.json").read_text())
    fdir = AW / a.window
    tiles = []
    for fi in [int(x) for x in a.frames.split(",")]:
        if fi >= len(tr):
            continue
        fr = tr[fi]
        img = cv2.imread(str(fdir / fr["file"]))
        if img is None:
            continue
        poss = fr.get("poss_track_id")
        for p in fr.get("players", []):
            x1, y1, x2, y2 = [int(v) for v in p["bbox"]]
            is_p = (p["track_id"] == poss)
            col = (0, 255, 255) if is_p else (140, 140, 140)
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 5 if is_p else 2)
            cv2.putText(img, f"{p['track_id']}", (x1, max(24, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 3)
        b = fr.get("ball")
        if b and "bbox" in b:
            bx1, by1, bx2, by2 = [int(v) for v in b["bbox"]]
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (0, 255, 0), 4)
            bc = ((bx1 + bx2) // 2, (by1 + by2) // 2)
            cv2.circle(img, bc, 10, (0, 0, 255), -1)
            # 连到持球者框
            for p in fr.get("players", []):
                if p["track_id"] == poss:
                    px1, py1, px2, py2 = [int(v) for v in p["bbox"]]
                    cv2.line(img, bc, ((px1 + px2) // 2, (py1 + py2) // 2), (0, 0, 255), 3)
                    cv2.putText(img, f"d={np.hypot(bc[0]-(px1+px2)/2, bc[1]-(py1+py2)/2):.0f}",
                                (bx2 + 12, by1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        cv2.putText(img, f"f{fr['frame']}  poss={poss}  ball_interp={b.get('interp') if b else None}",
                    (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 3)
        tiles.append(cv2.resize(img, None, fx=a.scale, fy=a.scale,
                                interpolation=cv2.INTER_AREA))
    if not tiles:
        print("no tiles"); return 1
    rows = []
    for i in range(0, len(tiles), 2):
        r = tiles[i:i + 2]
        if len(r) == 1:
            r.append(np.zeros_like(r[0]))
        rows.append(np.hstack(r))
    cv2.imwrite(a.out, np.vstack(rows))
    print("[图]", a.out, np.vstack(rows).shape)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
