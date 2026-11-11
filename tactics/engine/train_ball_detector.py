#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_ball_detector.py — YOLOv8n 篮球检测器微调（MPS）。
用法: python train_ball_detector.py <dataset_dir> [--epochs 30 --imgsz 1280 --batch 4]
产出: <dataset_dir>/runs/ball_ft/weights/best.pt
"""
import argparse
from pathlib import Path

from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset_dir")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--base", default="yolov8n.pt")
    args = ap.parse_args()

    data = str(Path(args.dataset_dir) / "dataset.yaml")
    model = YOLO(args.base)
    r = model.train(
        data=data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        device="mps", project=str(Path(args.dataset_dir) / "runs"),
        name="ball_ft", exist_ok=True, patience=10, verbose=True,
    )
    best = Path(args.dataset_dir) / "runs" / "ball_ft" / "weights" / "best.pt"
    print("BEST:", best, best.exists())


if __name__ == "__main__":
    main()
