#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""融合评估：外观(DINOv2 TTA) ⊕ 几何(conf/框) ⊕ 多帧运动 —— 判断运动特征能否突破 w3 瓶颈。

用法: ball_fusion_eval.py [--motion/--no-motion]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common.nba_paths import tactics_data_file

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
MOT = ["d_med", "d_min", "d_max", "d_min_norm", "static_frac", "near25_frac",
       "nframe_with", "ncand_med", "recur20", "conf_std"]
MOT2 = ["d_prev", "d_next", "plaus_prev", "plaus_next", "chain_tot", "chain_fwd",
        "chain_bwd", "turn_cos", "extrap_resid"]
MSK = ["in_floor", "foot_in_floor", "center_dist", "gap_below", "col_floor_frac"]


def load(appearance=True, motion=True, motion2=False, mask=False):
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    y = np.array([r["label"] == "TP" for r in bank]).astype(int)
    wins = np.array([r["window"] for r in bank])
    parts = []
    if appearance:
        for s in (256, 512):
            f = np.load(MS / f"dino_feats_base_{s}.npy")
            fl = np.load(MS / f"dino_feats_base_{s}_flip.npy")
            parts.append((f + fl) / 2.0)
        c1 = np.array([r["conf1"] for r in bank])[:, None]
        c2 = np.array([r["conf2"] for r in bank])[:, None]
        bw = np.array([r["bbox"][2] - r["bbox"][0] for r in bank])[:, None]
        bh = np.array([r["bbox"][3] - r["bbox"][1] for r in bank])[:, None]
        cy = np.array([(r["bbox"][1] + r["bbox"][3]) / 2 for r in bank])[:, None] / 1080.0
        parts += [c1, c2, np.log1p(bw), np.log1p(bh), cy]
    for fn, keys in (("motion_rows.json", MOT), ("motion_rows2.json", MOT2)):
        if fn.startswith("motion_rows2") and not motion2:
            continue
        if fn.startswith("motion_rows.") and not motion:
            continue
        mr = {(r["window"], r["frame"]): r
              for r in json.loads((MS / fn).read_text())}
        M = np.array([[np.log1p(min(mr[(r["window"], r["frame"])][k], 300)) for k in keys]
                      for r in bank], float)
        parts.append(M)
    if mask:
        mr = {(r["window"], r["frame"]): r for r in json.loads((MS / "mask_rows.json").read_text())}
        M = np.array([[np.log1p(min(mr[(r["window"], r["frame"])][k], 600)) for k in MSK]
                      for r in bank], float)
        parts.append(M)
    return np.hstack(parts), y, wins, bank


def lowo(F, y, wins):
    p = np.zeros(len(y))
    for w in ("w1", "w2", "w3", "w4"):
        te = wins == w
        pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000))
        pipe.fit(F[~te], y[~te])
        p[te] = pipe.predict_proba(F[te])[:, 1]
    return p


def op(pp, y, m, target=0.90):
    yy = y[m]
    npos = int((yy == 1).sum())
    best = (0.0, None)
    for th in np.arange(0.05, 0.995, 0.005):
        pred = pp[m] > th
        tp = int((pred & (yy == 1)).sum())
        fp = int((pred & (yy == 0)).sum())
        if tp + fp == 0:
            continue
        P = tp / (tp + fp)
        if P >= target:
            R = tp / npos
            if R > best[0]:
                best = (R, (float(th), P, tp, fp))
    return best


def run(tag, F, y, wins):
    p = lowo(F, y, wins)
    print(f"\n### {tag}   特征 {F.shape[1]}")
    print(f"全局 AUC={roc_auc_score(y, p):.4f}")
    for w in ("w1", "w2", "w3", "w4"):
        m = wins == w
        a = roc_auc_score(y[m], p[m])
        b = op(p, y, m)
        s = (f"R={b[0]*100:.1f}% @ P={b[1][1]*100:.1f}% (th={b[1][0]:.3f} TP{b[1][2]}/FP{b[1][3]})"
             if b[1] else "无 P≥90% 工作点")
        print(f"  {w}: AUC={a:.4f}   {s}")
    b = op(p, y, np.ones(len(y), bool))
    if b[1]:
        print(f"  全局 P≥90%: R={b[0]*100:.1f}%  (th={b[1][0]:.3f} P={b[1][1]*100:.1f}% TP{b[1][2]}/FP{b[1][3]})")
    else:
        print("  全局: 无 P≥90% 工作点")
    return p


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--motion", default=True, action=argparse.BooleanOptionalAction)
    ap.add_argument("--appearance", default=True, action=argparse.BooleanOptionalAction)
    ap.add_argument("--motion2", default=False, action=argparse.BooleanOptionalAction)
    ap.add_argument("--mask", default=False, action=argparse.BooleanOptionalAction)
    a = ap.parse_args()
    F, y, wins, bank = load(a.appearance, a.motion, a.motion2, a.mask)
    tag = ("外观+几何" if a.appearance else "仅")
    tag += ("+运动v1" if a.motion else "") + ("+运动v2" if a.motion2 else "") + ("+掩膜" if a.mask else "")
    run(tag, F, y, wins)
    if a.appearance and (a.motion or a.motion2):
        Fa, _, _, _ = load(True, False, False, False)
        run("仅外观+几何（对照）", Fa, y, wins)
