#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ball_diag.py — 探测 COCO sports-ball 在本素材上的检测率上限。
逐帧以极低阈值(conf=0.01)跑球检测，统计不同阈值下的检出率与最大置信，
并报告球员检测率、含球帧里最近球员距离。用于判断 COCO 基线是否可用、
还是必须换 UCD-MBB 篮球域微调权重。
"""
import argparse
import sys
from pathlib import Path

import cv2
from ultralytics import YOLO

PERSON = 0
BALL = 32
THRESH = [0.01, 0.05, 0.1, 0.2, 0.3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("--ball-model", default="yolov8n.pt")
    ap.add_argument("--player-model", default="yolov8n.pt")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--start", type=int, default=100)
    ap.add_argument("--end", type=int, default=320)
    args = ap.parse_args()

    ball_model = YOLO(args.ball_model)
    player_model = YOLO(args.player_model)
    frames = sorted(Path(args.frames_dir).glob("*.jpg"))[args.start:args.end]
    if not frames:
        print("no frames", file=sys.stderr); sys.exit(1)

    cnt = {t: 0 for t in THRESH}
    max_conf = 0.0
    n_player = 0
    n_frames_ball = 0
    poss_in_ball_frames = 0

    for f in frames:
        br = ball_model(str(f), classes=[BALL], conf=0.01,
                        device=args.device, verbose=False)[0]
        pr = player_model(str(f), classes=[PERSON], conf=0.3,
                          device=args.device, verbose=False)[0]
        if len(pr.boxes.xyxy) > 0:
            n_player += 1
        if len(br.boxes.xyxy) > 0:
            confs = br.boxes.conf.tolist()
            mc = max(confs)
            max_conf = max(max_conf, mc)
            n_frames_ball += 1
            for t in THRESH:
                if mc >= t:
                    cnt[t] += 1
            # 最近球员距离(看占有权是否可赋)
            bx = sum(br.boxes.xyxy[0].tolist()[0:4:2]) / 2
            by = sum(br.boxes.xyxy[0].tolist()[1:4:2]) / 2
            pxy = pr.boxes.xyxy.tolist()
            md = 1e9
            for (x1, y1, x2, y2) in pxy:
                px = (x1 + x2) / 2; py = (y1 + y2) / 2
                md = min(md, ((px - bx) ** 2 + (py - by) ** 2) ** 0.5)
            if md < 1e8:
                poss_in_ball_frames += 1

    n = len(frames)
    print(f"frames={n} (idx {args.start}..{args.end-1})")
    print(f"player_detect_rate={n_player/n:.3f}")
    print(f"frames_with_any_ball(conf>=0.01)={n_frames_ball} ({n_frames_ball/n:.3f})")
    print(f"max_ball_conf={max_conf:.3f}")
    for t in THRESH:
        print(f"  ball_rate @conf>={t}: {cnt[t]}/{n} = {cnt[t]/n:.3f}")
    print(f"ball_frames_with_near_player={poss_in_ball_frames}/{n_frames_ball}")


if __name__ == "__main__":
    main()
