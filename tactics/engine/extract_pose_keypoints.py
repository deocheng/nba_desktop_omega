#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_pose_keypoints.py — 用 yolo11n-pose 抽球员关键点（手臂/护球动作线索诊断的输入）。

产出: <out>.json = { "<fn>.jpg": [ {bbox, kps:[[x,y,conf]x17], conf}, ... ] }
COCO 关键点序: 5=左肩 6=右肩 7=左肘 8=右肘 9=左腕 10=右腕 11=左髋 12=右髋
用法:
  python engine/extract_pose_keypoints.py <frames_dir> <out.json> [--conf 0.35] [--device mps]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import time
from pathlib import Path

import cv2

from common.nba_paths import tactics_data_file

W = str(tactics_data_file("action_work/weights/yolo11n-pose.pt"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("out")
    ap.add_argument("--model", default=W)
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--device", default="mps")
    a = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(a.model)
    frames = sorted(Path(a.frames_dir).glob("*.jpg"))
    out = {}
    t0 = time.time()
    for n, f in enumerate(frames):
        img = cv2.imread(str(f))
        if img is None:
            out[f.name] = []
            continue
        res = model.predict(img, conf=a.conf, device=a.device, verbose=False)[0]
        rec = []
        if res.keypoints is not None and res.boxes is not None:
            kps = res.keypoints.data.tolist()
            boxes = res.boxes.xyxy.tolist()
            confs = res.boxes.conf.tolist()
            for b, k, c in zip(boxes, kps, confs):
                rec.append({"bbox": [round(float(v), 1) for v in b], "conf": round(float(c), 3),
                            "kps": [[round(float(p[0]), 1), round(float(p[1]), 1), round(float(p[2]), 3)]
                                    for p in k]})
        out[f.name] = rec
        if (n + 1) % 100 == 0:
            print(f"  {n+1}/{len(frames)}  {time.time()-t0:.0f}s", flush=True)
    Path(a.out).write_text(json.dumps(out))
    nk = sum(1 for v in out.values() if v)
    print(f"[out] {a.out}  帧 {len(out)}  有关键点帧 {nk}  用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
