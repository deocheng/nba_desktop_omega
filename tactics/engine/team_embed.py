#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""队色识别 —— 学习式外观嵌入 + 聚类（取代全部手工颜色特征）。

为什么放弃手工特征
------------------
在 6 个目视真值框上实测过 6 种组合，**全部不分离**：
  · ROI 定义：框内百分比矩形 / 肩髋关键点多边形
  · 特征：中位 RGB | 低饱和像素中位 V | 高亮低饱和占比 | 6×6×6 颜色直方图卡方
同队距离与跨队距离完全重叠（例：直方图卡方 同队 0.2926 vs 跨队 0.3170）。
根因：躯干多边形常常只有 200–2500 px、角度倾斜、白球衣在阴影下变暗、
黑球衣带银/红装饰 —— 单一统计量无法表达"有没有一个成片的白色区域"。

改用：DINOv2-small（22M，HF 镜像可得）对**遮掉背景的躯干裁剪**取 CLS 嵌入，
再对嵌入做 k-means。这是队伍识别在文献里的标准做法。

🔴 验证纪律：**不用 6 个手工标签验证**（那批标签自身可疑，见上）。
验证 = 全窗嵌入聚类 + 多帧目视验收 + 跨帧一致性。

用法: team_embed.py <window> [--stride 3] [--k 2] [--render outdir]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
AW = Path(str(tactics_data_file("action_work")))
MODEL = "facebook/dinov2-small"
KPT = None


def match_person(persons, box, tol=1500.0):
    best, bd = None, 1e18
    for p in persons:
        d = sum((a - b) ** 2 for a, b in zip(p["box"], box))
        if d < bd:
            bd, best = d, p
    return best if bd < tol else None


def torso_crop(img, kpt, pad=0.15, fill=114):
    idx = [5, 6, 12, 11]  # l_sh, r_sh, r_hip, l_hip
    if min(kpt[i][2] for i in idx) < 0.30:
        return None
    poly = np.array([[kpt[i][0], kpt[i][1]] for i in idx], np.float32)
    x1, y1 = poly[:, 0].min(), poly[:, 1].min()
    x2, y2 = poly[:, 0].max(), poly[:, 1].max()
    pw, ph = max(1.0, x2 - x1), max(1.0, y2 - y1)
    x1, x2 = x1 - pad * pw, x2 + pad * pw
    y1, y2 = y1 - pad * ph, y2 + pad * ph
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(img.shape[1] - 1, int(x2)), min(img.shape[0] - 1, int(y2))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    crop = img[y1:y2, x1:x2].copy()
    m = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillPoly(m, [(poly - np.array([x1, y1])).astype(np.int32)], 255)
    crop[m == 0] = fill
    return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)


def embed_window(win, stride, batch=64):
    import torch
    from transformers import AutoImageProcessor, AutoModel

    proc = AutoImageProcessor.from_pretrained(MODEL)
    mod = AutoModel.from_pretrained(MODEL).eval()
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    mod = mod.to(dev)

    tracks = json.loads((AW / f"{win}_poss" / "ball_tracks.json").read_text())
    pk = json.loads((AW / win / "pose_kpt_cache.json").read_text())
    names = pk["meta"]["kpt_names"]
    rows, buf, meta = [], [], []
    for i in range(0, len(tracks), stride):
        fr = tracks[i]
        pfr = pk["frames"].get(str(i)) or pk["frames"].get(i)
        if pfr is None:
            continue
        img = cv2.imread(str(AW / win / fr["file"]))
        if img is None:
            continue
        for p in fr.get("players", []):
            q = match_person(pfr["persons"], p["bbox"])
            if q is None:
                continue
            c = torso_crop(img, q["kpt"])
            if c is None:
                continue
            buf.append(c)
            meta.append({"frame": i, "track_id": p["track_id"],
                         "bbox": p["bbox"], "crop": [c.shape[1], c.shape[0]]})
        while len(buf) >= batch:
            chunk, buf = buf[:batch], buf[batch:]
            with torch.no_grad():
                inp = proc(images=chunk, return_tensors="pt").to(dev)
                e = mod(**inp).last_hidden_state[:, 0]
                e = torch.nn.functional.normalize(e, dim=-1)
            rows.append(e.cpu().numpy())
    if buf:
        with torch.no_grad():
            inp = proc(images=buf, return_tensors="pt").to(dev)
            e = mod(**inp).last_hidden_state[:, 0]
            e = torch.nn.functional.normalize(e, dim=-1)
        rows.append(e.cpu().numpy())
    E = np.concatenate(rows, 0) if rows else np.zeros((0, 384), np.float32)
    return E, meta


def kmeans(X, k, iters=100, seed=7):
    rng = np.random.default_rng(seed)
    C = X[rng.choice(len(X), k, replace=False)].copy()
    L = np.zeros(len(X), int)
    for _ in range(iters):
        L = ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1).argmin(1)
        newC = np.array([X[L == j].mean(0) if (L == j).sum() else C[j]
                         for j in range(k)])
        if np.allclose(newC, C, atol=1e-6):
            C = newC
            break
        C = newC
    return C, L


def render(win, meta, labels, outdir, frames):
    tracks = json.loads((AW / f"{win}_poss" / "ball_tracks.json").read_text())
    by_frame = {}
    for r, lab in zip(meta, labels):
        by_frame.setdefault(r["frame"], {})[r["track_id"]] = int(lab)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    PAL = [(60, 60, 235), (235, 160, 40), (60, 210, 60), (200, 60, 200)]
    for fi in frames:
        if fi >= len(tracks) or fi not in by_frame:
            continue
        fr = tracks[fi]
        img = cv2.imread(str(AW / win / fr["file"]))
        if img is None:
            continue
        lab_map = by_frame[fi]
        for p in fr.get("players", []):
            tid = p["track_id"]
            x1, y1, x2, y2 = [int(v) for v in p["bbox"]]
            if tid in lab_map:
                col = PAL[lab_map[tid] % len(PAL)]
                cv2.rectangle(img, (x1, y1), (x2, y2), col, 3)
                cv2.putText(img, f"T{lab_map[tid]}", (x1, max(18, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
            else:
                cv2.rectangle(img, (x1, y1), (x2, y2), (128, 128, 128), 2)
        b = fr.get("ball")
        if b and "bbox" in b:
            cv2.rectangle(img, (int(b["bbox"][0]), int(b["bbox"][1])),
                          (int(b["bbox"][2]), int(b["bbox"][3])), (0, 255, 255), 3)
        cv2.putText(img, f"{win} f{fi:05d}", (24, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
        p = out / f"team_{win}_f{fi:05d}.jpg"
        cv2.imwrite(str(p), img)
        print("[图]", p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("window")
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--render", default=None)
    ap.add_argument("--frames", nargs="+", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    E, meta = embed_window(a.window, a.stride)
    print(f"[{a.window}] 嵌入 {E.shape}  样本 {len(meta)}")
    if len(E) < 20:
        print("样本不足"); return 1
    C, L = kmeans(E, a.k)
    for j in range(a.k):
        print(f"  cluster {j}: n={int((L==j).sum())} ({100*(L==j).mean():.1f}%)")
    # 簇内/簇间余弦距离（应是「簇内明显小于簇间」）
    same = [float(1 - E[i] @ E[j]) for i in range(0, len(E), 7)
            for j in range(i + 1, len(E), 11) if L[i] == L[j]]
    diff = [float(1 - E[i] @ E[j]) for i in range(0, len(E), 7)
            for j in range(i + 1, len(E), 11) if L[i] != L[j]]
    if same and diff:
        print(f"  簇内余弦距离 均值 {np.mean(same):.4f}   "
              f"簇间 {np.mean(diff):.4f}   比值 {np.mean(diff)/np.mean(same):.2f}×")

    if a.render:
        fr = a.frames or [0, len(json.loads((AW / f'{a.window}_poss' /
                                            'ball_tracks.json').read_text())) // 3]
        render(a.window, meta, L, a.render, fr)
    if a.out:
        Path(a.out).write_text(json.dumps(
            {"window": a.window, "model": MODEL, "k": a.k, "stride": a.stride,
             "n": len(meta),
             "labels": [{"frame": r["frame"], "track_id": r["track_id"],
                         "bbox": r["bbox"], "cluster": int(l)}
                        for r, l in zip(meta, L)]}, indent=1))
        print(f"[写] {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
