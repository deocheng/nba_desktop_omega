#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证器工作点扫描：裁切尺寸 × 匹配规则 × conf 阈值，在 60 标注样本上找 TP保留/FP杀伤 平衡。

裁切尺寸: 192(2x zoom) / 256(1.5x) / 384(1x, 原生 tile 尺度)
匹配规则: IoU>0.3 / IoU>0.1 / 球心落在检出框内(center-in)
YOLO 只用 class 32 (sports ball)。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection
from ultralytics import YOLO

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MEAS = Path(str(tactics_data_file("reports/milestone_05/measure")))
RF = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
      + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
      + "46c33088c790670a7e81e21e753fa368b2d77a70")
YOLO_BB = AW / "weights" / "yolo11_basketball.pt"


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def center_in(det, mb):
    cx, cy = (mb[0] + mb[2]) / 2, (mb[1] + mb[3]) / 2
    return det[0] <= cx <= det[2] and det[1] <= cy <= det[3]


def main():
    man = json.loads((MEAS / "manifest.json").read_text())
    lab = json.loads((MEAS / "labels.json").read_text())
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    rf = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()
    ym = YOLO(str(YOLO_BB))

    def rf_infer(bgr, thresh=0.1):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        inp = proc(images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            out = rf(**inp)
        h, w = rgb.shape[:2]
        res = proc.post_process_object_detection(
            out, threshold=thresh, target_sizes=torch.tensor([[h, w]]).to(dev))[0]
        return [(b, s) for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(),
                                          res["labels"].tolist()) if int(l) == 0]

    feats = []  # 每样本: {label, crop:{size:{rf_dets:[(bbox,conf)], yo_dets}}}
    for i, (m, l) in enumerate(zip(man, lab)):
        img = cv2.imread(str(AW / m["window"] / m["frame"]))
        if img is None:
            continue
        x1, y1, x2, y2 = m["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rec = {"label": l["label"], "crops": {}}
        for CROP in (192, 256, 384):
            h = CROP // 2
            X1, Y1 = int(cx - h), int(cy - h)
            sx1, sy1 = max(0, X1), max(0, Y1)
            sx2, sy2 = min(img.shape[1], X1 + CROP), min(img.shape[0], Y1 + CROP)
            crop = img[sy1:sy2, sx1:sx2].copy()
            ch, cw = crop.shape[:2]
            if ch < 30 or cw < 30:
                continue
            sc = 384.0 / cw
            mb = [(x1 - X1) * sc, (y1 - Y1) * sc, (x2 - X1) * sc, (y2 - Y1) * sc]
            rd = rf_infer(cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC))
            yres = ym.predict(cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC),
                              conf=0.1, device=dev, verbose=False)[0]
            yd = []
            if yres.boxes is not None and len(yres.boxes):
                for b, s, c in zip(yres.boxes.xyxy.tolist(), yres.boxes.conf.tolist(),
                                   yres.boxes.cls.tolist()):
                    if int(c) == 32:
                        yd.append((b, float(s)))
            rec["crops"][CROP] = {"rf": rd, "yo": yd, "mb": mb}
        feats.append(rec)

    def hit_rate(rf_hit, yo_hit, keep):
        tp = sum(1 for f in feats if f["label"] and keep(f))
        fp = sum(1 for f in feats if not f["label"] and keep(f))
        prec = tp / (tp + fp) * 100 if tp + fp else 0
        return f"TP {tp}/33  FP {fp}/27  精度 {prec:.1f}%"

    rules = {
        "IoU>0.3": lambda d, mb: iou(d, mb) > 0.3,
        "IoU>0.1": lambda d, mb: iou(d, mb) > 0.1,
        "center-in": lambda d, mb: center_in(d, mb),
    }
    for CROP in (192, 256, 384):
        print(f"\n===== CROP={CROP} =====")
        for rname, rule in rules.items():
            for cth in (0.0, 0.2, 0.3, 0.5):
                def keep(f, C=CROP, R=rule, T=cth):
                    c = f["crops"].get(C)
                    if not c:
                        return False
                    return any(R(d, c["mb"]) and s > T for d, s in c["rf"])
                print(f"  RF {rname:<9} conf>{cth:<4} {hit_rate(None,None,keep)}")
        # AND 与 YOLO
        def keep_and(f, C=CROP, T=0.0):
            c = f["crops"].get(C)
            if not c:
                return False
            rf_ok = any(iou(d, c["mb"]) > 0.1 and s > T for d, s in c["rf"])
            yo_ok = any(iou(d, c["mb"]) > 0.1 and s > T for d, s in c["yo"])
            return rf_ok and yo_ok
        print(f"  RF∧YOLO(IoU>0.1,conf>{0.0}) {hit_rate(None,None,keep_and)}")
    (MEAS / "verify_sweep.json").write_text(json.dumps(
        [{k: v for k, v in f.items() if k != "crops"} for f in feats], indent=1))


if __name__ == "__main__":
    raise SystemExit(main())
