#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""水平翻转 TTA 特征：与 dino_feats_{model}_{size}.npy 同中心、同尺度，仅图像水平镜像。
输出 dino_feats_{model}_{size}_flip.npy，供 ball_cls_analysis.py --tta 做特征平均。
"""
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

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="base")
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    from transformers import AutoImageProcessor, AutoModel
    dev = a.device
    proc = AutoImageProcessor.from_pretrained(f"facebook/dinov2-{a.model}")
    model = AutoModel.from_pretrained(f"facebook/dinov2-{a.model}").to(dev).eval()
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]

    for csize in (256, 512):
        feats, t0 = [], time.time()
        for i, r in enumerate(bank):
            x1, y1, x2, y2 = r["bbox"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            img = cv2.imread(str(AW / r["window"] / r["frame"]))
            H, W = img.shape[:2]
            h = csize // 2
            X1, Y1 = int(cx - h), int(cy - h)
            c = img[max(0, Y1):min(H, Y1 + csize), max(0, X1):min(W, X1 + csize)]
            pad = np.zeros((csize, csize, 3), np.uint8)
            ch, cw = min(c.shape[0], csize), min(c.shape[1], csize)
            pad[:ch, :cw] = c[:ch, :cw]
            pad = pad[:, ::-1]                      # 水平翻转
            rgb = cv2.cvtColor(cv2.resize(pad, (224, 224)), cv2.COLOR_BGR2RGB)
            inp = proc(images=rgb, return_tensors="pt").to(dev)
            with torch.no_grad():
                o = model(**inp).last_hidden_state[:, 0]
            feats.append(o[0].cpu().float().numpy())
            if (i + 1) % 60 == 0:
                print(f"  flip {csize} {i+1}/{len(bank)}  {time.time()-t0:.0f}s", flush=True)
        np.save(MS / f"dino_feats_{a.model}_{csize}_flip.npy", np.array(feats))
        print(f"[缓存] dino_feats_{a.model}_{csize}_flip.npy")


if __name__ == "__main__":
    raise SystemExit(main())
