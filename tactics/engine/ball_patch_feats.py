#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外观特征 v2：DINOv2 **patch token 中心池化**（替代全局 CLS）。

动机
----
CLS 是整幅裁切的**全局**描述子。球直径仅 ~25px：
  · 256 窗 → 球占面积 1.0%   · 512 窗 → 0.24%
⇒ CLS 主要编码「周围场景」，球的像素贡献可忽略 —— 这与实测 AUC 卡在 ~0.89
  且**裁切尺度消融无趋势**（ball_scale_ablation.py，0.83–0.886）一致。

修法
----
不用 CLS，改取 DINOv2 patch token 网格的**中心 k×k 池化**（候选框心即球心）：
  · 224 输入 @ patch 14 → 16×16=256 个 token
  · 96px 窗：球 25px → 224 输入下 ~58px → ~4.2 个 token 宽
⇒ 中心 3×3 / 5×5 池化 ≈ 直接取「球本体」的语义特征。

同时并列 CLS 作对照，验证「聚焦」是否真的带来增益。

用法:
  python engine/ball_patch_feats.py --crops 96 128 256 --ks 1 3 5 7
  输出: measure/patch_ablation.json + measure/patch_{crop}_{k}.npy
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from transformers import AutoImageProcessor, AutoModel

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
MODEL = "facebook/dinov2-base"
GRID = 16          # 224/14


def load_bank():
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    y = np.array([1 if r["label"] == "TP" else 0 for r in bank])
    w = np.array([r["window"] for r in bank])
    return bank, y, w


def crop_center(img, box, n):
    H, W = img.shape[:2]
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    X1, Y1 = int(cx - n / 2), int(cy - n / 2)
    out = np.zeros((n, n, 3), np.uint8)
    sx1, sy1 = max(0, X1), max(0, Y1)
    sx2, sy2 = min(W, X1 + n), min(H, Y1 + n)
    if sx2 > sx1 and sy2 > sy1:
        out[sy1 - Y1:sy2 - Y1, sx1 - X1:sx2 - X1] = img[sy1:sy2, sx1:sx2]
    return out


def tokens_all(bank, crop, dev):
    """返回 (CLS[N,768], PATCH[N,16,16,768])，带缓存。"""
    f_cls = MS / f"tok_cls_{crop}.npy"
    f_pat = MS / f"tok_patch_{crop}.npy"
    if f_cls.exists() and f_pat.exists():
        a, b = np.load(f_cls), np.load(f_pat)
        if len(a) == len(bank) and len(b) == len(bank):
            return a, b
    proc = AutoImageProcessor.from_pretrained(MODEL)
    model = AutoModel.from_pretrained(MODEL).to(dev).eval()
    cls_l, pat_l, t0 = [], [], time.time()
    for i, r in enumerate(bank):
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        c = crop_center(img, r["bbox"], crop)
        rgb = cv2.cvtColor(cv2.resize(c, (224, 224), interpolation=cv2.INTER_CUBIC),
                           cv2.COLOR_BGR2RGB)
        inp = proc(images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            h = model(**inp).last_hidden_state[0]
        cls_l.append(h[0].cpu().float().numpy())
        pat_l.append(h[1:1 + GRID * GRID].cpu().float().numpy().reshape(GRID, GRID, -1))
        if (i + 1) % 80 == 0:
            print(f"    tok {crop} {i+1}/{len(bank)} {time.time()-t0:.0f}s", flush=True)
    A, B = np.array(cls_l, np.float32), np.array(pat_l, np.float32)
    np.save(f_cls, A); np.save(f_pat, B)
    del model
    if dev == "mps":
        torch.mps.empty_cache()
    return A, B


def center_pool(P, k):
    c = GRID // 2
    lo = c - (k - 1) // 2
    hi = lo + k
    return P[:, lo:hi, lo:hi, :].mean(axis=(1, 2))


def auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float)
    r = np.argsort(np.argsort(s)) + 1.0
    n1, n0 = y.sum(), (1 - y).sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def cv_probs(X, y, n=5):
    skf = StratifiedKFold(n, shuffle=True, random_state=0)
    p = np.zeros(len(y))
    for tr, te in skf.split(X, y):
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000))
        m.fit(X[tr], y[tr])
        p[te] = m.predict_proba(X[te])[:, 1]
    return p


def lowo_probs(X, y, w):
    p = np.zeros(len(y))
    for ww in np.unique(w):
        te = w == ww
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000))
        m.fit(X[~te], y[~te])
        p[te] = m.predict_proba(X[te])[:, 1]
    return p


def work_point(y, p, target=0.90, step=0.005):
    best = (0.0, float("nan"), float("nan"))
    for th in np.arange(0.05, 1.0, step):
        sel = p >= th
        if sel.sum() == 0:
            continue
        if y[sel].mean() >= target and sel.mean() > best[0]:
            best = (float(sel.mean()), float(y[sel].mean()), float(th))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crops", nargs="+", type=int, default=[96, 128, 256])
    ap.add_argument("--ks", nargs="+", type=int, default=[1, 3, 5, 7])
    ap.add_argument("--dev", default="mps")
    a = ap.parse_args()
    if a.dev == "mps" and not torch.backends.mps.is_available():
        a.dev = "cpu"
    bank, y, w = load_bank()
    print(f"真值 {len(bank)} TP={y.sum()} FP={(1-y).sum()} dev={a.dev}")
    res = {}
    print(f"{'配置':<16}{'dim':>5}{'5折AUC':>9}{'LOWO':>9}{'P≥90%R':>9}{'该点P':>8}")
    for crop in a.crops:
        C, P = tokens_all(bank, crop, a.dev)
        for k in a.ks:
            X = center_pool(P, k)
            pc, pl = cv_probs(X, y), lowo_probs(X, y, w)
            rc, pv, th = work_point(y, pc)
            tag = f"c{crop}_k{k}"
            res[tag] = {"dim": int(X.shape[1]), "auc_cv": auc(y, pc), "auc_lowo": auc(y, pl),
                        "wp_recall": rc, "wp_prec": pv, "wp_th": th}
            np.save(MS / f"patch_{tag}.npy", X)
            print(f"{tag:<16}{X.shape[1]:>5}{auc(y,pc):>9.4f}{auc(y,pl):>9.4f}"
                  f"{rc*100:>8.1f}%{pv:>8.3f}", flush=True)
        X = C
        pc, pl = cv_probs(X, y), lowo_probs(X, y, w)
        rc, pv, th = work_point(y, pc)
        tag = f"c{crop}_cls"
        res[tag] = {"dim": int(X.shape[1]), "auc_cv": auc(y, pc), "auc_lowo": auc(y, pl),
                    "wp_recall": rc, "wp_prec": pv, "wp_th": th}
        print(f"{tag:<16}{X.shape[1]:>5}{auc(y,pc):>9.4f}{auc(y,pl):>9.4f}{rc*100:>8.1f}%{pv:>8.3f}",
              flush=True)
    json.dump(res, open(MS / "patch_ablation.json", "w"), ensure_ascii=False, indent=1)
    print(f"[out] {MS/'patch_ablation.json'}")


if __name__ == "__main__":
    main()
