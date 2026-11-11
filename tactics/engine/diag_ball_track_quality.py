#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.51 诊断: 球轨迹能不能用? —— 在人工 GT 段内量化检测的位置保真度与连续性。

怀疑(A4.51 球运动学读数): 飞行占 72.8%/中位速度 463px/s/最大段距 1524px 未必是真球运动,
可能是 FP 乱跳(FPR≈46%, A4.45 实测)。本诊断用人球 GT(18 段/154 帧)在「真球确实存在且
位置已知」的帧上检验:
  A) 定位误差: top1 检测心 vs GT 心 距离分布(A4.35 实测真球尺寸 p25/50/75=20/22/25 max33px
     ⇒ 用 33px 作「命中」判据, 实测来源非手写常量);
  B) 位移保真: 相邻帧 GT 位移 vs 检测位移(若检测位移远大于 GT ⇒ 检测在乱跳/被 FP 污染);
  C) 连续性: GT 段内(真球连续存在)检测 episode 长度分布(GT 连续但检测断 ⇒ 丢检或误检切换)。

零新模型, 只读。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
import sys
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
CLIP = sys.argv[1] if len(sys.argv) > 1 else "sas_det"
TH, DIAG_MAX, FPS = 0.30, 60, 10.0
HIT_PX = 33.0  # A4.35 实测真球最大尺寸 33px

gt = json.loads((AW / "validate" / f"{CLIP}_human_ball_events.json").read_text())
scores = json.loads((AW / "validate" / f"ball_cand_scores_dense_a442_{CLIP}_joint.json").read_text())
fr_scores = scores[CLIP] if CLIP in scores else scores


def top1(fk):
    best = None
    for c in fr_scores.get(f"f{fk:05d}.jpg", []):
        d = max(c["bbox"][2] - c["bbox"][0], c["bbox"][3] - c["bbox"][1])
        if c["prob"] >= TH and d < DIAG_MAX:
            if best is None or c["prob"] > best["prob"]:
                best = c
    return best


gt_center, gt_frames = {}, []
for seg in gt:
    for fk, c in zip(seg["frames"], seg["centers"]):
        gt_center[fk] = c
        gt_frames.append(fk)
gt_frames = sorted(set(gt_frames))
print(f"[{CLIP}] GT 段={len(gt)} GT 帧={len(gt_frames)}")

# A) 定位误差 + 命中率
errs, hit, det = [], 0, 0
for fk in gt_frames:
    t = top1(fk)
    if t is None:
        continue
    det += 1
    b = t["bbox"]
    e = math.hypot((b[0] + b[2]) / 2 - gt_center[fk][0], (b[1] + b[3]) / 2 - gt_center[fk][1])
    errs.append(e)
    if e <= HIT_PX:
        hit += 1
errs = np.array(errs)
print(f"A) GT 帧有检测 {det}/{len(gt_frames)} ({det/len(gt_frames)*100:.1f}%); "
      f"命中(≤{HIT_PX:.0f}px) {hit}/{len(gt_frames)} = {hit/len(gt_frames)*100:.1f}%")
if len(errs):
    print(f"   定位误差 p25={np.percentile(errs,25):.0f} p50={np.percentile(errs,50):.0f} "
          f"p75={np.percentile(errs,75):.0f} p90={np.percentile(errs,90):.0f} max={errs.max():.0f} px")

# B) 位移保真: 相邻 GT 帧(连续编号)上比较
gt_step, det_step, both = [], [], 0
for a, b in zip(gt_frames, gt_frames[1:]):
    if b - a != 1:
        continue
    g = math.hypot(gt_center[b][0] - gt_center[a][0], gt_center[b][1] - gt_center[a][1])
    ta, tb = top1(a), top1(b)
    if ta is None or tb is None:
        continue
    both += 1
    ca = ((ta["bbox"][0] + ta["bbox"][2]) / 2, (ta["bbox"][1] + ta["bbox"][3]) / 2)
    cb = ((tb["bbox"][0] + tb["bbox"][2]) / 2, (tb["bbox"][1] + tb["bbox"][3]) / 2)
    gt_step.append(g)
    det_step.append(math.hypot(cb[0] - ca[0], cb[1] - ca[1]))
if gt_step:
    g_, d_ = np.array(gt_step), np.array(det_step)
    print(f"B) 相邻GT帧对(两端都有检测) {both} 对")
    print(f"   GT   真球每帧位移 p50={np.percentile(g_,50):.0f} p75={np.percentile(g_,75):.0f} "
          f"max={g_.max():.0f} px  (×10 = {np.percentile(g_,50)*10:.0f} px/s)")
    print(f"   检测 每帧位移     p50={np.percentile(d_,50):.0f} p75={np.percentile(d_,75):.0f} "
          f"max={d_.max():.0f} px  (×10 = {np.percentile(d_,50)*10:.0f} px/s)")
    print(f"   检测位移/GT位移 中位比 = {np.median(d_/np.maximum(g_,1e-6)):.2f}×  "
          f"⇒ >1 表示检测比真球动得多(FP 乱跳)")

# C) 连续性: GT 段内检测 episode
lens = []
for seg in gt:
    cur = 0
    for fk in seg["frames"]:
        if top1(fk) is not None:
            cur += 1
        else:
            if cur:
                lens.append(cur)
            cur = 0
    if cur:
        lens.append(cur)
if lens:
    l = np.array(lens)
    print(f"C) GT段内检测连续子段={len(l)} 段, 长度 p50={np.percentile(l,50):.0f} "
          f"max={l.max()} 帧 (GT 段本身连续, 破碎即丢检/误检切换)")
