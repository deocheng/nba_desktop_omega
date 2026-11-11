#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""掩膜几何特征（把"球场掩膜"从硬门禁降级为连续特征，解决空中球被误杀）。

上一轮硬门禁（脚点在掩膜内）得 P80%/R31% —— 方向性错误：球多在空中/掩膜外。
本轮改为对每个候选算连续量：
  in_floor       : 框心是否在木地板掩膜内
  foot_in_floor  : 框底中点是否在内
  center_dist    : 框心到掩膜最近像素距离（在内=0）
  gap_below      : 框底中点**正下方**到掩膜上边界的垂直距离（= 该物体在图像中"高出地板"的量）
  col_floor_frac : 该列中地板像素占比
  frame_cover    : 全帧掩膜占比（镜头/场次上下文）
输出 mask_rows.json + 逐特征 AUC。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from court_mask import court_mask  # noqa: E402

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def feats_for(img, cm, box):
    x1, y1, x2, y2 = box
    cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
    fx, fy = int((x1 + x2) / 2), int(y2)
    H, W = cm.shape
    cx = min(max(cx, 0), W - 1); cy = min(max(cy, 0), H - 1)
    fx = min(max(fx, 0), W - 1); fy = min(max(fy, 0), H - 1)
    inside = cm > 0
    in_floor = float(inside[cy, cx])
    foot_in = float(inside[fy, fx])
    # 框心到掩膜最近像素（用带距离变换的高效写法）
    if inside.any():
        dist = cv2.distanceTransform((~inside).astype(np.uint8), cv2.DIST_L2, 3)
        center_dist = float(dist[cy, cx])
    else:
        center_dist = 600.0
    # 正下方垂直间隙
    col = inside[:, fx]
    below = np.where(col[fy:])[0]
    gap = float(below[0]) if below.size else 600.0
    col_floor_frac = float(col.mean())
    return {"in_floor": in_floor, "foot_in_floor": foot_in,
            "center_dist": min(center_dist, 600.0), "gap_below": gap,
            "col_floor_frac": col_floor_frac, "frame_cover": float(inside.mean())}


def main():
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    rows, cache = [], {}
    for i, r in enumerate(bank):
        key = (r["window"], r["frame"])
        if key not in cache:
            img = cv2.imread(str(AW / r["window"] / r["frame"]))
            cache[key] = court_mask(img)
        f = feats_for(None, cache[key], r["bbox"])
        rows.append({"window": r["window"], "frame": r["frame"], "label": r["label"], **f})
        if (i + 1) % 80 == 0:
            print(f"  {i+1}/{len(bank)}", flush=True)
    (MS / "mask_rows.json").write_text(json.dumps(rows, indent=1))

    from sklearn.metrics import roc_auc_score
    y = np.array([r["label"] == "TP" for r in rows]).astype(int)
    print(f"\n样本 {len(rows)} TP={y.sum()} FP={(1-y).sum()}")
    print(f"{'特征':<16}{'AUC':>8}{'TP中位':>10}{'FP中位':>10}")
    for k in ("in_floor", "foot_in_floor", "center_dist", "gap_below",
              "col_floor_frac", "frame_cover"):
        v = np.array([r[k] for r in rows], float)
        auc = roc_auc_score(y, v)
        flag = " ←" if abs(auc - 0.5) > 0.08 else ""
        print(f"{k:<16}{auc:>8.4f}{np.median(v[y==1]):>10.2f}{np.median(v[y==0]):>10.2f}{flag}")
    print("\n分窗 AUC:")
    for w in ("w1", "w2", "w3", "w4"):
        m = np.array([r["window"] == w for r in rows])
        print(f"  {w}: " + "  ".join(
            f"{k}={roc_auc_score(y[m], np.array([r[k] for r in rows], float)[m]):.3f}"
            for k in ("in_floor", "gap_below", "center_dist", "col_floor_frac")))


if __name__ == "__main__":
    raise SystemExit(main())
