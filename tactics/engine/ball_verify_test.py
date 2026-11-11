#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""级联验证测试：裁切放大二次检测能否把球精度从 55% 推向 90%。

对 60 个目视标注样本，把候选框中心裁 CROP×CROP（放大到 384 后 2x 变焦），
分别跑 RF-DETR（basketball 微调版）与 yolo11_basketball.pt：
  · 命中 = 裁切内检出 ball 且与原框映射 IoU > 0.3
输出各验证器 / 双模型交集(AND)、并集(OR) 的 TP 保留率 / FP 杀伤率 / 投影精度。
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
CROP = 192          # 裁切边长（px）
CONF_RF = 0.2       # 验证阶段用低阈值，靠 IoU 匹配而非阈值
CONF_YO = 0.2
IOU_MATCH = 0.3


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def rf_infer(proc, model, dev, bgr, thresh):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    inp = proc(images=rgb, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model(**inp)
    h, w = rgb.shape[:2]
    res = proc.post_process_object_detection(
        out, threshold=thresh, target_sizes=torch.tensor([[h, w]]).to(dev))[0]
    return [(b, s) for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(),
                                      res["labels"].tolist()) if int(l) == 0]


def main():
    man = json.loads((MEAS / "manifest.json").read_text())
    lab = json.loads((MEAS / "labels.json").read_text())
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    rf = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()
    ym = YOLO(str(YOLO_BB))
    print("yolo11_basketball 类别:", ym.names)
    ball_cls = [i for i, n in ym.names.items() if "ball" in n.lower() and "hoop" not in n.lower()]
    print("ball 类 id:", ball_cls)

    rows = []
    for i, (m, l) in enumerate(zip(man, lab)):
        w, f = m["window"], m["frame"]
        img = cv2.imread(str(AW / w / f))
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
        crop = cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC)
        sc = 384.0 / cw
        # 原框映射到裁切坐标
        mb = [(x1 - X1) * sc, (y1 - Y1) * sc, (x2 - X1) * sc, (y2 - Y1) * sc]
        # RF-DETR 验证
        rfb = rf_infer(proc, rf, dev, crop, CONF_RF)
        rf_hit = max((s for b, s in rfb if iou(b, mb) > IOU_MATCH), default=0.0)
        # YOLO basketball 验证
        yres = ym.predict(crop, conf=CONF_YO, device=dev, verbose=False)[0]
        yo_hit = 0.0
        if yres.boxes is not None and len(yres.boxes):
            for b, s, c in zip(yres.boxes.xyxy.tolist(), yres.boxes.conf.tolist(),
                               yres.boxes.cls.tolist()):
                if int(c) in ball_cls and iou(b, mb) > IOU_MATCH:
                    yo_hit = max(yo_hit, s)
        rows.append({"w": w, "f": f, "label": l["label"], "rf": round(rf_hit, 3),
                     "yo": round(yo_hit, 3), "conf": m["conf"]})

    def ev(name, keep):
        tp = [r for r in rows if r["label"] and keep(r)]
        fp = [r for r in rows if not r["label"] and keep(r)]
        prec = len(tp) / (len(tp) + len(fp)) * 100 if tp or fp else 0
        print(f"  {name:<22} TP保留 {len(tp)}/33  FP存活 {len(fp)}/27  投影精度 {prec:.1f}%")

    print("\n=== 验证器评测（keep=保留该样本） ===")
    ev("基线(全保留)", lambda r: True)
    ev("RF-DETR 命中", lambda r: r["rf"] > 0)
    ev(f"RF conf>{0.3:.1f}", lambda r: r["rf"] > 0.3)
    ev("YOLO 命中", lambda r: r["yo"] > 0)
    ev("AND(双模型都中)", lambda r: r["rf"] > 0 and r["yo"] > 0)
    ev("OR(任一命中)", lambda r: r["rf"] > 0 or r["yo"] > 0)
    ev("RF>0.3 且 YOLO>0", lambda r: r["rf"] > 0.3 and r["yo"] > 0)
    print("\n逐样本:")
    print(f"{'样本':<12}{'lab':<5}{'rf':>6}{'yo':>6}{'conf':>6}")
    for r in rows:
        print(f"{r['w']}/{r['f'][1:6]:<9}{'TP' if r['label'] else 'FP':<5}{r['rf']:>6}{r['yo']:>6}{r['conf']:>6}")
    (MEAS / "verify_features.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
