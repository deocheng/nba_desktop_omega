#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_multiscale_e2e.py — A4.42 multiscale 池端到端评估（同一 final351 头，仅换候选池）。

对比 old(640×384 ov96 top-4 生产池) vs new(multiscale 不截断池)，隔离「分块配置」单一变量：
  ① 覆盖率 @0.3/0.8：全 400 帧 / honest unlabeled（bank 帧以外 = 纯泛化）/ sas_det 零回归
  ② GT 帧 top-1 正确性：TP 帧 argmax-prob 候选是否命中真球（strict≤12px / inbox）
     —— 密集池 FP 洪泛可能让 argmax 被垃圾候选抢走，此指标是候选召回诊断测不到的头侧精度
  ③ 新 empty-cloud 帧清单（multiscale 下 0 候选帧）→ 中期人工点球输入

诚实纪律：
  - 分母独立（final351 bank TP 帧作 GT，不从候选派生）
  - 同一头（ball_head_joint.joblib final351）、同一帧集，仅候选池不同 ⇒ 差异只来自分块配置
  - top-1 正确性是「头+池」联合口径；覆盖率是必要非充分（FP 洪泛可虚增覆盖）
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
VAL = ROOT / "action_work/validate"
OLD_TAG, NEW_TAG = "final351", "multiscale"


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
    """每 GT 帧 argmax-prob 候选是否命中任一 GT 框（strict≤12px / inbox=中心在框内）。"""
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
    bank = load(VAL / "sas_lal_label_bank_final351.json")
    labels = bank["labels"]
    gt_boxes = {}
    for L in labels:
        if L.get("label") == "TP":
            gt_boxes.setdefault(L["frame"], []).append(L["bbox"])
    gt_frames = sorted(gt_boxes)
    # bank 帧集 = 头训练所见帧（honest unlabeled 的补集）
    bank_frames = {L["frame"] for L in labels}
    all_frames = [f"f{j:05d}.jpg" for j in range(1, 401)]
    honest = [f for f in all_frames if f not in bank_frames]

    det_human = load(VAL / "sas_det_label_bank_human.json")["labels"]
    det_bank_frames = {L["frame"] for L in det_human}
    det_honest = [f for f in all_frames if f not in det_bank_frames]

    print("=" * 72)
    print(f"帧集：all=400  sas_lal bank={len(bank_frames)}  honest={len(honest)}"
          f"  GT(TP帧)={len(gt_frames)}  sas_det bank={len(det_bank_frames)}")
    print("=" * 72)

    res = {}
    for clip, honest_set in (("sas_lal", honest), ("sas_det", det_honest)):
        old = load(VAL / f"ball_cand_scores_{OLD_TAG}_{clip}_joint.json")[clip]
        new = load(VAL / f"ball_cand_scores_{NEW_TAG}_{clip}_joint.json")[clip]
        res[clip] = (old, new)
        print(f"\n### {clip} 覆盖率（头=final351，仅换池）")
        for th in (0.3, 0.8):
            for name, sc in (("old(640 top-4)", old), ("new(multiscale)", new)):
                c_all, _ = coverage(sc, all_frames, th)
                c_h, n_h = coverage(sc, honest_set, th)
                print(f"  @th={th} {name:16s} all400={c_all}/400={100*c_all/400:5.1f}%"
                      f"   honest={c_h}/{n_h}={100*c_h/n_h:5.1f}%")

        if clip == "sas_lal":
            print(f"\n### sas_lal GT 帧 top-1 正确性（{len(gt_frames)} TP 帧）")
            for name, sc in (("old(640 top-4)", old), ("new(multiscale)", new)):
                st, ib, n, miss = top1_hit(sc, gt_boxes, gt_frames)
                print(f"  {name:16s} strict={st}/{n}={100*st/n:5.1f}%"
                      f"  inbox={ib}/{n}={100*ib/n:5.1f}%"
                      f"  miss={len(miss)}")
            # 存 miss 清单供目视复核
            _, _, _, miss_new = top1_hit(new, gt_boxes, gt_frames)
            (VAL / "multiscale_gt_top1_miss.json").write_text(
                json.dumps({"tag": NEW_TAG, "miss_frames": miss_new}, ensure_ascii=False, indent=1))

    # empty-cloud（multiscale 下 0 候选帧）
    print("\n### empty-cloud 变化（sas_lal）")
    for tag, pool_f in (("old", "sas_lal_cands.json"), ("new", "sas_lal_cands_multiscale.json")):
        pool = load(VAL / pool_f)["sas_lal"]
        empty = [f for f in all_frames if not pool.get(f)]
        print(f"  {tag:4s} 0候选帧: {len(empty)}  {empty[:16]}")
    (VAL / "multiscale_empty_cloud.json").write_text(json.dumps(
        {"new_empty": [f for f in all_frames if not load(VAL / "sas_lal_cands_multiscale.json")["sas_lal"].get(f)]},
        ensure_ascii=False, indent=1))
    print("\n→ 明细落盘 multiscale_gt_top1_miss.json / multiscale_empty_cloud.json")


if __name__ == "__main__":
    main()
