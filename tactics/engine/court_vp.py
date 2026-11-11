#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场线 → 两族消失点 → 地平线（球场识别的几何核心）。

为什么是消失点
--------------
球场线分两族（平行关系是世界里的**刚体事实**，与涂装/光照无关）：
  · 族 X：沿场地长轴的线 —— 两条边线、油漆区两条边、三分线直线段、中线刻度
  · 族 Y：沿场地短轴的线 —— 两条底线、中线、两条罚球线、篮板线
同一族的世界平行线在图像中交于同一点 = 消失点。两族消失点 VX/VY 连线 = **地平线**
（地平面的消失线）。地平线是**不需要知道哪条线是哪条**就能拿到的硬几何量。

关键判据（残差用角度而非距离，避免远距离消失点数值病态）
  line(a,b,c) 归一化方向 d 与线上一点 q；对候选消失点 x：
    residual = |sin∠((x−q), d)| = |cross(unit(x−q), d)|
  同族线该残差 → 0。内点阈值取 sin(2°)≈0.035。

用法:
  python engine/court_vp.py --img measure/median_w1_r158.jpg
  python engine/court_vp.py --img ... --min-len 180 --thr 0.22
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
MAXCOORD = 30000.0        # 消失点坐标上限（视为「无穷远」）
ANG_TOL = np.sin(np.deg2rad(2.0))


def floor_roi(img, dilate=25):
    from court_gate import env_at, floor_mask, top_envelope
    m, sc = floor_mask(img)
    if m is None:
        return np.full(img.shape[:2], 255, np.uint8), None
    env = top_envelope(m)
    roi = np.zeros(img.shape[:2], np.uint8)
    if env is not None:
        for x in range(img.shape[1]):
            t = int(np.clip(env_at(env, float(x)), 0, img.shape[0] - 1))
            roi[t:, x] = 255
    mf = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate | 1, dilate | 1))
    mf = cv2.dilate(cv2.morphologyEx(mf, cv2.MORPH_CLOSE, k), k)
    return cv2.bitwise_and(roi, mf), env


def line_pixels(img, roi, kernel=15, thr=0.22):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    th = cv2.GaussianBlur(cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k), (3, 3), 0)
    v = np.percentile(th[roi > 0], 99.0) if (roi > 0).any() else 1.0
    b = ((th >= thr * max(v, 1.0)) & (roi > 0)).astype(np.uint8) * 255
    b = cv2.morphologyEx(b, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return b


def long_segments(binary, min_len=180, max_gap=25, vote=60):
    ls = cv2.HoughLinesP(binary, 1, np.pi / 720, vote,
                         minLineLength=min_len, maxLineGap=max_gap)
    if ls is None:
        return np.zeros((0, 4))
    return np.asarray(ls).reshape(-1, 4).astype(float)


def seg_to_line(s):
    x1, y1, x2, y2 = s
    a, b, c = y1 - y2, x2 - x1, x1 * y2 - x2 * y1
    n = np.hypot(a, b)
    if n < 1e-9:
        return None
    return np.array([a / n, b / n, c / n]), np.array([x1, y1], float), \
        np.array([(x2 - x1), (y2 - y1)], float) / max(1e-9, np.hypot(x2 - x1, y2 - y1))


def vp_resid(x, q, d):
    v = x - q
    n = np.linalg.norm(v)
    if n < 1e-9:
        return 1.0
    return abs(v[0] * d[1] - v[1] * d[0]) / n


def _resid_all(p, Q, D):
    v = Q - p
    n = np.linalg.norm(v, axis=1)
    n[n < 1e-9] = 1e-9
    return np.abs(v[:, 0] * D[:, 1] - v[:, 1] * D[:, 0]) / n


def find_vp(models, rng, n_iter=20000):
    if len(models) < 2:
        return None
    L = np.array([m[0] for m in models])       # (m,3) 归一化线
    Q = np.array([m[1] for m in models])       # (m,2) 线上点
    D = np.array([m[2] for m in models])       # (m,2) 单位方向
    m = len(models)
    best = (0, None)
    for _ in range(n_iter):
        i, j = rng.choice(m, 2, replace=False)
        x = np.cross(L[i], L[j])
        if abs(x[2]) < 1e-12:
            continue
        p = x[:2] / x[2]
        if not np.all(np.isfinite(p)) or np.hypot(*p) > MAXCOORD:
            continue
        inl = int((_resid_all(p, Q, D) < ANG_TOL).sum())
        if inl > best[0]:
            best = (inl, p)
    if best[1] is None:
        return None
    p0 = best[1]
    inl = _resid_all(p0, Q, D) < ANG_TOL
    if inl.sum() >= 2:
        try:
            p0 = np.linalg.lstsq(L[inl][:, :2], -L[inl][:, 2], rcond=None)[0]
        except np.linalg.LinAlgError:
            pass
    return {"vp": p0, "inliers": int((_resid_all(p0, Q, D) < ANG_TOL).sum()),
            "n": int(m), "mask": _resid_all(p0, Q, D) < ANG_TOL}


def horizon_from(v1, v2):
    """两消失点连线 = 地平线（返回 (a,b,c)，a*x+b*y+c=0）。"""
    p1 = np.array([v1[0], v1[1], 1.0])
    p2 = np.array([v2[0], v2[1], 1.0])
    l = np.cross(p1, p2)
    n = np.hypot(l[0], l[1])
    return l / n if n > 1e-9 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default=None)
    ap.add_argument("--window", default=None)
    ap.add_argument("--frame", default=None)
    ap.add_argument("--min-len", type=int, default=180)
    ap.add_argument("--max-gap", type=int, default=25)
    ap.add_argument("--kernel", type=int, default=15)
    ap.add_argument("--thr", type=float, default=0.22)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.img:
        img = cv2.imread(a.img)
        tag = Path(a.img).stem
    else:
        img = cv2.imread(str(AW / a.window / a.frame))
        tag = f"{a.window}_{Path(a.frame).stem}"
    if img is None:
        raise SystemExit("读不到图像")

    roi, _ = floor_roi(img)
    b = line_pixels(img, roi, a.kernel, a.thr)
    segs = long_segments(b, a.min_len, a.max_gap)
    models = [m for m in (seg_to_line(s) for s in segs) if m is not None]
    print(f"[{tag}] 线像素 {b.mean()/255*100:.2f}%  长线段 {len(segs)}")

    rng = np.random.default_rng(a.seed)
    used = set()
    vps = []
    for _ in range(2):
        mm = [m for k, m in enumerate(models) if k not in used]
        r = find_vp(mm, rng)
        if r is None:
            break
        vps.append(r)
        for k, m in enumerate(models):
            if k not in used and vp_resid(r["vp"], m[1], m[2]) < ANG_TOL:
                used.add(k)
        print(f"  消失点#{len(vps)}: ({r['vp'][0]:.0f}, {r['vp'][1]:.0f})  "
              f"内点 {r['inliers']}/{r['n']}")

    ov = img.copy()
    ov[b > 0] = (0, 220, 255)
    cols = [(0, 255, 0), (255, 0, 255)]
    fam = {}
    for k, m in enumerate(models):
        for fi, r in enumerate(vps):
            if vp_resid(r["vp"], m[1], m[2]) < ANG_TOL:
                fam[k] = fi
                break
    for k, s in enumerate(segs):
        f = fam.get(k)
        if f is None:
            cv2.line(ov, (int(s[0]), int(s[1])), (int(s[2]), int(s[3])), (120, 120, 120), 1)
        else:
            cv2.line(ov, (int(s[0]), int(s[1])), (int(s[2]), int(s[3])), cols[f], 3)
    txt = [f"{tag} segs={len(segs)}"]
    for fi, r in enumerate(vps):
        p = r["vp"]
        if abs(p[0]) < 4000 and abs(p[1]) < 4000:
            cv2.drawMarker(ov, (int(p[0]), int(p[1])), cols[fi], cv2.MARKER_CROSS, 40, 3)
        txt.append(f"VP{fi+1}=({p[0]:.0f},{p[1]:.0f}) inl={r['inliers']}")
    H = horizon_from(vps[0]["vp"], vps[1]["vp"]) if len(vps) == 2 else None
    if H is not None:
        # 解出地平线的 y=f(x)：a x + b y + c = 0
        if abs(H[1]) > 1e-9:
            xs = np.array([0, img.shape[1] - 1], float)
            ys = -(H[0] * xs + H[2]) / H[1]
            cv2.line(ov, (int(xs[0]), int(ys[0])), (int(xs[1]), int(ys[1])),
                     (255, 255, 0), 3)
            txt.append(f"地平线 y = {ys[0]:.0f} → {ys[1]:.0f}")
        else:
            txt.append("地平线：竖直（退化）")
    for i, t in enumerate(txt):
        cv2.putText(ov, t, (20, 36 + 34 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                    (255, 255, 255), 2, cv2.LINE_AA)
    out = a.out or str(MS / f"vp_{tag}.jpg")
    cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}")
    for t in txt:
        print("  " + t)
    if len(vps) == 2:
        json.dump({"tag": tag, "vp1": vps[0]["vp"].tolist(), "vp2": vps[1]["vp"].tolist(),
                   "inl1": vps[0]["inliers"], "inl2": vps[1]["inliers"],
                   "horizon": H.tolist() if H is not None else None,
                   "n_seg": int(len(segs))},
                  open(MS / f"vp_{tag}.json", "w"), ensure_ascii=False, indent=1)
        print(f"[out] {MS / f'vp_{tag}.json'}")


if __name__ == "__main__":
    main()
