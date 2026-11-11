#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_possession.py — 渲染占有权段供目视验收。
绿框=球(RF-DETR)，红框=被判持球的球员，标注 track_id 与帧号。
用法: python render_possession.py <frames_dir> <ball_tracks.json> <out_dir>
        --start 635 --end 658 [--cols 6]
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("ball_tracks_json")
    ap.add_argument("out_dir")
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--thumb-w", type=int, default=460)
    args = ap.parse_args()

    d = json.loads(Path(args.ball_tracks_json).read_text())
    sel = [fr for fr in d if args.start <= fr["frame"] < args.end]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    thumbs = []
    for fr in sel:
        img = cv2.imread(str(Path(args.frames_dir) / fr["file"]))
        if img is None:
            continue
        h, w = img.shape[:2]
        s = args.thumb_w / w
        t = cv2.resize(img, (args.thumb_w, int(h * s)))
        if fr["ball"]:
            b = [int(v * s) for v in fr["ball"]["bbox"]]
            cv2.rectangle(t, (b[0], b[1]), (b[2], b[3]), (0, 255, 0), 2)
        pid = fr["poss_track_id"]
        for p in fr["players"]:
            if pid is not None and p["track_id"] == pid:
                b = [int(v * s) for v in p["bbox"]]
                cv2.rectangle(t, (b[0], b[1]), (b[2], b[3]), (0, 0, 255), 3)
                cv2.putText(t, f"P{p['track_id']}", (b[0], max(14, b[1] - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(t, f"f{fr['frame']}", (4, 18), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1)
        thumbs.append(t)

    th = thumbs[0].shape[0]
    while len(thumbs) % args.cols != 0:
        thumbs.append(np.zeros((th, args.thumb_w, 3), np.uint8))
    rows = [cv2.hconcat(thumbs[i:i + args.cols])
            for i in range(0, len(thumbs), args.cols)]
    sheet = cv2.vconcat(rows)
    p = out / f"poss_{args.start}_{args.end}.png"
    cv2.imwrite(str(p), sheet)
    print("wrote", p, f"({len(sel)} frames)")


if __name__ == "__main__":
    main()
