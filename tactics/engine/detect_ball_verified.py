#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球检测级联验证（集成进管线）：
  tile 检出(w*_rfdetr_tile.json) → 逐候选框 256px 裁切放大 384 → RF-DETR 二次验证
  → 只保留 verify_conf > --vconf 且与原框 IoU>0.3 的球。
输出 w*_ball_verified.json: {frame:[{bbox,conf1,conf2}]} + 覆盖率统计（支撑率）。
用法: detect_ball_verified.py <window> <out.json> [--vconf 0.4] [--crop 256] [--iouth 0.3]
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
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from common.nba_paths import tactics_data_file

RF = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
      + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
      + "46c33088c790670a7e81e21e753fa368b2d77a70")
AW = Path(str(tactics_data_file("action_work")))


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("window"); ap.add_argument("out")
    ap.add_argument("--vconf", type=float, default=0.4)
    ap.add_argument("--crop", type=int, default=256)
    ap.add_argument("--iouth", type=float, default=0.3)
    ap.add_argument("--top1", action="store_true",
                    help="只验证每帧 top-conf 框（与调参评估口径一致），其余框直接丢弃")
    a = ap.parse_args()
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    model = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()

    det = json.loads((AW / f"{a.window}_rfdetr_tile.json").read_text())
    keys = sorted(det.keys())
    out, t0 = {}, time.time()
    n_verify = 0
    for fn in keys:
        cands = det[fn]
        if a.top1 and cands:
            cands = [max(cands, key=lambda c: c["conf"])]  # 口径对齐：仅 top-1
        if not cands:
            out[fn] = []
            continue
        img = cv2.imread(str(AW / a.window / fn))
        if img is None:
            out[fn] = []
            continue
        H, W = img.shape[:2]
        keep = []
        for c in cands:
            x1, y1, x2, y2 = c["bbox"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            h = a.crop // 2
            X1, Y1 = int(cx - h), int(cy - h)
            sx1, sy1 = max(0, X1), max(0, Y1)
            sx2, sy2 = min(W, X1 + a.crop), min(H, Y1 + a.crop)
            crop = img[sy1:sy2, sx1:sx2]
            ch, cw = crop.shape[:2]
            if ch < 30 or cw < 30:
                continue
            sc = 384.0 / cw
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
                if int(li) == 0 and iou(b, mb) > a.iouth:
                    best = max(best, float(s))
            n_verify += 1
            if best > a.vconf:
                keep.append({"bbox": c["bbox"], "conf1": c["conf"], "conf2": round(best, 3)})
        out[fn] = keep
    cov = sum(1 for v in out.values() if v)
    print(f"[{a.window}] 帧={len(out)} 有验证球={cov} ({100*cov/len(out):.1f}%)  "
          f"验证调用={n_verify}  用时 {time.time()-t0:.0f}s")
    Path(a.out).write_text(json.dumps(out))
    print("[out]", a.out)


if __name__ == "__main__":
    raise SystemExit(main())
