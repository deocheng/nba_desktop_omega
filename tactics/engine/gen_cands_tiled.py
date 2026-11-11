#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_cands_tiled.py — 生成指定分块参数的候选池（含 conf2 二次验证），namespaced 输出。

A4.41 诊断 → A4.42 转正。preset：
  - single    单网格（--tw/--th/--ov）
  - small480  480x384 ov192（诊断召回 84.3/90.9/94.2）
  - multiscale 640x384 ov96 + 480x384 ov192 双网格合并跨NMS（诊断召回 89.3/93.4/95.0，老程定为正式口径）
复用 validate_clips.tiled（topk<=0 不截断，A4.42 已修切片 bug）+ conf2 逻辑（头特征需要）。
输出 namespaced（--out），不覆盖生产 <clip>_cands.json；打分由 rescore_clip_heads.py --head 完成。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_clips import iou, tiled  # 复用 tiled + iou（已加 topk 参数）

ROOT = Path(str(tactics_data_file("")))
RF = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
      + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
      + "46c33088c790670a7e81e21e753fa368b2d77a70")
BALL = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--preset", default="multiscale",
                    choices=["single", "small480", "multiscale"],
                    help="single=用 --tw/--th/--ov 单网格；small480=480x384 ov192；"
                         "multiscale=640x384 ov96 + 480x384 ov192 双网格合并跨NMS（A4.42 转正口径，默认）")
    ap.add_argument("--tw", type=int, default=480)
    ap.add_argument("--th", type=int, default=384)
    ap.add_argument("--ov", type=int, default=192)
    ap.add_argument("--thresh", type=float, default=0.05)
    ap.add_argument("--nms", type=float, default=0.4)
    ap.add_argument("--topk", type=int, default=0,
                    help="0=不截断(返回全部 NMS 保留)；否则保留前 k")
    ap.add_argument("--vconf", type=float, default=-1.0)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--out", required=True, help="namespaced 候选池 json")
    a = ap.parse_args()

    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    model = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()

    fdir = Path(a.frames_dir)
    frames = sorted(fdir.glob("*.jpg"))

    if a.preset == "multiscale":
        grids = [(640, 384, 96), (480, 384, 192)]
    elif a.preset == "small480":
        grids = [(480, 384, 192)]
    else:
        grids = [(a.tw, a.th, a.ov)]
    print(f"[preset] {a.preset} grids={grids} topk={a.topk}", flush=True)

    def merged_tiles(img):
        """各网格 tiled()（网格内已NMS）→ 合并 → 跨网格 NMS IoU<0.4（conf 降序保序）。
        与 cand_pool_recall_multiscale.infer_config 同口径。topk 语义由 tiled() 内处理（0=不截断）。"""
        rec, nt = [], 0
        for tw, th, ov in grids:
            r, n = tiled(proc, model, dev, img, tw, th, ov, a.thresh, a.topk)
            rec.extend(r)
            nt += n
        rec.sort(key=lambda r: -r["conf"])
        keep = []
        for r in rec:
            if all(iou(r["bbox"], k["bbox"]) < a.nms for k in keep):
                keep.append(r)
        return keep, nt

    cands = {}
    t0 = time.time()
    for n, f in enumerate(frames):
        img = cv2.imread(str(f))
        if img is None:
            cands[f.name] = []
            continue
        tile_rec, _ = merged_tiles(img)
        keep = []
        for c in tile_rec:
            x1, y1, x2, y2 = c["bbox"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            h = 128
            X1, Y1 = int(cx - h), int(cy - h)
            sx1, sy1 = max(0, X1), max(0, Y1)
            sx2, sy2 = min(img.shape[1], X1 + 256), min(img.shape[0], Y1 + 256)
            crop = img[sy1:sy2, sx1:sx2]
            if crop.shape[0] < 30 or crop.shape[1] < 30:
                keep.append({"bbox": c["bbox"], "conf1": c["conf"], "conf2": 0.0})
                continue
            sc = 384.0 / crop.shape[1]
            mb = [(x1 - X1) * sc, (y1 - Y1) * sc, (x2 - X1) * sc, (y2 - Y1) * sc]
            rgb = cv2.cvtColor(cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC),
                              cv2.COLOR_BGR2RGB)
            inp = proc(images=rgb, return_tensors="pt").to(dev)
            with torch.no_grad():
                o = model(**inp)
            res = proc.post_process_object_detection(
                o, threshold=0.05, target_sizes=torch.tensor([[384, 384]]).to(dev))[0]
            best = 0.0
            for b, s, li in zip(res["boxes"].tolist(), res["scores"].tolist(),
                               res["labels"].tolist()):
                if int(li) == BALL and iou(b, mb) > 0.3:
                    best = max(best, float(s))
            if best > a.vconf:
                keep.append({"bbox": [float(v) for v in c["bbox"]],
                             "conf1": float(c["conf"]), "conf2": round(best, 3)})
        cands[f.name] = keep
        if (n + 1) % 50 == 0:
            print(f"  {n+1}/{len(frames)}  {time.time()-t0:.0f}s", flush=True)

    Path(a.out).write_text(json.dumps({a.clip: cands}))
    print(f"[cands] preset={a.preset}  {a.out}  候选帧 {sum(1 for v in cands.values() if v)}/{len(cands)}  "
          f"总候选 {sum(len(v) for v in cands.values())}", flush=True)


if __name__ == "__main__":
    main()
