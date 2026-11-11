#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ball_head_sas —— 用 sas_det AI 自标标签重训验证头（用户授权覆盖 74.4% 门禁，探索性）。

口径镜像 engine/backups 的 ball_head_v2.py（同一 build_all 特征、同一 Logistic 配方），
差异：
  1) 标签源 = sas_det_label_bank.json（AI 自标 v2-3panel，TP49/FP210/unc9，67 帧）；
     标签按 (frame, idx) 与候选云精确匹配，无 IoU 匹配误差。
  2) unc 剔除出训练（技能铁律 4）。
  3) 除 StratifiedKFold 外加 **GroupKFold(按帧)**——同帧候选共享上下文，随机折会泄漏。
  4) 训练后对 sas_det 全部 1592 候选打分 -> ball_cand_scores_sas.json，
     并用 track_ball 门禁（覆盖 + trackable）与旧 conf1 源同口径对比。

⚠️ 全部产出标注：AI 自标 ≤74% 可靠性，仅探索，不作结论。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
MS = ROOT / "reports/milestone_05/measure"
sys.path.insert(0, str(ROOT / "engine"))
import ball_feats_all as B  # noqa: E402


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def work_at(y, p, target):
    best = (0.0, None)
    for th in np.arange(0.05, 0.998, 0.002):
        pred = p > th
        tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
        if tp + fp == 0:
            continue
        P = tp / (tp + fp)
        if P >= target and tp / max(1, int(y.sum())) > best[0]:
            best = (tp / max(1, int(y.sum())), (float(th), float(P), tp, fp))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cands", default=str(AW / "validate" / "sas_det_cands.json"))
    ap.add_argument("--bank", default=str(AW / "validate" / "sas_det_label_bank.json"))
    ap.add_argument("--out", default=str(MS / "ball_head_sas.joblib"))
    ap.add_argument("--scores-out", default=str(AW / "validate" / "ball_cand_scores_sas.json"))
    ap.add_argument("--target-p", type=float, default=0.80)
    ap.add_argument("--dev", default="cpu")
    a = ap.parse_args()

    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    cands = json.loads(Path(a.cands).read_text())["sas_det"]
    idx = {"sas_det": B.build_det_index(cands)}
    n_c = sum(len(v) for v in cands.values())
    print(f"候选云 sas_det: {len(cands)} 帧 {n_c} 候选", flush=True)

    bank = json.loads(Path(a.bank).read_text())["labels"]
    bank = [r for r in bank if r["label"] in ("TP", "FP")]
    # (frame, idx) 精确匹配候选
    rows, y, gframe = [], [], []
    for r in bank:
        cs = cands[r["frame"]]
        c = cs[r["idx"]]
        assert iou(c["bbox"], r["bbox"]) > 0.99, f"bbox mismatch {r['frame']}#{r['idx']}"
        rows.append({"window": "sas_det", "frame": r["frame"], "bbox": c["bbox"],
                     "conf1": c.get("conf1", 0.0), "conf2": c.get("conf2", 0.0)})
        y.append(1 if r["label"] == "TP" else 0)
        gframe.append(r["frame"])
    y = np.array(y); gframe = np.array(gframe)
    print(f"训练样本 {len(y)}  TP={y.sum()}  FP={(1-y).sum()}", flush=True)

    X = B.build_all(rows, idx, dev=a.dev)
    np.save(MS / "feats_sas.npy", X)
    print(f"特征 {X.shape}", flush=True)

    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000, C=1.0))
    cv = cross_val_predict(pipe, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0),
                           method="predict_proba")[:, 1]
    auc_s = roc_auc_score(y, cv)
    r_s, w_s = work_at(y, cv, a.target_p)
    print(f"[Stratified5] AUC={auc_s:.4f}  " + (
        f"P>={a.target_p}: th={w_s[0]:.3f} P={w_s[1]*100:.1f}% R={r_s*100:.1f}%"
        if w_s else f"无 P>={a.target_p} 工作点"), flush=True)

    gcv = cross_val_predict(pipe, X, y, cv=GroupKFold(5), groups=gframe,
                            method="predict_proba")[:, 1]
    auc_g = roc_auc_score(y, gcv)
    r_g, w_g = work_at(y, gcv, a.target_p)
    print(f"[GroupByFrame5] AUC={auc_g:.4f}  " + (
        f"P>={a.target_p}: th={w_g[0]:.3f} P={w_g[1]*100:.1f}% R={r_g*100:.1f}%"
        if w_g else f"无 P>={a.target_p} 工作点"), flush=True)

    pipe.fit(X, y)
    joblib.dump({"pipe": pipe, "target_p": a.target_p,
                 "auc_stratified": float(auc_s), "auc_group_frame": float(auc_g),
                 "threshold": float(w_g[0]) if w_g else 0.5,
                 "n": int(len(y)), "feat_dim": int(X.shape[1]),
                 "labels_source": "sas_det_label_bank.json (AI-self, OVERRIDE 74.4%)",
                 "exploratory": True}, a.out)
    print(f"[out] {a.out}", flush=True)

    # 全候选打分
    all_rows, meta = [], []
    for f, cs in cands.items():
        for c in cs:
            all_rows.append({"window": "sas_det", "frame": f, "bbox": c["bbox"],
                             "conf1": c.get("conf1", 0.0), "conf2": c.get("conf2", 0.0)})
            meta.append(f)
    print(f"全候选打分 {len(all_rows)} ...", flush=True)
    Xa = B.build_all(all_rows, idx, dev=a.dev, progress=True)
    pp = pipe.predict_proba(Xa)[:, 1]
    out = {}
    k = 0
    for f, cs in cands.items():
        row = []
        for c in cs:  # 🔴 k 必须按"候选"递增（pp 与 all_rows 按候选对齐），按帧递增会整体错位
            row.append({"bbox": c["bbox"], "prob": float(pp[k]), "conf1": c.get("conf1", 0.0)})
            k += 1
        out[f] = row
    assert k == len(pp), f"打分对齐失败 k={k} != {len(pp)}"
    Path(a.scores_out).write_text(json.dumps(out))
    print(f"[out] {a.scores_out}", flush=True)


if __name__ == "__main__":
    main()
