#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""court_accum_mask.py — A5.14 多帧频率累积球场掩膜（镜头静止 ⇒ 可用）

动机
----
单帧 `court_filter.court_mask` 的形状是**锯齿色块**（`ep24_s1 f70` 轮廓 720 点 / 凸包 IoU 0.692），
因为它在颜色空间抠地板，被**移动前景（球员）**和**球员色球衣**啃出大量凹陷。

做法
----
A5.1 已证「镜头基本静止」（`cv2.phaseCorrelate` 每帧位移中位 0.29 px）⇒
一段之内**地板在图像里的位置固定**，而**球员在动**。
于是把一段内 N 帧的地板掩膜**按出现频率**累积：
    freq(x,y) = 该像素被判为地板的帧数 / 有效帧数
移动前景（球员）只在少数帧占据某像素 ⇒ 被压掉；地板在大多数帧都在 ⇒ 保留。

🔴 边界（诚实声明）
- 累积能修「**移动前景啃出的凹陷**」，**不能**修「**画面边缘裁切**」和「**固定遮挡**」
  （观众坐着不动，那些像素永远不是地板）⇒ 累积掩膜≠真实球场矩形，只是形状更规整。
- 因此本工具**只产出「场内区域」掩膜**（给门1 用），**不产出米制单应**。

用法
----
  court_accum_mask.py --seg ep24_s1 --n 50
  court_accum_mask.py --seg ep24_s1 --th 0.5 --save
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
from court_filter import court_mask  # noqa: E402


def shape_stats(m):
    """掩膜的形状统计：面积占比 / 轮廓点数 / 凸包 IoU / 旋转矩形 IoU。"""
    if m is None or m.max() == 0:
        return None
    b = (m > 0).astype(np.uint8)
    cnts, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(c)
    hm = np.zeros_like(b)
    cv2.fillPoly(hm, [hull], 1)
    inter = int(((b > 0) & (hm > 0)).sum())
    union = int(((b > 0) | (hm > 0)).sum())
    hull_iou = inter / max(union, 1)
    rect = cv2.minAreaRect(c)
    rm = np.zeros_like(b)
    cv2.fillPoly(rm, [np.array(cv2.boxPoints(rect), np.float32).astype(np.int32)], 1)
    ri = int(((b > 0) & (rm > 0)).sum())
    ru = int(((b > 0) | (rm > 0)).sum())
    return dict(area=round(float((b > 0).mean()), 3),
                pts=len(c),
                hull_iou=round(hull_iou, 3),
                rect_iou=round(ri / max(ru, 1), 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--n", type=int, default=50, help="采样的帧数（全段均匀取样）")
    ap.add_argument("--ths", default="0.3,0.5,0.7")
    ap.add_argument("--r0", type=int, default=None, help="帧范围起点（含），用于镜头窗口")
    ap.add_argument("--r1", type=int, default=None, help="帧范围终点（含）")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    if not files:
        print(f"无帧: {SEGD / a.seg / 'frames'}")
        return
    step = max(len(files) // a.n, 1)
    idxs = list(range(0, len(files), step))[:a.n]
    if a.r0 is not None or a.r1 is not None:
        lo = a.r0 if a.r0 is not None else 0
        hi = a.r1 if a.r1 is not None else len(files) - 1
        idxs = [i for i in idxs if lo <= i <= hi]
        tag = f"_w{lo}_{hi}"
    else:
        tag = ""

    acc = None
    ok = 0
    for i in idxs:
        img = cv2.imread(str(files[i]))
        if img is None:
            continue
        m, _ = court_mask(img)
        if m is None:
            continue
        m = (m > 0).astype(np.float32)
        acc = m if acc is None else acc + m
        ok += 1
    if acc is None:
        print(f"{a.seg}: 全部帧 court_mask 均返回 None")
        return
    freq = acc / ok
    print(f"{a.seg}: 采样 {len(idxs)} 帧, court_mask 有效 {ok} 帧")
    s0 = shape_stats((freq > 0).astype(np.uint8) * 255)
    print(f"  并集口径(≥1 帧命中)      {s0}")

    base = cv2.imread(str(files[idxs[len(idxs) // 2]]))
    for th in [float(x) for x in a.ths.split(",")]:
        m = (freq >= th).astype(np.uint8) * 255
        s = shape_stats(m)
        print(f"  累积 th={th}  {s}")
        if a.save:
            vis = base.copy()
            vis[m > 0] = (0.5 * vis[m > 0] + 0.5 * np.array([0, 200, 0])).astype(np.uint8)
            op = OUT / f"_dbg_accum_{a.seg}_th{th}.png"
            cv2.imwrite(str(op), vis)
            print(f"    -> {op}")
    np.save(str(OUT / f"_tmp_freq_{a.seg}{tag}.npy"), freq)
    print(f"  freq -> _tmp_freq_{a.seg}{tag}.npy")


if __name__ == "__main__":
    main()
