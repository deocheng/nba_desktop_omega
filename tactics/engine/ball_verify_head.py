#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球验证头：训练（外观+几何+多帧运动+掩膜 → 逻辑回归）与推理（过滤检测 JSON）。

特征由 `ball_feats_all.build_all()` 统一产出（训练与推理同源，1565 维）：
  外观 base256⊕512 CLS(TTA) ⊕ 几何 ⊕ 运动v1 ⊕ 运动v2 ⊕ 掩膜几何
运动/掩膜特征在推理时**从输入 JSON 自身的逐帧候选 + 磁盘帧现算**，无需额外输入。

用法:
  ball_verify_head.py train  [--target-p 0.90] [--out measure/ball_head.joblib]
  ball_verify_head.py apply  <in.json> <out.json> [--head ...]
"""
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ball_feats_all as B  # noqa: E402

MS = B.MS


def cmd_train(a):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    y = np.array([r["label"] == "TP" for r in bank]).astype(int)
    wins = np.array([r["window"] for r in bank])
    X = B.build_all(bank, B.load_det_index(), dev=a.device)
    np.save(MS / "feats_all.npy", X)
    print(f"样本 {len(y)} TP={y.sum()} FP={(1-y).sum()} 特征 {X.shape[1]}")

    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=1.0))
    cv = cross_val_predict(pipe, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0),
                           method="predict_proba")[:, 1]
    best = (0.0, None)
    npos = int(y.sum())
    for th in np.arange(0.05, 0.995, 0.005):
        pred = cv > th
        tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
        if tp + fp == 0:
            continue
        P = tp / (tp + fp)
        if P >= a.target_p and tp / npos > best[0]:
            best = (tp / npos, (float(th), float(P), tp, fp))
    th, P, tp, fp = best[1] if best[1] else (0.5, 0.0, 0, 0)
    print(f"5-fold 目标 P>={a.target_p}: th={th:.3f} P={P*100:.1f}% R={best[0]*100:.1f}% (TP{tp}/FP{fp})")
    print(f"5-fold 全局 AUC={roc_auc_score(y, cv):.4f}")

    lowo = np.zeros(len(y))
    for w in ("w1", "w2", "w3", "w4"):
        te = wins == w
        q = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=1.0))
        q.fit(X[~te], y[~te])
        lowo[te] = q.predict_proba(X[te])[:, 1]
    print(f"LOWO 全局 AUC={roc_auc_score(y, lowo):.4f}")
    for w in ("w1", "w2", "w3", "w4"):
        m = wins == w
        yy, pp = y[m], lowo[m]
        b2 = (0.0, None)
        for tt in np.arange(0.05, 0.995, 0.005):
            pred = pp > tt
            t2 = int((pred & (yy == 1)).sum()); f2 = int((pred & (yy == 0)).sum())
            if t2 + f2 == 0:
                continue
            P2 = t2 / (t2 + f2)
            if P2 >= a.target_p and t2 / int((yy == 1).sum()) > b2[0]:
                b2 = (t2 / int((yy == 1).sum()), (float(tt), P2, t2, f2))
        s = (f"R={b2[0]*100:.1f}% @ P={b2[1][1]*100:.1f}% (th={b2[1][0]:.3f})"
             if b2[1] else "无 P≥90% 工作点")
        print(f"  {w}: AUC={roc_auc_score(y[m], pp):.4f}  {s}")

    pipe.fit(X, y)
    joblib.dump({"pipe": pipe, "threshold": float(th), "target_p": a.target_p,
                 "cv_precision": float(P), "cv_recall": float(best[0]),
                 "lowo_auc": float(roc_auc_score(y, lowo)),
                 "cv_auc": float(roc_auc_score(y, cv)),
                 "n": int(len(y)), "feat_dim": int(X.shape[1]),
                 "features": "appearance(base256+512,TTA)+geo+motion_v1+motion_v2+mask"}, a.out)
    print(f"[out] {a.out} (阈值 {th:.3f})")


def cmd_apply(a):
    head = joblib.load(a.head)
    det = json.loads(Path(a.injson).read_text())       # {window: {frame: [cands]}}
    rows = []
    for w, fr in det.items():
        for f, cands in fr.items():
            for c in cands:
                rows.append({"window": w, "frame": f, "bbox": c["bbox"],
                             "conf1": c.get("conf1", 0.0), "conf2": c.get("conf2", 0.0)})
    if not rows:
        print("无候选"); return
    # 🔴 多帧运动特征依赖「候选云」。训练时用的是 action_work/{w}_ball_verified.json
    #    （即 load_det_index 的默认）。若推理时改用另一套候选云（如全候选 4748），
    #    运动块会出现**分布漂移**，头给出的分数不再与训练口径可比。
    #    ⇒ 默认强制用**与训练同一套**索引；要用别的需显式 --index-suffix（并自行承担漂移）。
    if a.index_suffix == "input":
        idx = {w: B.build_det_index(fr) for w, fr in det.items()}
        src = "输入 JSON 自身（⚠️ 与训练口径不同，运动块会漂移）"
    else:
        idx = {w: B.build_det_index(json.loads(
            (B.AW / f"{w}{a.index_suffix}.json").read_text()))
            for w in det.keys()}
        src = f"action_work/*{a.index_suffix}.json"
    print(f"候选 {len(rows)}；运动索引来源：{src}")
    X = B.build_all(rows, idx, dev=a.device)
    p = head["pipe"].predict_proba(X)[:, 1]
    th = head["threshold"]
    out = {}
    for r, pp in zip(rows, p):
        if pp <= th:
            continue
        out.setdefault(r["window"], {}).setdefault(r["frame"], []).append(
            {"bbox": r["bbox"], "prob": float(pp), "conf1": r["conf1"], "conf2": r["conf2"]})
    Path(a.outjson).write_text(json.dumps(out))
    n_out = sum(len(v) for fr in out.values() for v in fr.values())
    print(f"候选 {len(rows)} -> 通过 {n_out}（阈值 {th:.3f}，目标 P≥{head['target_p']}，"
          f"训练口径 LOWO AUC={head.get('lowo_auc', float('nan')):.4f}）")
    print(f"[out] {a.outjson}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--target-p", type=float, default=0.90)
    t.add_argument("--out", default=str(MS / "ball_head.joblib"))
    t.add_argument("--device", default="cpu")
    t.set_defaults(func=cmd_train)
    p = sub.add_parser("apply")
    p.add_argument("injson"); p.add_argument("outjson")
    p.add_argument("--head", default=str(MS / "ball_head.joblib"))
    p.add_argument("--device", default="cpu")
    p.add_argument("--index-suffix", default="_ball_verified",
                   help="多帧运动特征所用的候选云后缀，默认与训练一致（load_det_index 的默认）。"
                        "传 'input' 表示用输入 JSON 自身。")
    p.set_defaults(func=cmd_apply)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
