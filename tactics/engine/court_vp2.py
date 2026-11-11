#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L4 · 消失点 v2 —— 联合四线 RANSAC + **两条几何门禁**。

v1 的失败教训（`court_vp.py`）
-----------------------------
v1 用「找内点最多的单族消失点」两轮贪心，得到 VP1=(6270,237) / VP2=(−1431,863)，
地平线 y=747→591。**该结果被几何反证**：地板上包络（远侧边线）实测 y∈[367,711]，
地平线却掉到 y(0)=747 —— **地平面消失线不可能低于地平面上可见的边线**。

根因有两条：
  ① 线像素阈值归一化用 p99 而线只占 ~1% ⇒ 阈值落在噪声里、7% 像素成"线"；
  ② 单族贪心会选中**退化 VP**（远到 6270px 的 VP，角度容差覆盖极宽方向，噪声线也成内点）。
     内点数最大化 ≠ 几何正确。

v2 的三处硬改动
---------------
1. 线像素：**白度图 + p99.9 归一化**（见 `court_lines2.py`，实测误检率降 3.5×）。
2. **联合四线 RANSAC**：一次采样 4 条线（2+2）同时解两族 VP，用**几何门禁**筛，
   而不是先贪心取一族的最大内点。
3. **两条几何门禁**（缺一不可）：
   · **地平线门禁**：地平面消失线必须在**地板可见区域之上** ⇒ `y_h(x) < env(x) − margin`；
   · **正交门禁**：NBA 球场是矩形，两族方向世界正交 ⇒ 由 `f² = −(a·b)`
     （a,b 为相对主点的两 VP 向量）反解焦距，要求 `f/画幅宽 ∈ [FMIN, FMAX]`。

用法:
  python engine/court_vp2.py --img reports/milestone_05/measure/median_w1_r158.jpg
  python engine/court_vp2.py --img ... --no-hgate      # 诊断：关掉地平线门禁看次优解
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

MAXCOORD = 60000.0
ANG_TOL = np.sin(np.deg2rad(1.0))     # 内点角度容差 sin(1°)
FMIN, FMAX = 0.40, 8.0                # f / 画幅宽


# ---------- 线提取（白度 + p99.9） ----------
def whiteness(img):
    f = img.astype(np.float32)
    mn = f.min(axis=2)
    mx = f.max(axis=2)
    return np.clip(mn * (1.0 - (mx - mn) / np.maximum(mx, 1.0)), 0, 255).astype(np.uint8)


def line_binary(img, roi, kernel=21, thr=0.35, norm_q=99.9):
    w = whiteness(img)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel | 1, kernel | 1))
    resp = cv2.GaussianBlur(cv2.morphologyEx(w, cv2.MORPH_TOPHAT, k), (3, 3), 0)
    r = resp.astype(np.float32)
    v = np.percentile(r[roi > 0], norm_q) if (roi > 0).any() else 1.0
    b = ((r >= thr * max(v, 1.0)) & (roi > 0)).astype(np.uint8) * 255
    return cv2.morphologyEx(b, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))


def segments(binary, min_len=150, max_gap=8):
    ls = cv2.HoughLinesP(binary, 1, np.pi / 720, 55,
                         minLineLength=min_len, maxLineGap=max_gap)
    if ls is None:
        return np.zeros((0, 4))
    return np.asarray(ls).reshape(-1, 4).astype(float)


def seg_models(segs):
    """→ L (m,3) 归一化线、Q (m,2) 线上点、D (m,2) 单位方向、W (m,) 长度"""
    out = []
    for x1, y1, x2, y2 in segs:
        a, b, c = y1 - y2, x2 - x1, x1 * y2 - x2 * y1
        n = np.hypot(a, b)
        if n < 1e-9:
            continue
        L = np.array([a / n, b / n, c / n])
        Q = np.array([x1, y1], float)
        d = np.array([x2 - x1, y2 - y1], float)
        ln = np.hypot(*d)
        D = d / max(1e-9, ln)
        out.append((L, Q, D, ln))
    if not out:
        return (np.zeros((0, 3)), np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0))
    return (np.array([o[0] for o in out]), np.array([o[1] for o in out]),
            np.array([o[2] for o in out]), np.array([o[3] for o in out]))


def resid(L, Q, D, x):
    """角度残差 |sin∠((x−q), d)| —— 远距离 VP 下的数值稳健写法。"""
    v = Q - x
    n = np.linalg.norm(v, axis=1)
    n[n < 1e-9] = 1e-9
    return np.abs(v[:, 0] * D[:, 1] - v[:, 1] * D[:, 0]) / n


def cross_vp(Li, Lj):
    x = np.cross(Li, Lj)
    if abs(x[2]) < 1e-12:
        return None
    p = x[:2] / x[2]
    if not np.all(np.isfinite(p)) or np.hypot(*p) > MAXCOORD:
        return None
    return p


def horizon_line(v1, v2):
    l = np.cross(np.array([v1[0], v1[1], 1.0]), np.array([v2[0], v2[1], 1.0]))
    n = np.hypot(l[0], l[1])
    return l / n if n > 1e-9 else None


def hor_y(H, x):
    if abs(H[1]) < 1e-9:
        return None
    return -(H[0] * x + H[2]) / H[1]


def focal_from(v1, v2, W, H):
    """两族世界正交 ⇒ f² = −(a·b)，a,b 为相对主点(图像中心)的 VP 向量。"""
    a = np.array([v1[0] - W / 2.0, v1[1] - H / 2.0])
    b = np.array([v2[0] - W / 2.0, v2[1] - H / 2.0])
    f2 = -(a @ b)
    if f2 <= 0:
        return None
    return float(np.sqrt(f2))


def gates(v1, v2, W, H, envs, no_hgate=False, margin=5.0, frac=0.9):
    """返回 (ok, 详情)。两条门禁都必须过。

    `envs` = (xs, env_at_xs) 预采样，避免每轮迭代都遍历 1920 列（RANSAC 内层开销）。
    """
    d = {}
    Hl = horizon_line(v1, v2)
    if Hl is None:
        return False, {"horizon": None, "why": "退化地平线"}
    d["horizon"] = Hl.tolist()
    if abs(Hl[1]) < 1e-9:
        return False, {**d, "why": "竖直地平线（退化）"}
    if envs is not None:
        xs, ev = envs
        ys = -(Hl[0] * xs + Hl[2]) / Hl[1]
        above = ys < (ev - margin)
        d["above_env_frac"] = float(above.mean())
        d["env_min"] = float(np.nanmin(ev))
        if not no_hgate and d["above_env_frac"] < frac:
            return False, {**d, "why": f"地平线未高于地板包络 (frac={d['above_env_frac']:.2f})"}
    d["focal"] = focal_from(v1, v2, W, H)
    d["f_over_W"] = (d["focal"] / W) if d["focal"] else None
    if d["focal"] is None or not (FMIN <= d["f_over_W"] <= FMAX):
        return False, {**d, "why": f"焦距门禁不过 (f/W={d['f_over_W']})"}
    return True, d


def joint_ransac(L, Q, D, Wl, W, H, envs, rng, n_iter=40000, no_hgate=False):
    """联合四线 RANSAC：一次采样 4 条（2+2）同时解两族 VP，门禁筛，长度加权计分。"""
    m = len(L)
    if m < 4:
        return None
    best = None
    for _ in range(n_iter):
        i, j, k, l = rng.choice(m, 4, replace=False)
        v1 = cross_vp(L[i], L[j])
        if v1 is None:
            continue
        v2 = cross_vp(L[k], L[l])
        if v2 is None:
            continue
        ok, _ = gates(v1, v2, W, H, envs, no_hgate)
        if not ok:
            continue
        r1 = resid(L, Q, D, v1)
        r2 = resid(L, Q, D, v2)
        a1 = r1 < ANG_TOL
        a2 = r2 < ANG_TOL
        # 同族互斥：归给残差更小的那族
        a1b = a1 & (r1 <= r2)
        a2b = a2 & (r2 < r1)
        if a1b.sum() < 2 or a2b.sum() < 2:
            continue
        score = float(Wl[a1b].sum() + Wl[a2b].sum())
        if best is None or score > best[0]:
            best = (score, v1, v2, a1b, a2b)
    if best is None:
        return None
    score, v1, v2, a1b, a2b = best
    # 迭代精修：TL SVD 重估每一族 → 重新归类
    for _ in range(6):
        for which in range(2):
            sel = a1b if which == 0 else a2b
            if sel.sum() >= 2:
                _, _, vt = np.linalg.svd(L[sel])
                x = vt[-1]
                if abs(x[2]) > 1e-12:
                    p = x[:2] / x[2]
                    if np.all(np.isfinite(p)) and np.hypot(*p) < MAXCOORD:
                        if which == 0:
                            v1 = p
                        else:
                            v2 = p
        r1 = resid(L, Q, D, v1)
        r2 = resid(L, Q, D, v2)
        a1b = (r1 < ANG_TOL) & (r1 <= r2)
        a2b = (r2 < ANG_TOL) & (r2 < r1)
    ok, det = gates(v1, v2, W, H, envs, no_hgate)
    return {"v1": v1, "v2": v2, "mask1": a1b, "mask2": a2b, "gates_ok": ok,
            "gate_detail": det, "score": score}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--min-len", type=int, default=150)
    ap.add_argument("--kernel", type=int, default=21)
    ap.add_argument("--thr", type=float, default=0.35)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-hgate", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    img = cv2.imread(a.img)
    if img is None:
        raise SystemExit("读不到图像")
    H, W = img.shape[:2]
    tag = Path(a.img).stem
    from court_lines import floor_roi
    roi, envp = floor_roi(img)
    env = None
    if envp is not None:
        from court_gate import env_at
        env = np.array([env_at(envp, float(x)) for x in range(W)], float)
    xs_s = np.linspace(0, W - 1, 96)
    envs = None
    if env is not None:
        ei = np.clip(np.round(xs_s).astype(int), 0, W - 1)
        envs = (xs_s, env[ei])

    b = line_binary(img, roi, a.kernel, a.thr)
    segs = segments(b, a.min_len)
    L, Q, D, Wl = seg_models(segs)
    print(f"[{tag}] 线像素 {b.mean()/255*100:.3f}%  长线段 {len(segs)} (min_len={a.min_len})")
    if env is not None:
        print(f"  地板包络 y: min {np.nanmin(env):.0f} median {np.nanmedian(env):.0f} max {np.nanmax(env):.0f}")

    rng = np.random.default_rng(a.seed)
    r = joint_ransac(L, Q, D, Wl, W, H, envs, rng, no_hgate=a.no_hgate)
    ov = img.copy()
    ov[b > 0] = (0, 220, 255)
    if r is None:
        print("  ❌ 无任何四线组合能通过几何门禁 —— 线提取质量仍不足（这是合法结论，不许硬凑）")
        cv2.putText(ov, f"{tag} segs={len(segs)}  NO SOLUTION (gates rejected all)",
                    (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)
        out = a.out or str(MS / f"vp2_{tag}.jpg")
        cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
        json.dump({"tag": tag, "solved": False, "n_seg": int(len(segs)),
                   "linepx_pct": round(float(b.mean()) / 255 * 100, 3)},
                  open(MS / f"vp2_{tag}.json", "w"), ensure_ascii=False, indent=1)
        print(f"[out] {out}")
        return

    det = r["gate_detail"]
    cols = [(0, 255, 0), (255, 0, 255)]
    for k, s in enumerate(segs):
        if r["mask1"][k]:
            cv2.line(ov, (int(s[0]), int(s[1])), (int(s[2]), int(s[3])), cols[0], 3)
        elif r["mask2"][k]:
            cv2.line(ov, (int(s[0]), int(s[1])), (int(s[2]), int(s[3])), cols[1], 3)
        else:
            cv2.line(ov, (int(s[0]), int(s[1])), (int(s[2]), int(s[3])), (110, 110, 110), 1)
    txt = [f"{tag}  segs={len(segs)}  gates={'PASS' if r['gates_ok'] else 'FAIL'}"]
    for fi, v in enumerate((r["v1"], r["v2"])):
        n_in = int((r["mask1"] if fi == 0 else r["mask2"]).sum())
        txt.append(f"VP{fi+1}=({v[0]:.0f},{v[1]:.0f})  线{int(n_in)}/{len(segs)}")
        if abs(v[0]) < 4000 and abs(v[1]) < 4000:
            cv2.drawMarker(ov, (int(v[0]), int(v[1])), cols[fi], cv2.MARKER_CROSS, 40, 3)
    Hl = det.get("horizon")
    if Hl:
        xs = np.array([0, W - 1], float)
        ys = [hor_y(np.array(Hl), float(x)) for x in xs]
        if all(y is not None and -5000 < y < 5000 for y in ys):
            cv2.line(ov, (int(xs[0]), int(ys[0])), (int(xs[1]), int(ys[1])), (255, 255, 0), 3)
            txt.append(f"地平线 y={ys[0]:.0f}→{ys[1]:.0f}")
    if det.get("f_over_W"):
        fov = 2 * np.degrees(np.arctan(W / (2 * det["focal"])))
        txt.append(f"f/W={det['f_over_W']:.2f}  HFOV={fov:.0f}°  高于包络 {det.get('above_env_frac', float('nan')):.2f}")
    if env is not None:
        pts = np.array([(x, int(np.clip(env[x], 0, H - 1))) for x in range(0, W, 6)])
        cv2.polylines(ov, [pts.reshape(-1, 1, 2)], False, (60, 60, 255), 2)
    for i, t in enumerate(txt):
        cv2.putText(ov, t, (20, 36 + 34 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                    (255, 255, 255), 2, cv2.LINE_AA)
    out = a.out or str(MS / f"vp2_{tag}.jpg")
    cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}")
    for t in txt:
        print("  " + t)
    json.dump({"tag": tag, "solved": True, "n_seg": int(len(segs)),
               "v1": r["v1"].tolist(), "v2": r["v2"].tolist(),
               "n1": int(r["mask1"].sum()), "n2": int(r["mask2"].sum()),
               "gates_ok": bool(r["gates_ok"]), "gate_detail": det,
               "linepx_pct": round(float(b.mean()) / 255 * 100, 3)},
              open(MS / f"vp2_{tag}.json", "w"), ensure_ascii=False, indent=1)
    print(f"[out] {MS / f'vp2_{tag}.json'}")


if __name__ == "__main__":
    main()
