#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_pose_on_boxes.py — 对球员框裁剪后跑 pose（全帧 pose 在宽景下覆盖仅 33%，不够用）。

为什么：yolo11n-pose 全帧推理在 1080p 转播帧上抓不到小球员（实测 133/400 帧有关键点，
真值含球帧只覆盖 10.5% → 支撑率不达标，线索不可入特征）。裁剪放大后重测，才是对照实验。

产出: <out>.json = { "<fn>.jpg": [ {pbox, kps:[[x,y,c]x17], conf}, ... ] }  （kps 已映射回帧坐标）
用法:
  python engine/extract_pose_on_boxes.py <frames_dir> <players.json> <out.json> [--min-h 40]
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

from common.nba_paths import tactics_data_file

W = str(tactics_data_file("action_work/weights/yolo11n-pose.pt"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("players")
    ap.add_argument("out")
    ap.add_argument("--model", default=W)
    ap.add_argument("--conf", type=float, default=0.30)
    ap.add_argument("--min-h", type=int, default=40, help="框高小于此值的球员跳过(太糊)")
    ap.add_argument("--device", default="mps")
    a = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(a.model)
    boxes = json.loads(Path(a.players).read_text())
    fdir = Path(a.frames_dir)
    out = {}
    t0 = time.time()
    for n, (fn, recs) in enumerate(sorted(boxes.items())):
        img = cv2.imread(str(fdir / fn))
        if img is None:
            out[fn] = []
            continue
        H, W_ = img.shape[:2]
        pl = [r for r in recs if r.get("cls", "player") == "player"]
        pl = [r for r in pl if (r["bbox"][3] - r["bbox"][1]) >= a.min_h]
        crops, metas = [], []
        for r in pl:
            x1, y1, x2, y2 = [int(v) for v in r["bbox"]]
            pad = int(0.15 * max(x2 - x1, y2 - y1))
            sx1, sy1 = max(0, x1 - pad), max(0, y1 - pad)
            sx2, sy2 = min(W_, x2 + pad), min(H, y2 + pad)
            if sx2 - sx1 < 16 or sy2 - sy1 < 16:
                continue
            crops.append(img[sy1:sy2, sx1:sx2])
            metas.append((sx1, sy1))
        res = []
        if crops:
            preds = model.predict(crops, conf=a.conf, device=a.device, verbose=False)
            for (ox, oy), p in zip(metas, preds):
                if p.keypoints is None or len(p.keypoints.data) == 0:
                    continue
                k = p.keypoints.data[0].tolist()
                res.append({"pbox": [round(float(v), 1) for v in pl[len(res)]["bbox"]],
                            "kps": [[round(float(q[0]) + ox, 1), round(float(q[1]) + oy, 1),
                                     round(float(q[2]), 3)] for q in k],
                            "conf": round(float(p.boxes.conf[0]), 3)})
        out[fn] = res
        if (n + 1) % 100 == 0:
            print(f"  {n+1}/{len(boxes)}  {time.time()-t0:.0f}s", flush=True)
    Path(a.out).write_text(json.dumps(out))
    cov = sum(1 for v in out.values() if v)
    print(f"[out] {a.out}  帧 {len(out)}  有关键点帧 {cov}  用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
