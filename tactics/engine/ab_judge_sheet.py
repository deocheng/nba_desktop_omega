#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_judge_sheet.py — 为「全候选重排 A/B 的变化帧」生成**判读友好**接触表。

背景
----
`ball_head_v2.py` 的 A/B 只能给出精度**区间** [下界, 上界]：
  · 下界 = 变化帧里新 top-1 全是 FP
  · 上界 = 变化帧里新 top-1 全是 TP
要收敛成单点，只能**人工判读每个变化帧的新 top-1 到底是不是球**。本脚本产这个表。

判读友好约束（来自已验证的目视判据）
-----------------------------------
  · `cell ≥ 240px`、半窗 ≈ 50–64px —— 更小就看不清球（8 列压到 ~90px 判不动）。
  · 因此每张表 **3 列 × 3 行 = 9 格**，整表 720×1440 → 长边 <1568，**不会被下采样**。
  · 每格上下两半：上 = 旧框（绿=原标注 TP / 红=原标注 FP），下 = 新 top-1（黄）。
  · 格头印 `#序号 窗 帧号 原标注 新prob`，便于逐格记录判读结果。

用法:
  python engine/ab_judge_sheet.py --ab reports/milestone_05/measure/allcand_ab.json
  # 产出 measure/judge/judge_sheet{k}.jpg + judge/judge_key.json
判读结果写到 measure/judge/judge_verdicts.json（人工填写），再由 resolve 子命令收口。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
MS = ROOT / "reports/milestone_05/measure"
OUTDIR = MS / "judge"

CELL = 240           # 每半格边长
HALF = 50            # 裁切半窗（像素）—— 对齐已验证判据 half≈50：裁 100px → 2.4× → 球 60–84px
COLS, ROWS = 3, 3    # 每表 9 格


def crop_pad(img, box, half):
    """以 box 中心裁 2*half 方窗，越界则镜像填充。"""
    h, w = img.shape[:2]
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    x0, y0 = int(round(cx - half)), int(round(cy - half))
    x1, y1 = x0 + 2 * half, y0 + 2 * half
    px0, py0 = max(0, -x0), max(0, -y0)
    px1, py1 = max(0, x1 - w), max(0, y1 - h)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    patch = img[y0:y1, x0:x1]
    if px0 or py0 or px1 or py1:
        patch = cv2.copyMakeBorder(patch, py0, py1, px0, px1, cv2.BORDER_REPLICATE)
    return patch


def half_cell(img, box, color, tag, probtag=""):
    """上半格或下半格：裁切 + 画框 + 顶部标签条。"""
    p = crop_pad(img, box, HALF)
    p = cv2.resize(p, (CELL, CELL), interpolation=cv2.INTER_LANCZOS4)
    # 框（把原图坐标映射到 240 格内）
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    s = CELL / (2.0 * HALF)
    bx0 = int((box[0] - (cx - HALF)) * s); by0 = int((box[1] - (cy - HALF)) * s)
    bx1 = int((box[2] - (cx - HALF)) * s); by1 = int((box[3] - (cy - HALF)) * s)
    cv2.rectangle(p, (bx0, by0), (bx1, by1), color, 2)
    # 标签条
    bar = np.zeros((26, CELL, 3), np.uint8)
    bar[:] = (28, 28, 28)
    cv2.putText(bar, tag, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 1, cv2.LINE_AA)
    if probtag:
        (tw, _), _ = cv2.getTextSize(probtag, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
        cv2.putText(bar, probtag, (CELL - tw - 6, 19), cv2.FONT_HERSHEY_SIMPLEX,
                    0.52, (60, 220, 255), 1, cv2.LINE_AA)
    return np.concatenate([bar, p], axis=0)


def tile_for(idx, r, scores, ab_key):
    img = cv2.imread(str(AW / r["window"] / r["frame"]))
    if img is None:
        return None, None
    old_col = (80, 220, 80) if r["label"] == "TP" else (60, 60, 235)
    top = None
    cs = scores.get(r["window"], {}).get(r["frame"], [])
    if cs:
        top = max(cs, key=lambda c: c["prob"])
    tag_old = f"#{idx:03d} {r['window']} {r['frame'][1:6]} OLD:{r['label']}"
    half1 = half_cell(img, r["bbox"], old_col, tag_old)
    if top is not None:
        half2 = half_cell(img, top["bbox"], (0, 220, 255),
                          f"#{idx:03d} NEW top-1", f"p={top['prob']:.2f}")
        # 旧框在新格里也用细线标出（便于判断"新框是否就是同一个东西"）
        cx, cy = (top["bbox"][0]+top["bbox"][2])/2.0, (top["bbox"][1]+top["bbox"][3])/2.0
        s = CELL / (2.0*HALF)
        ox0 = int((r["bbox"][0]-(cx-HALF))*s); oy0 = int((r["bbox"][1]-(cy-HALF))*s)
        ox1 = int((r["bbox"][2]-(cx-HALF))*s); oy1 = int((r["bbox"][3]-(cy-HALF))*s)
        sub = half2[26:]
        cv2.rectangle(sub, (ox0, oy0), (ox1, oy1), old_col, 1)
    else:
        half2 = np.zeros_like(half1)
    return np.concatenate([half1, half2], axis=0), (top or {}).get("prob")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ab", default=str(MS / "allcand_ab.json"))
    ap.add_argument("--scores", default=str(AW / "ball_cand_scores_v2.json"))
    ap.add_argument("--max-fp", type=int, default=48,
                    help="『原标注 FP 的变化帧』抽样上限（原 TP 变化帧全判）")
    ap.add_argument("--all", action="store_true", help="不做抽样，全判")
    a = ap.parse_args()
    OUTDIR.mkdir(parents=True, exist_ok=True)

    ab = json.load(open(a.ab))
    scores = json.load(open(a.scores))
    ch_all = ab.get("change_list", [])
    print(f"变化帧 {len(ch_all)}（A/B 区间 [{ab['lo']:.1f}%, {ab['hi']:.1f}%]，"
          f"旧口径 {ab['oldP']:.1f}%）")

    # 分层：原 TP 变化帧全取；原 FP 变化帧抽样（判读量大，用比例估计收口）
    ch_tp = [r for r in ch_all if r["label"] == "TP"]
    ch_fp = [r for r in ch_all if r["label"] == "FP"]
    rng = np.random.default_rng(0)
    if a.all:
        ch = ch_all
    else:
        samp = list(rng.choice(len(ch_fp), min(a.max_fp, len(ch_fp)), replace=False)) if ch_fp else []
        ch = [ch_fp[i] for i in sorted(samp)] + ch_tp
    print(f"分层抽样：原TP变化帧 {len(ch_tp)}/{len(ch_tp)} 全判；"
          f"原FP变化帧 {0 if a.all else min(a.max_fp, len(ch_fp))}/{len(ch_fp)} 抽判"
          f"  ⇒ 实际渲染 {len(ch)} 格")

    key, tiles = [], []
    for i, r in enumerate(ch):
        t, prob = tile_for(i, r, scores, ab)
        if t is None:
            print(f"  ⚠️ #{i:03d} 读图失败 {r['window']}/{r['frame']}")
            continue
        key.append({"idx": i, "window": r["window"], "frame": r["frame"],
                    "label": r["label"], "new_prob": prob})
        tiles.append(t)

    per_sheet = COLS * ROWS
    nsheet = max(1, math.ceil(len(tiles) / per_sheet))
    for si in range(nsheet):
        chunk = tiles[si*per_sheet:(si+1)*per_sheet]
        if not chunk:
            continue
        rows = []
        for i in range(0, len(chunk), COLS):
            row = chunk[i:i+COLS]
            while len(row) < COLS:
                row.append(np.full_like(chunk[0], 24))
            rows.append(np.concatenate(row, axis=1))
        while len(rows) < ROWS:
            rows.append(np.full_like(rows[0], 24))
        sheet = np.concatenate(rows, axis=0)
        p = OUTDIR / f"judge_sheet{si}.jpg"
        cv2.imwrite(str(p), sheet, [cv2.IMWRITE_JPEG_QUALITY, 95])
        print(f"[out] {p}  {sheet.shape[1]}x{sheet.shape[0]}  格数 {len(chunk)}")

    json.dump({"ab_path": a.ab, "n_change": len(ch_all), "lo": ab["lo"], "hi": ab["hi"],
               "oldP": ab["oldP"], "same_TP": ab.get("same_TP"), "same_FP": ab.get("same_FP"),
               "n_bank": ab.get("n"),
               "group_sizes": {"changed_oldTP": len(ch_tp), "changed_oldFP": len(ch_fp)},
               "judged": {"changed_oldTP": len(ch_tp),
                          "changed_oldFP": (len(ch) - len(ch_tp))},
               "key": key},
              open(OUTDIR / "judge_key.json", "w"), ensure_ascii=False, indent=1)
    print(f"[out] {OUTDIR/'judge_key.json'}")
    print(f"\n判读规则：每格看**下半（NEW top-1）**——中心那个橙/棕色球形物是不是篮球？"
          f"\n  可判：BALL（是球）/ NOT（不是）/ UNC（看不清或半个球）"
          f"\n把结果写成 {{\"0\":\"BALL\",\"1\":\"NOT\",...}} 存到 {OUTDIR/'judge_verdicts.json'}")


if __name__ == "__main__":
    main()
