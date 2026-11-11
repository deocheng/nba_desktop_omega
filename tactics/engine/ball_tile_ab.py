#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tile 几何 A/B —— 检验「非等比拉伸毁球」假设（本脚本只做测量，不改管线）。

背景（已实测，非推断）
--------------------
`preprocessor_config.json` -> `"size": {"height":384,"width":384}`，而
`RfDetrImageProcessor.resize()` 的源码明写：给了 height+width 就 **resize 到精确尺寸，
不保持长宽比**（"Do NOT keep the aspect ratio"）。
⇒ 现行管线 `--tile-w 640 --tile-h 384` 把每块**拉伸**到 384x384：
   横轴 x0.600、纵轴 x1.000 ⇒ 真值库里 25x29 px 的球被压成 **15x29 px**（宽高比 1.93:1）。
⇒ 球变椭圆、横向像素丢 40%。**方形 tile 是恒等缩放，球保持 25x29。**

本脚本对同一批**已人工标注**的帧跑多种 tile 几何，比较：
  · 真球（人工 TP 框）上的最高置信度  —— 假设成立 ⇒ 方形/更小 tile 应显著更高
  · top-1 框与人工框是否一致（IoU>=0.3）—— 衡量 top-1 是否"还落在原来那个东西上"
  · 每帧 tile 数 / 推理次数（成本）

用法:
  python engine/ball_tile_ab.py --n 40 --out reports/milestone_05/measure/tileab.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import time
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
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
BALL = 0

CONFIGS = [
    ("640x384 (现行)", 640, 384, 96),
    ("384x384 (方形恒等)", 384, 384, 96),
    ("288x288 (方形上采样1.33x)", 288, 288, 72),
    ("256x256 (方形上采样1.5x)", 256, 256, 64),
]


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / ua if ua > 0 else 0.0


def infer(proc, model, dev, bgr, thresh):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    inp = proc(images=rgb, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model(**inp)
    res = proc.post_process_object_detection(
        out, threshold=thresh, target_sizes=torch.tensor([[h, w]]).to(dev))[0]
    return [{"bbox": [float(v) for v in b], "conf": float(s)}
            for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(),
                               res["labels"].tolist()) if int(l) == BALL]


def tiled(proc, model, dev, img, tw, th, ov, thresh):
    H, W = img.shape[:2]
    rec, ntile = [], 0
    for y in range(0, H, th - ov):
        for x in range(0, W, tw - ov):
            x2, y2 = min(W, x + tw), min(H, y + th)
            if x2 - x <= ov or y2 - y <= ov:
                continue
            ntile += 1
            for r in infer(proc, model, dev, img[y:y2, x:x2], thresh):
                b = r["bbox"]
                rec.append({"bbox": [b[0] + x, b[1] + y, b[2] + x, b[3] + y],
                            "conf": r["conf"]})
    rec.sort(key=lambda r: -r["conf"])
    keep = []
    for r in rec:
        if all(iou(r["bbox"], k["bbox"]) < 0.4 for k in keep):
            keep.append(r)
    return keep[:4], ntile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="每类取多少个（TP/FP 各 n）")
    ap.add_argument("--conf", type=float, default=0.05, help="很低，用于观察完整分布")
    ap.add_argument("--out", default=str(MS / "tileab.json"))
    a = ap.parse_args()

    bank = json.loads((MS / "labels_bank.json").read_text())
    byfr = {}
    for r in bank:
        byfr.setdefault((r["window"], r["frame"]), r)
    rows = list(byfr.values())
    tp = [r for r in rows if r["label"] == "TP"]
    fp = [r for r in rows if r["label"] == "FP"]
    rng = np.random.default_rng(0)
    sel = (list(rng.choice(tp, min(a.n, len(tp)), replace=False)) +
           list(rng.choice(fp, min(a.n, len(fp)), replace=False)))
    print(f"真值库 {len(rows)} 帧（TP {len(tp)} / FP {len(fp)}）；本次抽 {len(sel)} 帧")

    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    proc = AutoImageProcessor.from_pretrained(MODEL)
    model = AutoModelForObjectDetection.from_pretrained(MODEL).to(dev).eval()

    res = {name: {"tp_best": [], "tp_hit": 0, "top1": [], "ntile": 0, "ncall": 0}
           for name, *_ in CONFIGS}
    t0 = time.time()
    for k, r in enumerate(sel):
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        if img is None:
            continue
        gt = r["bbox"]
        for name, tw, th, ov in CONFIGS:
            rec, nt = tiled(proc, model, dev, img, tw, th, ov, a.conf)
            res[name]["ntile"] += nt
            res[name]["ncall"] += nt
            top1 = rec[0] if rec else None
            if r["label"] == "TP":
                best = max([c["conf"] for c in rec if iou(c["bbox"], gt) >= 0.3], default=0.0)
                res[name]["tp_best"].append(best)
                res[name]["tp_hit"] += int(best > 0)
            res[name]["top1"].append({
                "label": r["label"],
                "conf": (top1["conf"] if top1 else None),
                "iou_gt": (iou(top1["bbox"], gt) if top1 else None),
            })
        if (k + 1) % 10 == 0:
            print(f"  {k+1}/{len(sel)}  {time.time()-t0:.0f}s", flush=True)

    print(f"\n{'配置':<26}{'真球命中率':>10}{'真球中位置信中位':>17}{'真球置信均值':>13}"
          f"{'FP帧top1≠原FP':>14}{'tile/帧':>9}")
    out = {}
    for name, *_ in CONFIGS:
        d = res[name]
        tpb = np.array(d["tp_best"])
        hit = float((tpb > 0).mean()) if len(tpb) else 0.0
        fp_top1 = [t for t in d["top1"] if t["label"] == "FP"]
        changed = float(np.mean([1 if (t["iou_gt"] is not None and t["iou_gt"] < 0.3)
                                 else 0 for t in fp_top1])) if fp_top1 else 0.0
        nf = len(sel)
        print(f"{name:<26}{hit*100:>9.1f}%{np.median(tpb):>17.3f}{tpb.mean():>13.3f}"
              f"{changed*100:>13.1f}%{d['ntile']/max(1,nf):>9.1f}")
        out[name] = {"tp_hit_rate": hit, "tp_best_median": float(np.median(tpb)),
                     "tp_best_mean": float(tpb.mean()),
                     "fp_top1_changed": changed, "tiles_per_frame": d["ntile"] / max(1, nf),
                     "tp_best": d["tp_best"], "top1": d["top1"]}
    json.dump({"n_per_class": a.n, "results": out}, open(a.out, "w"),
              ensure_ascii=False, indent=1)
    print(f"[out] {a.out}")


if __name__ == "__main__":
    main()
