#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""权重可用性核验：证明 yolo11_basketball.pt 在本片源上失效、yolov8n.pt 可用。
在 4 个代表性时间点上分别用 CPU/MPS 跑同一帧，输出类别直方图与人框高度中位数。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import os

from common.nba_paths import data_file, tactics_data_file

os.environ["PYTHONPATH"] = ""
os.environ["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import collections

import cv2
import numpy as np
from ultralytics import YOLO

SRC = str(data_file("比赛录像/2027/季前赛/2026-27 Silver & Black Spurs Open Scrimmage.mp4"))
W11 = str(tactics_data_file("action_work/weights/yolo11_basketball.pt"))
V8N = str(tactics_data_file("yolov8n.pt"))
TIMES = [3.0, 120.0, 600.0, 1800.0]

cap = cv2.VideoCapture(SRC)
frames = {}
for t in TIMES:
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    if ok:
        frames[t] = f
cap.release()

for name, w in [("yolo11_basketball", W11), ("yolov8n", V8N)]:
    m = YOLO(w)
    for dev in ["cpu", "mps"]:
        for t, f in frames.items():
            r = m.predict(f, imgsz=640, conf=0.20, verbose=False, device=dev)[0]
            xy = r.boxes.xyxy.cpu().numpy()
            cs = r.boxes.cls.cpu().numpy().astype(int)
            cf = r.boxes.conf.cpu().numpy()
            hist = dict(collections.Counter(cs.tolist()))
            nper = int((cs == 0).sum())
            hs = (xy[:, 3] - xy[:, 1]) if len(xy) else np.array([0.0])
            print(f"{name:20s} {dev:4s} t={t:7.1f}  dets={len(cs):3d}  person={nper:3d}  "
                  f"cls_hist={hist}  medianH={np.median(hs):.0f}px  maxconf={cf.max():.2f}")
