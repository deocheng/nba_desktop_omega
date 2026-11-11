#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量 B 诊断：线像素来源统计 + ROI 收紧，看反向项 R 能否降到个位数。

思路（用户指定优先级）
----------------------
原 court_fit 的目标函数里 R 是「cap 到 30px 后的均值」，看不出构成。本脚本把它拆开：
  1) 用默认 ROI 配准得 p0；对**每个线像素**算它到模型线的距离 → 分布 + 近距离占比
     （近=被球场模型解释=真球场线；远=不可解释=干扰）。
  2) 空间定位：切 6×8 网格，报「线像素密度」与「远端(>20px)占比」热区 ⇒ 干扰在哪。
  3) ROI 收紧：用 p0 的 H_ground 把规范球场四角投影回图像，取其多边形为球场 footprint，
     与 floor_roi 求交 ⇒ 只保留球场范围内的线像素；再配准一次，比较 R。
     注：用位姿导出的多边形反过来收紧再重拟合，属 self-consistency 迭代（类 ICP），报告中须注明。

用法
----
  python engine/_diag_linesource.py baseline_w1 250
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
sys.path.insert(0, str(ROOT / "engine"))
AW = ROOT / "action_work"

import court_fit as cf
import court_render as cr
from court_fit import OVERLAY_BOXES, Scorer, line_map, make_cam, template
from court_lines import floor_roi
from court_model import HALF_L, HALF_W


def model_dist_map(img, segs, cam, thick=5, only_floor=True):
    """把模型线按该位姿画出来，返回每像素到最近模型线的距离图。"""
    H, W = img.shape[:2]
    can = np.zeros((H, W), np.uint8)
    for nm, pts in segs:
        if only_floor and nm.endswith(("rim", "bb_top", "bb_bot", "bb_lft", "bb_rgt")):
            continue
        uv, z = cam.proj(pts)
        ok = z > 0.5
        if ok.sum() < 2:
            continue
        pp = np.round(uv[ok]).astype(np.int32)
        pp[:, 0] = np.clip(pp[:, 0], -5000, W + 5000)
        pp[:, 1] = np.clip(pp[:, 1], -5000, H + 5000)
        cv2.polylines(can, [pp.reshape(-1, 1, 2)], False, 255, thick)
    return cv2.distanceTransform(255 - can, cv2.DIST_L2, 5).astype(np.float32)


def court_polygon_mask(img, cam):
    """用 H_ground 把规范球场四角投影回图像，取其多边形为球场 footprint 掩码。"""
    Hc = cam.H_ground
    pts = []
    for (x, y) in [(-HALF_L, -HALF_W), (HALF_L, -HALF_W), (HALF_L, HALF_W), (-HALF_L, HALF_W)]:
        v = Hc @ np.array([x, y, 1.0])
        if abs(v[2]) < 1e-9:
            return None
        pts.append([v[0] / v[2], v[1] / v[2]])
    poly = np.array(pts, np.float32)
    if not np.all(np.isfinite(poly)):
        return None
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(m, [np.round(poly).astype(np.int32)], 255)
    return m


def line_pixels_and_dists(img, mask, cam, segs):
    """返回 (线像素布尔图, 这些像素到模型线的距离数组)。"""
    b = line_map(img, mask)
    for (x0, y0, x1, y1) in OVERLAY_BOXES:
        b[y0:y1, x0:x1] = 0
    line_px = b > 0
    dt = model_dist_map(img, segs, cam)
    return line_px, dt[line_px], dt


def report_decomp(tag, d, line_px, dt, rows=6, cols=8):
    n = len(d)
    if n == 0:
        print(f"  [{tag}] 无线像素")
        return
    q = np.percentile(d, [50, 75, 90])
    w5, w10, w20 = (float((d <= t).mean()) for t in (5, 10, 20))
    print(f"  [{tag}] 线像素数={n}  中位={q[0]:.1f} p75={q[1]:.1f} p90={q[2]:.1f}  "
          f"未截断均值={d.mean():.1f}  cap均值(R-like)={np.minimum(d, 30).mean():.2f}")
    print(f"       近距离占比: ≤5px {w5*100:.1f}%  ≤10px {w10*100:.1f}%  "
          f"≤20px {w20*100:.1f}%   >20px {100-w20*100:.1f}%")
    H, W = line_px.shape
    print(f"       网格（行=自上而下{rows}，列=自左而右{cols}）: 每格 密度/远端占比(F) 仅显示密度≥20的格")
    for r in range(rows):
        cells = []
        for c in range(cols):
            y0, y1 = int(H * r / rows), int(H * (r + 1) / rows)
            x0, x1 = int(W * c / cols), int(W * (c + 1) / cols)
            sub = line_px[y0:y1, x0:x1]
            cnt = int(sub.sum())
            if cnt < 20:
                cells.append("    ·    ")
            else:
                farf = float((dt[y0:y1, x0:x1][sub] > 20).mean())
                cells.append(f"{cnt:4d}/{farf*100:3.0f}%")
        print("       " + " ".join(cells))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("frame", type=int)
    ap.add_argument("--iters", type=int, default=2, help="footprint 收紧迭代轮数（默认2）")
    a = ap.parse_args()
    img_path = cr.frame_img(a.clip, a.frame)
    img = cv2.imread(str(img_path))
    if img is None:
        raise SystemExit(f"读不到 {img_path}")
    print(f"=== {a.clip} f{a.frame:05d}   {img_path}")

    P, segs = template(1)
    roi, _ = floor_roi(img)
    mask0 = roi.copy()
    for (x0, y0, x1, y1) in OVERLAY_BOXES:
        mask0[y0:y1, x0:x1] = 0

    # ---- 第一遍：默认 ROI ----
    print("\n[1] 默认 ROI 配准 …")
    p0, det0 = cr.register_frame(img_path, seed=None, require_ok=False)  # 诊断：拿到最佳位姿本身
    if p0 is None:
        print("  默认 ROI 配准失败：", det0)
        return
    print(f"  p0 detail = {det0}")
    cam0 = make_cam(p0)
    lp0, d0, dt0 = line_pixels_and_dists(img, mask0, cam0, segs)
    print("[1] 线像素来源分解（默认 ROI）")
    report_decomp("default", d0, lp0, dt0)

    # ---- 多轮 self-consistency 迭代：footprint 收紧 → 重配准 ----
    # 正当性：球场线只可能存在于球场 footprint 内，属物理先验，非「删掉解释不了的点」（后者会自证达标）。
    # 收敛判据：连续两轮位姿位移很小且 R 不再下降 ⇒ 停。
    prev_p = p0
    cur_mask = mask0
    hist = []
    for it in range(a.iters):
        pm = court_polygon_mask(img, make_cam(prev_p))
        if pm is None:
            print(f"\n[{it+1}] 无法构造球场多边形，停止迭代")
            break
        cur_mask = cv2.bitwise_and(mask0, pm)
        keep = int((cur_mask > 0).sum()) / max(int((mask0 > 0).sum()), 1)
        sc = Scorer(img, P, segs, cur_mask, verbose=(it == 0))
        raw = cf.grid_search(sc, 4)
        live = []
        for _, p in raw:
            s = sc.score(make_cam(p))
            if isinstance(s, tuple):
                s = s[0]
            if np.isfinite(s) and s < 1e5:
                live.append((float(s), tuple(p)))
        live.sort(key=lambda r: r[0])
        if not live:
            print(f"\n[{it+1}] 无有效候选，停止"); break
        finals = [cf.refine(sc, np.array(p, float)) for _, p in live[:4]]
        finals.sort(key=lambda r: r[0])
        s_cur, p_cur = finals[0]
        cam_cur = make_cam(p_cur)
        _, det = sc.score(cam_cur, ret_detail=True)
        fit = (det.get("F", 99) or 99) + (det.get("R", 99) or 99)
        dp = float(np.max(np.abs(np.array(p_cur) - np.array(prev_p))))
        hist.append((it + 1, round(float(det.get("R", 99)), 2), round(float(det.get("F", 99)), 2),
                     round(fit, 2), round(dp, 3)))
        print(f"[{it+1}] 保留ROI {keep*100:.1f}%  R={det.get('R'):.2f}  F={det.get('F'):.2f}  "
              f"fit={fit:.2f}  位姿位移max={dp:.3f}")
        if hist[-1][1] < 9.0:
            print("      → R 已降到个位数")
            prev_p = p_cur
            break
        prev_p = p_cur
        if dp < 0.05 and len(hist) >= 2 and hist[-1][1] >= hist[-2][1] - 0.1:
            print("      → 位姿已收敛且 R 不再下降，停止迭代")
            break

    lp1, d1, dt1 = line_pixels_and_dists(img, cur_mask, make_cam(prev_p), segs)
    print("[2] 最终线像素来源分解（收紧 ROI）")
    report_decomp("tight", d1, lp1, dt1)

    print("\n=== 结论 ===")
    print("  迭代历程 (round, R, F, fit, 位移):", hist)
    r0, r1 = det0.get("R"), hist[-1][1] if hist else None
    print(f"  R: 默认 {r0:.2f}  →  最终 {r1}")
    if hist and hist[-1][1] < 9.0:
        print("  判定：R 降到个位数 ⇒ 可继续打 B")
    else:
        print(f"  判定：R 仍为 {r1}（未降到个位数）⇒ 果断回 A，精力转回球事件/轨迹本身")
    print("  ⚠️ 提醒：footprint 收紧属物理先验（正当）；若再进一步『删掉解释不了的像素』则变自证达标，无效。")


if __name__ == "__main__":
    main()
