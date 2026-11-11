#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""detect_players_rfdetr.py — 全帧 RF-DETR 球员/裁判框检测（shot_type 过滤器的框来源）。

与 detect_ball_rfdetr.py 同模型（koppolusameer RF-DETR, 类别 {0:ball,1:player,2:referee}），
但导出 **player+referee** 类别框（全帧一次推理，无 tile —— 框统计用途不需要小目标精度）。

用法:
  python detect_players_rfdetr.py <frames_dir> <out_json> [--conf 0.3] [--device mps]
产出 JSON:
  { "<fn>.jpg": [ {"bbox":[x1,y1,x2,y2], "cls":"player"|"referee", "conf":s}, ... ] }
"""
# --- nba-paths bootstrap (auto, idempotent) ---

import argparse
import json
from pathlib import Path

import cv2
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection

DEFAULT_MODEL = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
                 + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
                 + "46c33088c790670a7e81e21e753fa368b2d77a70")
NAMES = {1: "player", 2: "referee"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("out_json")
    ap.add_argument("--model-dir", default=DEFAULT_MODEL)
    ap.add_argument("--conf", type=float, default=0.3)
    ap.add_argument("--device", default="mps")
    a = ap.parse_args()

    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(a.model_dir)
    model = AutoModelForObjectDetection.from_pretrained(a.model_dir).to(dev).eval()

    frames = sorted(Path(a.frames_dir).glob("*.jpg"))
    out = {}
    import time
    t0 = time.time()
    for n, f in enumerate(frames):
        img = cv2.imread(str(f))
        if img is None:
            out[f.name] = []
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        inp = proc(images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            o = model(**inp)
        res = proc.post_process_object_detection(
            o, threshold=a.conf, target_sizes=torch.tensor([[h, w]]).to(dev))[0]
        rec = []
        for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(), res["labels"].tolist()):
            if int(l) in NAMES:
                rec.append({"bbox": [round(float(v), 1) for v in b],
                            "cls": NAMES[int(l)], "conf": round(float(s), 3)})
        out[f.name] = rec
        if (n + 1) % 100 == 0:
            print(f"  {n+1}/{len(frames)}  {time.time()-t0:.0f}s", flush=True)

    Path(a.out_json).write_text(json.dumps(out))
    n_med = sum(len(v) for v in out.values()) / max(1, len(out))
    print(f"[out] {a.out_json}  帧 {len(out)}  均值框/帧 {n_med:.1f}  用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
