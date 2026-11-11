#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.52 球的移动追踪 v1 —— 球候选跨帧数据关联(tracklet), 把孤立的 top1 检测连成轨迹。

动机(A4.51 诊断, 已实测):
  GT 段内检测定位 p50=0px/p75=5px、位移与真球比 1.00× ⇒ 检测本身忠实;
  轨迹破碎源 = ①覆盖 58.8% 的间隙 ②GT 段外 ~46% FPR 的**孤立** FP(制造假飞行段)。
  孤立 FP 的天然克星 = 跨帧关联: 真球连续, FP 孤立(连不上)。

方法(tracking-by-detection, 零新模型):
  每帧取 top-K 候选(prob≥PROB_MIN) → 相邻帧贪心最近邻匹配(代价=中心距 + 尺寸偏离惩罚,
  门控 GATE_PX) → 连续链构成 tracklet, 长度≥MIN_LEN 才保留(孤立 FP 自然被淘汰)。
  BRIDGE: 允许桥接最多 N 帧丢检(桥接帧**不填位置**, 绝非插值)。
  不插值: 断就断, tracklet 内位置全为实测检测。

门控/阈值来源(实测, 禁手写常量):
  SIZE_REF=22 ← A4.35 实测真球尺寸中位 22px(p25/p75=20/25, max33);
  GATE 扫描区间 ← A4.51 实测 GT 真球每帧位移 p75=35/max=151px。

验收(独立, 用人球 GT 18 段/154 帧, 绝不拿 GT 参与关联):
  覆盖率 = GT 帧被某 tracklet 覆盖的比例; 精度 = tracklet 帧落在 GT 帧的比例(1-FPR);
  与 baseline(top1 逐帧 th0.30, 无关联) 同口径对比; F1 为取舍参考。

用法: ball_tracklet.py [clip] [--gate G] [--min-len N] [--bridge N] [--sweep]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
ap = argparse.ArgumentParser()
ap.add_argument("clip", nargs="?", default="sas_det")
ap.add_argument("--gate", type=float, default=100.0)
ap.add_argument("--min-len", type=int, default=3)
ap.add_argument("--bridge", type=int, default=0, help="允许桥接的最大丢检帧数(桥接帧不填位置)")
ap.add_argument("--topk", type=int, default=8)
ap.add_argument("--prob-min", type=float, default=0.10)
ap.add_argument("--max-diag", type=float, default=33.0,
                help="tracklet 平均直径上限(px); 默认 33 = A4.35 实测真球 max, 硬先验证伪球轨迹")
ap.add_argument("--sweep", action="store_true", help="参数扫描(不写产物)")
A = ap.parse_args()

CLIP = A.clip
OUT = AW / "validate" / f"{CLIP}_ball_tracklets.json"
N_FRAMES = 400
TOPK = A.topk
PROB_MIN = A.prob_min
SIZE_REF = 22.0      # A4.35 实测真球尺寸中位
W_SIZE = 1.5         # 尺寸偏离惩罚权重(px 等价)

scores = json.loads((AW / "validate" / f"ball_cand_scores_dense_a442_{CLIP}_joint.json").read_text())
fr_scores = scores[CLIP] if CLIP in scores else scores
gt = json.loads((AW / "validate" / f"{CLIP}_human_ball_events.json").read_text())
gt_frames = set()
for seg in gt:
    gt_frames.update(seg["frames"])


def cands(fk):
    cs = []
    for c in fr_scores.get(f"f{fk:05d}.jpg", []):
        if c["prob"] < PROB_MIN:
            continue
        b = c["bbox"]
        cs.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2,
                   max(b[2] - b[0], b[3] - b[1]), c["prob"]))
    cs.sort(key=lambda t: -t[3])
    return cs[:TOPK]


def associate(gate, min_len, bridge):
    tracks = []
    active = {}   # ti -> (last_cand, miss)
    for fk in range(1, N_FRAMES + 1):
        cs = cands(fk)
        pairs = []
        for ti, (last, miss) in active.items():
            for j, c in enumerate(cs):
                d = math.hypot(c[0] - last[0], c[1] - last[1])
                pen = W_SIZE * (abs(c[2] - SIZE_REF) + abs(last[2] - SIZE_REF))
                # 门控按桥接帧数放宽(丢检期间球可移动更远)
                if d <= gate * (miss + 1):
                    pairs.append((d + pen, ti, j))
        pairs.sort()
        used_t, used_c = set(), set()
        new_active = {}
        for cc, ti, j in pairs:
            if ti in used_t or j in used_c:
                continue
            used_t.add(ti); used_c.add(j)
            tr = tracks[ti]
            tr["frames"].append(fk); tr["pts"].append((cs[j][0], cs[j][1]))
            tr["probs"].append(cs[j][3]); tr["diags"].append(cs[j][2])
            new_active[ti] = (cs[j], 0)
        # 未匹配的 active: 桥接容忍
        for ti, (last, miss) in active.items():
            if ti in used_t:
                continue
            if miss + 1 <= bridge:
                new_active[ti] = (last, miss + 1)   # 保留等待, 不追加帧(不填位置)
        for j, c in enumerate(cs):
            if j in used_c:
                continue
            tracks.append({"frames": [fk], "pts": [(c[0], c[1])], "probs": [c[3]], "diags": [c[2]]})
            new_active[len(tracks) - 1] = (c, 0)
        active = new_active
    out = []
    for t in tracks:
        if len(t["frames"]) < min_len:
            continue
        if A.max_diag and float(np.mean(t["diags"])) > A.max_diag:   # 尺寸硬先验(A4.35 真球 max)
            continue
        out.append(t)
    return out


def score(kept):
    fs = set()
    for t in kept:
        fs.update(t["frames"])
    inter = fs & gt_frames
    cov = len(inter) / len(gt_frames) * 100
    prec = len(inter) / len(fs) * 100 if fs else 0.0
    f1 = 2 * prec * cov / (prec + cov) if (prec + cov) else 0.0
    return cov, prec, f1, len(fs)


# baseline: 生产 top1(th=0.30, diag<60)
base = set()
for fk in range(1, N_FRAMES + 1):
    best = None
    for c in fr_scores.get(f"f{fk:05d}.jpg", []):
        b = c["bbox"]
        if c["prob"] >= 0.30 and max(b[2] - b[0], b[3] - b[1]) < 60:
            if best is None or c["prob"] > best["prob"]:
                best = c
    if best:
        base.add(fk)
binter = base & gt_frames
bcov = len(binter) / len(gt_frames) * 100
bprec = len(binter) / len(base) * 100
bf1 = 2 * bprec * bcov / (bprec + bcov)
print(f"[{CLIP}] GT 帧 {len(gt_frames)} | baseline top1: 覆盖 {bcov:.1f}% 精度 {bprec:.1f}% F1 {bf1:.1f}")

if A.sweep:
    print(f"\n{'gate':>5}{'minlen':>7}{'bridge':>7}{'n_trk':>7}{'帧数':>6}{'覆盖':>8}{'精度':>8}{'F1':>7}")
    best = None
    for gate in (60.0, 100.0, 150.0, 200.0):
        for min_len in (2, 3):
            for bridge in (0, 1, 2):
                kept = associate(gate, min_len, bridge)
                cov, prec, f1, nf = score(kept)
                print(f"{gate:>5.0f}{min_len:>7d}{bridge:>7d}{len(kept):>7d}{nf:>6d}"
                      f"{cov:>7.1f}%{prec:>7.1f}%{f1:>7.1f}")
                if best is None or f1 > best[0]:
                    best = (f1, gate, min_len, bridge, cov, prec)
    print(f"\n最佳 F1={best[0]:.1f} @ gate={best[1]:.0f} min_len={best[2]} bridge={best[3]} "
          f"(覆盖 {best[4]:.1f}% 精度 {best[5]:.1f}%)")
else:
    kept = associate(A.gate, A.min_len, A.bridge)
    cov, prec, f1, nf = score(kept)
    print(f"[tracklet] gate={A.gate:.0f} min_len={A.min_len} bridge={A.bridge}: "
          f"保留 {len(kept)} 条(原始 {len(associate(A.gate,1,A.bridge))} 链), 覆盖帧 {nf}")
    print(f"   覆盖 {cov:.1f}% | 精度 {prec:.1f}% | F1 {f1:.1f}")
    ls = sorted(len(t["frames"]) for t in kept)
    if ls:
        print(f"   tracklet 长度 p50={ls[len(ls)//2]} max={ls[-1]} 帧")
    json.dump({"meta": {"clip": CLIP, "prob_min": PROB_MIN, "topk": TOPK, "gate_px": A.gate,
                        "min_len": A.min_len, "bridge": A.bridge, "size_ref": SIZE_REF,
                        "max_diag_px": A.max_diag, "no_interp": True, "bridge_frames_unfilled": True},
               "eval": {"gt_frames": len(gt_frames), "coverage_pct": round(cov, 1),
                        "precision_pct": round(prec, 1), "f1": round(f1, 1),
                        "baseline": {"coverage_pct": round(bcov, 1), "precision_pct": round(bprec, 1),
                                     "f1": round(bf1, 1)}},
               "tracklets": [{"frames": t["frames"],
                              "pts": [[round(x, 1), round(y, 1)] for x, y in t["pts"]],
                              "mean_prob": round(float(np.mean(t["probs"])), 3),
                              "mean_diag": round(float(np.mean(t["diags"])), 1),
                              "n": len(t["frames"])} for t in kept]},
              open(OUT, "w"), indent=1)
    print(f"[out] {OUT}")
