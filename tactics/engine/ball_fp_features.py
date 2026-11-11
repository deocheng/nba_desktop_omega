#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球检 FP 外观特征提取：在我目视标注的 60 样本上量化 TP/FP 可分性。

特征（每样本框中心裁切）:
  hue/sat/val  = HSV 均值（中心 60% 区域，避框边缘）
  sat_p90      = 饱和度 90 分位（球皮饱和度高）
  ar           = 框长宽比
  dia          = 框短边 px
  edge         = Laplacian 方差（球有筋沟纹理；球衣/地板较平）
输出逐样本表 + TP/FP 均值对比，供定阈值。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MEAS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def main():
    man = json.loads((MEAS / "manifest.json").read_text())
    lab = json.loads((MEAS / "labels.json").read_text())
    assert len(man) == len(lab), f"{len(man)} vs {len(lab)}"
    rows = []
    for m, l in zip(man, lab):
        w, f = m["window"], m["frame"]
        x1, y1, x2, y2 = m["bbox"]
        img = cv2.imread(str(AW / w / f))
        if img is None:
            continue
        H, W = img.shape[:2]
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(W, int(x2)), min(H, int(y2))
        bw, bh = x2 - x1, y2 - y1
        if bw < 3 or bh < 3:
            continue
        crop = img[y1:y2, x1:x2]
        # 中心 60% 区域
        ch, cw = crop.shape[:2]
        cy1, cy2 = int(ch * 0.2), int(ch * 0.8)
        cx1, cx2 = int(cw * 0.2), int(cw * 0.8)
        core = crop[cy1:cy2, cx1:cx2]
        hsv = cv2.cvtColor(core, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.mean(hsv)[:3]
        sat_p90 = float(np.percentile(hsv[:, :, 1], 90))
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        edge = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        ar = bw / bh if bh else 0
        rows.append({"w": w, "f": f, "label": l["label"], "hue": round(h, 1), "sat": round(s, 1),
                     "val": round(v, 1), "sat90": round(sat_p90, 1), "ar": round(ar, 2),
                     "dia": min(bw, bh), "edge": round(edge, 0), "conf": m["conf"]})
    # TP/FP 均值对比
    feats = ["hue", "sat", "val", "sat90", "ar", "dia", "edge", "conf"]
    print(f"{'样本':<14}{'label':<6}" + "".join(f"{k:>8}" for k in feats))
    for r in rows:
        print(f"{r['w']}/{r['f'][1:6]:<8}{'TP' if r['label'] else 'FP':<6}" +
              "".join(f"{r[k]:>8}" for k in feats))
    print("\n=== TP/FP 均值对比 ===")
    tp = [r for r in rows if r["label"]]
    fp = [r for r in rows if not r["label"]]
    for k in feats:
        mt = sum(r[k] for r in tp) / max(1, len(tp))
        mf = sum(r[k] for r in fp) / max(1, len(fp))
        print(f"  {k:>6}: TP均值={mt:8.1f}  FP均值={mf:8.1f}  差={mt-mf:+8.1f}")
    (MEAS / "features.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"\n[写] {MEAS/'features.json'}  TP={len(tp)} FP={len(fp)}")


if __name__ == "__main__":
    raise SystemExit(main())
