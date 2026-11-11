#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OWLv2 二次验证测试：在 60 个真实目视标注样本上测区分度。

对 manifest2_t1.json 每个样本：从原帧裁 256px → 放大 384 →
OWLv2("a basketball") 检测，取与标注 bbox IoU 最大的框的 score。
报 TP/FP score 分布 + 阈值扫描。若可分 ⇒ 集成进管线；不可分 ⇒ 训练路线。
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
from transformers import AutoProcessor, Owlv2ForObjectDetection

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
QUERIES = ["a basketball"]


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model",
                    default="google/owlv2-base-patch16-ensemble")
    ap.add_argument("--crop", type=int, default=256)
    ap.add_argument("--out", default=str(MS / "owlv2_rows.json"))
    a = ap.parse_args()
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    proc = AutoProcessor.from_pretrained(a.model)
    model = Owlv2ForObjectDetection.from_pretrained(a.model).to(dev).eval()

    labels = json.loads((MS / "labels3_visual.json").read_text())
    man = {(m["window"], m["frame"]): m for m in
           json.loads((MS / "manifest2_t1.json").read_text())}

    rows, t0 = [], time.time()
    for r in labels:
        w, fn = r["window"], r["frame"]
        m = man[(w, fn)]
        x1, y1, x2, y2 = m["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        img = cv2.imread(str(AW / w / fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        h = a.crop // 2
        X1, Y1 = int(cx - h), int(cy - h)
        sx1, sy1, sx2, sy2 = max(0, X1), max(0, Y1), min(W, X1 + a.crop), min(H, Y1 + a.crop)
        crop = img[sy1:sy2, sx1:sx2]
        ch, cw = crop.shape[:2]
        if ch < 30 or cw < 30:
            continue
        sc = 384.0 / cw
        mb = [(x1 - X1) * sc, (y1 - Y1) * sc, (x2 - X1) * sc, (y2 - Y1) * sc]
        rgb = cv2.cvtColor(cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC),
                           cv2.COLOR_BGR2RGB)
        inp = proc(text=[QUERIES], images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            o = model(**inp)
        res = proc.post_process_grounded_object_detection(
            o, threshold=0.05, target_sizes=torch.tensor([[384, 384]]).to(dev))[0]
        best, bestbox = 0.0, None
        for b, s, li in zip(res["boxes"].tolist(), res["scores"].tolist(),
                            res["labels"].tolist()):
            if int(li) == 0:
                if float(s) > best:
                    best, bestbox = float(s), b
        # 也记录与标注框 IoU>0.1 的匹配分（更贴近「验这个框」语义）
        match = 0.0
        for b, s, li in zip(res["boxes"].tolist(), res["scores"].tolist(),
                            res["labels"].tolist()):
            if int(li) == 0 and iou(b, mb) > 0.1:
                match = max(match, float(s))
        rows.append({**r, "owl_best": round(best, 4), "owl_match": round(match, 4),
                     "bbox": m["bbox"], "conf2": m["conf2"]})
        if len(rows) % 15 == 0:
            print(f"  {len(rows)}/60  {time.time()-t0:.0f}s")

    Path(a.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print("[out]", a.out, f"用时 {time.time()-t0:.0f}s")

    for key in ("owl_best", "owl_match"):
        for strict, unc_as in (("严格(unc=FP)", "FP"), ("宽松(unc=TP)", "TP")):
            tp = [r[key] for r in rows if r["label"] == "TP" or
                  (r["label"] == "unc" and unc_as == "TP")]
            fp = [r[key] for r in rows if r["label"] == "FP" or
                  (r["label"] == "unc" and unc_as == "FP")]
            print(f"\n=== {key} {strict}: TP={len(tp)} FP={len(fp)} ===")
            print("TP:", sorted(tp))
            print("FP:", sorted(fp))
            for th in (0.1, 0.2, 0.3, 0.4, 0.5):
                ktp = sum(1 for v in tp if v > th)
                kfp = sum(1 for v in fp if v > th)
                P = ktp / (ktp + kfp) if ktp + kfp else 0
                R = ktp / len(tp) if tp else 0
                print(f"  th={th:.2f}  P={P*100:5.1f}%  R={R*100:5.1f}%  "
                      f"杀FP={len(fp)-kfp}  损TP={len(tp)-ktp}")


if __name__ == "__main__":
    raise SystemExit(main())
