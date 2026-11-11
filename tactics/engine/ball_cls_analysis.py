#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证头分析：AUC（阈值无关）+ 各窗 P>=90% 最大召回 + 错误清单。
用法: ball_cls_analysis.py [--suffix _reloc] [--geo/--no-geo]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="base")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--geo", default=True, action=argparse.BooleanOptionalAction)
    ap.add_argument("--rows", default="labels_bank.json")
    ap.add_argument("--tta", action="store_true", help="与 _flip 特征做平均（TTA）")
    a = ap.parse_args()

    bank = [r for r in json.loads((MS / a.rows).read_text()) if r["label"] in ("TP", "FP")]
    y = np.array([r["label"] == "TP" for r in bank]).astype(int)
    wins = np.array([r["window"] for r in bank])

    parts = []
    for s in (256, 512):
        f = np.load(MS / f"dino_feats_{a.model}_{s}{a.suffix}.npy")
        if a.tta:
            f = (f + np.load(MS / f"dino_feats_{a.model}_{s}_flip.npy")) / 2.0
        parts.append(f)
    F = np.hstack(parts)
    if a.geo:
        c1 = np.array([r["conf1"] for r in bank])[:, None]
        c2 = np.array([r["conf2"] for r in bank])[:, None]
        bw = np.array([r["bbox"][2] - r["bbox"][0] for r in bank])[:, None]
        bh = np.array([r["bbox"][3] - r["bbox"][1] for r in bank])[:, None]
        cy = np.array([(r["bbox"][1] + r["bbox"][3]) / 2 for r in bank])[:, None] / 1080.0
        F = np.hstack([F, c1, c2, np.log1p(bw), np.log1p(bh), cy])

    lowow = np.zeros(len(y))
    for w in ("w1", "w2", "w3", "w4"):
        te = wins == w
        p = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
        p.fit(F[~te], y[~te])
        lowow[te] = p.predict_proba(F[te])[:, 1]

    tag = f"{a.model}{a.suffix}{'+geo' if a.geo else ''}"
    print(f"=== {tag}  样本 {len(y)} TP={y.sum()} FP={(1-y).sum()} 特征 {F.shape[1]} ===")
    print(f"全局 AUC = {roc_auc_score(y, lowow):.4f}")
    print(f"{'窗':<4}{'AUC':>8}{'P@maxR':>12}{'th':>7}{'TP':>5}{'FP':>5}{'R':>8}")
    for w in ("w1", "w2", "w3", "w4"):
        m = wins == w
        auc = roc_auc_score(y[m], lowow[m])
        yy, pp = y[m], lowow[m]
        npos = int((yy == 1).sum())
        best = (0, None)
        for th in np.arange(0.05, 0.995, 0.005):
            pred = pp > th
            tp = int((pred & (yy == 1)).sum()); fp = int((pred & (yy == 0)).sum())
            if tp + fp == 0:
                continue
            P = tp / (tp + fp)
            R = tp / npos
            if P >= 0.90 and R > best[0]:
                best = (R, (th, P, tp, fp))
        if best[1]:
            th, P, tp, fp = best[1]
            print(f"{w:<4}{auc:>8.4f}{'':>12}{th:>7.2f}{tp:>5}{fp:>5}{best[0]*100:>7.1f}%")
        else:
            print(f"{w:<4}{auc:>8.4f}{'  —— 无P>=90%工作点':>12}")
    # 全局最优工作点（P>=90% 下最大召回）
    npos = int(y.sum())
    best = (0, None)
    for th in np.arange(0.05, 0.995, 0.005):
        pred = lowow > th
        tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
        if tp + fp == 0:
            continue
        P = tp / (tp + fp)
        if P >= 0.90:
            R = tp / npos
            if R > best[0]:
                best = (R, (th, P, tp, fp))
    if best[1]:
        th, P, tp, fp = best[1]
        print(f"全局 P>=90% 最大召回: R={best[0]*100:.1f}%  (th={th:.2f} P={P*100:.1f}% TP={tp} FP={fp})")
    else:
        print("全局: 无 P>=90% 工作点")
    np.save(MS / f"lowow_probs{tag.replace('+','_')}.npy", lowow)


if __name__ == "__main__":
    raise SystemExit(main())
