#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.15+ 老程想法(正解版)：用「v3 累积掩膜稳健推断的场地边线」作锚点 + 已知场地真实尺寸 → 单应恢复完整虚拟场地边线 + 数值比例尺。

为什么不用油漆区 4 角单独做（court_homography_recover / court_homography_scale）：
  单应从 4 个油漆区角点标定，但颜色法检测的油漆区四边形噪声大，
  在全场 94×50ft 尺度上被放大 → 与 v3 边线差 300-440px（已证伪）。
  本版改用 v3 边线（near/far/baseline/right，50 帧累积证据，containment≈96%）作主锚点，
  已知场地尺寸 (50ft×94ft) 给绝对尺度；油漆区角点(已知世界位置)作尺度校验。

锚点对应（半场广播视角，相机在近端底线后方）：
  v3.near(最下长线) ↔ 世界 近端底线 x=0
  v3.far(累积掩膜上边界) ↔ 世界 远端可见线 x=Xf (默认半场线 47ft=14.33m)
  v3.baseline(累积掩膜左边界) ↔ 世界 左侧边线 y=0
  v3.right(画幅右缘) ↔ 世界 右侧边线 y=15.24m
  ⇒ 4 角 ↔ 世界矩形 4 角 → 单应 (过定，因另有油漆区校验)

输出：完整虚拟场地(黄) + 关键结构 + 1m网格 + 比例尺 + 与 v3 边线/油漆区自证。
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
import court_homography_recover as HR  # noqa: E402
import court_infer_lines as CI  # noqa: E402

COURT_L, COURT_W = HR.COURT_L, HR.COURT_W          # 28.65 × 15.24 m
HALF = COURT_L / 2.0                                 # 14.33 m (半场线, 默认远端可见线)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--freq", default="_tmp_freq_ep24_s1_w0_93.npy")
    ap.add_argument("--spaint", type=float, default=133.8)
    ap.add_argument("--xf", type=float, default=HALF, help="远端可见线世界x(默认半场线)")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    # ---- v3 稳健边线 ----
    poly_v3, lo_v3, info_v3 = CI.infer(img, a.seg, a.freq, s_paint_win=a.spaint)
    if lo_v3 is None:
        print("v3 推断失败:", info_v3.get("why")); return
    near, far, base = lo_v3["near"], lo_v3["far"], lo_v3["baseline"]
    right = (float(W - 1), 0.0, float(W - 1), float(H - 1))

    c_nb = CI.intersect(near, base); c_nr = CI.intersect(near, right)
    c_fb = CI.intersect(far, base);  c_fr = CI.intersect(far, right)
    if any(p is None for p in (c_nb, c_nr, c_fb, c_fr)):
        print("v3 边线交点缺失"); return
    img_corners = np.array([c_nb, c_nr, c_fb, c_fr], np.float32)   # 下左,下右,上左,上右

    # 油漆区检测(已知世界位置, 用于标定深度尺度 Xf)
    pm = HR.paint_mask(img); qk = HR.fit_quad(pm)
    qa = np.asarray(qk, float)
    idx = np.argsort(qa[:, 1]); up = qa[idx[:2]]; up = up[np.argsort(up[:, 0])]
    dn = qa[idx[2:]]; dn = dn[np.argsort(dn[:, 0])]
    det_key = np.array([up[0], up[1], dn[1], dn[0]], float)   # 检测角(上左,上右,下右,下左)
    world_key = np.array([[0.0, HR.KEY_Y0], [0.0, HR.KEY_Y0 + HR.KEY_W],
                          [HR.KEY_D, HR.KEY_Y0 + HR.KEY_W], [HR.KEY_D, HR.KEY_Y0]], np.float32)

    # 搜 Xf(远端可见线世界深度)：使投影油漆区↔检测最小误差 → 用已知 5.79m 纵深标定
    best = None
    for Xf in np.arange(8.0, COURT_L / 2 + 0.01, 0.25):
        wc = np.array([[0.0, 0.0], [0.0, COURT_W], [Xf, 0.0], [Xf, COURT_W]], np.float32)
        Ht = cv2.getPerspectiveTransform(wc, img_corners)
        kp = cv2.perspectiveTransform(world_key[None], Ht)[0]
        err = float(np.abs(kp - det_key).max())
        if best is None or err < best[0]:
            best = (err, Xf, Ht)
    key_err0, Xf, Hm = best
    world_corners = np.array([[0.0, 0.0], [0.0, COURT_W], [Xf, 0.0], [Xf, COURT_W]], np.float32)
    if a.xf != HALF:
        # 用户强制指定 Xf
        wc = np.array([[0.0, 0.0], [0.0, COURT_W], [a.xf, 0.0], [a.xf, COURT_W]], np.float32)
        Hm = cv2.getPerspectiveTransform(wc, img_corners)
        Xf = a.xf

    # ---- 投影完整虚拟场地 ----
    cw = np.array([[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]], np.float32)
    cproj = cv2.perspectiveTransform(cw[None], Hm)[0]
    half = cv2.perspectiveTransform(np.array([[[Xf, 0], [Xf, COURT_W]]], np.float32), Hm)[0]
    left = cv2.perspectiveTransform(np.array([[[0, 0], [COURT_L, 0]]], np.float32), Hm)[0]
    rightp = cv2.perspectiveTransform(np.array([[[0, COURT_W], [COURT_L, COURT_W]]], np.float32), Hm)[0]

    # ---- 比例尺 ----
    p0 = cv2.perspectiveTransform(np.array([[[0.0, 0.0]]], np.float32), Hm)[0][0]
    p1 = cv2.perspectiveTransform(np.array([[[0.0, 1.0]]], np.float32), Hm)[0][0]
    d_m = float(np.linalg.norm(p1 - p0))
    q0 = cv2.perspectiveTransform(np.array([[[0.0, COURT_W / 2]]], np.float32), Hm)[0][0]
    q1 = cv2.perspectiveTransform(np.array([[[1.0, COURT_W / 2]]], np.float32), Hm)[0][0]
    d_l = float(np.linalg.norm(q1 - q0))

    # ---- 油漆区尺度校验：投影已知世界油漆区 ↔ 检测油漆区(用已算 det_key/world_key) ----
    key_proj = cv2.perspectiveTransform(world_key[None], Hm)[0]
    key_err = float(np.abs(key_proj - det_key).max())

    # v3 边线自证：4 角应回到原处(构造保真)
    back = cv2.perspectiveTransform(world_corners[None], Hm)[0]
    corner_err = float(np.abs(back - img_corners).max())

    print(f"=== A5.15+ v3边线锚定单应 {a.seg} f{a.idx} ===")
    print(f"  标定远端线 Xf={Xf:.2f}m (搜值使油漆区投影↔检测最小, 误差={key_err0:.1f}px)")
    print(f"  比例尺(近端, 沿宽): 1m≈{d_m:.1f}px  1ft≈{d_m/0.3048:.1f}px")
    print(f"  比例尺(近端, 沿纵深): 1m≈{d_l:.1f}px")
    print(f"  球场宽15.24m≈{15.24*d_m:.0f}px  长28.65m≈{28.65*d_l:.0f}px")
    print(f"  自证: v3四角重投影误差={corner_err:.2f}px  油漆区投影↔检测最大误差={key_err:.1f}px")
    kc_det = det_key.mean(0); kc_proj = key_proj.mean(0)
    print(f"  归因诊断: 检测油漆区中心=({kc_det[0]:.0f},{kc_det[1]:.0f})  "
          f"单应投影真油漆区中心=({kc_proj[0]:.0f},{kc_proj[1]:.0f})  偏移={np.linalg.norm(kc_proj-kc_det):.0f}px")
    print(f"  v3: containment={info_v3.get('containment')} coverage={info_v3.get('coverage')} "
          f"baseline_angle={info_v3.get('baseline_angle_deg')} ratio_dev={info_v3.get('ratio_dev_pct')}%")

    # ---- 出图 ----
    vis = img.copy()
    cv2.polylines(vis, [cproj.astype(np.int32)], True, (0, 215, 255), 3)
    cv2.line(vis, tuple(np.int32(half[0])), tuple(np.int32(half[1])), (0, 160, 220), 2)
    cv2.line(vis, tuple(np.int32(left[0])), tuple(np.int32(left[1])), (0, 160, 220), 2)
    cv2.line(vis, tuple(np.int32(rightp[0])), tuple(np.int32(rightp[1])), (0, 160, 220), 2)
    def proj(pts):
        return cv2.perspectiveTransform(np.asarray([pts], np.float32), Hm)[0]
    def circle(cx, cy, r, n=180, a0=0.0, a1=np.pi):
        t = np.linspace(a0, a1, n); return np.stack([cx + r*np.cos(t), cy + r*np.sin(t)], 1)
    BSK = (1.575, COURT_W/2)
    for pts, col in [(circle(HR.KEY_D, COURT_W/2, 1.8288, 181), (255, 0, 255)),
                     (circle(BSK[0], BSK[1], 7.239, 181, -np.pi/2, np.pi/2), (0, 255, 0)),
                     (circle(BSK[0], BSK[1], 1.2192, 91, -np.pi/2, np.pi/2), (255, 255, 0))]:
        cv2.polylines(vis, [proj(pts).astype(np.int32)], False, col, 2)
    for xm in np.arange(0, COURT_L+0.01, 1.0):
        p = cv2.perspectiveTransform(np.array([[[xm, 0], [xm, COURT_W]]], np.float32), Hm)
        cv2.line(vis, tuple(np.int32(p[0][0])), tuple(np.int32(p[0][1])), (255, 120, 0), 1)
    for ym in np.arange(0, COURT_W+0.01, 1.0):
        p = cv2.perspectiveTransform(np.array([[[0, ym], [COURT_L, ym]]], np.float32), Hm)
        cv2.line(vis, tuple(np.int32(p[0][0])), tuple(np.int32(p[0][1])), (255, 120, 0), 1)
    # v3 边线(虚线对照)
    CI.draw_ext(vis, near, (0, 255, 0)); CI.draw_ext(vis, far, (0, 255, 255))
    CI.draw_ext(vis, base, (255, 0, 255))
    txt = [(f"1m≈{d_m:.0f}px(宽) {d_l:.0f}px(纵) | 1ft≈{d_m/0.3048:.0f}px | Xf={Xf:.1f}m",
           (12, 28), (0, 215, 255)),
          (f"key_err={key_err:.0f}px corner_err={corner_err:.1f}px | 黄=虚拟场地 橙=1m网格 绿青品红=v3",
           (12, 56), (0, 215, 255))]
    for s, pos, col in txt:
        cv2.putText(vis, s, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4)
        cv2.putText(vis, s, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.62, col, 2)
    op = OUT / f"{a.seg}_f{a.idx}_homog_v3.png"
    cv2.imwrite(str(op), vis)
    print(f"  -> {op}")
    json.dump({"seg": a.seg, "idx": a.idx, "xf_m": round(Xf, 2), "xf_search_err_px": round(key_err0, 1),
               "px_per_m_width": round(d_m, 1), "px_per_m_length": round(d_l, 1),
               "px_per_ft_width": round(d_m/0.3048, 1),
               "court_W_px": round(15.24*d_m, 0), "court_L_px": round(28.65*d_l, 0),
               "v3_corner_reproj_px": round(corner_err, 2),
               "paintkey_proj_vs_det_px": round(key_err, 1),
               "v3": {k: info_v3.get(k) for k in ("containment", "coverage", "baseline_angle_deg", "ratio_dev_pct")}},
              open(str(OUT / f"{a.seg}_f{a.idx}_homog_v3.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
