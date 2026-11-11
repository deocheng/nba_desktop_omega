#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微调验证头 PoC：DINOv2 末层解冻 + 分类头，留一窗评估（默认留 w1 = 最难窗）。

对比冻结特征（w1 AUC 0.849）判断微调是否值得推广。
用法: ball_finetune.py [--model small|base] [--holdout w1] [--epochs 15] [--device mps|cpu]
"""
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
import torch.nn as nn
from sklearn.metrics import roc_auc_score

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


class Head(nn.Module):
    def __init__(self, backbone, dim, unfreeze_blocks=2):
        super().__init__()
        self.bb = backbone
        for p in self.bb.parameters():
            p.requires_grad = False
        layers = self.bb.encoder.layer
        for blk in list(layers)[-unfreeze_blocks:]:
            for p in blk.parameters():
                p.requires_grad = True
        self.drop = nn.Dropout(0.3)
        self.fc = nn.Linear(dim, 1)

    def forward(self, x):
        o = self.bb(x).last_hidden_state[:, 0]
        return self.fc(self.drop(o)).squeeze(-1)


def load_crops(bank, csize, flip=False):
    imgs = []
    for r in bank:
        x1, y1, x2, y2 = r["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        H, W = img.shape[:2]
        h = csize // 2
        X1, Y1 = int(cx - h), int(cy - h)
        c = img[max(0, Y1):min(H, Y1 + csize), max(0, X1):min(W, X1 + csize)]
        pad = np.zeros((csize, csize, 3), np.uint8)
        ch, cw = min(c.shape[0], csize), min(c.shape[1], csize)
        pad[:ch, :cw] = c[:ch, :cw]
        if flip:
            pad = pad[:, ::-1]
        imgs.append(cv2.cvtColor(pad, cv2.COLOR_BGR2RGB))
    return imgs


def augment(rgb, rng):
    out = rgb
    if rng.random() < 0.5:
        out = out[:, ::-1]
    # 小范围平移+缩放
    H, W = out.shape[:2]
    s = rng.uniform(0.85, 1.0)
    nh, nw = int(H * s), int(W * s)
    oy, ox = rng.integers(0, H - nh + 1), rng.integers(0, W - nw + 1)
    out = out[oy:oy + nh, ox:ox + nw]
    out = cv2.resize(out, (224, 224))
    # 亮度/对比微扰
    a = rng.uniform(0.85, 1.15)
    b = rng.uniform(-18, 18)
    out = np.clip(out.astype(np.float32) * a + b, 0, 255).astype(np.uint8)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small", choices=["small", "base"])
    ap.add_argument("--holdout", default="w1")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--csize", type=int, default=256)
    ap.add_argument("--unfreeze", type=int, default=2)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    from transformers import AutoModel
    torch.manual_seed(a.seed); np.random.seed(a.seed)
    bb = AutoModel.from_pretrained(f"facebook/dinov2-{a.model}")
    dim = bb.config.hidden_size
    net = Head(bb, dim, a.unfreeze).to(dev)

    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    te = [r for r in bank if r["window"] == a.holdout]
    tr = [r for r in bank if r["window"] != a.holdout]
    ytr = np.array([r["label"] == "TP" for r in tr]).astype(np.float32)
    yte = np.array([r["label"] == "TP" for r in te]).astype(int)
    print(f"留出 {a.holdout}: 训练 {len(tr)} (TP{int(ytr.sum())}) / 测试 {len(te)} (TP{int(yte.sum())}) dev={dev} 末层解冻 {a.unfreeze}")

    tr_imgs = load_crops(tr, a.csize)
    te_imgs = load_crops(te, a.csize)
    rng = np.random.default_rng(a.seed)

    params = [p for p in net.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.01)
    lossf = nn.BCEWithLogitsLoss()
    n = len(tr)
    for ep in range(a.epochs):
        net.train()
        idx = rng.permutation(n)
        tot, cnt = 0.0, 0
        t0 = time.time()
        for i in range(0, n, a.bs):
            sel = idx[i:i + a.bs]
            batch = np.stack([augment(tr_imgs[j], rng) for j in sel])
            x = torch.tensor(batch, dtype=torch.float32).permute(0, 3, 1, 2).to(dev)
            x = (x / 255.0 - 0.5) / 0.5
            y = torch.tensor(ytr[sel], dtype=torch.float32).to(dev)
            opt.zero_grad()
            out = net(x)
            loss = lossf(out, y)
            loss.backward()
            opt.step()
            tot += float(loss) * len(sel); cnt += len(sel)
        # 评估
        net.eval()
        pr = []
        with torch.no_grad():
            for i in range(0, len(te_imgs), a.bs):
                batch = np.stack(te_imgs[i:i + a.bs])
                x = torch.tensor(batch, dtype=torch.float32).permute(0, 3, 1, 2).to(dev)
                x = (x / 255.0 - 0.5) / 0.5
                pr.append(torch.sigmoid(net(x)).cpu().numpy())
        p = np.concatenate(pr)
        auc = roc_auc_score(yte, p)
        print(f"  ep{ep+1:02d} loss={tot/cnt:.4f}  {a.holdout} AUC={auc:.4f}  {time.time()-t0:.0f}s", flush=True)

    # 冻结特征对照
    try:
        f = np.hstack([np.load(MS / f"dino_feats_{a.model}_{s}.npy") for s in (256, 512)])
        bi = [r for r in bank]
        m = np.array([r["window"] == a.holdout for r in bi])
        mtr = ~m
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
        pipe.fit(f[mtr], np.array([r["label"] == "TP" for r in bi])[mtr].astype(int))
        pf = pipe.predict_proba(f[m])[:, 1]
        print(f"[对照] 冻结特征 {a.holdout} AUC={roc_auc_score(yte, pf):.4f}")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
