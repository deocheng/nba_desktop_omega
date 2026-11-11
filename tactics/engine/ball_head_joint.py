#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ball_head_joint.py — 多片段联合训练球验证头 + 留一片交叉验证（LOCO）。

第 2 步（用户四步计划）产物。与 ball_head_sas.py 同配方（build_all 特征 + StandardScaler/
LogisticRegression），差异：
  1) 多片候选云 + 多片人工 bank 联合训练（每片各建 det_index，window 键隔离）；
  2) 🔴 **LOCO 留一片交叉验证**：train(sas_det)→test(sas_lal) 与 train(sas_lal)→test(sas_det)，
     直接量化「跨转播泛化」，是第 2 步能否入账的核心证据；
  3) GroupKFold 按 (clip,frame) 分组（同帧候选共享上下文，随机折泄漏）；
  4) 训练后对每片全候选打分落盘。

用法:
  python engine/ball_head_joint.py \
      --spec sas_det=action_work/validate/sas_det_cands.json:action_work/validate/sas_det_label_bank_human.json \
      --spec sas_lal=action_work/validate/sas_lal_cands.json:action_work/validate/sas_lal_label_bank_human.json \
      --out reports/milestone_05/measure/ball_head_joint.joblib \
      --scores-prefix action_work/validate/ball_cand_scores
产出: <scores-prefix>_<clip>_joint.json（每片）；控制台打印 LOCO/合并 CV 指标。
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
    ap.add_argument("--spec", action="append", required=True,
                    help="clip=cands.json:bank.json（可多组）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scores-prefix", default=str(AW / "validate" / "ball_cand_scores"))
    ap.add_argument("--target-p", type=float, default=0.80)
    ap.add_argument("--dev", default="cpu")
    a = ap.parse_args()

    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    cands, banks, clips = {}, {}, []
    for spec in a.spec:
        clip, rest = spec.split("=", 1)
        cp, bp = rest.split(":")
        cands[clip] = json.loads(Path(cp).read_text())[clip]
        banks[clip] = [r for r in json.loads(Path(bp).read_text())["labels"]
                       if r["label"] in ("TP", "FP")]
        clips.append(clip)
        print(f"[{clip}] 候选 {sum(len(v) for v in cands[clip].values())}  "
              f"样本 {len(banks[clip])}  TP={sum(1 for r in banks[clip] if r['label']=='TP')}")

    idx = {c: B.build_det_index(cands[c]) for c in clips}

    rows, y, g = [], [], []
    per_clip_idx = {}
    for c in clips:
        s0 = len(rows)
        for r in banks[c]:
            cs = cands[c][r["frame"]]
            cand = cs[r["idx"]]
            assert iou(cand["bbox"], r["bbox"]) > 0.99, f"bbox mismatch {c} {r['frame']}#{r['idx']}"
            rows.append({"window": c, "frame": r["frame"], "bbox": cand["bbox"],
                         "conf1": cand.get("conf1", 0.0), "conf2": cand.get("conf2", 0.0)})
            y.append(1 if r["label"] == "TP" else 0)
            g.append(f"{c}|{r['frame']}")
        per_clip_idx[c] = (s0, len(rows))
    y = np.array(y); g = np.array(g)
    print(f"训练样本 {len(y)}  TP={y.sum()}  FP={(1-y).sum()}", flush=True)

    X = B.build_all(rows, idx, dev=a.dev, progress=True)
    print(f"特征 {X.shape}", flush=True)
    np.save(MS / "feats_joint.npy", X)

    def mk():
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000, C=1.0))

    # ---- 合并 CV ----
    cv = cross_val_predict(mk(), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0),
                           method="predict_proba")[:, 1]
    auc_s = roc_auc_score(y, cv)
    r_s, w_s = work_at(y, cv, a.target_p)
    print(f"[合并 Stratified5] AUC={auc_s:.4f}  " + (
        f"P>={a.target_p}: th={w_s[0]:.3f} P={w_s[1]*100:.1f}% R={r_s*100:.1f}%" if w_s
        else f"无 P>={a.target_p} 工作点"), flush=True)
    gcv = cross_val_predict(mk(), X, y, cv=GroupKFold(5), groups=g,
                            method="predict_proba")[:, 1]
    auc_g = roc_auc_score(y, gcv)
    r_g, w_g = work_at(y, gcv, a.target_p)
    print(f"[合并 GroupByFrame5] AUC={auc_g:.4f}  " + (
        f"P>={a.target_p}: th={w_g[0]:.3f} P={w_g[1]*100:.1f}% R={r_g*100:.1f}%" if w_g
        else f"无 P>={a.target_p} 工作点"), flush=True)

    # ---- 分片 in-sample AUC（合并模型在每片上的表现）----
    pipe = mk(); pipe.fit(X, y)
    for c in clips:
        s, e = per_clip_idx[c]
        p = pipe.predict_proba(X[s:e])[:, 1]
        print(f"  [{c}] in-sample AUC={roc_auc_score(y[s:e], p):.4f} "
              f"(n={e-s}, TP={int(y[s:e].sum())})", flush=True)

    # ---- 🔴 LOCO 留一片交叉验证（跨转播泛化的直接证据）----
    loco = {}
    for c in clips:
        tr = np.array([i for i in range(len(y)) if not g[i].startswith(c + "|")])
        te = np.array([i for i in range(len(y)) if g[i].startswith(c + "|")])
        if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            continue
        m = mk(); m.fit(X[tr], y[tr])
        p = m.predict_proba(X[te])[:, 1]
        auc = roc_auc_score(y[te], p)
        r, w = work_at(y[te], p, a.target_p)
        loco[c] = auc
        print(f"[LOCO] 训练排除{c} → 测试{c}: AUC={auc:.4f}  " + (
            f"P>={a.target_p} th={w[0]:.3f} P={w[1]*100:.1f}% R={r*100:.1f}%" if w
            else f"无 P>={a.target_p} 工作点"), flush=True)

    joblib.dump({"pipe": pipe, "target_p": a.target_p, "clips": clips,
                 "auc_stratified": float(auc_s), "auc_group_frame": float(auc_g),
                 "loco_auc": {k: float(v) for k, v in loco.items()},
                 "threshold": float(w_g[0]) if w_g else 0.5,
                 "n": int(len(y)), "feat_dim": int(X.shape[1]),
                 "labels_source": "human banks: " + ",".join(clips)}, a.out)
    print(f"[out] {a.out}", flush=True)

    # ---- 每片全候选打分 ----
    for c in clips:
        all_rows, meta = [], []
        for f, cs in cands[c].items():
            for cand in cs:
                all_rows.append({"window": c, "frame": f, "bbox": cand["bbox"],
                                 "conf1": cand.get("conf1", 0.0), "conf2": cand.get("conf2", 0.0)})
                meta.append(f)
        print(f"[{c}] 全候选打分 {len(all_rows)} ...", flush=True)
        Xa = B.build_all(all_rows, idx, dev=a.dev, progress=False)
        pp = pipe.predict_proba(Xa)[:, 1]
        out, k = {}, 0
        for f, cs in cands[c].items():
            row = []
            for cand in cs:
                row.append({"bbox": cand["bbox"], "prob": float(pp[k]),
                            "conf1": cand.get("conf1", 0.0)})
                k += 1
            out[f] = row
        assert k == len(pp), f"[{c}] 打分对齐失败 k={k} != {len(pp)}"
        p = Path(f"{a.scores_prefix}_{c}_joint.json")
        p.write_text(json.dumps({c: out}))
        print(f"[out] {p}", flush=True)


if __name__ == "__main__":
    main()
