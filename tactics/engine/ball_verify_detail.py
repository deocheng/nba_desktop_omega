#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CROP=256 验证器逐样本明细：每样本的最佳匹配 conf，列出幸存 FP 与阵亡 TP，
并输出它们在帧内的位置（用于判断球场掩膜能否杀掉幸存 FP）。
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

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MEAS = Path(str(tactics_data_file("reports/milestone_05/measure")))
RF = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
      + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
      + "46c33088c790670a7e81e21e753fa368b2d77a70")
CROP = 256


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def main():
    man = json.loads((MEAS / "manifest.json").read_text())
    lab = json.loads((MEAS / "labels.json").read_text())
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    rf = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()

    rows = []
    for i, (m, l) in enumerate(zip(man, lab)):
        img = cv2.imread(str(AW / m["window"] / m["frame"]))
        if img is None:
            continue
        x1, y1, x2, y2 = m["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        h = CROP // 2
        X1, Y1 = int(cx - h), int(cy - h)
        sx1, sy1 = max(0, X1), max(0, Y1)
        sx2, sy2 = min(img.shape[1], X1 + CROP), min(img.shape[0], Y1 + CROP)
        crop = img[sy1:sy2, sx1:sx2].copy()
        ch, cw = crop.shape[:2]
        sc = 384.0 / cw
        mb = [(x1 - X1) * sc, (y1 - Y1) * sc, (x2 - X1) * sc, (y2 - Y1) * sc]
        rgb = cv2.cvtColor(cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC),
                           cv2.COLOR_BGR2RGB)
        inp = proc(images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            out = rf(**inp)
        res = proc.post_process_object_detection(
            out, threshold=0.05, target_sizes=torch.tensor([[384, 384]]).to(dev))[0]
        best = 0.0
        for b, s, li in zip(res["boxes"].tolist(), res["scores"].tolist(), res["labels"].tolist()):
            if int(li) == 0 and iou(b, mb) > 0.3:
                best = max(best, float(s))
        rows.append({"w": m["window"], "f": m["frame"], "label": l["label"],
                     "verify_conf": round(best, 3), "stage1_conf": m["conf"],
                     "cx": round(cx), "cy": round(cy)})
    rows.sort(key=lambda r: (not r["label"], -r["verify_conf"]))
    print(f"{'样本':<12}{'lab':<5}{'verify':>7}{'stage1':>7}{'cx':>6}{'cy':>6}")
    for r in rows:
        print(f"{r['w']}/{r['f'][1:6]:<9}{'TP' if r['label'] else 'FP':<5}"
              f"{r['verify_conf']:>7}{r['stage1_conf']:>7}{r['cx']:>6}{r['cy']:>6}")
    # 工作点
    for th in (0.1, 0.2, 0.3, 0.4, 0.5):
        tp = sum(1 for r in rows if r["label"] and r["verify_conf"] > th)
        fp = sum(1 for r in rows if not r["label"] and r["verify_conf"] > th)
        print(f"conf>{th}: TP {tp}/33 FP {fp}/27 精度 {tp/(tp+fp)*100 if tp+fp else 0:.1f}%")
    (MEAS / "verify_c256_detail.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
