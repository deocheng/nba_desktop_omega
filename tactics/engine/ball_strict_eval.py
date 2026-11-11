#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STRICT 跨窗标定评估 —— 唯一可交付的口径（`ball_verify_head.py train` 只报"自选阈值"）。

口径三级（本项目统一）
--------------------
  · CV       ：同折内自选阈值      —— 最乐观，仅作参考
  · LOWO自选 ：留出窗**用自己的标签**挑阈值 —— 中，仍有选择偏差
  · **STRICT**：留出窗的阈值**只能由其他窗标定** —— 可交付，以此为准

STRICT 实现（嵌套）
------------------
  对每个留出窗 w：
    ① 在其余 3 个窗上做 leave-one-window-out：训练 2 窗 → 给第 3 窗打分；
       得到这 3 个窗的**域外分数** → 在这些分数上选满足 P≥target 的最大召回阈值 th*。
    ② 用其余 3 个窗**全量**训练 → 只拿 th* 去卡留出窗 w，报 P/R。
  这样阈值从未见过 w 的标签 ⇒ 无选择偏差。

用法:
  python engine/ball_strict_eval.py --feats reports/milestone_05/measure/feats_all_v2.npy \
      --target-p 0.90
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
MS = ROOT / "reports/milestone_05/measure"
WINS = ("w1", "w2", "w3", "w4")


def pick_th(y, p, target):
    """在给定分数上选满足 P>=target 的最大召回阈值。"""
    best = (0.0, None)
    for th in np.arange(0.05, 0.9985, 0.005):
        pred = p > th
        tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
        if tp + fp == 0:
            continue
        P = tp / (tp + fp)
        if P >= target:
            R = tp / max(1, int(y.sum()))
            if R > best[0]:
                best = (R, (float(th), float(P), R, tp, fp))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feats", default=str(MS / "feats_all_v2.npy"))
    ap.add_argument("--target-p", type=float, default=0.90)
    a = ap.parse_args()
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = np.load(a.feats)
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    y = np.array([r["label"] == "TP" for r in bank]).astype(int)
    wins = np.array([r["window"] for r in bank])
    assert len(y) == len(X), f"特征 {len(X)} 与标签 {len(y)} 不匹配"

    def mk():
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000, C=1.0))

    print(f"样本 {len(y)}  TP={y.sum()}  FP={(y==0).sum()}  特征 {X.shape[1]}"
          f"  目标 P>={a.target_p}")
    print(f"\n{'留出窗':>8}{'内层阈值th*':>12}{'内层P':>9}{'内层R':>9}"
          f"{'留出R':>9}{'留出P':>9}{'AUC':>9}{'TP':>6}{'FP':>5}")
    rows, allP, allR = [], [], []
    for w in WINS:
        rest = [q for q in WINS if q != w]
        # ① 内层：其余 3 窗互相留出，拿域外分数
        sc, yy = np.zeros(0), np.zeros(0, int)
        for q in rest:
            te = wins == q
            q2 = mk().fit(X[~te], y[~te])
            sc = np.concatenate([sc, q2.predict_proba(X[te])[:, 1]])
            yy = np.concatenate([yy, y[te]])
        inner = pick_th(yy, sc, a.target_p)
        if inner[1] is None:
            print(f"{w:>8}{'—':>12}  其余窗内无 P>={a.target_p} 工作点")
            rows.append({"win": w, "ok": False})
            continue
        th, iP, iR = inner[1][0], inner[1][1], inner[1][2]
        # ② 外层：其余 3 窗全量训练，只拿 th* 卡留出窗
        te = wins == w
        m = mk().fit(X[~te], y[~te])
        pp = m.predict_proba(X[te])[:, 1]
        pred = pp > th
        tp = int((pred & (y[te] == 1)).sum()); fp = int((pred & (y[te] == 0)).sum())
        P = tp / (tp + fp) if tp + fp else 0.0
        R = tp / max(1, int((y[te] == 1).sum()))
        auc = roc_auc_score(y[te], pp)
        print(f"{w:>8}{th:>12.3f}{iP*100:>8.1f}%{iR*100:>8.1f}%"
              f"{R*100:>8.1f}%{P*100:>8.1f}%{auc:>9.4f}{tp:>6}{fp:>5}")
        rows.append({"win": w, "ok": True, "th": th, "innerP": iP, "innerR": iR,
                     "R": R, "P": P, "auc": float(auc), "tp": tp, "fp": fp,
                     "n": int(te.sum())})
        allP.append(P); allR.append(R)
    nok = len(rows)
    npass = sum(1 for r in rows if r["ok"] and r["P"] >= a.target_p)
    print(f"\n**STRICT 裁定：{npass}/{nok} 个窗在留出后仍达 P>={a.target_p}**")
    if allP:
        print(f"  留出 P 均值 {np.mean(allP)*100:.1f}% / 留出 R 均值 {np.mean(allR)*100:.1f}%")
    strict = {"target_p": a.target_p, "n_pass": npass, "n_win": nok,
              "per_win": rows, "feats": str(a.feats)}
    (MS / "strict_eval_v2.json").write_text(json.dumps(strict, ensure_ascii=False, indent=1))
    print(f"[out] {MS / 'strict_eval_v2.json'}")


if __name__ == "__main__":
    main()
