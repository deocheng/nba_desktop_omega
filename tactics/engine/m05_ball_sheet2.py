#!/usr/bin/env python3
"""RF-DETR 真实检出（排除插值）目视验收接触表。
只取样 RF-DETR 自己报出的球框，逐格裁 160x160@2x，左上标 frame/conf，
并标注该框是否落在某个球员框内（in=P 表示可能被持球）。
用法: m05_ball_sheet2.py <window> <out.jpg> [--n 40] [--minconf 0.0]
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
    ap.add_argument("--half", type=int, default=70)
    ap.add_argument("--minconf", type=float, default=0.0)
    a = ap.parse_args()
    rf = json.loads((AW / f"{a.window}_rfdetr.json").read_text())
    bt = {fr["file"]: fr for fr in json.loads((AW / f"{a.window}_poss" / "ball_tracks.json").read_text())}
    fdir = AW / a.window
    # 只取非插值的真实检出
    real = []
    for f, cs in rf.items():
        if not cs:
            continue
        b = bt.get(f, {}).get("ball")
        if b is None or b.get("interp"):
            continue          # 被插值覆盖 -> 跳过
        c = max(cs, key=lambda x: x["conf"])
        if c["conf"] < a.minconf:
            continue
        real.append((f, c, bt.get(f, {}).get("players", [])))
    print(f"RF-DETR 真实检出帧 {len(real)}  取样 {min(a.n,len(real))}")
    idx = np.linspace(0, len(real) - 1, min(a.n, len(real))).astype(int)
    tiles = []
    for j in idx:
        f, c, players = real[j]
        img = cv2.imread(str(fdir / f))
        if img is None:
            continue
        bx1, by1, bx2, by2 = c["bbox"]
        cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
        h = a.half
        x1, y1 = int(cx - h), int(cy - h)
        pad = np.zeros((2 * h, 2 * h, 3), np.uint8)
        sx1, sy1 = max(0, x1), max(0, y1)
        sx2, sy2 = min(img.shape[1], x2 := x1 + 2 * h), min(img.shape[0], y1 + 2 * h)
        if sx2 > sx1 and sy2 > sy1:
            pad[sy1 - y1:sy2 - y1, sx1 - x1:sx2 - x1] = img[sy1:sy2, sx1:sx2]
        t = cv2.resize(pad, (a.cell, a.cell), interpolation=cv2.INTER_CUBIC)
        cv2.rectangle(t, (int((bx1 - x1) * a.cell / (2 * h)), int((by1 - y1) * a.cell / (2 * h))),
                      (int((bx2 - x1) * a.cell / (2 * h)), int((by2 - y1) * a.cell / (2 * h))),
                      (0, 255, 0), 2)
        inside = any(p["bbox"][0] <= cx <= p["bbox"][2] and p["bbox"][1] <= cy <= p["bbox"][3]
                     for p in players)
        cv2.putText(t, f"{f[1:6]} {c['conf']:.2f}", (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 255, 255), 1)
        cv2.putText(t, "inP" if inside else "-", (3, a.cell - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255) if inside else (180, 180, 180), 2)
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
