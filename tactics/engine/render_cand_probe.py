#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_cand_probe.py —— 把「放开 top-k」后提出的候选渲染成接触表，供目视复核。

用途：判断检测器漏提的球，是否其实存在于 top-4 之外的低 conf 候选里。
      若存在 → 扩容 top-k（或改排序依据）就能直接抬高覆盖率天花板；
      若不存在 → 天花板真在检测器，只能换模型/改 tile 分辨率。

输入: cand_probe_frames.json（engine/cand_pool_recall.py --probe-frames 产出）
产出: action_work/validate/<clip>_candprobe/<frame>_probe.jpg
      —— 上半=全帧（绿框+编号#i，红框=现役 top-4）  下半=top-N 候选 5x 放大网格
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_det")
    ap.add_argument("--frames-dir", default="action_work/sas_det")
    ap.add_argument("--probe", default="action_work/validate/cand_probe_frames.json")
    ap.add_argument("--topn", type=int, default=16)
    ap.add_argument("--outdir", default="action_work/validate/sas_det_candprobe")
    ap.add_argument("--ref", default=None, help="已知球候选号（在图上标绿星，作为外观基准）")
    a = ap.parse_args()

    d = json.loads((ROOT / a.probe).read_text())
    fdir = ROOT / a.frames_dir
    outd = ROOT / a.outdir
    outd.mkdir(parents=True, exist_ok=True)

    for fr, cands in d["frames"].items():
        img = cv2.imread(str(fdir / fr))
        if img is None:
            print(f"  [skip] {fr} 无帧"); continue
        H, W = img.shape[:2]
        top = cands[:a.topn]
        ov = img.copy()
        for i, c in enumerate(cands):
            x1, y1, x2, y2 = [int(v) for v in c["bbox"]]
            col = (40, 60, 230) if i < 4 else (60, 210, 90)   # BGR: 红=现役top4 绿=扩容新增
            cv2.rectangle(ov, (x1, y1), (x2, y2), col, 3 if i < 4 else 2)
            if i < a.topn:
                cv2.putText(ov, f"#{i}", (x1, max(12, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        scale = 1280.0 / W
        full = cv2.resize(ov, (1280, int(H * scale)))
        cv2.putText(full, f"{fr}  NMS候选={len(cands)}  红=现役top4  绿=扩容新增(top{a.topn})",
                    (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2)

        # 候选放大网格 5x（以候选中心裁 64px 源区 → 放大 5 倍 = 320px）
        cell, cols = 300, 6
        rows = int(np.ceil(len(top) / cols))
        grid = np.full((rows * cell, cols * cell, 3), 24, np.uint8)
        for i, c in enumerate(top):
            x1, y1, x2, y2 = c["bbox"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            h = 32
            sx1, sy1 = int(max(0, cx - h)), int(max(0, cy - h))
            sx2, sy2 = int(min(W, cx + h)), int(min(H, cy + h))
            crop = img[sy1:sy2, sx1:sx2]
            if crop.size == 0:
                continue
            big = cv2.resize(crop, (cell, cell), interpolation=cv2.INTER_CUBIC)
            r, cc = divmod(i, cols)
            grid[r*cell:(r+1)*cell, cc*cell:(cc+1)*cell] = big
            col = (40, 60, 230) if i < 4 else (60, 210, 90)
            cv2.rectangle(grid, (cc*cell, r*cell), ((cc+1)*cell, (r+1)*cell), (90, 90, 90), 2)
            # 大字：编号独占一行（避免 "#2 0.35" 挤成 "2035"）
            for txt, dy, sc in ((f"#{i}", 58, 1.9), (f"conf {c['conf']:.2f}", 106, 1.0)):
                cv2.putText(grid, txt, (cc*cell + 14, r*cell + dy),
                            cv2.FONT_HERSHEY_SIMPLEX, sc, (0, 0, 0), 8)
                cv2.putText(grid, txt, (cc*cell + 14, r*cell + dy),
                            cv2.FONT_HERSHEY_SIMPLEX, sc, col, 2)

        if a.ref is not None:
            ri = int(a.ref)
            if ri < len(top):
                rr, rc = divmod(ri, cols)   # divmod -> (行, 列)
                cv2.putText(grid, "KNOWN BALL", (rc*cell + 14, rr*cell + 152),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 3)
        gw = 1280
        grid = cv2.resize(grid, (gw, int(grid.shape[0] * gw / grid.shape[1])))
        out = np.vstack([full, grid])
        p = outd / f"{fr.replace('.jpg','')}_probe.jpg"
        cv2.imwrite(str(p), out)
        print(f"  [out] {p}  {out.shape[1]}x{out.shape[0]}  候选{len(top)}")
    print(f"[done] {outd}")


if __name__ == "__main__":
    main()
