#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球检测分辨率对照 —— RF-DETR 的预处理默认 size=384x384（实测 preprocessor_config.json），
1920x1080 帧缩进去后 35px 的球只剩 ~7px。本脚本对照：
   (a) 全帧 @size N        N=384(基线)/768/1152/1536
   (b) 分块推理 tile WxH   保持 384 原生尺度，重叠 overlap 后跨块 NMS 合并
用法: detect_ball_hi.py <window> <out.json> --mode full|tile --size 768
        [--tile-w 640 --tile-h 384 --overlap 96 --conf 0.3 --n 60]
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
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from common.nba_paths import tactics_data_file

MODEL = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
         + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
         + "46c33088c790670a7e81e21e753fa368b2d77a70")
AW = Path(str(tactics_data_file("action_work")))
BALL = 0

def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0

def infer(proc, model, dev, bgr, thresh):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    inp = proc(images=rgb, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model(**inp)
    res = proc.post_process_object_detection(
        out, threshold=thresh, target_sizes=torch.tensor([[h, w]]).to(dev))[0]
    rec = []
    for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(), res["labels"].tolist()):
        if int(l) == BALL:
            rec.append({"bbox": [float(v) for v in b], "conf": float(s)})
    return rec

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("window"); ap.add_argument("out")
    ap.add_argument("--mode", default="full", choices=["full", "tile"])
    ap.add_argument("--size", type=int, default=384)
    ap.add_argument("--tile-w", type=int, default=640); ap.add_argument("--tile-h", type=int, default=384)
    ap.add_argument("--overlap", type=int, default=96)
    ap.add_argument("--conf", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--device", default="mps")
    a = ap.parse_args()
    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(MODEL)
    if a.mode == "full" and a.size != 384:
        proc.size = {"height": a.size, "width": a.size}
    model = AutoModelForObjectDetection.from_pretrained(MODEL).to(dev).eval()
    print(f"mode={a.mode} size={a.size} proc.size={proc.size} dev={dev}")

    fdir = AW / a.window
    files = sorted(p.name for p in fdir.glob("*.jpg"))
    step = max(1, len(files) // a.n)
    sel = files[::step][:a.n]
    out = {}
    import time

    t0 = time.time()
    for fn in sel:
        img = cv2.imread(str(fdir / fn))
        if img is None: continue
        if a.mode == "full":
            rec = infer(proc, model, dev, img, a.conf)
        else:
            H, W = img.shape[:2]
            tw, th, ov = a.tile_w, a.tile_h, a.overlap
            rec = []
            for y in range(0, H, th - ov):
                for x in range(0, W, tw - ov):
                    x2, y2 = min(W, x + tw), min(H, y + th)
                    if x2 - x <= ov or y2 - y <= ov: continue
                    sub = img[y:y2, x:x2]
                    for r in infer(proc, model, dev, sub, a.conf):
                        b = r["bbox"]
                        rec.append({"bbox": [b[0]+x, b[1]+y, b[2]+x, b[3]+y], "conf": r["conf"]})
            rec.sort(key=lambda r: -r["conf"])
            keep = []
            for r in rec:                      # 跨块 NMS
                if all(iou(r["bbox"], k["bbox"]) < 0.4 for k in keep):
                    keep.append(r)
            rec = keep[:4]
        rec.sort(key=lambda r: -r["conf"])
        out[fn] = rec
    print(f"frames={len(out)} with_ball={sum(1 for v in out.values() if v)} "
          f"({sum(1 for v in out.values() if v)/len(out)*100:.1f}%)  "
          f"boxes={sum(len(v) for v in out.values())}  用时 {time.time()-t0:.0f}s")
    Path(a.out).write_text(json.dumps(out))
    print("[out]", a.out)

if __name__ == "__main__":
    raise SystemExit(main())
