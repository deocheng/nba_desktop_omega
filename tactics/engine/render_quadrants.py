#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_quadrants.py —— 全帧切块编号放大图，供老程快速指认「球在哪一块」。

为什么：人眼在 1080p 全帧里找 20–30px 的球很吃力，且口头描述坐标不可靠。
切成 rows×cols 块、每块放大并打**大号字母编号**，老程只需回答「球在 C 块」。

用法:
  python engine/render_quadrants.py --clip sas_lal --frames 205,204,206 [--cols 4] [--rows 3]
产出: action_work/validate/<clip>_quad/<frame>_quad.jpg
      每块左上标 A/B/C…（先列后行），块内再画 100px 细网格 + 边缘坐标，便于精确定位。
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
LBL = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def big(img, txt, org, sc, col, th=3):
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, sc, (0, 0, 0), th + 5)
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, sc, col, th)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_lal")
    ap.add_argument("--frames-dir", default=None)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--cell", type=int, default=480, help="每块显示边长 px")
    ap.add_argument("--outdir", default=None)
    a = ap.parse_args()

    fdir = Path(a.frames_dir) if a.frames_dir else ROOT / "action_work" / a.clip
    outd = Path(a.outdir) if a.outdir else ROOT / "action_work/validate" / f"{a.clip}_quad"
    outd.mkdir(parents=True, exist_ok=True)

    for tok in str(a.frames).split(","):
        tok = tok.strip()
        if not tok:
            continue
        n = int(tok)
        fr = f"f{n:05d}.jpg"
        img = cv2.imread(str(fdir / fr))
        if img is None:
            print(f"  [skip] {fr}"); continue
        H, W = img.shape[:2]
        cw, ch = W // a.cols, H // a.rows
        tiles = []
        for r in range(a.rows):
            row = []
            for c in range(a.cols):
                blk = img[r*ch:(r+1)*ch, c*cw:(c+1)*cw]
                disp = cv2.resize(blk, (a.cell, int(a.cell * ch / cw)))
                # 100px 细网格 + 边缘坐标
                sx = disp.shape[1] / cw
                for gx in range(0, cw, 100):
                    cv2.line(disp, (int(gx*sx), 0), (int(gx*sx), disp.shape[0]), (60, 60, 60), 1)
                for gy in range(0, ch, 100):
                    cv2.line(disp, (0, int(gy*sx)), (disp.shape[1], int(gy*sx)), (60, 60, 60), 1)
                cv2.rectangle(disp, (0, 0), (disp.shape[1]-1, disp.shape[0]-1), (90, 90, 90), 2)
                lbl = LBL[r*a.cols + c] if (r*a.cols + c) < len(LBL) else "?"
                big(disp, lbl, (14, 62), 2.2, (80, 230, 110), 6)
                big(disp, f"x{c*cw}-{c*cw+cw} y{r*ch}-{r*ch+ch}", (14, disp.shape[0]-14), 0.75,
                    (200, 220, 255), 2)
                row.append(disp)
            tiles.append(np.hstack(row))
        out = np.vstack(tiles)
        hdr = np.full((58, out.shape[1], 3), 24, np.uint8)
        t = (n - 1) / 10.0
        big(hdr, f"{fr}   t={t:.2f}s   请回答：球在哪一块？（A/B/C...）", (16, 42), 1.2, (255, 255, 255), 3)
        out = np.vstack([hdr, out])
        p = outd / f"{fr.replace('.jpg','')}_quad.jpg"
        cv2.imwrite(str(p), out)
        print(f"  [out] {p}  {out.shape[1]}x{out.shape[0]}  {a.rows}x{a.cols}={a.rows*a.cols} 块")
    print(f"[done] {outd}")


if __name__ == "__main__":
    main()
