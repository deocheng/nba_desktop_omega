#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge_batch.py — 人工判读用接触表生成（两种模式，同一渲染口径）。

为什么需要「标定模式」
--------------------
本项目铁律：**视觉能力先自证** —— 任何"目视标注"出数字前，必须先证明判得准。
所以在对 214 个**无真值宣称**动手之前，先用**已知标签的随机样本**做盲测：
  渲染时不显示标签，我判完再与真值比对。一致率不达标 ⇒ 停止，不产出数字。

两种模式
--------
  calib : 从标注库随机抽 N 条（默认 27），**盲**（格头只给序号），key 里存真值。
  claims: 渲染指定条件下的候选（如 th=0.975 的 TypeII 宣称），无真值。
  tie   : 渲染同一帧的**多个候选**并排（用于判断"两个框哪个是球"，上限 2 个/帧）。

渲染口径（与已验证判据一致）
---------------------------
  裁切半窗 50px（100px 方窗）→ 放大到 240px 格（2.4×），球 25–35px → 60–84px。
  每格 = 标签条(26px) + 图(240px) = 266px。每表 3×3 = 9 格 → 720×798，**不被下采样**。

用法:
  python engine/judge_batch.py --mode calib --n 27 --seed 7
  python engine/judge_batch.py --mode claims --th 0.975 --kind TypeII
  python engine/judge_batch.py --mode tie --th 0.975
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
AW, MS = ROOT / "action_work", ROOT / "reports/milestone_05/measure"
OUT = MS / "judge"
CELL, HALF, COLS, ROWS = 240, 50, 3, 3


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2-x1) * max(0, y2-y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i/ua if ua > 0 else 0.0


def crop_pad(img, box, half):
    h, w = img.shape[:2]
    cx, cy = (box[0]+box[2])/2.0, (box[1]+box[3])/2.0
    x0, y0 = int(round(cx-half)), int(round(cy-half))
    x1, y1 = x0+2*half, y0+2*half
    px0, py0 = max(0, -x0), max(0, -y0)
    px1, py1 = max(0, x1-w), max(0, y1-h)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    patch = img[y0:y1, x0:x1]
    if px0 or py0 or px1 or py1:
        patch = cv2.copyMakeBorder(patch, py0, py1, px0, px1, cv2.BORDER_REPLICATE)
    return patch


def cell_once(img, box, tag, color=(0, 220, 255), extra_boxes=(), half=None, cell=None):
    """一格 = 标签条 + 裁切放大图（单框居中）。extra_boxes 用细线画参考框。"""
    half = half or HALF
    cell = cell or CELL
    p = cv2.resize(crop_pad(img, box, half), (cell, cell), interpolation=cv2.INTER_LANCZOS4)
    s = cell / (2.0*half)
    cx, cy = (box[0]+box[2])/2.0, (box[1]+box[3])/2.0
    ox, oy = cx-half, cy-half
    cv2.rectangle(p, (int((box[0]-ox)*s), int((box[1]-oy)*s)),
                  (int((box[2]-ox)*s), int((box[3]-oy)*s)), color, 2)
    for eb, ec in extra_boxes:
        cv2.rectangle(p, (int((eb[0]-ox)*s), int((eb[1]-oy)*s)),
                      (int((eb[2]-ox)*s), int((eb[3]-oy)*s)), ec, 1)
    bar = np.full((26, cell, 3), 28, np.uint8)
    cv2.putText(bar, tag, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
    return np.concatenate([bar, p], axis=0)


def sheet(tiles, path):
    rows = []
    for i in range(0, len(tiles), COLS):
        row = tiles[i:i+COLS]
        while len(row) < COLS:
            row.append(np.full_like(tiles[0], 24))
        rows.append(np.concatenate(row, axis=1))
    while len(rows) < ROWS:
        rows.append(np.full_like(rows[0], 24))
    img = np.concatenate(rows, axis=0)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return img.shape


def emit(tiles, keys, stem, per_sheet=COLS*ROWS):
    n = 0
    for si in range(0, max(1, math.ceil(len(tiles)/per_sheet))):
        ch = tiles[si*per_sheet:(si+1)*per_sheet]
        if not ch:
            continue
        sh = sheet(ch, OUT / f"{stem}_sheet{si}.jpg")
        print(f"[out] {OUT/f'{stem}_sheet{si}.jpg'}  {sh[1]}x{sh[0]}  格 {len(ch)}")
        n += 1
    json.dump(keys, open(OUT / f"{stem}_key.json", "w"), ensure_ascii=False, indent=1)
    print(f"[out] {OUT/f'{stem}_key.json'}  共 {len(keys)} 条 / {n} 表")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["calib", "claims", "tie"])
    ap.add_argument("--n", type=int, default=27)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--th", type=float, default=0.975)
    ap.add_argument("--kind", default="TypeII", choices=["TypeII", "TypeI", "all"])
    ap.add_argument("--half", type=int, default=HALF, help="裁切半窗像素")
    ap.add_argument("--cell", type=int, default=CELL, help="每格边长像素")
    ap.add_argument("--tag", default="", help="输出文件名后缀（区分不同轮次）")
    ap.add_argument("--order-seed", type=int, default=None,
                    help="重测用：保持样本不变，只打乱格序")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed)
    bank = json.load(open(MS / "labels_bank.json"))
    scores = json.load(open(AW / "ball_cand_scores_v2.json"))

    # ---------- calib：盲测 ----------
    if a.mode == "calib":
        pool = [r for r in bank if r["label"] in ("TP", "FP")]
        # 分层：TP/FP 各半，覆盖面广
        tp = [r for r in pool if r["label"] == "TP"]
        fp = [r for r in pool if r["label"] == "FP"]
        k = a.n // 2
        samp = list(rng.choice(len(tp), k, replace=False)) + list(rng.choice(len(fp), a.n-k, replace=False))
        samp = [tp[i] for i in samp[:k]] + [fp[i] for i in samp[k:]]
        rng.shuffle(samp)
        if a.order_seed is not None:          # 重测：样本不变，只重排格序
            np.random.default_rng(a.order_seed).shuffle(samp)
        tiles, keys = [], []
        for i, r in enumerate(samp):
            img = cv2.imread(str(AW / r["window"] / r["frame"]))
            if img is None:
                continue
            tiles.append(cell_once(img, r["bbox"], f"#{i:02d}  {r['window']}",
                                   color=(0, 220, 255), half=a.half, cell=a.cell))
            keys.append({"idx": i, "window": r["window"], "frame": r["frame"],
                         "bbox": r["bbox"], "truth": r["label"]})
        print(f"标定表（**盲**，格头只有序号）：half={a.half} cell={a.cell} "
              f"order_seed={a.order_seed}")
        emit(tiles, keys, "calib" + a.tag)
        print("\n判读规则：看格中心那个物体是不是篮球（橙色球体，可能带黑色线条）。"
              "\n  写成 {\"0\":\"BALL\",\"1\":\"NOT\",\"2\":\"UNC\"} 存到 judge/calib_verdicts.json"
              "\n  然后跑：python engine/judge_calib_score.py")
        return

    # ---------- claims / tie ----------
    bank_wf = {(r["window"], r["frame"]): r for r in bank}
    items = []
    for w, frames in scores.items():
        for f, cs in sorted(frames.items()):
            r = bank_wf.get((w, f))
            for c in cs:
                if c["prob"] <= a.th:
                    continue
                if r is not None and iou(c["bbox"], r["bbox"]) >= 0.5:
                    continue  # 已验证
                kind = "TypeI" if r is not None else "TypeII"
                if a.kind != "all" and kind != a.kind:
                    continue
                items.append({"window": w, "frame": f, "bbox": c["bbox"],
                              "prob": c["prob"], "kind": kind})
    print(f"符合条件（th>{a.th}, kind={a.kind}）的候选 {len(items)}")
    if a.mode == "tie":
        byf = {}
        for it in items:
            byf.setdefault((it["window"], it["frame"]), []).append(it)
        byf = {k: v for k, v in byf.items() if len(v) > 1}
        print(f"同帧多候选（并排比对）{len(byf)} 帧")
        tiles, keys = [], []
        for i, ((w, f), v) in enumerate(sorted(byf.items())):
            img = cv2.imread(str(AW / w / f))
            if img is None:
                continue
            v = sorted(v, key=lambda x: -x["prob"])
            sub = [cell_once(img, v[0]["bbox"], f"#{i:02d} {f[1:6]} A p={v[0]['prob']:.2f}") ,
                   cell_once(img, v[1]["bbox"], f"#{i:02d} {f[1:6]} B p={v[1]['prob']:.2f}") ,
                   np.full((CELL+26, CELL, 3), 24, np.uint8)]
            tiles.extend(sub)
            keys.append({"idx": i, "window": w, "frame": f,
                         "A": v[0]["bbox"], "B": v[1]["bbox"],
                         "Aprob": v[0]["prob"], "Bprob": v[1]["prob"]})
        emit(tiles, keys, "tie", per_sheet=3)
        print("\n判读规则：A/B 两格里**哪一个**是真球（可 A / B / BOTH / NONE / UNC）"
              "\n  写成 {\"0\":\"A\",...} 存到 judge/tie_verdicts.json")
        return

    tiles, keys = [], []
    for i, it in enumerate(items):
        img = cv2.imread(str(AW / it["window"] / it["frame"]))
        if img is None:
            continue
        tiles.append(cell_once(img, it["bbox"], f"#{i:03d} {it['window']} {it['frame'][1:6]}"))
        keys.append({"idx": i, "window": it["window"], "frame": it["frame"],
                     "bbox": it["bbox"], "prob": it["prob"], "kind": it["kind"]})
    emit(tiles, keys, f"claims_{a.kind}")
    print("\n判读规则：格中心那个物体会不会是一个篮球？(BALL / NOT / UNC)"
          f"\n  写成 {{\"0\":\"BALL\",...}} 存到 {OUT/f'claims_{a.kind}_verdicts.json'}")


if __name__ == "__main__":
    main()
