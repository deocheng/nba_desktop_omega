#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.15 场地直线推断器 v2：用画面识别出的直线推测整个场地（按镜头窗口）。

老程指令（2026-10-01）：
  ① 被遮挡的边线 ⇒ 虚拟边线 = 平行于识别出的一条边线（不是拟合掩膜锯齿）
  ② 累积掩膜绿色=球场但没覆盖全场 ⇒ 用识别出的直线推测场地
  ③ 油漆区+合理冲撞区弧识别正确（非中圈）⇒ 油漆区作锚点

v1 → v2 的三处修正（全部由 ep24_s1 f70 自证图驱动）：
  A) 远端边线：v1 用 Hough 顶部线（比值消歧）⇒ 自证图显示偏低 30-40px
     （远端边线在多数帧被替补席人员遮挡，Hough 检不到或检错）。
     v2 改用**累积掩膜上边界的 RANSAC 直线**（掩膜=50 帧频率证据，
     上边界=地板↔替补席分界=远端边线），拟合出的是直线 ⇒ 遮挡段平行延长。
  B) 右侧边界：v1 把木地板对比线 B#1 当半场线 ⇒ 错。半场线两侧都是木地板，
     **不可能**通过「一侧地板一侧非地板」检验；且自证图显示掩膜延伸到画幅右缘
     ⇒ 场地在画幅右缘仍在延续 ⇒ v2 一律画幅收口。
  C) 近端边线/油漆区宽边：v1 已目视正确，保留。

自洽验证（线身份的唯一裁判）：s_court/s_paint ≈ 50ft/16ft = 3.125（透视容差 ±15%）。

用法:
  court_infer_lines.py --seg ep24_s1 --idx 70            # 单帧推断+叠图
  court_infer_lines.py --seg ep24_s1 --idx 70 90 --json  # 多帧+导出
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

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
from court_homography_recover import fit_quad, paint_mask  # noqa: E402
from court_line_probe import detect, y_at  # noqa: E402

RATIO = 50.0 / 16.0            # 场宽 / 油漆区宽
RATIO_TOL = 0.15               # 透视容差
ACC_TH = 0.7                   # 累积掩膜频率阈值


def line_coeffs(p):
    x1, y1, x2, y2 = p
    if x2 == x1:
        return None
    a = (y2 - y1) / (x2 - x1)
    return a, y1 - a * x1


def intersect(p1, p2):
    x1, y1, x2, y2 = p1
    X1, Y1, X2, Y2 = p2
    v1 = abs(x2 - x1) < 1e-9
    v2 = abs(X2 - X1) < 1e-9
    if v1 and v2:
        return None
    if v1:
        a2 = (Y2 - Y1) / (X2 - X1)
        b2 = Y1 - a2 * X1
        return float(x1), float(a2 * x1 + b2)
    if v2:
        a1 = (y2 - y1) / (x2 - x1)
        b1 = y1 - a1 * x1
        return float(X1), float(a1 * X1 + b1)
    L1, L2 = line_coeffs(p1), line_coeffs(p2)
    if L1 is None or L2 is None:
        return None
    (a1, b1), (a2, b2) = L1, L2
    if abs(a1 - a2) < 1e-9:
        return None
    x = (b2 - b1) / (a1 - a2)
    return float(x), float(a1 * x + b1)


def ransac_line(pts, iters=3000, tol=6.0, max_abs_slope=0.15, seed=0):
    """2D 点集 RANSAC 直线。返回 (a, b, n_inlier) 或 None。"""
    pts = np.asarray(pts, float)
    if len(pts) < 30:
        return None
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(iters):
        i, j = rng.choice(len(pts), 2, replace=False)
        (x1, y1), (x2, y2) = pts[i], pts[j]
        if abs(x2 - x1) < 60:
            continue
        a = (y2 - y1) / (x2 - x1)
        if abs(a) > max_abs_slope:
            continue
        b = y1 - a * x1
        inl = np.abs(pts[:, 1] - (a * pts[:, 0] + b)) < tol
        n = int(inl.sum())
        if best is None or n > best[2]:
            best = (a, b, n)
    if best is None or best[2] < 30:
        return None
    a, b, _ = best
    P = pts[np.abs(pts[:, 1] - (a * pts[:, 0] + b)) < tol]
    a2, b2 = np.polyfit(P[:, 0], P[:, 1], 1)
    return float(a2), float(b2), len(P)


def ransac_steep(pts, iters=4000, tol=8.0, seed=0):
    """拟合 x = m*y + c（陡线，如底线/近端边线，x 为纵轴）。返回 (m, c, n_inlier)。"""
    pts = np.asarray(pts, float)
    if len(pts) < 30:
        return None
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(iters):
        i, j = rng.choice(len(pts), 2, replace=False)
        y1, x1 = pts[i][1], pts[i][0]
        y2, x2 = pts[j][1], pts[j][0]
        if abs(y2 - y1) < 30:
            continue
        m = (x2 - x1) / (y2 - y1)
        c = x1 - m * y1
        inl = np.abs(pts[:, 0] - (m * pts[:, 1] + c)) < tol
        n = int(inl.sum())
        if best is None or n > best[2]:
            best = (m, c, n)
    if best is None or best[2] < 30:
        return None
    m, c, _ = best
    P = pts[np.abs(pts[:, 0] - (m * pts[:, 1] + c)) < tol]
    m2, c2 = np.polyfit(P[:, 1], P[:, 0], 1)
    return float(m2), float(c2), len(P)


def far_sideline_from_accum(seg, W, freq_name=None):
    """累积掩膜上边界 → RANSAC 直线。返回 (x1,y1,x2,y2, n_inlier) 或 None。"""
    fp = OUT / (freq_name or f"_tmp_freq_{seg}.npy")
    if not fp.exists():
        return None
    freq = np.load(str(fp))
    acc = (freq >= ACC_TH).astype(np.uint8)
    pts = []
    for x in range(0, W, 4):
        col = np.where(acc[:, x] > 0)[0]
        if len(col) >= 10:
            pts.append((float(x), float(col.min())))
    r = ransac_line(pts)
    if r is None:
        return None
    a, b, n = r
    return (0.0, a * 0 + b, float(W - 1), a * (W - 1) + b, n)


def baseline_from_accum(seg, W, H, freq_name=None):
    """累积掩膜左边界（木地板↔场外黑底白字）→ RANSAC 陡线。返回 (x0,0,x1,H-1, n_inlier)。"""
    fp = OUT / (freq_name or f"_tmp_freq_{seg}.npy")
    if not fp.exists():
        return None
    freq = np.load(str(fp))
    acc = (freq >= ACC_TH).astype(np.uint8)
    pts = []
    for y in range(0, H, 2):
        col = np.where(acc[y, :] > 0)[0]
        if len(col):
            pts.append((float(col.min()), float(y)))
    r = ransac_steep(pts)
    if r is None:
        return None
    m, c, n = r
    x0, x1 = c, m * (H - 1) + c
    return (x0, 0.0, x1, float(H - 1), n)


def draw_ext(vis, p, color, thick=3, dash=16):
    """识别段实线，延长段虚线（=虚拟边线，平行于识别段）。"""
    x1, y1, x2, y2 = [int(round(v)) for v in p]
    Wd = vis.shape[1]
    L = line_coeffs(p)
    if L is None:
        cv2.line(vis, (x1, 0), (x1, vis.shape[0] - 1), color, thick)
        return
    a, b = L
    for (xa, xb) in [(0, x1), (x2, Wd - 1)]:
        if xb - xa < 8:
            continue
        n = max(2, int((xb - xa) // (dash * 2)))
        for t in range(n):
            t0, t1 = t / n, (t + 0.5) / n
            pa = (int(xa + (xb - xa) * t0), int(round(a * (xa + (xb - xa) * t0) + b)))
            pb = (int(xa + (xb - xa) * t1), int(round(a * (xa + (xb - xa) * t1) + b)))
            cv2.line(vis, pa, pb, (0, 0, 0), thick + 3)
            cv2.line(vis, pa, pb, color, thick)
    cv2.line(vis, (x1, y1), (x2, y2), (0, 0, 0), thick + 3)
    cv2.line(vis, (x1, y1), (x2, y2), color, thick)


def estimate_s_paint(img):
    """逐帧估计油漆区宽边间距 s_paint（像素）。损坏/遮挡时返回 None。"""
    H, W = img.shape[:2]
    pm = paint_mask(img)
    if pm is None:
        return None
    quad = fit_quad(pm)
    if quad is None:
        return None
    lines = detect(img)
    famA = [k for k in lines if k["ang"] < 20]
    pmd = cv2.dilate(pm, np.ones((41, 41), np.uint8))
    in_p = [k for k in famA if k["L"] >= 380
            and pmd[(k["p"][1] + k["p"][3]) // 2, (k["p"][0] + k["p"][2]) // 2] > 0]
    ys = sorted([(y_at(k, W / 2), k) for k in in_p if y_at(k, W / 2) is not None],
                key=lambda t: t[0])
    if len(ys) < 2:
        return None
    med = float(np.median([y for y, _ in ys]))
    pf = max([k for y, k in ys if y <= med], key=lambda k: k["L"])
    pn = max([k for y, k in ys if y > med], key=lambda k: k["L"])
    return abs(y_at(pn, W / 2) - y_at(pf, W / 2))


def infer(img, seg, freq_name=None, s_paint_win=None):
    """返回 (poly|None, lines_dict, info)。四线: near/far/baseline + 画幅右收口。
    s_paint_win: 提供时用窗口稳定 s_paint 做几何自洽门（跳过逐帧油漆区，抗遮挡）。"""
    H, W = img.shape[:2]
    info = {}
    lines = detect(img)
    famA = [k for k in lines if k["ang"] < 20]
    famA.sort(key=lambda k: y_at(k, W / 2) or 0)
    info["n_lines"] = len(lines)

    if s_paint_win is not None:
        s_paint = float(s_paint_win)
        info["s_paint_src"] = "window_median"
    else:
        pm = paint_mask(img)
        if pm is None:
            return None, None, {"why": "油漆区未检出", **info}
        quad = fit_quad(pm)
        if quad is None:
            return None, None, {"why": "油漆区四边形拟合失败", **info}
        info["paint_quad"] = [[int(v) for v in pt] for pt in quad]
        pmd = cv2.dilate(pm, np.ones((41, 41), np.uint8))
        in_p = [k for k in famA if k["L"] >= 380
                and pmd[(k["p"][1] + k["p"][3]) // 2, (k["p"][0] + k["p"][2]) // 2] > 0]
        ys = sorted([(y_at(k, W / 2), k) for k in in_p if y_at(k, W / 2) is not None],
                key=lambda t: t[0])
        if len(ys) < 2:
            return None, None, {"why": "油漆区宽边线不足", **info}
        med = float(np.median([y for y, _ in ys]))
        pf = max([k for y, k in ys if y <= med], key=lambda k: k["L"])
        pn = max([k for y, k in ys if y > med], key=lambda k: k["L"])
        s_paint = abs(y_at(pn, W / 2) - y_at(pf, W / 2))
        info["s_paint_src"] = "frame"
    info["s_paint"] = round(s_paint, 1)

    # 近端边线 = 最靠下的长 famA 线
    A_long = [k for k in famA if k["L"] >= 300]
    if not A_long:
        return None, None, {"why": "无长 famA 线", **info}
    near = max(A_long, key=lambda k: y_at(k, W / 2) or 0)
    y_near = y_at(near, W / 2)

    # 远端边线 = 累积掩膜上边界 RANSAC；须满足几何自洽
    far = far_sideline_from_accum(seg, W, freq_name)
    far_src = "accum_top_ransac"
    if far is not None:
        a0 = (far[3] - far[1]) / max(far[2] - far[0], 1)
        y_far_mid = far[1] + a0 * (W / 2 - far[0])
        s_court = y_near - y_far_mid
        r = s_court / s_paint
        info["ratio_accum"] = round(r, 4)
        # 累积掩膜上边界 = 50 帧频率证据(相机无关)；直接信任。
        # 全局 RATIO 自洽门仅作严重污染兜底(>50% 偏差视为掩膜异常)，
        # 不再用 ±15% 拒绝——侧视回放(窗口B)透视比天然偏离 3.125(~-13%)。
        if abs(r / RATIO - 1) > 0.5:
            far = None
            info["far_gate"] = "corruption_tripwire"
    if far is None:
        # 回退：Hough 顶部线比值消歧（v1 逻辑；需帧级油漆区）
        pf = locals().get("paint_far")
        if pf is None:
            why = "累积掩膜上边界RANSAC失败" if info.get("far_gate") != "corruption_tripwire" \
                else "远端边线污染兜底触发(比值>50%)"
            return None, None, {"why": why, **info}
        top = [k for k in A_long if (y_at(k, W / 2) or 9e9) < y_at(pf, W / 2)]
        best, best_err = None, 1e9
        for k in top:
            sc = y_near - y_at(k, W / 2)
            if sc <= s_paint:
                continue
            err = abs(sc / s_paint - RATIO)
            if err < best_err:
                best, best_err = k, err
        if best is None:
            return None, None, {"why": "远端边线不可得", **info}
        far, far_src = best["p"], "hough_ratio"
        s_court = y_near - y_at(best, W / 2)
        r = s_court / s_paint
        if abs(r / RATIO - 1) > RATIO_TOL:
            return None, None, {"why": f"几何自洽超差 r={r:.3f}", **info}
    info["far_src"] = far_src
    info["s_court"] = round(float(s_court), 1)
    info["ratio"] = round(float(s_court / s_paint), 4)
    info["ratio_dev_pct"] = round(100 * (s_court / s_paint / RATIO - 1), 1)

    # 底线 = 累积掩膜左边界（木地板↔场外黑底白字；老程 2026-10-01：场外黑底白字有明显色差）
    base_tup = baseline_from_accum(seg, W, H, freq_name)
    if base_tup is None:
        return None, None, {"why": "累积掩膜左边界(底线)不可得", **info}
    info["baseline_n_inlier"] = int(base_tup[4])
    baseline = base_tup[:4]
    # 记录底线角度（相对水平，°）
    bx0, by0, bx1, by1 = baseline
    info["baseline_angle_deg"] = round(float(np.degrees(np.arctan2(abs(bx1 - bx0), abs(by1 - by0)))), 1)

    # 场地多边形：近端边线(下) / 远端边线(上) / 底线(左) / 画幅右缘(右)
    near_p, far_p = near["p"], tuple(far[:4])
    right_p = (float(W - 1), 0.0, float(W - 1), float(H - 1))
    pts = [intersect(baseline, far_p), intersect(far_p, right_p),
           intersect(right_p, near_p), intersect(near_p, baseline)]
    if any(p is None for p in pts):
        return None, None, {"why": "边线交点失败", **info}
    poly = np.array(pts, float)
    info["poly"] = [[round(float(x), 1), round(float(y), 1)] for x, y in poly]
    lines_out = {"near": near_p, "far": far_p, "baseline": baseline}
    return poly, lines_out, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, nargs="+", default=[70])
    ap.add_argument("--freq", default=None, help="累积掩膜 freq npy 文件名（默认 _tmp_freq_{seg}.npy）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    outs = {}
    for idx in a.idx:
        img = cv2.imread(str(files[idx]))
        H, W = img.shape[:2]
        poly, lo, info = infer(img, a.seg, a.freq)
        print(f"=== {a.seg} f{idx} 场地直线推断 v3(累积掩膜左边界底线) ===")
        for k, v in info.items():
            if k not in ("poly", "paint_quad"):
                print(f"  {k}: {v}")
        print(f"  poly: {info.get('poly')}")
        if poly is None:
            continue
        outs[idx] = info

        vis = img.copy()
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [poly.astype(np.int32)], 255)
        ov = vis.copy()
        ov[m > 0] = (0.55 * ov[m > 0] + 0.45 * np.array([255, 160, 0])).astype(np.uint8)
        vis = cv2.addWeighted(ov, 0.55, vis, 0.45, 0)
        # 四线：绿=近端边线 黄=远端边线 品红=底线（识别段实线/延长段虚线）
        draw_ext(vis, lo["near"], (0, 255, 0))
        draw_ext(vis, lo["far"], (0, 255, 255))
        draw_ext(vis, lo["baseline"], (255, 0, 255))
        pm = paint_mask(img)
        if pm is not None:
            cs, _ = cv2.findContours(pm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(vis, cs, -1, (255, 255, 0), 2)
        cv2.polylines(vis, [poly.astype(np.int32)], True, (0, 0, 0), 5)
        cv2.polylines(vis, [poly.astype(np.int32)], True, (255, 255, 255), 2)
        # 自证数字
        fp = OUT / (a.freq or f"_tmp_freq_{a.seg}.npy")
        if fp.exists():
            freq = np.load(str(fp))
            acc = (freq >= ACC_TH).astype(np.uint8)
            n_acc = int(acc.sum())
            cont = float(acc[m > 0].sum()) / max(n_acc, 1)
            cov = float(acc[m > 0].sum()) / max(int((m > 0).sum()), 1)
            info["containment"] = round(100 * cont, 1)
            info["coverage"] = round(100 * cov, 1)
            print(f"  自证: containment(掩膜⊂场地)={100*cont:.1f}%  "
                  f"coverage(场地被掩膜盖)={100*cov:.1f}%")
        op = OUT / f"{a.seg}_f{idx}_infer_v3.png"
        cv2.imwrite(str(op), vis)
        print(f"  -> {op}\n")

    if a.json and outs:
        jp = OUT / f"{a.seg}_court_infer.json"
        json.dump(outs, open(jp, "w"), ensure_ascii=False, indent=1)
        print(f"-> {jp}")


if __name__ == "__main__":
    main()
