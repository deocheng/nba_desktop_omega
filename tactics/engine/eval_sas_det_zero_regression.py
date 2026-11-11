#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_sas_det_zero_regression.py — A4.42 转正终裁：sas_det 零回归检查。

对比：OLD = final351 头 + 640×384 ov96 top-4 生产池（报告基线 55.2%@0.3 / 45.5%@0.8）
      NEW = dense_a442 头 + multiscale 不截断池（待生成）

口径（与 sas_lal 附录 §23 一致）：
  ① 覆盖率 @0.3/0.8：all400 / honest（bank 帧以外 = 纯泛化）
  ② GT 帧 top-1 正确性：sas_det human bank 44 个 TP 帧，argmax-prob 候选是否命中真球
     （strict≤12px / inbox）—— 头侧精度真指标，FP 洪泛可虚增覆盖但不增此
  ③ 无球帧 FPR：bank 标注「全 FP = 无球」帧，NEW 在 th=0.3 触发（max prob>th）的占比

零回归门禁：NEW all400 覆盖 ≥ OLD 基线（55.2/45.5）；GT top-1 ≥ 80%；无球帧 FPR ≤ 老程容忍（≤10%）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

VAL = Path(str(tactics_data_file("action_work/validate")))
OLD_SCORES = VAL / "ball_cand_scores_final351_sas_det_joint.json"
DET_BANK = VAL / "sas_det_label_bank_human.json"
OLD_BASELINE = {"cov03": 55.2, "cov08": 45.5}  # 报告 §2 文档化基线


def load(p):
    return json.loads(Path(p).read_text())


def center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def coverage(scores, frames, th):
    cov = 0
    for fr in frames:
        row = scores.get(fr, [])
        if row and max(c["prob"] for c in row) > th:
            cov += 1
    return cov, len(frames)


def top1_hit(scores, gt_boxes, frames):
    st = ib = 0
    miss = []
    for fr in frames:
        row = scores.get(fr, [])
        gts = gt_boxes.get(fr, [])
        if not row or not gts:
            miss.append(fr)
            continue
        top = max(row, key=lambda c: c["prob"])
        cx, cy = center(top["bbox"])
        hit_s = hit_i = False
        for g in gts:
            gx1, gy1, gx2, gy2 = g
            d = np.hypot(cx - (gx1 + gx2) / 2, cy - (gy1 + gy2) / 2)
            if d <= 12:
                hit_s = True
            if gx1 <= cx <= gx2 and gy1 <= cy <= gy2:
                hit_i = True
        st += hit_s
        ib += hit_i
        if not (hit_s or hit_i):
            miss.append(fr)
    return st, ib, len(frames), miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default=str(VAL / "ball_cand_scores_dense_a442_sas_det_joint.json"))
    a = ap.parse_args()

    all_frames = [f"f{j:05d}.jpg" for j in range(1, 401)]

    # sas_det human bank：GT 框 + bank 帧集 + 无球帧
    bank = load(DET_BANK)["labels"]
    gt_boxes = {}
    bank_frames = set()
    tp_frames = set()
    for L in bank:
        fr = L["frame"]
        bank_frames.add(fr)
        if L.get("label") == "TP":
            gt_boxes.setdefault(fr, []).append(L["bbox"])
            tp_frames.add(fr)
    # 无球帧 = bank 帧中「无任何 TP 标注」者（排除「同时含 TP+FP 候选」的持球帧）
    no_ball_frames = bank_frames - tp_frames
    honest = [f for f in all_frames if f not in bank_frames]
    gt_frames = sorted(gt_boxes)
    print("=" * 74)
    print(f"sas_det 帧集: all=400  bank={len(bank_frames)}  honest={len(honest)}"
          f"  GT(TP帧)={len(gt_frames)}  无球帧(全FP标注)={len(no_ball_frames)}")
    print("=" * 74)

    old = load(OLD_SCORES)
    old = old["sas_det"] if "sas_det" in old else old
    new = load(a.new)
    new = new["sas_det"] if "sas_det" in new else new

    print("\n### 覆盖率（头×池）")
    print(f"{'config':22s} {'all@0.3':>9s} {'all@0.8':>9s} {'honest@0.3':>12s} {'honest@0.8':>12s}")
    for name, sc in (("OLD final351+top4", old), ("NEW dense+multiscale", new)):
        c03, _ = coverage(sc, all_frames, 0.3)
        c08, _ = coverage(sc, all_frames, 0.8)
        h03, n_h = coverage(sc, honest, 0.3)
        h08, _ = coverage(sc, honest, 0.8)
        print(f"{name:22s} {100*c03/400:8.1f}% {100*c08/400:8.1f}%"
              f" {100*h03/n_h:11.1f}% {100*h08/n_h:11.1f}%")

    print("\n### GT 帧 top-1 正确性（44 TP 帧，sas_det human bank）")
    for name, sc in (("OLD final351+top4", old), ("NEW dense+multiscale", new)):
        st, ib, n, miss = top1_hit(sc, gt_boxes, gt_frames)
        print(f"  {name:22s} strict={st}/{n}={100*st/n:5.1f}%"
              f"  inbox={ib}/{n}={100*ib/n:5.1f}%  miss={len(miss)}")

    print("\n### 无球帧 FPR（th=0.3，bank 全FP标注帧 = 真·无球）")
    for name, sc in (("OLD final351+top4", old), ("NEW dense+multiscale", new)):
        fp = 0
        for fr in no_ball_frames:
            row = sc.get(fr, [])
            if row and max(c["prob"] for c in row) > 0.3:
                fp += 1
        print(f"  {name:22s} FP触发 {fp}/{len(no_ball_frames)}"
              f" = {100*fp/len(no_ball_frames):5.1f}%")

    # 零回归裁定
    print("\n### 零回归裁定")
    c03, _ = coverage(new, all_frames, 0.3)
    c08, _ = coverage(new, all_frames, 0.8)
    st, ib, n, _ = top1_hit(new, gt_boxes, gt_frames)
    fp = sum(1 for fr in no_ball_frames
             if new.get(fr) and max(c["prob"] for c in new[fr]) > 0.3)
    new03, new08 = 100*c03/400, 100*c08/400
    gt1 = 100*st/n
    fpr = 100*fp/len(no_ball_frames)
    print(f"  NEW all@0.3 = {new03:.1f}%  (基线 {OLD_BASELINE['cov03']}%)  "
          f"{'PASS✓' if new03 >= OLD_BASELINE['cov03'] else 'REGRESS✗'}")
    print(f"  NEW all@0.8 = {new08:.1f}%  (基线 {OLD_BASELINE['cov08']}%)  "
          f"{'PASS✓' if new08 >= OLD_BASELINE['cov08'] else 'REGRESS✗'}")
    print(f"  NEW GT top-1 = {gt1:.1f}%  (门禁 ≥80%)  {'PASS✓' if gt1 >= 80 else 'FAIL✗'}")
    print(f"  NEW 无球FPR = {fpr:.1f}%  (容忍 ≤10%)  {'PASS✓' if fpr <= 10 else 'WARN⚠'}")
    verdict = (new03 >= OLD_BASELINE['cov03'] and new08 >= OLD_BASELINE['cov08']
               and gt1 >= 80 and fpr <= 10)
    print(f"\n  → 终裁: {'✅ 零回归达成，可转正' if verdict else '⚠️ 未全部达标，需老程裁决'}")

    out = {
        "old_baseline": OLD_BASELINE,
        "new": {"cov03_all": round(new03, 1), "cov08_all": round(new08, 1),
                "gt_top1_strict": round(gt1, 1), "noball_fpr": round(fpr, 1)},
        "verdict_pass": verdict,
    }
    (VAL / "sas_det_zero_regression.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("→ 落盘 sas_det_zero_regression.json")


if __name__ == "__main__":
    main()
