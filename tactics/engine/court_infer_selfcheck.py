#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.15 场地推断自证：多边形 vs 多帧累积掩膜（老程证据：绿色=球场但没覆盖全场）。

判据（双向）：
  containment = 累积掩膜像素落在场地多边形内的比例   ⇒ 应 ≈100%（掩膜是球场的子集）
  coverage    = 场地多边形像素被累积掩膜覆盖的比例   ⇒ 应 <100%（老程：掩膜没覆盖全场）
  两者之差 = 多边形比掩膜多出来的部分 = 被固定遮挡/掩膜漏掉的场地 ⇒ 老程要的就是这块

用法: court_infer_selfcheck.py --seg ep24_s1 --idx 70 --th 0.7
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
from court_infer_lines import infer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--th", type=float, default=0.7)
    a = ap.parse_args()

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    poly, info = infer(img)
    print(f"=== {a.seg} f{a.idx} 自证 (th={a.th}) ===")
    for k, v in info.items():
        if k not in ("poly", "paint_quad"):
            print(f"  {k}: {v}")
    if poly is None:
        print("  推断失败，退出")
        return

    fp = OUT / f"_tmp_freq_{a.seg}.npy"
    if not fp.exists():
        print(f"  缺 {fp}，先跑 court_accum_mask.py --save")
        return
    freq = np.load(str(fp))
    acc = (freq >= a.th).astype(np.uint8)

    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [poly.astype(np.int32)], 1)

    n_acc = int(acc.sum())
    cont = float((acc[m > 0]).sum()) / max(n_acc, 1)
    n_poly = int((m > 0).sum())
    cov = float(acc[m > 0].sum()) / max(n_poly, 1)
    print(f"  累积掩膜像素 {n_acc}  场地多边形像素 {n_poly}")
    print(f"  containment(掩膜⊂场地) = {100*cont:.1f}%   ← 应≈100%")
    print(f"  coverage   (场地被掩膜盖) = {100*cov:.1f}%   ← 应<100%，差额=掩膜漏掉的场地")

    # 叠图：绿=累积掩膜，黄框=场地多边形，青=油漆区
    vis = img.copy()
    ov = vis.copy()
    ov[acc > 0] = (0.5 * ov[acc > 0] + 0.5 * np.array([0, 200, 0])).astype(np.uint8)
    vis = cv2.addWeighted(ov, 0.6, vis, 0.4, 0)
    cv2.polylines(vis, [poly.astype(np.int32)], True, (0, 0, 0), 6)
    cv2.polylines(vis, [poly.astype(np.int32)], True, (0, 255, 255), 3)
    pm_mask_only = None
    from court_homography_recover import paint_mask
    pm = paint_mask(img)
    if pm is not None:
        cs, _ = cv2.findContours(pm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vis, cs, -1, (255, 255, 0), 2)
    op = OUT / f"{a.seg}_f{a.idx}_selfcheck_v1.png"
    cv2.imwrite(str(op), vis)
    print(f"  -> {op}")


if __name__ == "__main__":
    main()
