#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球验证头 · 融合评估 v2 —— 检验本轮三项新特征是否抬升 90% 工作点。

配置：
  C0  feats_all（现行：外观TTA1536 ⊕ geo5 ⊕ 运动v1 10 ⊕ 运动v2 9 ⊕ 掩膜5 = 1565）
  C1  C0 + 球场门禁 3（above_top / in_floor / foot_in_floor）
  C2  C0 + patch中心池化 768（c96 k7）
  C3  C0 + patch768 + patch128k7 + 球场门禁3
  C4  以 patch768 替换外观块（1565 − 1536 + 768 = 797）
评估：5-fold CV、leave-one-window-out、以及 **P≥90% 工作点扫描（步长 0.005）**，
并给每个窗单独算工作点（因为 w1 是唯一无工作点的窗）。

用法:
  python engine/ball_fusion_v2.py
  python engine/ball_fusion_v2.py --configs C0 C3
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
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common.nba_paths import tactics_data_file

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
WIN_ORDER = ["w1", "w2", "w3", "w4"]


def load():
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    keys = [(r["window"], r["frame"]) for r in bank]
    pos = {k: i for i, k in enumerate(keys)}
    y = np.array([1 if r["label"] == "TP" else 0 for r in bank])
    w = np.array([r["window"] for r in bank])
    F = {"feats_all": np.load(MS / "feats_all.npy")}
    for tag, fn in (("patch96", "patch_c96_k7.npy"), ("patch128", "patch_c128_k7.npy"),
                    ("patch256", "patch_c256_k3.npy")):
        p = MS / fn
        if p.exists():
            F[tag] = np.load(p)
    # 球场门禁：按 (window, frame) 对齐
    cg = json.loads((MS / "courtgate_rows.json").read_text())
    G = np.zeros((len(bank), 3), np.float32)
    for r in cg:
        i = pos.get((r["window"], r["frame"]))
        if i is None:
            continue
        G[i] = [r["above_top"] / 100.0, r["in_floor"], r["foot_in_floor"]]
    F["court"] = G
    return bank, y, w, F


def auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float)
    if y.sum() in (0, len(y)):
        return float("nan")
    r = np.argsort(np.argsort(s)) + 1.0
    n1, n0 = y.sum(), (1 - y).sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def cv_probs(X, y, n=5, Xte=None):
    skf = StratifiedKFold(n, shuffle=True, random_state=0)
    p = np.zeros(len(y))
    for tr, te in skf.split(X, y):
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=6000, C=1.0))
        m.fit(X[tr], y[tr])
        p[te] = m.predict_proba(X[te])[:, 1]
    return p


def lowo_probs(X, y, w):
    p = np.zeros(len(y))
    for ww in np.unique(w):
        te = w == ww
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=6000, C=1.0))
        m.fit(X[~te], y[~te])
        p[te] = m.predict_proba(X[te])[:, 1]
    return p


def work_point(y, p, target=0.90, step=0.005):
    """返回 (召回率, 精度, 阈值)。召回 = 命中 TP / 全部 TP（不是被选中占比！）。"""
    best = (0.0, float("nan"), float("nan"))
    ntp = max(1, int(y.sum()))
    for th in np.arange(0.05, 1.0, step):
        sel = p >= th
        if sel.sum() == 0:
            continue
        prec = y[sel].mean()
        rec = y[sel].sum() / ntp
        if prec >= target and rec > best[0]:
            best = (float(rec), float(prec), float(th))
    return best


def build(F, cfg):
    cols = []
    app = "app" in cfg
    parts = cfg.split("+")
    if app:
        base = F["feats_all"]
        cols.append(np.concatenate([base[:, 1536:], F["patch96"]], 1))  # 非外观29 + patch768
    else:
        cols.append(F["feats_all"])
    for pt in parts:
        if pt == "patch96":
            cols.append(F["patch96"])
        elif pt == "patch128":
            cols.append(F["patch128"])
        elif pt == "patch256":
            cols.append(F["patch256"])
        elif pt == "court":
            cols.append(F["court"])
    return np.concatenate(cols, 1)


def strict_work_point(X, y, w, target=0.90, step=0.005):
    """最严格口径：留出窗的阈值由「其他窗」的嵌套 CV 标定，绝不用被留出窗的标签。

    对每个窗 w：
      ① 只用其他窗样本跑 inner 5-fold → 得到训练侧概率 → 选 P≥target 的最大召回阈值 t*
      ② 用「只训练于其他窗」的模型预测 w → 用 t* 报 w 的 precision/recall
    """
    res = {}
    for ww in np.unique(w):
        tr = w != ww
        te = w == ww
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=6000, C=1.0))
        m.fit(X[tr], y[tr])
        p_te = m.predict_proba(X[te])[:, 1]
        # inner CV on training windows only
        skf = StratifiedKFold(5, shuffle=True, random_state=0)
        p_tr = np.zeros(tr.sum())
        Xt, yt = X[tr], y[tr]
        for a, b in skf.split(Xt, yt):
            mm = make_pipeline(StandardScaler(), LogisticRegression(max_iter=6000, C=1.0))
            mm.fit(Xt[a], yt[a])
            p_tr[b] = mm.predict_proba(Xt[b])[:, 1]
        t_star = None
        for th in np.arange(0.05, 1.0, step):
            sel = p_tr >= th
            if sel.sum() == 0:
                continue
            if yt[sel].mean() >= target:
                t_star = float(th)
                break
        if t_star is None:
            res[ww] = (0.0, float("nan"), float("nan"))
            continue
        sel = p_te >= t_star
        if sel.sum() == 0:
            res[ww] = (0.0, float("nan"), t_star)
            continue
        res[ww] = (float(y[te][sel].sum() / max(1, y[te].sum())),
                   float(y[te][sel].mean()), t_star)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="+", default=None)
    a = ap.parse_args()
    bank, y, w, F = load()
    print(f"真值 {len(bank)} TP={y.sum()} FP={(1-y).sum()}  可用特征块: {sorted(F)}")
    CFG = {
        "C0": "none",
        "C1": "court",
        "C2": "patch96",
        "C3": "patch96+patch128+court",
        "C4": "app+patch96+court",
    }
    names = a.configs or list(CFG)
    cache, DETAIL = {}, {}
    for name in names:
        X = build(F, CFG[name]) if CFG[name] != "none" else F["feats_all"]
        pc, pl = cv_probs(X, y), lowo_probs(X, y, w)
        rc, pv, th = work_point(y, pc)
        print(f"\n[{name}] dim={X.shape[1]}  CV AUC={auc(y,pc):.4f}  LOWO AUC={auc(y,pl):.4f}  "
              f"全局 P≥90% → R={rc*100:.1f}%  P={pv:.3f}  th={th:.3f}")
        for tag, pp in (("CV  ", pc), ("LOWO", pl)):
            win_line = []
            for ww in WIN_ORDER:
                s = w == ww
                r2, p2, t2 = work_point(y[s], pp[s])
                win_line.append(f"{ww}:{'R%.0f@P%.0f' % (r2*100, p2*100) if r2 > 0 else '无'}")
            print(f"        {tag} 分窗 " + "  ".join(win_line) +
                  (f"   全局R={work_point(y, pp)[0]*100:.1f}%@P≥90" if tag == "LOWO" else ""))
        cache[name] = (X, pc, pl)
        sw = strict_work_point(X, y, w)
        line = "  ".join(f"{k}:{'R%.0f@P%.0f(t=%.3f)' % (v[0]*100, v[1]*100, v[2]) if v[0] > 0 else '无'}"
                         for k, v in sw.items())
        print("        STRICT（阈值跨窗标定）分窗 " + line)
        DETAIL[name] = {
            "dim": int(X.shape[1]), "auc_cv": auc(y, pc), "auc_lowo": auc(y, pl),
            "wp_cv_global": work_point(y, pc), "wp_lowo_global": work_point(y, pl),
            "wp_cv_win": {ww: work_point(y[w == ww], pc[w == ww]) for ww in WIN_ORDER},
            "wp_lowo_win": {ww: work_point(y[w == ww], pl[w == ww]) for ww in WIN_ORDER},
            "wp_strict_win": {k: list(v) for k, v in sw.items()},
        }
    json.dump(DETAIL, open(MS / "fusion_v2.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n[out] {MS/'fusion_v2.json'}")


if __name__ == "__main__":
    main()
