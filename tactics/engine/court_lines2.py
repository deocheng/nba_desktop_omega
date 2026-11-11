#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场线提取 v2 —— 按用户思路「黑白化预处理后再检线」。

问题（v1 `court_lines.py` 的实测）
----------------------------------
灰度 top-hat 在紫色涂装区**大片误检**：紫漆内部有斑驳纹理与白色碎点，灰度上与
「白线」不可分。目视 `courtlines_median_w1_r158.jpg` 可见黄色线像素糊满整个油漆区。

v2 的核心变换 = 白度图（whiteness）
-----------------------------------
NBA 球场线**都是浅色/白色**（少数黑线）。而：
  · 木地板 = 橙 —— B 通道极低
  · 紫色涂装 = 紫 —— G 通道极低
  · 白线     = 三通道都高、且**饱和低**
故  w = min(B,G,R) × (1 − (max−min)/max)  对木/紫都接近 0，只对白线高。
在 w 上做 top-hat（比核细的亮结构）⇒ 木/紫边界不再产生亮脊。
可选再叠 blackhat(w) 抓黑线（部分球馆用深色线）。

可量化验收（不靠目视也能判）
---------------------------
  · `on_paint` = 线像素落在紫色涂装掩膜内的比例  ← 越低越好（v1 会很高）
  · `on_wood`  = 落在木色地板内的比例
  · `above`    = 落在地板上包络之上的比例（应由 ROI 保证 ≈ 0）
  · `n_seg`    = 长线段条数（同 min_len 下应显著下降）

用法:
  python engine/court_lines2.py --img reports/milestone_05/measure/median_w1_r158.jpg
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
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
AW = Path(str(tactics_data_file("action_work")))

PUR_H, PUR_S, PUR_V = (115, 170), 55, 40
WOOD_H, WOOD_S, WOOD_V = (6, 32), 55, 50


def masks(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    pur = (H >= PUR_H[0]) & (H <= PUR_H[1]) & (S >= PUR_S) & (V >= PUR_V)
    wood = (H >= WOOD_H[0]) & (H <= WOOD_H[1]) & (S >= WOOD_S) & (V >= WOOD_V)
    return pur, wood


def whiteness(img):
    """白度图：低饱和 ∧ 高亮 ⇒ 只留浅色球场线。"""
    f = img.astype(np.float32)
    mn = f.min(axis=2)
    mx = f.max(axis=2)
    w = mn * (1.0 - (mx - mn) / np.maximum(mx, 1.0))
    return np.clip(w, 0, 255).astype(np.uint8)


def resp_tophat(g, k):
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k | 1, k | 1))
    return cv2.GaussianBlur(cv2.morphologyEx(g, cv2.MORPH_TOPHAT, ker), (3, 3), 0)


def resp_blackhat(g, k):
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k | 1, k | 1))
    return cv2.GaussianBlur(cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, ker), (3, 3), 0)


def binarize(resp, roi, thr, norm_q=99.9):
    """🔴 归一化必须用 p99.9 而非 p99（v1 的实锤 bug）。

    线像素只占 ~1%，p99 本身就落在**噪声**里；用 `thr × p99` 等于把阈值压到噪声之下
    （实测 gray p99=75 → thr0.18 阈值仅 13.5，而真线响应 80–200）⇒ 7% 像素变"线"。
    """
    r = resp.astype(np.float32)
    v = np.percentile(r[roi > 0], norm_q) if (roi > 0).any() else 1.0
    b = ((r >= thr * max(v, 1.0)) & (roi > 0)).astype(np.uint8) * 255
    return cv2.morphologyEx(b, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))


def lsd_or_hough(b, min_len, max_gap=8):
    segs = []
    try:
        lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        lines = lsd.detect(b)[0]
        if lines is not None:
            segs = [(float(l[0][0]), float(l[0][1]), float(l[0][2]), float(l[0][3])) for l in lines]
    except Exception:
        segs = []
    if not segs:
        ls = cv2.HoughLinesP(b, 1, np.pi / 360, 40,
                             minLineLength=min_len, maxLineGap=max_gap)
        if ls is not None:
            segs = [tuple(map(float, v)) for v in np.asarray(ls).reshape(-1, 4)]
    return [s for s in segs if np.hypot(s[2] - s[0], s[3] - s[1]) >= min_len]


def build_variant(img, roi, name, kernel, thr, norm_q=99.9):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if name == "gray":
        return binarize(resp_tophat(gray, kernel), roi, thr, norm_q)
    w = whiteness(img)
    if name == "white":
        return binarize(resp_tophat(w, kernel), roi, thr, norm_q)
    if name == "white_black":
        a = binarize(resp_tophat(w, kernel), roi, thr, norm_q)
        c = binarize(resp_blackhat(w, kernel), roi, thr, norm_q)
        return cv2.max(a, c)
    raise SystemExit(f"未知变体 {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--kernel", type=int, default=21)
    ap.add_argument("--thr", type=float, default=0.35)
    ap.add_argument("--norm-q", type=float, default=99.9)
    ap.add_argument("--min-len", type=int, default=90)
    ap.add_argument("--variants", default="gray,white,white_black")
    a = ap.parse_args()

    img = cv2.imread(a.img)
    if img is None:
        raise SystemExit("读不到图像")
    tag = Path(a.img).stem

    from court_lines import floor_roi
    roi, env = floor_roi(img)
    pur, wood = masks(img)
    if env is not None:
        from court_gate import env_at
        envf = np.array([env_at(env, float(x)) for x in range(img.shape[1])])
        above = np.zeros(img.shape[:2], bool)
        for x in range(img.shape[1]):
            t = int(np.clip(envf[x], 0, img.shape[0]))
            above[:t, x] = True
    else:
        above = np.zeros(img.shape[:2], bool)

    rows = {}
    for name in a.variants.split(","):
        name = name.strip()
        b = build_variant(img, roi, name, a.kernel, a.thr, a.norm_q)
        segs = lsd_or_hough(b, a.min_len)
        on = b > 0
        n = int(on.sum())
        frac = lambda m: float((on & m).sum()) / max(1, n)
        d = {"linepx_pct": round(float(on.mean()) * 100, 3), "n_pix": n,
             "n_seg": len(segs), "on_paint": round(frac(pur), 4),
             "on_wood": round(frac(wood), 4), "above_env": round(frac(above), 4)}
        rows[name] = d
        # on_paint / on_wood = 线像素落在**高饱和紫漆/木地板**里的比例。
        # 白线像素本身低饱和，故这两个数就是「误检率」的直接代理 ⇒ 越低越好。
        print(f"[{name:11s}] linepx={d['linepx_pct']:6.3f}%  seg={d['n_seg']:4d}  "
              f"误检ᵖᵃⁱⁿᵗ={d['on_paint']:.3f}  误检ʷᵒᵒᵈ={d['on_wood']:.3f}  "
              f"above_env={d['above_env']:.3f}")
        ov = img.copy()
        ov[on] = (0, 255, 255)
        for x1, y1, x2, y2 in segs:
            L = np.hypot(x2 - x1, y2 - y1)
            col = (0, 255, 0) if L > 200 else ((0, 165, 255) if L > 120 else (255, 0, 255))
            cv2.line(ov, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
        cv2.putText(ov, f"{tag} [{name}] segs={len(segs)} px={d['linepx_pct']:.2f}% "
                        f"onpaint={d['on_paint']:.2f}",
                    (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        out = MS / f"courtlines2_{name}_{tag}.jpg"
        cv2.imwrite(str(out), ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"           [out] {out}")

    json.dump({"tag": tag, "kernel": a.kernel, "thr": a.thr, "min_len": a.min_len,
               "variants": rows},
              open(MS / f"courtlines2_{tag}.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
