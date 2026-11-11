#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场区域门禁 v0 —— 不需要识别具体线条，只需「地板在图像中的上包络」。

思路（用户提议的「球场先行」最廉价可量化版本）
------------------------------------------------
观众席衣物/场边设备类 FP 位于「地板区域的上边界之外」。
逐帧求地板色的最大连通域 → 取**逐列最上可见行** → 用 RANSAC 二次曲线稳健拟合
（把渗进观众席的木色/肤色列当外点剔除）→ 得到上包络 top_row(u)。

特征（对球候选框，中心 (cx,cy)）：
  above_top       = top_row(cx) − cy        > 0 ⇒ 在场地之上（越界）
  in_floor        = 中心是否在地板掩膜内
  foot_in_floor   = 框底中点是否在地板掩膜内
  d_top           = above_top 的截断版（连续量）

同时给出 `--render` 目视验收（把包络画到帧上）与 `--auc` 逐特征 AUC。

用法:
  python engine/court_gate.py --render w1 f00010.jpg
  python engine/court_gate.py --auc
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
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))

WOOD_H, WOOD_S, WOOD_V = (6, 32), 55, 50
PUR_H, PUR_S, PUR_V = (115, 170), 55, 40
SCALE = 0.25


def floor_mask(img, scale=SCALE):
    s = cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)),
                   interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(s, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    m = (((H >= WOOD_H[0]) & (H <= WOOD_H[1]) & (S >= WOOD_S) & (V >= WOOD_V)) |
         ((H >= PUR_H[0]) & (H <= PUR_H[1]) & (S >= PUR_S) & (V >= PUR_V))
         ).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None, scale
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return (lab == i).astype(np.uint8), scale


def top_envelope(m, deg=2, n_iter=260, tol=6.0, min_col=5, seed=0):
    """逐列最上行 + RANSAC 多项式拟合 → 上包络参数（小尺度坐标）。"""
    H, W = m.shape
    cols = np.where(m.sum(axis=0) >= min_col)[0]
    if len(cols) < 20:
        return None
    tops = np.array([np.argmax(m[:, c] > 0) for c in cols], float)
    rng = np.random.default_rng(seed)
    best = None
    X = np.vstack([cols ** k for k in range(deg + 1)]).T  # [n, deg+1]
    for _ in range(n_iter):
        idx = rng.choice(len(cols), deg + 1, replace=False)
        try:
            coef = np.linalg.solve(X[idx], tops[idx])
        except np.linalg.LinAlgError:
            continue
        r = np.abs(X @ coef - tops)
        inl = r < tol
        if inl.sum() < deg + 1:
            continue
        try:
            coef = np.linalg.lstsq(X[inl], tops[inl], rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        r = np.abs(X @ coef - tops)
        n_in = int((r < tol).sum())
        if best is None or n_in > best[0]:
            best = (n_in, coef, float(np.median(r[r < tol])))
    if best is None:
        return None
    return {"coef": best[1], "inliers": best[0], "n": len(cols), "resid": best[2]}


def env_at(env, x, scale=SCALE):
    if env is None:
        return None
    coef = env["coef"]
    return float(sum(c * (x * scale) ** k for k, c in enumerate(coef))) / scale


def feats_for(img, box, cache):
    key = id(img)
    if key not in cache:
        m, sc = floor_mask(img)
        cache[key] = (m, sc, top_envelope(m) if m is not None else None)
    m_s, sc, env = cache[key]
    if m_s is None:
        return {"above_top": 0.0, "in_floor": 0.0, "foot_in_floor": 0.0, "env_ok": 0.0}
    mf = cv2.resize(m_s, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    H, W = mf.shape
    ic = 1.0 if (0 <= int(cy) < H and 0 <= int(cx) < W and mf[int(cy), int(cx)] > 0) else 0.0
    fy = min(max(int(y2), 0), H - 1)
    fx = min(max(int(cx), 0), W - 1)
    iff = 1.0 if mf[fy, fx] > 0 else 0.0
    t = env_at(env, cx) if env else None
    at = (t - cy) if t is not None else 0.0
    return {"above_top": at, "in_floor": ic, "foot_in_floor": iff,
            "env_ok": 1.0 if env else 0.0}


def auc(y, x):
    y = np.asarray(y, float); x = np.asarray(x, float)
    if y.sum() in (0, len(y)):
        return float("nan")
    r = np.argsort(np.argsort(x)) + 1.0
    n1, n0 = y.sum(), (1 - y).sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def render(win, frame, out=None):
    img = cv2.imread(str(AW / win / frame))
    cache = {}
    f = feats_for(img, [0, 0, 1, 1], cache)
    m_s, sc, env = list(cache.values())[0]
    ov = img.copy()
    if m_s is not None:
        mf = cv2.resize(m_s, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        ov[mf > 0] = (ov[mf > 0] * 0.6 + np.array([30, 110, 40]) * 0.4).astype(np.uint8)
    if env is not None:
        xs = np.arange(0, img.shape[1], 8)
        pts = np.array([[x, env_at(env, x)] for x in xs if env_at(env, x) is not None])
        pts = pts[(pts[:, 1] > -200) & (pts[:, 1] < img.shape[0] + 200)]
        if len(pts) > 1:
            cv2.polylines(ov, [pts.astype(int).reshape(-1, 1, 2)], False, (255, 0, 255), 3)
    txt = f"{win} {frame} env={'OK' if env else 'FAIL'} " + \
          (f"inliers={env['inliers']}/{env['n']} resid={env['resid']:.2f}" if env else "")
    cv2.putText(ov, txt, (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    out = out or str(MS / f"courtgate_{win}_{Path(frame).stem}.jpg")
    cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}  {txt}")


def run_auc():
    bank = json.loads((MS / "labels_bank.json").read_text())
    allrows, ok_env = [], 0
    for w in ("w1", "w2", "w3", "w4"):
        rows = [r for r in bank if r["window"] == w and r["label"] in ("TP", "FP")]
        cache, out = {}, []
        for r in rows:
            img = cv2.imread(str(AW / w / r["frame"]))
            f = feats_for(img, r["bbox"], cache)
            f.update({"window": w, "frame": r["frame"], "label": r["label"]})
            out.append(f)
        allrows += out
        ok_env += sum(1 for f in out if f["env_ok"] > 0)
        y = [1 if r["label"] == "TP" else 0 for r in out]
        print(f"[{w}] n={len(out)} TP={sum(y)}  " +
              "  ".join(f"{k}={auc(y,[r[k] for r in out]):.3f}"
                        for k in ("above_top", "in_floor", "foot_in_floor")))
    y = [1 if r["label"] == "TP" else 0 for r in allrows]
    print(f"[ALL] n={len(allrows)} TP={sum(y)} env_ok={ok_env}/{len(allrows)}  " +
          "  ".join(f"{k}={auc(y,[r[k] for r in allrows]):.3f}"
                    for k in ("above_top", "in_floor", "foot_in_floor")))
    for lab in ("TP", "FP"):
        v = np.array([r["above_top"] for r in allrows if r["label"] == lab], float)
        print(f"  above_top {lab}: 中位={np.median(v):7.1f}  >0 比例={np.mean(v>0)*100:5.1f}%")
    (MS / "courtgate_rows.json").write_text(json.dumps(allrows, ensure_ascii=False))
    print(f"[out] {MS/'courtgate_rows.json'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", nargs=2, default=None, metavar=("WIN", "FRAME"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--auc", action="store_true")
    a = ap.parse_args()
    if a.render:
        render(a.render[0], a.render[1], a.out)
    if a.auc:
        run_auc()


if __name__ == "__main__":
    main()
