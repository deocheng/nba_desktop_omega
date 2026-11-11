#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全候选重排 A/B —— 把「只用每帧 top-1」改成「用验证头在**全部候选**里挑」。

动机（2026-09-24 实测）
--------------------
  · 原始 tile 检出：**97% 的帧都有球候选**、每帧 2.6 个、共 4748 个。
  · 但现行 `detect_ball_verified.py --top1` **只留 conf 最高的那一个**再去验证/打分，
    其余 89% 候选从未被验证头看过。
  · 而 RF-DETR 自己的 conf 几乎不携带信息：4748 个候选 conf 中位 0.542、p90 0.701、
    p95 0.718（窄带堆积），模型卡自述 **Map Ball = 0.1805**。
  ⇒ 「按 conf 选 top-1」接近随机选。**用验证头（AUC≈0.90）在全部候选里重排**是免费的改进。

本脚本只做**测量与差异清单**，不改管线：
  1. 对 324 个**已人工标注**的帧，比较「旧 top-1（按 conf）」与「新 top-1（按头概率）」。
  2. 分类：未变（标签可直接沿用）／变了（需人工复核）。
  3. 把「变了」的帧渲成接触表，供人工判读。

用法:
  python engine/ball_allcand_eval.py --new action_work/ball_cand_scores.json \
      --out reports/milestone_05/measure/allcand_ab
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
MS = ROOT / "reports/milestone_05/measure"


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / ua if ua > 0 else 0.0


def cell(img, box, size=100, out=240, mark=(0, 0, 255), tag=""):
    x1, y1, x2, y2 = box
    cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
    h = size // 2
    X1, Y1 = cx - h, cy - h
    c = np.zeros((size, size, 3), np.uint8)
    sx1, sy1 = max(0, X1), max(0, Y1)
    sx2, sy2 = min(img.shape[1], X1 + size), min(img.shape[0], Y1 + size)
    if sx2 > sx1 and sy2 > sy1:
        c[sy1 - Y1:sy2 - Y1, sx1 - X1:sx2 - X1] = img[sy1:sy2, sx1:sx2]
    c = cv2.resize(c, (out, out), interpolation=cv2.INTER_CUBIC)
    sc = out / size
    bx1, by1 = (x1 - X1) * sc, (y1 - Y1) * sc
    bx2, by2 = (x2 - X1) * sc, (y2 - Y1) * sc
    cv2.rectangle(c, (int(bx1), int(by1)), (int(bx2), int(by2)), mark, 2)
    if tag:
        cv2.putText(c, tag, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3,
                    cv2.LINE_AA)
        cv2.putText(c, tag, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1,
                    cv2.LINE_AA)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True, help="{window:{frame:[{bbox,prob}]}}")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cell", type=int, default=100)
    ap.add_argument("--outpx", type=int, default=240)
    ap.add_argument("--per-sheet", type=int, default=48)
    a = ap.parse_args()

    new = json.loads(Path(a.new).read_text())
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    # 旧 top-1（按 conf）的集合
    old = {}
    for w in ("w1", "w2", "w3", "w4"):
        det = json.loads((AW / f"{w}_ball_verified_t1.json").read_text())
        for f, cs in det.items():
            if cs:
                old[(w, f)] = max(cs, key=lambda c: c["conf1"])

    changed, same = [], {"TP": 0, "FP": 0}
    for r in bank:
        k = (r["window"], r["frame"])
        cands = new.get(r["window"], {}).get(r["frame"], [])
        if not cands:
            changed.append((r, None, 0.0))
            continue
        top = max(cands, key=lambda c: c["prob"])
        v = iou(top["bbox"], r["bbox"])
        if v >= 0.5:
            same[r["label"]] += 1
        else:
            changed.append((r, top, float(v)))
    print(f"已标注帧 {len(bank)}：新 top-1 与原框一致 {same['TP']+same['FP']}"
          f"（其中原为 TP {same['TP']} / FP {same['FP']}）；**发生变化 {len(changed)}**")
    tp = sum(1 for r, t, v in changed if r["label"] == "TP")
    print(f"  变化集构成：原 TP {tp} / 原 FP {len(changed)-tp}")

    # 旧案：原 top-1 的标签就是人工标签 ⇒ 旧精度 = TP/(TP+FP)
    print(f"  旧口径（conf top-1 + conf2>0.4 筛选）在此 324 帧上："
          f"P={160/324*100:.1f}%")
    # 新案：未变的沿用标签；变化的待人工判读
    print(f"  新口径：一致且为 TP {same['TP']}；一致且为 FP {same['FP']}；"
          f"待判读 {len(changed)}  ⇒ 最终精度上下界 "
          f"[{(same['TP'])/(same['TP']+same['FP']+len(changed))*100:.1f}%, "
          f"{(same['TP']+len(changed))/(same['TP']+same['FP']+len(changed))*100:.1f}%]")

    # 接触表：每格画【新 top-1（红框）】+【原框（黄框，若不同）】
    tiles = []
    for r, top, v in changed:
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        if img is None:
            continue
        c = cell(img, r["bbox"], a.cell, a.outpx, (0, 220, 255), "orig")
        if top is not None:
            c2 = cell(img, top["bbox"], a.cell, a.outpx, (0, 0, 255),
                      f"new p={top['prob']:.2f}")
            c = np.concatenate([c, c2], axis=0)
        else:
            c = np.concatenate([c, np.zeros_like(c)], axis=0)
        tiles.append(c)
    # 打包成多张表
    per = a.per_sheet
    ncol = 8
    for si in range(0, max(1, (len(tiles) + per - 1) // per)):
        chunk = tiles[si * per:(si + 1) * per]
        if not chunk:
            continue
        rows = []
        for i in range(0, len(chunk), ncol):
            row = chunk[i:i + ncol]
            while len(row) < ncol:
                row.append(np.zeros_like(chunk[0]))
            rows.append(np.concatenate(row, axis=1))
        sheet = np.concatenate(rows, axis=0)
        p = f"{a.out}_sheet{si}.jpg"
        cv2.imwrite(p, sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"[out] {p}  格数 {len(chunk)}（上=原框 下=新 top-1）")


if __name__ == "__main__":
    main()
