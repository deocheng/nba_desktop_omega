#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""粗扫：从整场比赛录像按固定帧率抽帧，逐帧 YOLO 检出球员(+球，参考用)。
输出 JSONL: 每行一帧的 {t, people:[[x0,y0,x1,y1,conf]...], ball:[...]|None,
                    energy:帧差运动能量, cut:是否疑似镜头切换}
坐标系统一还原到原始 1280x720 (检测用 imgsz=640，坐标按比例还原)。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import argparse
import json
import os
import subprocess
import sys
import time

from common.nba_paths import data_file, tactics_data_file

os.environ["PYTHONPATH"] = ""
os.environ["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

SRC = str(data_file("比赛录像/2027/季前赛/2026-27 Silver & Black Spurs Open Scrimmage.mp4"))
FFMPEG = "/opt/homebrew/bin/ffmpeg"
# ⚠️ 指派指定的 yolo11_basketball.pt 在本片源上类别头损坏：CPU/MPS 均只输出 cls=32(sports ball)
#    的碎小框、person=0(实测 t=1800: cls直方图 {32:23}，medianH=30px)，
#    而其 ckpt 自报 COCO80 mAP50=0.979 → 权重本身不可疑，是与本工程的推理链路不兼容。
#    改用同目录可用权重 yolov8n.pt(实测同帧 cls直方图 {0:17}，人框贴合)。
#    该替换已在 REPORT.md 中显式记录。详见 verify_weights.py。
WEIGHTS = str(tactics_data_file("yolov8n.pt"))
W, H = 1280, 720

ap = argparse.ArgumentParser()
ap.add_argument("--fps", type=float, default=4.0)
ap.add_argument("--imgsz", type=int, default=640)
ap.add_argument("--conf", type=float, default=0.40)
ap.add_argument("--out", required=True)
ap.add_argument("--start", type=float, default=0.0)
ap.add_argument("--end", type=float, default=3912.0)
ap.add_argument("--limit", type=int, default=0, help="只处理前 N 帧(测速用)")
ap.add_argument("--stride", type=int, default=1, help="每隔 N 个采样帧处理一次(跳帧加速)")
a = ap.parse_args()

import cv2
import numpy as np
from ultralytics import YOLO

print("[init] loading model...", flush=True)
model = YOLO(WEIGHTS)
print("[init] ok", flush=True)

cmd = [FFMPEG, "-v", "error", "-ss", str(a.start), "-to", str(a.end),
       "-i", SRC, "-vf", f"fps={a.fps}", "-pix_fmt", "bgr24",
       "-f", "rawvideo", "-"]
print("[init] ffmpeg:", " ".join(cmd), flush=True)
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)

frame_bytes = W * H * 3
step_t = 1.0 / a.fps
prev_small = None
idx = 0            # 采样帧序号
fi = 0             # 已读取帧数
done = False
t0 = time.time()
os.makedirs(os.path.dirname(a.out), exist_ok=True)
fout = open(a.out, "w", encoding="utf-8")

res = model.predict  # 缓存
while not done:
    buf = proc.stdout.read(frame_bytes)
    if len(buf) < frame_bytes:
        break
    frame = np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 3)
    fi += 1
    if (fi - 1) % a.stride:
        continue
    # 运动能量 & 切换检测用的小图
    small = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.int16)
    if prev_small is None:
        energy, cut = 0.0, False
    else:
        d = np.abs(small - prev_small)
        energy = float(d.mean())
        cut = bool(d.mean() > 18.0)
    prev_small = small

    rec, ball = None, None
    people = []
    out = res(frame, imgsz=a.imgsz, conf=0.20, classes=[0, 32], device="mps", verbose=False)[0]
    bxy = out.boxes.xyxy.cpu().numpy()
    bcl = out.boxes.conf.cpu().numpy()
    bcs = out.boxes.cls.cpu().numpy().astype(int)
    for row, cf, cs in zip(bxy, bcl, bcs):
        if cs == 0 and cf >= a.conf:
            people.append([round(float(v), 1) for v in row[:4]])
        elif cs == 32 and cf >= 0.25 and ball is None:
            ball = [round(float(v), 1) for v in row[:4]] + [round(float(cf), 3)]

    t = a.start + idx * step_t
    fout.write(json.dumps({"i": idx, "t": round(t, 3), "n": len(people),
                           "people": people, "ball": ball,
                           "energy": round(energy, 3), "cut": cut}) + "\n")
    if idx % 8 == 0:
        fout.flush()
    idx += 1
    if idx % 400 == 0:
        el = time.time() - t0
        print(f"[scan] {idx} frames  {el:.0f}s  {idx/el:.1f} fps  t={t:.0f}s", flush=True)
        fout.flush()
    if a.limit and idx >= a.limit:
        done = True
        break

proc.stdout.close()
proc.wait()
fout.close()
print(f"[done] {idx} frames in {time.time()-t0:.0f}s -> {a.out}", flush=True)
