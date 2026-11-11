#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ball_label_gen.py — 篮球候选框生成（里程碑 05 · Phase B 标注）

策略：用里程碑 12 已标定的 HSV 颜色窗口(篮球专属线索)生成候选框，
并集 COCO sports-ball(conf>=0.01) 提案，最大化**召回**（假阳性由后续目视校验过滤）。
候选框由轮廓/检测直接给出，像素精确；我只需目视验收真假，不必手画框。

输出 labels_candidates.json:
  { "<frame.jpg>": [ {"bbox":[x1,y1,x2,y2], "src":"color"|"coco", "score":float}, ... ], ... }

阈值均可命令行调（校准用）。颜色窗口默认值已按里程碑 12 标定放宽以保召回。
OpenCV HSV: H 0-180, S/V 0-255。
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

PERSON = 0
BALL = 32


def color_candidates(img, args):
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 颜色窗口（OpenCV 0-180 / 0-255）
    lower = np.array([args.h_lo, args.s_lo, args.v_lo], np.uint8)
    upper = np.array([args.h_hi, args.s_hi, args.v_hi], np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    # RGB 差约束（R-G/R-B），OpenCV 为 BGR
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.int16)
    rg = rgb[:, :, 0] - rgb[:, :, 1]
    rb = rgb[:, :, 0] - rgb[:, :, 2]
    rg_mask = ((rg >= args.rg_lo) & (rg <= args.rg_hi)).astype(np.uint8) * 255
    rb_mask = ((rb >= args.rb_lo) & (rb <= args.rb_hi)).astype(np.uint8) * 255
    mask = cv2.bitwise_and(mask, rg_mask)
    mask = cv2.bitwise_and(mask, rb_mask)
    # 形态学去噪
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_d = args.min_d_rel * w
    max_d = args.max_d_rel * w
    out = []
    for c in cnts:
        area = cv2.contourArea(c)
        if area < args.min_area:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        diam = (bw + bh) / 2.0
        if diam < min_d or diam > max_d:
            continue
        # 圆度 + fill
        peri = cv2.arcLength(c, True)
        if peri < 1e-3:
            continue
        circ = 4 * np.pi * area / (peri * peri)
        fill = area / (bw * bh) if bw * bh > 0 else 0
        if circ < args.min_circ or fill < args.min_fill:
            continue
        out.append({"bbox": [float(x), float(y), float(x + bw), float(y + bh)],
                    "src": "color", "score": round(float(fill * circ), 3)})
    return out


def coco_candidates(img, model, args):
    res = model(img, classes=[BALL], conf=args.coco_conf, verbose=False)[0]
    out = []
    if len(res.boxes.xyxy) > 0:
        for (x1, y1, x2, y2), c in zip(res.boxes.xyxy.tolist(), res.boxes.conf.tolist()):
            out.append({"bbox": [float(x1), float(y1), float(x2), float(y2)],
                        "src": "coco", "score": round(float(c), 3)})
    return out


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    aA = (ax2 - ax1) * (ay2 - ay1)
    bA = (bx2 - bx1) * (by2 - by1)
    return inter / (aA + bA - inter)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--coco-model", default="yolov8n.pt")
    ap.add_argument("--no-coco", action="store_true")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    # 颜色窗口阈值（OpenCV 0-180 / 0-255）
    ap.add_argument("--h-lo", type=int, default=6)
    ap.add_argument("--h-hi", type=int, default=18)
    ap.add_argument("--s-lo", type=int, default=100)
    ap.add_argument("--s-hi", type=int, default=185)
    ap.add_argument("--v-lo", type=int, default=80)
    ap.add_argument("--v-hi", type=int, default=205)
    ap.add_argument("--rg-lo", type=int, default=20)
    ap.add_argument("--rg-hi", type=int, default=85)
    ap.add_argument("--rb-lo", type=int, default=35)
    ap.add_argument("--rb-hi", type=int, default=115)
    ap.add_argument("--min-area", type=int, default=20)
    ap.add_argument("--min-d-rel", type=float, default=0.010)
    ap.add_argument("--max-d-rel", type=float, default=0.060)
    ap.add_argument("--min-circ", type=float, default=0.5)
    ap.add_argument("--min-fill", type=float, default=0.5)
    ap.add_argument("--coco-conf", type=float, default=0.01)
    args = ap.parse_args()

    frames = sorted(Path(args.frames_dir).glob("*.jpg"))
    if args.end > 0:
        frames = frames[args.start:args.end]
    else:
        frames = frames[args.start:]

    coco = None
    if not args.no_coco:
        coco = YOLO(args.coco_model)

    result = {}
    for f in frames:
        img = cv2.imread(str(f))
        if img is None:
            continue
        cands = color_candidates(img, args)
        if coco is not None:
            cands += coco_candidates(img, coco, args)
        # 去重：IoU>0.5 合并（保留 score 高者）
        merged = []
        for c in sorted(cands, key=lambda x: -x["score"]):
            if any(iou(c["bbox"], m["bbox"]) > 0.5 for m in merged):
                continue
            merged.append(c)
        result[f.name] = merged

    Path(args.out).write_text(json.dumps(result, indent=1))
    n_frames = len(result)
    n_with = sum(1 for v in result.values() if v)
    total = sum(len(v) for v in result.values())
    print(f"frames={n_frames} with_candidate={n_with} total_candidates={total}")


if __name__ == "__main__":
    main()
