#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_frame_check.py —— 指定帧「大字」核对图（老程 2026-09-27「字太小分不清」专用）。

与 render_cand_probe.py 的区别：
  - 输入直接用现役候选池 `<clip>_cands.json`（不重跑检测器）；
  - **编号/尺寸/坐标一律大字号**，格子更大（cell=280），一眼可读；
  - 可选 `--neighbors N` 附带邻帧同一坐标窗（邻帧运动性检验用，静止=背景、穿越=球）。

用法:
  python engine/render_frame_check.py --clip sas_lal --frames 204,205,206 [--topn 4] [--neighbors 2]
产出: action_work/validate/<clip>_framecheck/<frame>_check.jpg
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

ROOT = Path(str(tactics_data_file("")))


def big_label(img, txt, org, scale=1.0, col=(255, 255, 255), thick=3):
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 4)
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, scale, col, thick)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_lal")
    ap.add_argument("--frames-dir", default=None)
    ap.add_argument("--cands", default=None)
    ap.add_argument("--frames", required=True, help="逗号分隔帧号，如 204,205,206")
    ap.add_argument("--topn", type=int, default=4)
    ap.add_argument("--neighbors", type=int, default=0,
                    help=">0 时附带邻帧同一坐标窗（运动性检验）")
    ap.add_argument("--outdir", default=None)
    a = ap.parse_args()

    fdir = Path(a.frames_dir) if a.frames_dir else ROOT / "action_work" / a.clip
    cands_p = Path(a.cands) if a.cands else ROOT / "action_work/validate" / f"{a.clip}_cands.json"
    cd = json.loads(cands_p.read_text())
    cands_all = cd.get(a.clip, cd)
    outd = Path(a.outdir) if a.outdir else ROOT / "action_work/validate" / f"{a.clip}_framecheck"
    outd.mkdir(parents=True, exist_ok=True)

    nums = [int(t) for t in a.frames.split(",") if t.strip()]
    for n in nums:
        fr = f"f{n:05d}.jpg"
        img = cv2.imread(str(fdir / fr))
        if img is None:
            print(f"  [skip] {fr} 无帧"); continue
        H, W = img.shape[:2]
        cs = cands_all.get(fr, [])[:a.topn]

        # ── 上半：全帧（框 + 大号 #i）──
        ov = img.copy()
        for i, c in enumerate(cs):
            x1, y1, x2, y2 = [int(v) for v in c["bbox"]]
            cv2.rectangle(ov, (x1, y1), (x2, y2), (60, 230, 90), 4)
            big_label(ov, f"#{i}", (x1, max(40, y1 - 12)), 1.6, (60, 230, 90), 4)
        sc = 1280.0 / W
        full = cv2.resize(ov, (1280, int(H * sc)))
        t = (n - 1) / 10.0
        big_label(full, f"{fr}   t={t:.2f}s   ({t//60:.0f}:{t%60:05.2f})", (16, 52), 1.25, (255, 255, 255), 3)

        # ── 下半：候选大格放大（cell 280，编号 2 倍字号）──
        cell = 280
        cols = min(len(cs), 4) or 1
        rows = int(np.ceil(len(cs) / cols))
        grid = np.full((rows * cell, cols * cell, 3), 22, np.uint8)
        for i, c in enumerate(cs):
            x1, y1, x2, y2 = c["bbox"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            h = 40
            sx1, sy1 = int(max(0, cx - h)), int(max(0, cy - h))
            sx2, sy2 = int(min(W, cx + h)), int(min(H, cy + h))
            crop = img[sy1:sy2, sx1:sx2]
            if crop.size == 0:
                continue
            big = cv2.resize(crop, (cell, cell), interpolation=cv2.INTER_CUBIC)
            r, cc = divmod(i, cols)
            grid[r*cell:(r+1)*cell, cc*cell:(cc+1)*cell] = big
            cv2.rectangle(grid, (cc*cell, r*cell), ((cc+1)*cell, (r+1)*cell), (90, 90, 90), 2)
            big_label(grid, f"#{i}", (cc*cell + 14, r*cell + 58), 2.0, (60, 230, 90), 5)
            big_label(grid, f"conf1={c['conf1']:.2f}", (cc*cell + 14, r*cell + 108), 0.95, (255, 255, 255), 3)
            big_label(grid, f"({cx:.0f},{cy:.0f}) {max(x2-x1,y2-y1):.0f}px",
                      (cc*cell + 14, r*cell + 148), 0.95, (180, 200, 255), 3)

        gw = 1280
        grid = cv2.resize(grid, (gw, int(grid.shape[0] * gw / grid.shape[1])))
        parts = [full, grid]

        # ── 可选：邻帧运动性检验条 ──
        if a.neighbors > 0 and cs:
            wins = []
            rng = range(n - a.neighbors, n + a.neighbors + 1)
            for m in rng:
                f2 = f"f{m:05d}.jpg"
                im2 = cv2.imread(str(fdir / f2))
                if im2 is None:
                    continue
                x1, y1, x2, y2 = cs[0]["bbox"]
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                h = 60
                crop = im2[int(max(0, cy-h)):int(cy+h), int(max(0, cx-h)):int(cx+h)]
                if crop.size == 0:
                    continue
                crop = cv2.resize(crop, (160, 160), interpolation=cv2.INTER_CUBIC)
                big_label(crop, f2.replace("f", "").replace(".jpg", ""), (6, 30), 0.7, (255, 255, 255), 2)
                cv2.rectangle(crop, (0, 0), (159, 159), (60, 230, 90), 2)
                wins.append(crop)
            if wins:
                bar = np.hstack(wins)
                bar = cv2.resize(bar, (1280, int(bar.shape[0] * 1280 / bar.shape[1])))
                cap = np.full((46, bar.shape[1], 3), 30, np.uint8)
                big_label(cap, "邻帧运动性检验 @#0 中心  (静止=背景 / 移动=球)",
                          (12, 34), 1.0, (255, 255, 255), 2)
                parts.append(np.vstack([cap, bar]))

        out = np.vstack(parts)
        p = outd / f"{fr.replace('.jpg','')}_check.jpg"
        cv2.imwrite(str(p), out)
        print(f"  [out] {p}  {out.shape[1]}x{out.shape[0]}  候选{len(cs)}")
    print(f"[done] {outd}")


if __name__ == "__main__":
    main()
