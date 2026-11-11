#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""队色分配（不含任何跟踪/ID 依赖）—— 把「哪个球员持球」升级为「哪支队持球」。

为什么必须绕开 track_id
----------------------
Phase 1.5 诊断：track_id 中位寿命仅 1.3–1.7s，187 个 ID 承载 12 个位置
（复用/流失 15.6×）。用「持球者 track_id」聚合成球权段 = 假连续。
**队色是逐帧独立判据，不需要 ID 跨帧稳定**，因此天然规避该失效模式；
而且 PBP 回合变更本身就是「换队」，队级球权才是与 PBP 同口径的量。

实现
----
  ① 躯干 ROI 取中位 RGB（丢最暗/最亮各 20%，抗号码/阴影）；
  ② 用 NBA 先验色心做最近邻（白/黑/红/蓝/金/紫/绿/灰），避免无监督聚类
     在「白 vs 灰」「黑 vs 深蓝」上不稳定；
  ③ 帧内 2-means（在色心投影上）确定该帧的两队主色 ⇒ 逐帧自适应，抗曝光漂移。

用法: team_color.py <window> <out_dir> [--frames 5] [--probe]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))

# NBA 常见球衣/裁判服先验色心（sRGB）
ANCHORS = {
    "white": (245, 245, 245), "lightgray": (190, 190, 190),
    "gray": (128, 128, 128), "black": (28, 28, 28),
    "red": (200, 30, 40), "darkred": (120, 20, 25),
    "orange": (225, 120, 30), "gold": (250, 200, 60),
    "yellow": (240, 220, 70), "green": (25, 130, 70),
    "blue": (30, 70, 175), "navy": (20, 35, 90),
    "purple": (105, 45, 150), "teal": (20, 120, 140),
    "maroon": (110, 30, 45), "silver": (170, 175, 180),
}


def torso_median(img, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    if w < 8 or h < 16:
        return None
    rx1 = x1 + int(0.20 * w); rx2 = x1 + int(0.80 * w)
    ry1 = y1 + int(0.12 * h); ry2 = y1 + int(0.45 * h)
    rx1, rx2 = max(0, rx1), min(img.shape[1], rx2)
    ry1, ry2 = max(0, ry1), min(img.shape[0], ry2)
    if rx2 - rx1 < 5 or ry2 - ry1 < 5:
        return None
    roi = img[ry1:ry2, rx1:rx2].reshape(-1, 3).astype(np.float32)
    # 抗号码/深阴影：按亮度分位裁剪
    lum = roi @ np.array([0.114, 0.587, 0.299], dtype=np.float32)
    lo, hi = np.percentile(lum, [25, 75])
    sel = roi[(lum >= lo) & (lum <= hi)]
    if len(sel) < 20:
        sel = roi
    return np.median(sel, axis=0)  # BGR


def nearest_anchor(rgb):
    best, bd = None, 1e18
    for k, v in ANCHORS.items():
        d = sum((a - b) ** 2 for a, b in zip(rgb, v))
        if d < bd:
            bd, best = d, k
    return best, bd ** 0.5


def probe(win, n_frames=5, outdir=None):
    tracks = json.loads((AW / f"{win}_poss" / "ball_tracks.json").read_text())
    frames_dir = AW / win
    samples = []
    for fr in tracks:
        if fr["frame"] % max(1, len(tracks) // 200) != 0:
            continue
        img = cv2.imread(str(frames_dir / fr["file"]))
        if img is None:
            continue
        for p in fr.get("players", []):
            rgb = torso_median(img, p["bbox"])
            if rgb is None:
                continue
            samples.append(rgb[::-1])  # BGR -> RGB
    arr = np.array(samples)
    print(f"[{win}] 躯干样本 {len(arr)}")
    # 先验色心最近邻分布
    from collections import Counter
    c = Counter(nearest_anchor(tuple(int(v) for v in s))[0] for s in arr)
    print("  先验色心最近邻 top8:", c.most_common(8))

    # 逐帧 2-means（在整窗样本上做 k=2 也有意义，先看整体）
    def kmeans2(X, iters=40, seed=1):
        rng = np.random.default_rng(seed)
        ctr = X[rng.choice(len(X), 2, replace=False)]
        for _ in range(iters):
            d = ((X[:, None, :] - ctr[None, :, :]) ** 2).sum(-1)
            lab = d.argmin(1)
            for k in range(2):
                if (lab == k).sum() > 0:
                    ctr[k] = X[lab == k].mean(0)
        return ctr, lab

    ctr, lab = kmeans2(arr)
    for k in range(2):
        n = int((lab == k).sum())
        name, d = nearest_anchor(tuple(ctr[k]))
        print(f"  cluster{k}: n={n:>5} ({n/len(arr)*100:.1f}%)  均值RGB="
              f"({ctr[k][0]:.0f},{ctr[k][1]:.0f},{ctr[k][2]:.0f})  "
              f"最近先验={name} (d={d:.0f})")
    return arr, ctr, lab


def render_overlay(win, outdir, ctr, frames=(0, 200, 400)):
    frames_dir = AW / win
    tracks = json.loads((AW / f"{win}_poss" / "ball_tracks.json").read_text())
    out = Path(outdir); out.mkdir(parents=True, exist_ok=True)
    for fi in frames:
        if fi >= len(tracks):
            continue
        fr = tracks[fi]
        img = cv2.imread(str(frames_dir / fr["file"]))
        if img is None:
            continue
        for p in fr.get("players", []):
            rgb = torso_median(img, p["bbox"])
            if rgb is None:
                continue
            r = rgb[::-1].astype(np.float32)
            d0 = ((r - ctr[0]) ** 2).sum(); d1 = ((r - ctr[1]) ** 2).sum()
            col = (60, 60, 230) if d0 < d1 else (230, 120, 40)  # BGR
            x1, y1, x2, y2 = [int(v) for v in p["bbox"]]
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 3)
            cv2.putText(img, f"{p['track_id']}", (x1, max(20, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        b = fr.get("ball")
        if b and "bbox" in b:
            bx1, by1, bx2, by2 = [int(v) for v in b["bbox"]]
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (0, 255, 0), 3)
        p = out / f"team_{win}_f{fi:05d}.jpg"
        cv2.imwrite(str(p), img)
        print("[图]", p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("window")
    ap.add_argument("--outdir", default="action_work/m05_team_qa")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    arr, ctr, lab = probe(a.window)
    if a.render:
        render_overlay(a.window, a.outdir, ctr)
    if a.out:
        Path(a.out).write_text(json.dumps(
            {"window": a.window, "n_samples": int(len(arr)),
             "centers_rgb": [[round(float(v), 1) for v in c] for c in ctr],
             "cluster_share": [round(float((lab == k).mean()), 3) for k in range(2)]},
            indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
