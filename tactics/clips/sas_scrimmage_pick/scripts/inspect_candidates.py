#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选目视核验: 为指定候选事件渲染「原始帧 + 检测标注」拼图, 供人工确认是不是真配合。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import argparse
import json
import math
import os

from common.nba_paths import data_file, tactics_data_file

os.environ["PYTHONPATH"] = ""
os.environ["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--events", required=True)
ap.add_argument("--idx", type=int, nargs="+", required=True)
ap.add_argument("--src", default=str(data_file("比赛录像/2027/季前赛/2026-27 Silver & Black Spurs Open Scrimmage.mp4")))
ap.add_argument("--outdir", required=True)
ap.add_argument("--min-h", type=float, default=100.0)
ap.add_argument("--ncols", type=int, default=4)
ap.add_argument("--scale", type=float, default=0.5)
a = ap.parse_args()

os.makedirs(a.outdir, exist_ok=True)
E = json.load(open(a.events, encoding="utf-8"))["events"]
cap = cv2.VideoCapture(a.src)

from ultralytics import YOLO

model = YOLO(str(tactics_data_file("yolov8n.pt")))

def grab(t):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    return f if ok else None

for rank in a.idx:
    e = E[rank - 1]
    ser = e["d_series"]
    # 接触段前后各取若干帧
    t_first, t_last = ser[0][0], ser[-1][0]
    span = t_last - t_first
    ts = [t_first - 1.2 + i * (span + 2.4) / (a.ncols * 2 - 1) for i in range(a.ncols * 2)]
    tiles = []
    for t in ts:
        f = grab(t)
        if f is None:
            continue
        r = model.predict(f, imgsz=640, conf=0.35, classes=[0], device="mps", verbose=False)[0]
        xy = r.boxes.xyxy.cpu().numpy()
        cf = r.boxes.conf.cpu().numpy()
        v = f.copy()
        for (x0, y0, x1, y1), c in zip(xy, cf):
            if (y1 - y0) < a.min_h:
                continue
            cv2.rectangle(v, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        # 该候选的配对两人: 用最接近的两个人高亮
        boxes = [(x0, y0, x1, y1) for (x0, y0, x1, y1) in xy if (y1 - y0) >= a.min_h]
        if len(boxes) >= 2:
            key = t_first + (t - ts[0])
            # 取该时刻最贴合序列距离的两框
            best, bp = None, None
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    cx1 = (boxes[i][0] + boxes[i][2]) / 2; cy1 = (boxes[i][1] + boxes[i][3]) / 2
                    cx2 = (boxes[j][0] + boxes[j][2]) / 2; cy2 = (boxes[j][1] + boxes[j][3]) / 2
                    d = math.hypot(cx1 - cx2, cy1 - cy2)
                    if best is None or d < best:
                        best, bp = d, (i, j)
            for idxc, col in ((bp[0], (0, 255, 255)), (bp[1], (0, 255, 0))):
                x0, y0, x1, y1 = boxes[idxc]
                cv2.rectangle(v, (int(x0), int(y0)), (int(x1), int(y1)), col, 3)
                cv2.circle(v, (int((x0 + x1) / 2), int((y0 + y1) / 2)), 4, col, -1)
            mx = int((boxes[bp[0]][0] + boxes[bp[0]][2]) / 2)
            my = int((boxes[bp[0]][1] + boxes[bp[0]][3]) / 2)
            cv2.line(v, (mx, my), (int((boxes[bp[1]][0] + boxes[bp[1]][2]) / 2),
                                    int((boxes[bp[1]][1] + boxes[bp[1]][3]) / 2)), (255, 255, 0), 2)
            cv2.putText(v, "d=%.0fpx" % best, (10, 34), 0, 1.1, (255, 255, 0), 3)
        cv2.putText(v, "t=%.2f" % t, (10, 700), 0, 0.9, (255, 255, 255), 2)
        tiles.append(v)
    if not tiles:
        continue
    cols = a.ncols
    rows = int(math.ceil(len(tiles) / cols))
    H, W = tiles[0].shape[:2]
    sc = a.scale
    sheet = np.zeros((int(H * sc) * rows, int(W * sc) * cols, 3), np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sm = cv2.resize(t, (int(W * sc), int(H * sc)))
        sheet[r * int(H * sc):(r + 1) * int(H * sc), c * int(W * sc):(c + 1) * int(W * sc)] = sm
    outp = os.path.join(a.outdir, "cand%02d_t%.1f.jpg" % (rank, e["apex_t"]))
    cv2.imwrite(outp, sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print("%s  t_apex=%.2f dmin=%.1f run=%d score=%.3f" % (outp, e["apex_t"], e["dmin"], e["run"], e["score"]))
cap.release()
