#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球/非球验证头训练：DINOv2 CLS 特征（本体256 + 上下文512 拼接）+ LogisticRegression。

输入 labels_bank.json（真实目视标注，unc 排除）。
评估：① 5-fold CV；② leave-one-window-out（最严格跨场景泛化）。
报告 precision-recall 扫描：找 P≥90% 工作点。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
import torch

from common.nba_paths import tactics_data_file

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from transformers import AutoImageProcessor, AutoModel

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))

bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
        if r["label"] in ("TP", "FP")]
labs = np.array([r["label"] for r in bank])
wins = np.array([r["window"] for r in bank])
y = (labs == "TP").astype(int)


def extract(model_name, crop_size, dev="mps"):
    cache = MS / f"dino_feats_{model_name.split('-')[-1]}_{crop_size}.npy"
    if cache.exists():
        f = np.load(cache)
        if len(f) == len(bank):
            return f
        print(f"  [缓存失效] {cache.name} 行数 {len(f)} != 标注 {len(bank)}，重新提取")
    dev = dev if dev != "mps" or torch.backends.mps.is_available() else "cpu"
    proc = AutoImageProcessor.from_pretrained(f"facebook/dinov2-{model_name}")
    model = AutoModel.from_pretrained(f"facebook/dinov2-{model_name}").to(dev).eval()
    feats, t0 = [], time.time()
    for i, r in enumerate(bank):
        x1, y1, x2, y2 = r["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        H, W = img.shape[:2]
        h = crop_size // 2
        X1, Y1 = int(cx - h), int(cy - h)
        crop = img[max(0, Y1):min(H, Y1 + crop_size), max(0, X1):min(W, X1 + crop_size)]
        pad = np.zeros((crop_size, crop_size, 3), np.uint8)
        ch, cw = min(crop.shape[0], crop_size), min(crop.shape[1], crop_size)
        pad[:ch, :cw] = crop[:ch, :cw]
        rgb = cv2.cvtColor(cv2.resize(pad, (224, 224)), cv2.COLOR_BGR2RGB)
        inp = proc(images=rgb, return_tensors="pt").to(dev)
        with torch.no_grad():
            o = model(**inp).last_hidden_state[:, 0]   # CLS
        feats.append(o[0].cpu().float().numpy())
        if (i + 1) % 60 == 0:
            print(f"  特征 {i+1}/{len(bank)}  {time.time()-t0:.0f}s", flush=True)
    feats = np.array(feats)
    np.save(cache, feats)
    print(f"[缓存] {cache}")
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small", choices=["small", "base", "large"])
    ap.add_argument("--no-ctx", action="store_true", help="仅本体特征（消融）")
    ap.add_argument("--cpu", action="store_true", help="强制 CPU（MPS OOM 时用）")
    ap.add_argument("--ctx-size", type=int, default=512, help="上下文裁切尺寸")
    ap.add_argument("--geo", action="store_true", help="附加 conf1/conf2/框尺寸/纵坐标 特征")
    a = ap.parse_args()

    dev = "cpu" if a.cpu else "mps"
    f_body = extract(a.model, 256, dev)
    if a.no_ctx:
        feats = f_body
    else:
        f_ctx = extract(a.model, a.ctx_size, dev)
        feats = np.hstack([f_body, f_ctx])
    if a.geo:
        c1 = np.array([r["conf1"] for r in bank])[:, None]
        c2 = np.array([r["conf2"] for r in bank])[:, None]
        bw = np.array([(r["bbox"][2] - r["bbox"][0]) for r in bank])[:, None]
        bh = np.array([(r["bbox"][3] - r["bbox"][1]) for r in bank])[:, None]
        cy = np.array([(r["bbox"][1] + r["bbox"][3]) / 2 for r in bank])[:, None] / 1080.0
        g = np.hstack([c1, c2, np.log1p(bw), np.log1p(bh), cy])
        feats = np.hstack([feats, g])
    print(f"样本 {len(bank)}  TP={y.sum()} FP={(1-y).sum()}  特征维度 {feats.shape[1]}")

    def report(tag, probs):
        for th in np.arange(0.2, 0.95, 0.05):
            pred = (probs > th).astype(int)
            tp = int(((pred == 1) & (y == 1)).sum())
            fp = int(((pred == 1) & (y == 0)).sum())
            fn = int(((pred == 0) & (y == 1)).sum())
            P = tp / (tp + fp) if tp + fp else 0
            R = tp / (tp + fn) if tp + fn else 0
            if P >= 0.80 or th in (0.2, 0.5):
                print(f"  [{tag}] th={th:.2f}  P={P*100:5.1f}%  R={R*100:5.1f}%  "
                      f"TP={tp} FP={fp} 漏={fn}")

    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
    skf = StratifiedKFold(5, shuffle=True, random_state=0)
    probs5 = cross_val_predict(pipe, feats, y, cv=skf, method="predict_proba")[:, 1]
    print("\n=== 5-fold CV ===")
    report("5f", probs5)

    print("\n=== Leave-one-window-out ===")
    lowow = np.zeros(len(y))
    for w in ("w1", "w2", "w3", "w4"):
        te = wins == w
        p = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
        p.fit(feats[~te], y[~te])
        lowow[te] = p.predict_proba(feats[te])[:, 1]
    report("LOWO", lowow)

    for w in ("w1", "w2", "w3", "w4"):
        m = wins == w
        yy, pp = y[m], lowow[m]
        best = ""
        for th in np.arange(0.2, 0.95, 0.05):
            pred = (pp > th).astype(int)
            tp = int(((pred == 1) & (yy == 1)).sum())
            fp = int(((pred == 1) & (yy == 0)).sum())
            P = tp / (tp + fp) if tp + fp else 0
            if P >= 0.9 and tp > 0:
                best = f"th={th:.2f} P={P*100:.0f}%"
                break
        print(f"  {w}: n={m.sum()} TP={yy.sum()}  P≥90% 工作点: {best or '无'}")

    np.save(MS / "lowow_probs.npy", lowow)
    print("\n[out] lowow_probs.npy 落盘")


if __name__ == "__main__":
    main()
