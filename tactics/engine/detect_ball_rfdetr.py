#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_ball_rfdetr.py — 用 RF-DETR 篮球检测器(Roboflow 数据集微调, Apache-2.0)
产出外置球检测 JSON，供 ball_possession.py --ball-json 使用。
模型类别: {0: ball, 1: player, 2: referee}；只导出 ball(cls=0)。

用法:
  python detect_ball_rfdetr.py <frames_dir> <out_json> [--start 0 --end 0]
      [--model-dir <local snapshot>] [--conf 0.3] [--device mps]
"""
# --- nba-paths bootstrap (auto, idempotent) ---

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection

DEFAULT_MODEL = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
                 + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
                 + "46c33088c790670a7e81e21e753fa368b2d77a70")
BALL = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("out_json")
    ap.add_argument("--model-dir", default=DEFAULT_MODEL)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--conf", type=float, default=0.3)
    ap.add_argument("--device", default="mps")
    args = ap.parse_args()

    dev = args.device if (args.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(args.model_dir)
    model = AutoModelForObjectDetection.from_pretrained(args.model_dir).to(dev).eval()

    frames = sorted(Path(args.frames_dir).glob("*.jpg"))
    frames = frames[args.start:args.end] if args.end > 0 else frames[args.start:]

    out = {}
    n_det = 0
    for f in frames:
        img = cv2.imread(str(f))
        if img is None:
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        inputs = proc(images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            outputs = model(**inputs)
        try:
            res = proc.post_process_object_detection(
                outputs, threshold=args.conf,
                target_sizes=torch.tensor([[h, w]]).to(dev))[0]
            boxes = res["boxes"].tolist()
            scores = res["scores"].tolist()
            labels = res["labels"].tolist()
        except Exception:
            # 手工解码回退
            logits = outputs.logits[0]
            prob = logits.sigmoid() if logits.max() <= 1.0 else logits.softmax(-1)
            cxcywh = outputs.pred_boxes[0]
            keep = prob.max(-1).values >= args.conf
            boxes, scores, labels = [], [], []
            for pb, (sc, lb) in zip(cxcywh[keep], zip(prob.max(-1).values[keep],
                                                     prob.argmax(-1)[keep])):
                cx, cy, bw, bh = pb.tolist()
                boxes.append([(cx - bw / 2) * w, (cy - bh / 2) * h,
                              (cx + bw / 2) * w, (cy + bh / 2) * h])
                scores.append(float(sc))
                labels.append(int(lb))

        recs = []
        for b, s, l in zip(boxes, scores, labels):
            if l != BALL:
                continue
            recs.append({"bbox": [float(v) for v in b], "conf": float(s)})
        recs.sort(key=lambda r: -r["conf"])
        if recs:
            n_det += 1
        out[f.name] = recs

    Path(args.out_json).write_text(json.dumps(out))
    print(f"frames={len(out)} frames_with_ball={n_det} "
          f"total_ball_boxes={sum(len(v) for v in out.values())} device={dev}")


if __name__ == "__main__":
    main()
