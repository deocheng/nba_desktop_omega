#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外观特征「裁切尺度」消融 —— 检验「DINOv2 是否真的看清了球」。

假设（待验证）
--------------
现有验证头用固定 256px 本体窗 + 512px 上下文窗。球直径仅 ~25px：
  · 256 窗里球占面积 (25/256)² ≈ 1.0%；224 输入下球 ≈ 22px
  · 512 窗里球占面积 (25/512)² ≈ 0.24%；224 输入下球 ≈ 11px
⇒ 若 DINOv2 主要编码的是「周围场景」而非「球本体」，则 AUC 0.85–0.90 是
  **裁切尺度造成的天花板**，而非特征/头的问题。

做法
----
对同一批真值（labels_bank.json，unc 排除），提取多种裁切规格的 DINOv2-base CLS：
  · fixed_{N}  ：以框心为中心、固定 N×N 窗（N ∈ 64,96,128,192,256）
  · rel_{k}    ：框的 k 倍外扩窗，缩放至 224（球按自身检出尺寸归一化）
评估：5-fold CV AUC + leave-one-window-out AUC，并报 P≥90% 时的最大召回。

用法:
  python engine/ball_scale_ablation.py                       # 全部规格
  python engine/ball_scale_ablation.py --specs fixed_96 rel_2.5
  python engine/ball_scale_ablation.py --dev cpu
  输出: measure/scale_ablation.json  + 控制台表
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

SPECS = ["fixed_64", "fixed_96", "fixed_128", "fixed_192", "fixed_256",
         "rel_1.6", "rel_2.5", "rel_4.0"]


def load_bank():
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    y = np.array([1 if r["label"] == "TP" else 0 for r in bank])
    w = np.array([r["window"] for r in bank])
    return bank, y, w


def crop_of(img, box, spec):
    H, W = img.shape[:2]
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    bw, bh = x2 - x1, y2 - y1
    if spec.startswith("fixed_"):
        n = int(spec.split("_")[1])
        X1, Y1 = int(cx - n / 2), int(cy - n / 2)
        nb = n
    else:
        k = float(spec.split("_")[1])
        s = max(bw, bh) * k
        X1, Y1 = int(cx - s / 2), int(cy - s / 2)
        nb = int(round(s))
    out = np.zeros((nb, nb, 3), np.uint8)
    sx1, sy1 = max(0, X1), max(0, Y1)
    sx2, sy2 = min(W, X1 + nb), min(H, Y1 + nb)
    if sx2 > sx1 and sy2 > sy1:
        out[sy1 - Y1:sy2 - Y1, sx1 - X1:sx2 - X1] = img[sy1:sy2, sx1:sx2]
    return out


def extract(bank, spec, dev):
    cache = MS / f"ablate_{spec}.npy"
    if cache.exists():
        f = np.load(cache)
        if len(f) == len(bank):
            return f
    proc = AutoImageProcessor.from_pretrained(MODEL)
    model = AutoModel.from_pretrained(MODEL).to(dev).eval()
    feats, t0 = [], time.time()
    for i, r in enumerate(bank):
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        c = crop_of(img, r["bbox"], spec)
        rgb = cv2.cvtColor(cv2.resize(c, (224, 224), interpolation=cv2.INTER_CUBIC),
                           cv2.COLOR_BGR2RGB)
        inp = proc(images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            feats.append(model(**inp).last_hidden_state[:, 0][0].cpu().float().numpy())
        if (i + 1) % 80 == 0:
            print(f"    {spec} {i+1}/{len(bank)} {time.time()-t0:.0f}s", flush=True)
    f = np.array(feats, np.float32)
    np.save(cache, f)
    del model
    if dev == "mps":
        torch.mps.empty_cache()
    return f


def auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float)
    r = np.argsort(np.argsort(s)) + 1.0
    n1, n0 = y.sum(), (1 - y).sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def cv_probs(X, y, n=5):
    skf = StratifiedKFold(n, shuffle=True, random_state=0)
    p = np.zeros(len(y))
    for tr, te in skf.split(X, y):
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000, C=1.0))
        m.fit(X[tr], y[tr])
        p[te] = m.predict_proba(X[te])[:, 1]
    return p


def lowo_probs(X, y, w):
    p = np.zeros(len(y))
    for ww in np.unique(w):
        te = w == ww
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000, C=1.0))
        m.fit(X[~te], y[~te])
        p[te] = m.predict_proba(X[te])[:, 1]
    return p


def work_point(y, p, target=0.90, step=0.005):
    best = (0.0, None)
    for th in np.arange(0.05, 1.0, step):
        sel = p >= th
        if sel.sum() == 0:
            continue
        pr = y[sel].mean()
        if pr >= target and sel.mean() > best[0]:
            best = (float(sel.mean()), float(pr), float(th))
    return best if best[1] is not None else (0.0, float("nan"), float("nan"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", nargs="+", default=SPECS)
    ap.add_argument("--dev", default="mps")
    a = ap.parse_args()
    if a.dev == "mps" and not torch.backends.mps.is_available():
        a.dev = "cpu"
    bank, y, w = load_bank()
    print(f"真值 {len(bank)}  TP={y.sum()}  FP={(1-y).sum()}  dev={a.dev}")
    res = {}
    print(f"{'规格':<12} {'5折AUC':>8} {'LOWO AUC':>9} {'P≥90%召回':>10} {'该点P':>7} {'阈值':>7}")
    for spec in a.specs:
        X = extract(bank, spec, a.dev)
        pc = cv_probs(X, y)
        pl = lowo_probs(X, y, w)
        rc, prc, th = work_point(y, pc)
        res[spec] = {"dim": int(X.shape[1]), "auc_cv": auc(y, pc), "auc_lowo": auc(y, pl),
                     "wp_recall": rc, "wp_prec": prc, "wp_th": th}
        print(f"{spec:<12} {auc(y,pc):8.4f} {auc(y,pl):9.4f} {rc*100:9.1f}% "
              f"{prc:7.3f} {th:7.3f}", flush=True)
    # 拼接：最佳紧凑窗 + 最佳相对框
    json.dump(res, open(MS / "scale_ablation.json", "w"), ensure_ascii=False, indent=1)
    print(f"[out] {MS/'scale_ablation.json'}")


if __name__ == "__main__":
    main()
