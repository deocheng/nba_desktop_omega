#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证头 v2 —— 运动上下文改用**全候选云**（4748），并在同一口径下做 A/B。

为什么要 v2（而不是直接套 v1 的头）
----------------------------------
`ball_feats_all.build_all()` 的「多帧运动」块依赖**候选云** `det_index`。
v1 训练时用的是 `{w}_ball_verified.json`（769 个候选，即"conf 最高的那 1–3 个/帧"）。
若推理时改用全候选云（4748）却不重训，运动块会有分布漂移；
若为了"一致"而继续用 769 的旧云去给非 top-1 候选打分，那些候选在旧云里没有邻居，
会被**系统性罚分**，等于把 A/B 做偏向旧方法。

⇒ 唯一干净的做法：**训练与推理都用同一套（全候选）云**，重训一次头。这也顺便回答一个真问题：
   把"候选云"从 769 扩到 4748，头的 AUC 会不会变好？

用法:
  python engine/ball_head_v2.py --cands action_work/ball_cands_all.json \
      --out reports/milestone_05/measure/ball_head_v2.joblib
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ball_feats_all as B  # noqa: E402
from ball_allcand_eval import cell  # noqa: E402

ROOT = Path(str(tactics_data_file("")))
AW, MS = ROOT / "action_work", ROOT / "reports/milestone_05/measure"
WINS = ("w1", "w2", "w3", "w4")


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def work_at(y, p, target):
    """在 CV 分数上找满足 P>=target 的最优召回工作点。"""
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
    ap.add_argument("--cands", default=str(AW / "ball_cands_all.json"))
    ap.add_argument("--out", default=str(MS / "ball_head_v2.joblib"))
    ap.add_argument("--target-p", type=float, default=0.90)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--ab-out", default=str(MS / "allcand_ab"))
    a = ap.parse_args()

    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    cands = json.loads(Path(a.cands).read_text())
    idx = {w: B.build_det_index(cands[w]) for w in WINS}
    print("全候选云：", {w: sum(len(v) for v in cands[w].values()) for w in WINS})

    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    y = np.array([r["label"] == "TP" for r in bank]).astype(int)
    wins = np.array([r["window"] for r in bank])
    print(f"训练样本 {len(y)}  TP={y.sum()} FP={(1-y).sum()}")
    X = B.build_all(bank, idx, dev=a.device)
    np.save(MS / "feats_all_v2.npy", X)
    print(f"特征 {X.shape}")

    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000, C=1.0))
    cv = cross_val_predict(pipe, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0),
                           method="predict_proba")[:, 1]
    auc_cv = roc_auc_score(y, cv)
    r_cv, w_cv = work_at(y, cv, a.target_p)
    print(f"[v2] 5折 AUC={auc_cv:.4f}  P>={a.target_p}: th={w_cv[0]:.3f} "
          f"P={w_cv[1]*100:.1f}% R={r_cv*100:.1f}% (TP{w_cv[2]}/FP{w_cv[3]})"
          if w_cv else f"[v2] 5折 AUC={auc_cv:.4f}  无 P>={a.target_p} 工作点")

    lowo = np.zeros(len(y))
    for w in WINS:
        te = wins == w
        q = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000, C=1.0))
        q.fit(X[~te], y[~te])
        lowo[te] = q.predict_proba(X[te])[:, 1]
    auc_lowo = roc_auc_score(y, lowo)
    print(f"[v2] LOWO AUC={auc_lowo:.4f}")
    per = {}
    for w in WINS:
        m = wins == w
        rr, ww = work_at(y[m], lowo[m], a.target_p)
        per[w] = {"auc": float(roc_auc_score(y[m], lowo[m])), "R": rr,
                  "th": ww[0] if ww else None, "P": ww[1] if ww else None}
        print(f"   {w}: AUC={per[w]['auc']:.4f}  "
              + (f"R={rr*100:.1f}% @ P={ww[1]*100:.1f}% (th={ww[0]:.3f})" if ww
                 else "无 P≥90% 工作点"))

    pipe.fit(X, y)
    joblib.dump({"pipe": pipe, "target_p": a.target_p,
                 "cv_auc": float(auc_cv), "lowo_auc": float(auc_lowo),
                 "threshold": float(w_cv[0]) if w_cv else 0.5,
                 "index_suffix": "ALL_CANDIDATES",
                 "n": int(len(y)), "feat_dim": int(X.shape[1]), "per_window": per},
                a.out)
    print(f"[out] {a.out}")

    # ---------------- 同一口径下应用 + A/B（**留窗口外**打分，杜绝 in-sample 乐观） ----------------
    # 🔴 关键方法论：324 条人工标签既是训练集又是评估集。若用**全量重训**的头去给这些帧打分，
    #    头在自家训练样本上必然"表现好"（尤其它会记住哪些框是 FP）⇒ A/B 会假性大涨。
    #    故 A/B 一律用 **LOWO 分数**：窗口 w 的每个候选，都用"没看过 w"的那个模型打分。
    #    这样 (a) 标签行是 out-of-fold，(b) 同帧内所有候选共用同一个打分函数，argmax 可比。
    lowo_models = {}
    for w in WINS:
        te = wins == w
        q = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000, C=1.0))
        q.fit(X[~te], y[~te])
        lowo_models[w] = q

    rows, meta = [], []
    for w in WINS:
        for f, cs in cands[w].items():
            for c in cs:
                rows.append({"window": w, "frame": f, "bbox": c["bbox"],
                             "conf1": c.get("conf1", 0.0), "conf2": c.get("conf2", 0.0)})
                meta.append((w, f))
    print(f"全候选打分：{len(rows)} 个（逐窗口用 LOWO 模型）")
    Xa = B.build_all(rows, idx, dev=a.device)
    out = {w: {} for w in WINS}
    for w in WINS:
        sel = np.array([m[0] == w for m in meta])
        if not sel.any():
            continue
        pp = lowo_models[w].predict_proba(Xa[sel])[:, 1]
        k = 0
        for f, cs in cands[w].items():
            lst = []
            for c in cs:
                lst.append({"bbox": c["bbox"], "prob": float(pp[k])})
                k += 1
            out[w][f] = lst
    Path(AW / "ball_cand_scores_v2.json").write_text(json.dumps(out))
    print(f"[out] {AW / 'ball_cand_scores_v2.json'}")

    change, same = [], {"TP": 0, "FP": 0}
    for r in bank:
        cs = out[r["window"]][r["frame"]]
        top = max(cs, key=lambda c: c["prob"]) if cs else None
        if top is not None and iou(top["bbox"], r["bbox"]) >= 0.5:
            same[r["label"]] += 1
        else:
            change.append(r)
    n = len(bank)
    ntp = int(y.sum())
    print(f"\n--- 全候选重排 A/B（LOWO 打分，{n} 帧）---")
    print(f"  新旧 top-1 一致 {same['TP']+same['FP']}（原TP {same['TP']} / 原FP {same['FP']}）"
          f"   变化 {len(change)}（其中原TP {sum(1 for r in change if r['label']=='TP')}）")
    print(f"  旧口径（conf top-1）基础精度 {ntp/n*100:.1f}%")
    print(f"  新口径区间 [{same['TP']/n*100:.1f}%, {(same['TP']+len(change))/n*100:.1f}%]")
    json.dump({"n": n, "same_TP": same["TP"], "same_FP": same["FP"],
               "changed": len(change),
               "changed_is_oldTP": sum(1 for r in change if r["label"] == "TP"),
               "oldP": ntp / n * 100, "lo": same["TP"] / n * 100,
               "hi": (same["TP"] + len(change)) / n * 100,
               "change_list": [{"window": r["window"], "frame": r["frame"],
                                "label": r["label"]} for r in change],
               "auc_cv": float(auc_cv), "auc_lowo": float(auc_lowo),
               "per_window": per},
              open(MS / "allcand_ab.json", "w"), ensure_ascii=False, indent=1)
    print(f"[out] {MS / 'allcand_ab.json'}")

    # 接触表：**分层抽样**（原FP 组抽 48、原TP 组全取），避免 178 格摊薄分辨率
    rng = np.random.default_rng(0)
    ch_fp = [r for r in change if r["label"] == "FP"]
    ch_tp = [r for r in change if r["label"] == "TP"]
    samp = list(rng.choice(ch_fp, min(48, len(ch_fp)), replace=False)) + ch_tp if ch_fp \
        else ch_tp
    tiles = []
    for r in samp:
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        if img is None:
            continue
        c1 = cell(img, r["bbox"], 80, 240, (0, 220, 255), "OLD:" + r["label"])
        cs = out[r["window"]][r["frame"]]
        if cs:
            top = max(cs, key=lambda c: c["prob"])
            c2 = cell(img, top["bbox"], 80, 240, (0, 0, 255), f"NEW p={top['prob']:.2f}")
        else:
            c2 = np.zeros_like(c1)
        tiles.append(np.concatenate([c1, c2], axis=0))
    ncol, per_sheet = 4, 12
    for si in range(0, max(1, (len(tiles) + per_sheet - 1) // per_sheet)):
        ch = tiles[si*per_sheet:(si+1)*per_sheet]
        if not ch:
            continue
        rr = []
        for i in range(0, len(ch), ncol):
            row = ch[i:i+ncol]
            while len(row) < ncol:
                row.append(np.zeros_like(ch[0]))
            rr.append(np.concatenate(row, axis=1))
        cv2.imwrite(f"{a.ab_out}_sheet{si}.jpg", np.concatenate(rr, axis=0),
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"[out] {a.ab_out}_sheet{si}.jpg  格数 {len(ch)}")
    print(f"  抽样：原FP 变化集抽 {min(48, len(ch_fp))}/{len(ch_fp)}，原TP 变化集全取 {len(ch_tp)}")


if __name__ == "__main__":
    main()
