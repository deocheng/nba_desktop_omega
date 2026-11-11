#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_verify_sheet.py — 目视校验图生成。

--frames 模式：整帧缩略拼图（画候选框，color=绿 coco=青），看整体布局。
--crops  模式：每个候选拉 64px 放大裁剪 + 全局 cand_id，12x8=96/页，
              小目标真假才判得准（球 vs logo/地板）。
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def frames_mode(args, cands):
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = sorted(cands.keys())
    per = args.cols * args.rows
    th = int(args.thumb_w * 0.5625)
    for si, i0 in enumerate(range(0, len(frames), per)):
        group = frames[i0:i0 + per]
        thumbs = []
        for name in group:
            img = cv2.imread(str(Path(args.frames_dir) / name))
            if img is None:
                img = np.zeros((th, args.thumb_w, 3), np.uint8)
            h, w = img.shape[:2]
            scale = args.thumb_w / w
            timg = cv2.resize(img, (args.thumb_w, int(h * scale)))
            for c in cands[name]:
                x1, y1, x2, y2 = [int(v * scale) for v in c["bbox"]]
                col = (0, 255, 0) if c.get("src") == "color" else (255, 255, 0)
                cv2.rectangle(timg, (x1, y1), (x2, y2), col, 1)
            cv2.putText(timg, name, (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                        (255, 255, 255), 1)
            thumbs.append(timg)
        while len(thumbs) < per:
            thumbs.append(np.zeros((th, args.thumb_w, 3), np.uint8))
        rows = [cv2.hconcat(thumbs[r * args.cols:(r + 1) * args.cols])
                for r in range(args.rows)]
        cv2.imwrite(str(out / f"sheet_{si:03d}.png"), cv2.vconcat(rows))
        print(f"wrote {out / f'sheet_{si:03d}.png'} ({len(group)} frames)")


def crops_mode(args, cands):
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # 展平
    items = []
    for name in sorted(cands.keys()):
        for c in cands[name]:
            items.append((name, c))
    per = args.cols * args.rows
    cell = args.cell
    sheets = [items[i:i + per] for i in range(0, len(items), per)]
    for si, group in enumerate(sheets):
        cells = []
        for name, c in group:
            img = cv2.imread(str(Path(args.frames_dir) / name))
            if img is None:
                img = np.zeros((cell, cell, 3), np.uint8)
            else:
                h, w = img.shape[:2]
                x1, y1, x2, y2 = [int(v) for v in c["bbox"]]
                pad = int(max(x2 - x1, y2 - y1) * 0.8) + 4
                cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
                cx2, cy2 = min(w, x2 + pad), min(h, y2 + pad)
                crop = img[cy1:cy2, cx1:cx2]
                if crop.size == 0:
                    crop = np.zeros((cell, cell, 3), np.uint8)
                crop = cv2.resize(crop, (cell, cell))
                cv2.rectangle(crop, (2, 2), (cell - 3, cell - 3), (0, 255, 0), 1)
            cv2.putText(crop, str(c["cand_id"]), (2, 13),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
            cells.append(crop)
        while len(cells) < per:
            cells.append(np.zeros((cell, cell, 3), np.uint8))
        rows = [cv2.hconcat(cells[r * args.cols:(r + 1) * args.cols])
                for r in range(args.rows)]
        cv2.imwrite(str(out / f"crops_{si:03d}.png"), cv2.vconcat(rows))
        print(f"wrote {out / f'crops_{si:03d}.png'} ({len(group)} candidates, "
              f"ids {group[0][1]['cand_id']}..{group[-1][1]['cand_id']})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("candidates_json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--mode", choices=["frames", "crops"], default="frames")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--rows", type=int, default=6)
    ap.add_argument("--thumb-w", type=int, default=240)
    ap.add_argument("--cell", type=int, default=64)
    args = ap.parse_args()
    cands = json.loads(Path(args.candidates_json).read_text())
    if args.mode == "frames":
        frames_mode(args, cands)
    else:
        crops_mode(args, cands)


if __name__ == "__main__":
    main()
