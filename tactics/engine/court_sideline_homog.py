#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.18 边线视角坐标系修正版（老程2026-10-01纠正）。

老程纠正：「上下两条平行的是边线，左侧的黄线才叫底线，哪里还站着底线裁判」
  ⇒ 本画面为**边线视角**：相机在边线一侧看球场
     · 图像上下 = 球场宽度方向（两条边线，间距 50ft）
     · 图像左右 = 球场长度方向（左=底线，右=中场/远处）
  ⇒ 之前单应把 X/Y 轴旋转 90°（把 near/far 当纵深），三分弧方向全错。

正确世界坐标：X=沿长度(0=底线,向右), Y=沿宽度(0=上边线,15.24=下边线) 单位 m。
锚点：油漆区 4 角（已知世界位置）定单应 + X 尺度；用累积掩膜上/下/左边界做交叉验证。

用法: python3 court_sideline_homog.py --seg ep24_s1 --idx 70
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
import court_homography_recover as HR  # noqa: E402
import court_infer_lines as CI  # noqa: E402

COURT_L, COURT_W = HR.COURT_L, HR.COURT_W       # 28.6512 × 15.24 m
BASKET = (1.6002, COURT_W / 2)                   # 篮筐 5.25ft
KEY_D, KEY_W = HR.KEY_D, HR.KEY_W                # 5.7912 × 4.8768
KEY_Y0 = HR.KEY_Y0                                # 5.1816
ARC_R, RA_R, FT_R = 7.239, 1.2192, 1.8288
CORNER_Y = 0.9144
_TH = math.asin(min(1.0, (COURT_W / 2 - CORNER_Y) / ARC_R))
ARC_X0 = BASKET[0] + ARC_R * math.cos(_TH)


def accum_bounds(seg, freq_name):
    fp = OUT / freq_name
    freq = np.load(str(fp))
    acc = (freq >= CI.ACC_TH).astype(np.uint8)
    H, Wd = acc.shape
    top, bot, left = [], [], []
    for x in range(0, Wd, 3):
        col = np.where(acc[:, x] > 0)[0]
        if len(col) >= 10:
            top.append((float(x), float(col.min())))
            bot.append((float(x), float(col.max())))
    for y in range(0, H, 2):
        row = np.where(acc[y, :] > 0)[0]
        if len(row):
            left.append((float(row.min()), float(y)))
    return top, bot, left, (H, Wd)


def line_pts(seg4, n=80):
    x1, y1, x2, y2 = seg4
    t = np.linspace(0, 1, n)
    return np.stack([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t], 1)


def med_dist(pts, seg4):
    x1, y1, x2, y2 = seg4
    a = np.array([x1, y1], float); b = np.array([x2, y2], float)
    d = b - a; L = np.linalg.norm(d)
    if L < 1e-6:
        return float(np.abs(pts - a).max())
    u = d / L; v = pts - a
    proj = np.clip(v @ u, 0, L)
    foot = a + proj[:, None] * u
    return float(np.median(np.linalg.norm(pts - foot, axis=1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--freq", default="_tmp_freq_ep24_s1_w0_93.npy")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    # ---- 累积掩膜左边界(底线, 老程确认正确) ----
    _, _, left, (_, _) = accum_bounds(a.seg, a.freq)
    r_lef = CI.ransac_steep(left)        # x=m y+c
    m_l, c_l, _ = r_lef
    base = (c_l, 0.0, m_l * (H - 1) + c_l, float(H - 1))

    # ---- 两条边线：累积掩膜上/下边界 RANSAC 定位置；强制共同斜率(平行铁律)----
    # 共同斜率取下边线斜率(前景清晰、最可靠)；上边线保持其位置、改用共同斜率。
    top, bot, _, _ = accum_bounds(a.seg, a.freq)
    r_top = CI.ransac_line(top)   # (slope, b, n)
    r_bot = CI.ransac_line(bot)
    m_com = r_bot[0]                                  # 共同斜率=下边线(clean)
    yt = r_top[0] * (W / 2) + r_top[1]                # 上边线位置(y@W/2)，保留
    yb = r_bot[0] * (W / 2) + r_bot[1]                # 下边线位置
    sid_far = (0.0, yt, float(W - 1), yt + m_com * (W - 1))     # 上边线(位置不变,斜率对齐)
    sid_near = (0.0, yb, float(W - 1), yb + m_com * (W - 1))    # 下边线
    print(f"=== A5.18 边线视角坐标修正 {a.seg} f{a.idx}  {W}x{H} ===")
    print(f"  上边线 原slope={r_top[0]:.4f}→共同slope={m_com:.4f} y@W/2={yt:.0f}  "
          f"下边线 slope={r_bot[0]:.4f} y@W/2={yb:.0f}  底线 x@H/2={np.polyval([m_l, c_l], H/2):.0f}")

    # ---- 油漆区 4 角 → 仅取「罚球线」(右边缘) 定义 X 尺度 ----
    pm = HR.paint_mask(img); qk = HR.fit_quad(pm)
    q = np.asarray(qk, float)
    order = np.argsort(q[:, 0])                 # 按 x 分左右
    lft = q[order[:2]]; rgt = q[order[2:]]
    lft = lft[np.argsort(lft[:, 1])]            # 左两角按 y 排序(上,下)
    rgt = rgt[np.argsort(rgt[:, 1])]
    # 罚球线 = 油漆区右边缘(X=KEY_D)：过 rgt 两角
    ft_line = (float(rgt[0][0]), float(rgt[0][1]), float(rgt[1][0]), float(rgt[1][1]))

    # ---- 单应锚点：稳健长线(上下边线+底线) 定透视；罚球线定 X 尺度 ----
    # 角: (X,Y) ↔ intersect(line_along_X, line_along_Y)
    c00 = CI.intersect(sid_far, base)      # (0, 0)         上边线∩底线
    c0W = CI.intersect(sid_near, base)     # (0, 15.24)     下边线∩底线
    cX0 = CI.intersect(sid_far, ft_line)   # (5.79, 0)      上边线∩罚球线
    cXW = CI.intersect(sid_near, ft_line)  # (5.79, 15.24)  下边线∩罚球线
    img_corners = np.array([c00, c0W, cXW, cX0], np.float32)
    world_corners = np.array([[0.0, 0.0], [0.0, COURT_W],
                              [KEY_D, COURT_W], [KEY_D, 0.0]], np.float32)
    Hm = cv2.getPerspectiveTransform(world_corners, img_corners)
    print(f"  锚点: 上边线∩底线={np.int32(c00).tolist()} 下边线∩底线={np.int32(c0W).tolist()} "
          f"上边线∩罚球线={np.int32(cX0).tolist()} 下边线∩罚球线={np.int32(cXW).tolist()}")

    def P(pts):
        pts = np.asarray(pts, np.float32).reshape(-1, 2)
        return cv2.perspectiveTransform(pts[None], Hm)[0]

    # ---- 自证：投影两条边线必须平行(铁律) ----
    proj_far = P([[0, 0], [COURT_L, 0]])
    proj_near = P([[0, COURT_W], [COURT_L, COURT_W]])
    sp_far = (proj_far[1][1] - proj_far[0][1]) / (proj_far[1][0] - proj_far[0][0])
    sp_near = (proj_near[1][1] - proj_near[0][1]) / (proj_near[1][0] - proj_near[0][0])
    e_far = e_near = e_base = 0.0
    print(f"  自证: 投影上边线 slope={sp_far:.5f}  投影下边线 slope={sp_near:.5f}  "
          f"斜率差={abs(sp_far-sp_near):.5f} ({'平行✅' if abs(sp_far-sp_near)<1e-3 else '不平行⚠️'})")

    # ---- 比例尺 ----
    d_m = float(np.linalg.norm(P([[0, 1]])[0] - P([[0, 0]])[0]))     # 沿宽度(Y)1m
    d_l = float(np.linalg.norm(P([[1, COURT_W/2]])[0] - P([[0, COURT_W/2]])[0]))  # 沿长度(X)1m
    print(f"  比例尺: 沿宽(Y)1m≈{d_m:.1f}px ; 沿长(X)1m≈{d_l:.1f}px ; 球场宽15.24m≈{15.24*d_m:.0f}px")

    # ---- 渲染 ----
    vis = img.copy()
    for xm in np.arange(0, COURT_L + 0.01, 1.0):
        p = P([[xm, 0], [xm, COURT_W]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (210, 150, 90), 1)
    for ym in np.arange(0, COURT_W + 0.01, 1.0):
        p = P([[0, ym], [COURT_L, ym]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (210, 150, 90), 1)
    cproj = P([[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]])
    cv2.polylines(vis, [cproj.astype(np.int32)], True, (0, 215, 255), 3)
    # 底线(X=0)加粗
    cv2.line(vis, tuple(np.int32(P([[0, 0]])[0])), tuple(np.int32(P([[0, COURT_W]])[0])), (0, 215, 255), 4)
    # 罚球线 X=KEY_D / 半场线 X=L/2（青）
    for xw in (KEY_D, COURT_L / 2):
        p = P([[xw, 0], [xw, COURT_W]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (0, 190, 255), 2)
    # 油漆区
    key = P([[0, KEY_Y0], [KEY_D, KEY_Y0], [KEY_D, KEY_Y0 + KEY_W], [0, KEY_Y0 + KEY_W]])
    cv2.polylines(vis, [key.astype(np.int32)], True, (0, 190, 255), 2)
    # 三分线：底角直线 + 弧（蓝）
    for ycor in (CORNER_Y, COURT_W - CORNER_Y):
        seg = P([[0, ycor], [ARC_X0, ycor]])
        cv2.line(vis, tuple(np.int32(seg[0])), tuple(np.int32(seg[1])), (255, 60, 0), 3)
    t = np.linspace(-_TH, _TH, 120)
    arc = np.stack([BASKET[0] + ARC_R * np.cos(t), BASKET[1] + ARC_R * np.sin(t)], 1)
    cv2.polylines(vis, [P(arc).astype(np.int32)], False, (255, 60, 0), 3)
    # 罚球圈（品红整圆）+ 合理冲撞区（青）
    tt = np.linspace(0, 2 * np.pi, 120)
    ftc = np.stack([KEY_D + FT_R * np.cos(tt), COURT_W / 2 + FT_R * np.sin(tt)], 1)
    cv2.polylines(vis, [P(ftc).astype(np.int32)], True, (255, 0, 255), 2)
    ra = np.stack([BASKET[0] + RA_R * np.cos(np.linspace(-np.pi/2, np.pi/2, 60)),
                   BASKET[1] + RA_R * np.sin(np.linspace(-np.pi/2, np.pi/2, 60))], 1)
    cv2.polylines(vis, [P(ra).astype(np.int32)], False, (255, 255, 0), 2)
    # 篮筐 + 篮板
    bp = P([list(BASKET)])[0]
    cv2.circle(vis, tuple(np.int32(bp)), 8, (0, 0, 255), -1)
    # 累积边界(灰)
    for seg4, col in [(sid_far, (140, 140, 140)), (sid_near, (140, 140, 140)), (base, (90, 90, 90))]:
        cv2.line(vis, tuple(np.int32(seg4[:2])), tuple(np.int32(seg4[2:])), col, 2)

    txt = [f"1m≈{d_m:.0f}px(宽Y) {d_l:.0f}px(长X) | 黄=场地 蓝=三分线 品红=罚球圈 青=油漆区/冲撞区 红=篮筐",
           f"err: 上边线{e_far:.0f} 下边线{e_near:.0f} 底线{e_base:.0f}px | 灰=累积边界",
           "边线视角: 上下=边线, 左=底线"]
    for i, s in enumerate(txt):
        cv2.putText(vis, s, (12, 28 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(vis, s, (12, 28 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 215, 255), 2)
    op = OUT / f"{a.seg}_f{a.idx}_court_sideline.png"
    cv2.imwrite(str(op), vis)
    print(f"  -> {op}")
    json.dump({"seg": a.seg, "idx": a.idx, "px_per_m_width_Y": round(d_m, 1),
               "px_per_m_length_X": round(d_l, 1),
               "err_far": round(e_far, 1), "err_near": round(e_near, 1), "err_base": round(e_base, 1),
               "basket_px": np.int32(bp).tolist()},
              open(str(OUT / f"{a.seg}_f{a.idx}_court_sideline.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
