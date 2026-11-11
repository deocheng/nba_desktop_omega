#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_gt_detector.py — 在「人工真值球位」上实测检测器真实响应（现役口径）。

动机：补标注入的候选 conf1/conf2 是 TP 中位数**填充值**，不是实测值。
若真值球位上检测器本身能给高分，则注入特征的 conf2 被低估 ⇒ 头打分偏低是特征失真；
若检测器在真值球位上就是 0，则天花板在检测器，注入样本只能教「头」，救不了候选池。

口径（与 engine/validate_clips.py 逐位一致）：
  conf1 = tile 检测 640x384 / overlap96 / NMS IoU<0.4 / thresh=0.05（本脚本不截断 top-k）
  conf2 = 以框中心取 256px 裁切 → resize 384x384 → RF-DETR thresh=0.05 → 取与框 IoU>0.3 的最高分

用法:
  python engine/probe_gt_detector.py \
      --probe sas_lal:action_work/sas_lal:f00205.jpg:719,339,26 \
      --probe sas_det:action_work/sas_det:f00031.jpg:1130,441,29
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

ROOT = Path(str(tactics_data_file("")))
RF = (Path.home() / ".cache/huggingface/hub/models--koppolusameer--rfdetr-basketball-player-"
      "ball-referee-detection/snapshots/46c33088c790670a7e81e21e753fa368b2d77a70")
BALL = 0  # 与 validate_clips.py:31 一致（该模型卡 ball 类 id=0）


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def infer(proc, model, dev, bgr, thresh=0.05):
    """返回 [(bbox_xyxy_in_input_coords, score)]，只留 ball 类。"""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    inp = proc(images=rgb, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model(**inp)
    res = proc.post_process_object_detection(
        out, threshold=thresh, target_sizes=torch.tensor([[h, w]]).to(dev))[0]
    return [([float(v) for v in b], float(s))
            for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(),
                               res["labels"].tolist()) if int(l) == BALL]


def tiled_raw(proc, model, dev, img, tw=640, th=384, ov=96, thresh=0.05):
    """现役 tile 口径，但**不截断 top-k**，返回全部原始检测（含被 NMS 前的）。"""
    H, W = img.shape[:2]
    rec, ntile = [], 0
    for y in range(0, H, th - ov):
        for x in range(0, W, tw - ov):
            x2, y2 = min(W, x + tw), min(H, y + th)
            if x2 - x <= ov or y2 - y <= ov:
                continue
            ntile += 1
            for b, s in infer(proc, model, dev, img[y:y2, x:x2], thresh):
                rec.append({"bbox": [b[0]+x, b[1]+y, b[2]+x, b[3]+y], "conf": s})
    return rec, ntile


def conf2_of(proc, model, dev, img, box, crop_half=128):
    """现役 conf2 口径：256px 裁切 → 384^2 → IoU>0.3 取最高分。"""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    X1, Y1 = int(cx - crop_half), int(cy - crop_half)
    X2, Y2 = min(img.shape[1], X1 + 2*crop_half), min(img.shape[0], Y1 + 2*crop_half)
    X1, Y1 = max(0, X1), max(0, Y1)
    crop = img[Y1:Y2, X1:X2]
    if crop.shape[0] < 30 or crop.shape[1] < 30:
        return 0.0, [], (X1, Y1, X2, Y2)
    dets = infer(proc, model, dev, crop, 0.05)   # 输入会被 proc resize 到模型尺寸，坐标按 crop 尺寸还原
    mapped = []
    for b, s in dets:
        fb = [b[0]+X1, b[1]+Y1, b[2]+X1, b[3]+Y1]
        mapped.append({"bbox": fb, "conf": s, "iou_gt": iou(fb, box)})
    best = max([m["conf"] for m in mapped if m["iou_gt"] > 0.3], default=0.0)
    return round(best, 3), mapped, (X1, Y1, X2, Y2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="append", required=True,
                    help="clip:frames_dir:frame.jpg:cx,cy,size")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--out", default="action_work/validate/gt_detector_probe.json")
    ap.add_argument("--dump-raw", default=None,
                    help="把每帧全部原始 tile 检测按 cand_probe 格式落盘（供 expand_cand_pool 消费）")
    a = ap.parse_args()

    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(str(RF))
    model = AutoModelForObjectDetection.from_pretrained(str(RF)).to(dev).eval()
    print(f"[probe] dev={dev}", flush=True)

    out = {"meta": {"rf": str(RF), "ball_label": BALL,
                    "conf2_rule": "256px crop -> 384^2 -> IoU>0.3 max score",
                    "tile_rule": "640x384/ov96/thresh0.05, NO top-k truncation"},
           "frames": {}}
    rawdump = {"meta": {"clip": "per-probe", "thresh": 0.05,
                        "note": "全量原始 tile 检测，未做 NMS/top-k 截断"},
               "frames": {}}
    for spec in a.probe:
        clip, fdir, fname, geo = spec.split(":")
        cx, cy, sz = [float(v) for v in geo.split(",")]
        box = [cx - sz/2, cy - sz/2, cx + sz/2, cy + sz/2]
        img = cv2.imread(str(ROOT / fdir / fname))
        assert img is not None, f"读不到 {ROOT/fdir/fname}"
        print(f"\n=== {clip} {fname}  GT box={[round(v,1) for v in box]}  (img {img.shape[1]}x{img.shape[0]})")

        t0 = time.time()
        rec, ntile = tiled_raw(proc, model, dev, img)
        rec.sort(key=lambda r: -r["conf"])
        def ctr(b):
            return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2

        near = []
        for r in rec:
            rx, ry = ctr(r["bbox"])
            dist = ((rx - cx) ** 2 + (ry - cy) ** 2) ** 0.5
            if dist <= 80:
                near.append({"bbox": [round(v, 1) for v in r["bbox"]],
                             "conf": round(r["conf"], 3),
                             "ctr_dist": round(dist, 1),
                             "iou_gt": round(iou(r["bbox"], box), 3)})
        near.sort(key=lambda z: z["ctr_dist"])
        print(f"  tile 原始检测 {len(rec)} 个 / {ntile} tiles  ({time.time()-t0:.1f}s)")
        print(f"  GT 中心 80px 内命中 {len(near)} 个: {near}")

        c2, mapped, win = conf2_of(proc, model, dev, img, box)
        print(f"  conf2 裁切窗口 {win}")
        print(f"  【实测 conf2】= {c2}")
        for m in sorted(mapped, key=lambda m: -m["conf"])[:6]:
            print(f"      det bbox={[round(v,1) for v in m['bbox']]} conf={m['conf']:.3f} IoU_GT={m['iou_gt']:.3f}")
        if not mapped:
            print("      （裁切内 0 个 ball 检测）")

        rawdump["frames"][fname] = [{"bbox": [round(v, 2) for v in r["bbox"]],
                                    "conf": round(r["conf"], 4)} for r in rec]

        out["frames"][f"{clip}/{fname}"] = {
            "clip": clip, "frame": fname, "gt_box": [round(v, 1) for v in box],
            "tile_raw_n": len(rec), "tile_near_80px": near,
            "conf2_measured": c2, "crop_window": win,
            "crop_dets": [{"bbox": [round(v, 1) for v in m["bbox"]],
                           "conf": round(m["conf"], 3), "iou_gt": round(m["iou_gt"], 3)}
                          for m in sorted(mapped, key=lambda m: -m["conf"])[:10]],
        }

    Path(ROOT / a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n[out] {a.out}")
    if a.dump_raw:
        Path(ROOT / a.dump_raw).write_text(json.dumps(rawdump, ensure_ascii=False, indent=1))
        n = {k: len(v) for k, v in rawdump["frames"].items()}
        print(f"[out] {a.dump_raw}  每帧原始检测数 {n}")


if __name__ == "__main__":
    main()
