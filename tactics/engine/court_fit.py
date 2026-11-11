#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单帧**球场配准**（court registration）—— 模型线拟合求相机位姿。

核心思想（把用户的洞察形式化）
----------------------------
「涂装/地板色是变量，边线/中线/三分线是常量」⇒ 不必去"识别"球场，
而是把**规范球场模型**投影到图上，用**实测线像素图**当监督，反解相机位姿：
    找到 (C, T, f, roll) 使「模型线投影」与「实测线像素」互相贴合。

为什么这条路优于消失点（v1/v2 已失败）
--------------------------------------
消失点要两条**足够长的**同族线段；本素材单帧 ≥150px 只有 3 条。
模型拟合用的是**整张线像素图 + 全部规范几何**：一条线被球员挡住 70% 仍然贡献约束，
远端边线只有 40px 可见也仍然贡献约束。**不要求任何一条线"长"**。

目标函数（对称的双向距离，缺一不可）
----------------------------------
  · 正向 F = mean_t min(D_img(proj(t)), CAP)   —— 模型线必须落在实测线像素上
  · 反向 R = mean_p min(D_tmpl(p), CAP)        —— 实测线像素必须被模型线解释
只加正向会退化成"把球场缩成一小团"（小团总能蹭到几条线）；反向项正是防这个。
两项都只统计**可信区域**（地板 ROI 内、非叠加图形遮罩内）。

用法:
  python engine/court_fit.py --img reports/milestone_05/measure/median_w1_r158.jpg \
      --grid --top 24 --out reports/milestone_05/measure/courtfit_median_w1_r158
  python engine/court_fit.py --img ... --from-json <上一步 json> --refine-only
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))

CAP = 30.0                     # 距离截断（像素）：超过即视为"完全没对上"，不再细分
OVERLAY_BOXES = [(60, 880, 580, 1020)]   # 比分板（检测前涂黑，同上游一致）


# ---------------- 从 court_model 拿一个 look-at 风格相机 ----------------
from court_model import (
    HALF_L,
    HALF_W,
    LANE_HW,
    R_3PT,
    R_CENTER,
    R_FT,
    R_RIM,
    X_BASKET,
    X_BOARD,
    X_LANE,
    Y_3PT_CORNER,
    Z_RIM,
    build_model,
)


class LookCam:
    """look-at 参数化：C=(Cx,Cy,Cz)，T=(Tx,Ty,0) 为光轴与地板的交点，roll，f(px)。"""

    def __init__(self, C, T, f, roll=0.0, cx=960.0, cy=540.0):
        self.C = np.asarray(C, float)
        self.f = float(f); self.cx = cx; self.cy = cy
        fwd = np.array([T[0] - C[0], T[1] - C[1], 0.0 - C[2]], float)
        n = np.linalg.norm(fwd)
        self.ok = n > 1e-6
        if not self.ok:
            self.R = np.eye(3); return
        zc = fwd / n
        up = np.array([0.0, 0.0, 1.0])
        xc = np.cross(zc, up)
        nx = np.linalg.norm(xc)
        if nx < 1e-9:
            xc = np.array([1.0, 0, 0])
        else:
            xc = xc / nx
        yc = np.cross(zc, xc)
        if abs(roll) > 1e-9:
            a = np.radians(roll)
            ca, sa = np.cos(a), np.sin(a)
            xc, yc = ca * xc + sa * yc, -sa * xc + ca * yc
        self.roll = float(roll)
        self.R = np.stack([xc, yc, zc], axis=0)

    @property
    def t_axis(self):
        return self.R @ self.C

    def proj(self, P):
        Q = P @ self.R.T - self.t_axis
        z = Q[:, 2]
        zz = np.where(np.abs(z) < 1e-6, 1e-6, z)
        return np.stack([self.cx + self.f * Q[:, 0] / zz,
                         self.cy + self.f * Q[:, 1] / zz], axis=1), z

    @property
    def H_ground(self):
        R = self.R
        A = np.zeros((3, 3))
        A[:, 0] = R[0]; A[:, 1] = R[1]; A[:, 2] = -R @ self.C
        K = np.array([[self.f, 0, self.cx], [0, self.f, self.cy], [0, 0, 1.0]])
        return K @ A

    def to_court(self, uv):
        Hi = np.linalg.inv(self.H_ground)
        p = np.concatenate([np.asarray(uv, float), np.ones((len(uv), 1))], axis=1)
        q = p @ Hi.T
        w = np.where(np.abs(q[:, 2]) < 1e-9, 1e-9, q[:, 2])
        return q[:, :2] / w[:, None], q[:, 2]


def make_cam(p):
    """p = [Cx, Cy, Cz, Tx, Ty, f, roll]"""
    return LookCam(p[:3], (p[3], p[4]), p[5], p[6])


# ---------------- 线像素图 + DT ----------------
def whiteness(img):
    f = img.astype(np.float32)
    mn = f.min(axis=2); mx = f.max(axis=2)
    return np.clip(mn * (1.0 - (mx - mn) / np.maximum(mx, 1.0)), 0, 255).astype(np.uint8)


def line_map(img, mask, kernel=21, thr=0.35, norm_q=99.9):
    w = whiteness(img)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel | 1, kernel | 1))
    resp = cv2.GaussianBlur(cv2.morphologyEx(w, cv2.MORPH_TOPHAT, k), (3, 3), 0)
    r = resp.astype(np.float32)
    v = np.percentile(r[mask > 0], norm_q) if (mask > 0).any() else 1.0
    b = (((r >= thr * max(v, 1.0)) & (mask > 0)).astype(np.uint8)) * 255
    return cv2.morphologyEx(b, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))


# ---------------- 模型模板 ----------------
def template(step=1):
    S = build_model()
    P, names, owner = [], [], []
    for i, (nm, pts) in enumerate(S):
        idx = np.arange(0, len(pts), step)
        P.append(pts[idx]); names += [nm] * len(idx); owner += [i] * len(idx)
    return np.concatenate(P, 0), S


# ---------------- 打分 ----------------
class Scorer:
    def __init__(self, img, tmpl_P, tmpl_segs, mask, verbose=False):
        self.img = img
        self.H, self.W = img.shape[:2]
        self.P = tmpl_P
        self.segs = tmpl_segs
        self.mask = mask
        b = line_map(img, mask)
        self.b = b
        self.line_px = (b > 0) & (mask > 0)
        # 正向查询用：线像素 DT（不可信区置大）
        d = cv2.distanceTransform(255 - b, cv2.DIST_L2, 5).astype(np.float32)
        self.D_img = np.where(mask > 0, d, CAP + 10)
        for x0, y0, x1, y1 in OVERLAY_BOXES:
            self.D_img[y0:y1, x0:x1] = CAP + 10
        self.n_line = int(self.line_px.sum())
        if verbose:
            print(f"  线像素 {b.mean()/255*100:.3f}%  可信线像素 {self.n_line}"
                  f"  模板点 {len(tmpl_P)}")

    def score(self, cam, ret_detail=False):
        uv, z = cam.proj(self.P)
        front = z > 0.5
        inb = ((uv[:, 0] > 2) & (uv[:, 0] < self.W - 3) &
               (uv[:, 1] > 2) & (uv[:, 1] < self.H - 3))
        vis = front & inb
        if vis.sum() < 150:                    # 可见模板点太少 ⇒ 直接判废
            return (1e6, {"why": "模板可见点过少", "n_vis": int(vis.sum())}) if ret_detail else 1e6
        iu = np.clip(np.round(uv[vis, 0]).astype(int), 0, self.W - 1)
        iv = np.clip(np.round(uv[vis, 1]).astype(int), 0, self.H - 1)
        D = self.D_img[iv, iu]
        trust = D < CAP + 5
        if trust.sum() < 120:
            return (1e6, {"why": "落在可信区的模板点过少",
                          "n_trust": int(trust.sum())}) if ret_detail else 1e6
        F = float(np.minimum(D[trust], CAP).mean())
        # ---- 反向：把模板画成线，看实测线像素离它多远 ----
        can = np.zeros((self.H, self.W), np.uint8)
        for nm, pts in self.segs:
            u2, z2 = cam.proj(pts)
            ok = z2 > 0.5
            if ok.sum() < 2:
                continue
            p = u2[ok]
            if not np.all(np.isfinite(p)):
                continue
            pp = np.round(p).astype(np.int32)
            pp[:, 0] = np.clip(pp[:, 0], -5000, self.W + 5000)
            pp[:, 1] = np.clip(pp[:, 1], -5000, self.H + 5000)
            cv2.polylines(can, [pp.reshape(-1, 1, 2)], False, 255, 5)
        dt = cv2.distanceTransform(255 - can, cv2.DIST_L2, 5).astype(np.float32)
        Rv = float(np.minimum(dt[self.line_px], CAP).mean())
        if ret_detail:
            return F + Rv, {"F": F, "R": Rv, "n_vis": int(vis.sum()),
                            "n_trust": int(trust.sum())}
        return F + Rv


# ---------------- 粗搜 ----------------
def grid_search(sc, subsample=4):
    P = sc.P[::subsample]
    xs = []
    for Cx in np.arange(-16, 17, 8.0):
        for Cy in (-24.0, -18.0, -13.0, -10.0):
            for Cz in (6.0, 10.0, 15.0, 22.0):
                for Tx in (0.0, 6.0, 12.0):
                    for Ty in (-4.0, 0.0, 4.0):
                        for f in (900.0, 1300.0, 1800.0, 2400.0, 3200.0):
                            xs.append([Cx, Cy, Cz, Tx, Ty, f, 0.0])
    X = np.array(xs)
    t0 = time.time()
    res = []
    for k, p in enumerate(X):
        cam = make_cam(p)
        if not cam.ok:
            continue
        uv, z = cam.proj(P)
        v = (z > 0.5) & (uv[:, 0] > 2) & (uv[:, 0] < sc.W - 3) & \
            (uv[:, 1] > 2) & (uv[:, 1] < sc.H - 3)
        if v.sum() < 40:
            continue
        iu = np.clip(np.round(uv[v, 0]).astype(int), 0, sc.W - 1)
        iv = np.clip(np.round(uv[v, 1]).astype(int), 0, sc.H - 1)
        D = sc.D_img[iv, iu]
        t = D < CAP + 5
        if t.sum() < 30:
            continue
        res.append((float(np.minimum(D[t], CAP).mean()), tuple(p)))
    res.sort(key=lambda r: r[0])
    print(f"  粗搜 {len(X)} 个位姿 → 有效 {len(res)}  {time.time()-t0:.0f}s")
    return res


def refine(sc, p0, verbose=False):
    from scipy.optimize import minimize
    def obj(x):
        cam = make_cam(x)
        if not cam.ok:
            return 1e6
        Cx, Cy, Cz, Tx, Ty, f, roll = x
        if not (2.0 <= Cz <= 45.0 and abs(Cx) < 35 and abs(Cy) < 35
                and 300.0 <= f <= 8000.0 and abs(roll) < 15.0):
            return 1e6
        return sc.score(cam)
    best = (obj(p0), np.array(p0, float))
    # 多轮 Powell（不同初始步长），避免过早收敛
    for s in (1.0, 0.35, 0.12):
        r = minimize(obj, best[1], method="Powell",
                     options={"xtol": 1e-4, "ftol": 1e-5, "maxiter": 4000,
                              "direc": np.eye(7) * s})
        if r.fun < best[0]:
            best = (float(r.fun), r.x.copy())
    return best


def render(img, cam, sc, out, title="", extra=None):
    ov = img.copy()
    can = np.zeros(img.shape[:2], np.uint8)
    cols = [(0, 255, 0), (255, 0, 255), (0, 255, 255), (255, 128, 0), (128, 0, 255)]
    for i, (nm, pts) in enumerate(sc.segs):
        uv, z = cam.proj(pts)
        ok = (z > 0.5) & np.isfinite(uv).all(axis=1)
        if ok.sum() < 2:
            continue
        pp = uv[ok]
        inside = ((pp[:, 0] > -300) & (pp[:, 0] < img.shape[1] + 300) &
                  (pp[:, 1] > -300) & (pp[:, 1] < img.shape[0] + 300))
        if not inside.any():
            continue
        c = cols[i % len(cols)]
        is3d = nm.endswith(("rim", "bb_top", "bb_bot"))
        c = (0, 0, 255) if is3d else c
        cv2.polylines(ov, [np.round(pp).astype(np.int32).reshape(-1, 1, 2)], False, c,
                      2 if is3d else 1)
        cv2.polylines(can, [np.round(pp).astype(np.int32).reshape(-1, 1, 2)], False, 255,
                      3)
    # 图角标出
    txt = [title]
    Hc = cam.H_ground
    for i, (x, y) in enumerate([(-HALF_L, -HALF_W), (HALF_L, -HALF_W),
                                (HALF_L, HALF_W), (-HALF_L, HALF_W)]):
        v = Hc @ np.array([x, y, 1.0]); uv = v[:2] / v[2]
        if np.all(np.isfinite(uv)) and -2000 < uv[0] < img.shape[1] + 2000 \
                and -2000 < uv[1] < img.shape[0] + 2000:
            p = (int(np.clip(uv[0], 0, img.shape[1] - 1)),
                 int(np.clip(uv[1], 0, img.shape[0] - 1)))
            cv2.circle(ov, p, 9, (0, 0, 255), -1)
            cv2.putText(ov, f"C{i+1}", (p[0] + 10, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 255), 2, cv2.LINE_AA)
    if extra:
        txt += extra
    for i, t in enumerate(txt):
        cv2.putText(ov, t, (16, 30 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(ov, t, (16, 30 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 93])
    return ov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--subsample", type=int, default=4)
    ap.add_argument("--top", type=int, default=24)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-grid", action="store_true")
    ap.add_argument("--manual", nargs=7, type=float, default=None,
                    help="直接给 p=[Cx Cy Cz Tx Ty f roll]，跳过粗搜")
    a = ap.parse_args()

    img = cv2.imread(a.img)
    if img is None:
        raise SystemExit("读不到图像")
    tag = Path(a.img).stem
    from court_lines import floor_roi
    roi, envp = floor_roi(img)
    mask = roi.copy()
    for x0, y0, x1, y1 in OVERLAY_BOXES:
        mask[y0:y1, x0:x1] = 0
    P, segs = template(1)
    sc = Scorer(img, P, segs, mask, verbose=True)

    cands = []
    if a.manual:
        cands = [(0.0, tuple(a.manual))]
    if not a.no_grid:
        cands += grid_search(sc, a.subsample)
    if not cands:
        raise SystemExit("粗搜无有效位姿")
    cands = cands[: a.top]
    print(f"  精修 top {len(cands)} …")
    finals = []
    t0 = time.time()
    for k, (s0, p) in enumerate(cands):
        s, p = refine(sc, p)
        finals.append((s, p))
        if (k + 1) % 4 == 0:
            print(f"    {k+1}/{len(cands)}  当前最好 {min(f[0] for f in finals):.2f}"
                  f"  {time.time()-t0:.0f}s", flush=True)
    finals.sort(key=lambda r: r[0])
    out = []
    for rank, (s, p) in enumerate(finals[:6]):
        cam = make_cam(p)
        _, det = sc.score(cam, ret_detail=True)
        G = cam.H_ground
        uv, _ = cam.proj(np.array([[0, 0, 0.0]]))
        court_uv, w = cam.to_court(uv)
        dc = {
            "rank": rank, "score": float(s), "detail": det,
            "p": [float(x) for x in p],
            "C": cam.C.tolist(), "T": [float(p[3]), float(p[4])], "f": float(p[5]),
            "fov_h": float(2 * np.degrees(np.arctan(960.0 / cam.f))),
            "H_ground": G.tolist(),
            "cam_ground_pt_roundtrip": court_uv.tolist()[0],
        }
        out.append(dc)
        print(f"  #{rank}  score {s:.2f}  F {det.get('F',-1):.2f} R {det.get('R',-1):.2f}"
              f"  C=({cam.C[0]:.1f},{cam.C[1]:.1f},{cam.C[2]:.1f})"
              f"  T=({p[3]:.1f},{p[4]:.1f})  f={cam.f:.0f} HFOV={dc['fov_h']:.0f}°"
              f"  可见模板点 {det.get('n_vis')}")
        render(img, cam, sc, f"{a.out}_rank{rank}.jpg",
               f"{tag} rank{rank} score={s:.2f} F={det.get('F',-1):.1f} R={det.get('R',-1):.1f}",
               [f"C=({cam.C[0]:.1f},{cam.C[1]:.1f},{cam.C[2]:.1f}) T=({p[3]:.1f},{p[4]:.1f})",
                f"f={cam.f:.0f}px  HFOV={dc['fov_h']:.0f}deg  roll={p[6]:.2f}"])
    json.dump({"img": a.img, "tag": tag, "results": out},
              open(f"{a.out}.json", "w"), ensure_ascii=False, indent=1)
    print(f"[out] {a.out}.json  +  {a.out}_rank0.jpg …")


if __name__ == "__main__":
    main()
