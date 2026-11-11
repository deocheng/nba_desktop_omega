#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重定位 + 居中裁切特征（针对"框偏移"诊断，2026-09-24）。

动机：审计发现 RF-DETR 的框常偏离真球 40-80px，导致以框中心裁切时真球偏在角落，
DINOv2 嵌入不"球心化"，TP/FP 特征重叠（AUC 0.89，w1/w3 无 P>=90% 工作点）。

做法：以检测框中心取 320x320 裁切 -> 放大到 384（球 ~32px，处于模型舒适区）
      -> RF-DETR 重定位 -> 用新中心裁 256(本体)/512(上下文) 提 DINOv2 CLS 特征。
输出：reloc_rows.json + dino_feats_{model}_{size}_reloc.npy
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

MODEL = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
         + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
         + "46c33088c790670a7e81e21e753fa368b2d77a70")
AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
BALL = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="base", choices=["small", "base"])
    ap.add_argument("--win", type=int, default=320, help="重定位搜索窗边长")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--conf", type=float, default=0.15, help="重定位接受的 conf 下限")
    a = ap.parse_args()

    from transformers import AutoImageProcessor, AutoModel, AutoModelForObjectDetection
    dev = a.device
    proc = AutoImageProcessor.from_pretrained(MODEL)
    det = AutoModelForObjectDetection.from_pretrained(MODEL).to(dev).eval()

    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]

    rows, t0 = [], time.time()
    for i, r in enumerate(bank):
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        H, W = img.shape[:2]
        x1, y1, x2, y2 = r["bbox"]
        ocx, ocy = (x1 + x2) / 2, (y1 + y2) / 2
        hw = a.win // 2
        sx1, sy1 = int(max(0, ocx - hw)), int(max(0, ocy - hw))
        sx2, sy2 = int(min(W, ocx + hw)), int(min(H, ocy + hw))
        crop = img[sy1:sy2, sx1:sx2]
        up = cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC)
        rgb = cv2.cvtColor(up, cv2.COLOR_BGR2RGB)
        inp = proc(images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            out = det(**inp)
        res = proc.post_process_object_detection(
            out, threshold=a.conf, target_sizes=torch.tensor([[384, 384]]).to(dev))[0]
        cand = [(float(s), b) for b, s, l in zip(res["boxes"].tolist(),
                                                 res["scores"].tolist(),
                                                 res["labels"].tolist()) if int(l) == BALL]
        cand.sort(key=lambda t: -t[0])
        kx, ky = 384.0 / max(1, crop.shape[1]), 384.0 / max(1, crop.shape[0])
        if cand and cand[0][0] >= a.conf:
            s, b = cand[0]
            ncx = sx1 + (b[0] + b[2]) / 2 / kx
            ncy = sy1 + (b[1] + b[3]) / 2 / ky
            rows.append({"window": r["window"], "frame": r["frame"], "label": r["label"],
                         "obox": r["bbox"], "conf1": r["conf1"], "conf2": r["conf2"],
                         "nbox": [float(v) for v in b], "reloc_conf": float(s),
                         "ocx": ocx, "ocy": ocy, "ncx": float(ncx), "ncy": float(ncy),
                         "moved": float(np.hypot(ncx - ocx, ncy - ocy))})
        else:
            rows.append({"window": r["window"], "frame": r["frame"], "label": r["label"],
                         "obox": r["bbox"], "conf1": r["conf1"], "conf2": r["conf2"],
                         "nbox": None, "reloc_conf": 0.0,
                         "ocx": ocx, "ocy": ocy, "ncx": ocx, "ncy": ocy, "moved": 0.0})
        if (i + 1) % 40 == 0:
            print(f"  重定位 {i+1}/{len(bank)}  {time.time()-t0:.0f}s", flush=True)
    (MS / "reloc_rows.json").write_text(json.dumps(rows, indent=1))

    # ---- 用新中心提 DINOv2 特征 ----
    dproc = AutoImageProcessor.from_pretrained(f"facebook/dinov2-{a.model}")
    dmod = AutoModel.from_pretrained(f"facebook/dinov2-{a.model}").to(dev).eval()

    def extract(csize):
        cache = MS / f"dino_feats_{a.model}_{csize}_reloc.npy"
        feats, tt = [], time.time()
        for i, row in enumerate(rows):
            img = cv2.imread(str(AW / row["window"] / row["frame"]))
            H, W = img.shape[:2]
            cx, cy = row["ncx"], row["ncy"]
            h = csize // 2
            X1, Y1 = int(cx - h), int(cy - h)
            c = img[max(0, Y1):min(H, Y1 + csize), max(0, X1):min(W, X1 + csize)]
            pad = np.zeros((csize, csize, 3), np.uint8)
            ch, cw = min(c.shape[0], csize), min(c.shape[1], csize)
            pad[:ch, :cw] = c[:ch, :cw]
            r224 = cv2.cvtColor(cv2.resize(pad, (224, 224)), cv2.COLOR_BGR2RGB)
            ii = dproc(images=r224, return_tensors="pt").to(dev)
            with torch.no_grad():
                o = dmod(**ii).last_hidden_state[:, 0]
            feats.append(o[0].cpu().float().numpy())
            if (i + 1) % 60 == 0:
                print(f"  特征{csize} {i+1}/{len(rows)}  {time.time()-tt:.0f}s", flush=True)
        f = np.array(feats)
        np.save(cache, f)
        print(f"[缓存] {cache}")
        return f

    extract(256)
    extract(512)

    mv = np.array([r["moved"] for r in rows])
    print(f"\n重定位：命中 {sum(1 for r in rows if r['nbox'])}/{len(rows)}  "
          f"位移中位={np.median(mv):.1f}px  p90={np.percentile(mv,90):.1f}px")
    for lab in ("TP", "FP"):
        m = np.array([r["label"] == lab for r in rows])
        print(f"  {lab}: n={m.sum()} 命中={sum(1 for r in rows if m[rows.index(r)] and r['nbox'])} "
              f"位移中位={np.median(mv[m]):.1f}px")


if __name__ == "__main__":
    raise SystemExit(main())
