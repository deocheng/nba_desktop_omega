#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.25 场地模型 v7：平行边线(共同斜率取自远端上边界) + 油漆区宽边定 X 尺度。

老程要求：① 边线平行铁律 ② 保留老程认可的位置 ③ 基于视觉判断。
视觉证据(见 _see_fABC / _see_nABC 原生条带)：
  · 远端上边界 原始 RANSAC slope≈+0.062，与真实地板远沿吻合(左半幅 y≈147→640 处 187)。
  · 近端下边界 位置 y@W/2≈605 吻合，但其 RANSAC slope(-0.008) 被观众/字幕污染。
  ⇒ 两条边线取**共同斜率 +0.062**(远端=干净参照)，各自保留累积位置。
坐标：X=长度(0=底线→右) / Y=宽度(0=远边线, 15.24=近边线)，m。
用法: court_model_v7.py --seg ep24_s1 --idx 70 --freq _tmp_freq_ep24_s1_w0_93.npy
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
import court_infer_lines as CI  # noqa: E402
from court_homography_recover import fit_quad  # noqa: E402

COURT_L, COURT_W = 28.6512, 15.2400
KEY_W, KEY_D = 4.8768, 5.7912
KEY_Y0 = (COURT_W - KEY_W) / 2.0
BASKET = (1.6002, COURT_W / 2)
ARC_R, FT_R, RA_R = 7.239, 1.8288, 1.2192
CORNER_Y = 0.9144
_TH = np.arcsin(min(1.0, (COURT_W / 2 - CORNER_Y) / ARC_R))
ARC_X0 = BASKET[0] + ARC_R * np.cos(_TH)
ACC_TH = 0.7


def paint_quad(img):
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    raw = cv2.inRange(hsv, np.array([110, 60, 70]), np.array([170, 255, 255]))
    m = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((31, 31), np.uint8))
    keep = np.zeros_like(m)
    keep[int(0.25 * H):int(0.75 * H), int(0.06 * W):int(0.72 * W)] = 255
    m = cv2.bitwise_and(m, keep)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return None, None
    b = 1 + int(np.argmax(st[1:, 4]))
    mm = np.where(lab == b, 255, 0).astype(np.uint8)
    q = fit_quad(mm)
    return (None if q is None else np.asarray(q, float)), mm


def accum_lines(seg, freq_name, W):
    freq = np.load(str(OUT / freq_name))
    acc = (freq >= ACC_TH).astype(np.uint8)
    top, bot = [], []
    for x in range(0, W, 3):
        col = np.where(acc[:, x] > 0)[0]
        if len(col) >= 10:
            top.append((float(x), float(col.min())))
            bot.append((float(x), float(col.max())))
    return CI.ransac_line(top), CI.ransac_line(bot)


def seg_of(a, b, W):
    return (0.0, float(b), float(W - 1), float(a * (W - 1) + b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--freq", default="_tmp_freq_ep24_s1_w0_93.npy")
    ap.add_argument("--slope-src", choices=["far", "near", "mean"], default="far")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]

    r_top, r_bot = accum_lines(a.seg, a.freq, W)
    yt = r_top[0] * (W / 2) + r_top[1]
    yb = r_bot[0] * (W / 2) + r_bot[1]
    if a.slope_src == "far":
        m = r_top[0]
    elif a.slope_src == "near":
        m = r_bot[0]
    else:
        m = 0.5 * (r_top[0] + r_bot[0])
    sid_far = seg_of(m, yt - m * (W / 2), W)
    sid_near = seg_of(m, yb - m * (W / 2), W)

    q, mm = paint_quad(img)
    if q is None:
        print("油漆区未检出"); return
    order = np.argsort(q[:, 0])
    lft = q[order[:2]]; rgt = q[order[2:]]
    lft = lft[np.argsort(lft[:, 1])]; rgt = rgt[np.argsort(rgt[:, 1])]
    base_line = (float(lft[0][0]), float(lft[0][1]), float(lft[1][0]), float(lft[1][1]))
    ft_line = (float(rgt[0][0]), float(rgt[0][1]), float(rgt[1][0]), float(rgt[1][1]))

    print(f"=== A5.25 场地模型 v7 {a.seg} f{a.idx}  {W}x{H}  slope_src={a.slope_src} ===")
    print(f"  远端上边界 raw slope={r_top[0]:.4f} y@W/2={yt:.1f} | 近端下边界 raw slope={r_bot[0]:.4f} y@W/2={yb:.1f}")
    print(f"  采用共同斜率 m={m:.4f} ; 边线平行(设计)")

    c00 = CI.intersect(sid_far, base_line)
    c0W = CI.intersect(sid_near, base_line)
    cX0 = CI.intersect(sid_far, ft_line)
    cXW = CI.intersect(sid_near, ft_line)
    if any(v is None for v in (c00, c0W, cX0, cXW)):
        print("交点失败"); return
    img_c = np.array([c00, c0W, cXW, cX0], np.float32)
    world_c = np.array([[0.0, 0.0], [0.0, COURT_W], [KEY_D, COURT_W], [KEY_D, 0.0]], np.float32)
    Hm = cv2.getPerspectiveTransform(world_c, img_c)
    print(f"  锚点: 上∩底={np.int32(c00).tolist()} 下∩底={np.int32(c0W).tolist()} "
          f"上∩罚球线={np.int32(cX0).tolist()} 下∩罚球线={np.int32(cXW).tolist()}")

    def P(pts):
        pts = np.asarray(pts, np.float32).reshape(-1, 2)
        return cv2.perspectiveTransform(pts[None], Hm)[0]

    pf = P([[0, 0], [COURT_L, 0]])
    pn = P([[0, COURT_W], [COURT_L, COURT_W]])
    spf = (pf[1][1] - pf[0][1]) / (pf[1][0] - pf[0][0])
    spn = (pn[1][1] - pn[0][1]) / (pn[1][0] - pn[0][0])
    d_m = float(np.linalg.norm(P([[0, 1]])[0] - P([[0, 0]])[0]))
    d_l = float(np.linalg.norm(P([[1, COURT_W / 2]])[0] - P([[0, COURT_W / 2]])[0]))
    print(f"  自证 投影两边线 slope={spf:.5f}/{spn:.5f} 差={abs(spf-spn):.5f} "
          f"({'平行✅' if abs(spf-spn)<1e-3 else '⚠️'})")
    print(f"  比例尺 宽(Y)1m≈{d_m:.1f}px 长(X)1m≈{d_l:.1f}px")

    # ---- 渲染 ----
    vis = img.copy()
    cp = P([[0, 0], [COURT_L, 0], [COURT_L, COURT_W], [0, COURT_W]])
    mfill = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mfill, [np.int32(cp)], 255)
    ov = vis.copy(); ov[mfill > 0] = (0.82 * ov[mfill > 0] + 0.18 * np.array([0, 180, 255])).astype(np.uint8)
    vis = ov
    for xm in np.arange(0, COURT_L + 0.01, 1.0):
        p = P([[xm, 0], [xm, COURT_W]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (205, 150, 95), 1)
    for ym in np.arange(0, COURT_W + 0.01, 1.0):
        p = P([[0, ym], [COURT_L, ym]])
        cv2.line(vis, tuple(np.int32(p[0])), tuple(np.int32(p[1])), (205, 150, 95), 1)
    cv2.polylines(vis, [np.int32(cp)], True, (0, 215, 255), 3)
    cv2.line(vis, tuple(np.int32(P([[0, 0]])[0])), tuple(np.int32(P([[0, COURT_W]])[0])), (0, 215, 255), 5)
    ph = P([[COURT_L / 2, 0], [COURT_L / 2, COURT_W]])
    cv2.line(vis, tuple(np.int32(ph[0])), tuple(np.int32(ph[1])), (0, 255, 120), 2)
    key = P([[0, KEY_Y0], [KEY_D, KEY_Y0], [KEY_D, KEY_Y0 + KEY_W], [0, KEY_Y0 + KEY_W]])
    cv2.polylines(vis, [np.int32(key)], True, (255, 255, 255), 2)
    for ycor in (CORNER_Y, COURT_W - CORNER_Y):
        s = P([[0, ycor], [ARC_X0, ycor]])
        cv2.line(vis, tuple(np.int32(s[0])), tuple(np.int32(s[1])), (255, 80, 0), 3)
    t = np.linspace(-_TH, _TH, 120)
    arc = np.stack([BASKET[0] + ARC_R * np.cos(t), BASKET[1] + ARC_R * np.sin(t)], 1)
    cv2.polylines(vis, [np.int32(P(arc))], False, (255, 80, 0), 3)
    tt = np.linspace(0, 2 * np.pi, 120)
    ftc = np.stack([KEY_D + FT_R * np.cos(tt), COURT_W / 2 + FT_R * np.sin(tt)], 1)
    cv2.polylines(vis, [np.int32(P(ftc))], True, (255, 0, 255), 2)
    ra = np.stack([BASKET[0] + RA_R * np.cos(np.linspace(-np.pi / 2, np.pi / 2, 60)),
                   BASKET[1] + RA_R * np.sin(np.linspace(-np.pi / 2, np.pi / 2, 60))], 1)
    cv2.polylines(vis, [np.int32(P(ra))], False, (255, 255, 0), 2)
    cv2.circle(vis, tuple(np.int32(P([list(BASKET)])[0])), 8, (0, 0, 255), -1)
    # 参考线：边线(灰, 采用) / 油漆区左右边(白细)
    for s4 in (sid_far, sid_near):
        cv2.line(vis, tuple(np.int32(s4[:2])), tuple(np.int32(s4[2:])), (150, 150, 150), 2)
    cs, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, cs, -1, (0, 255, 255), 1)

    txt = ["黄=场地/底线 蓝=三分线 品红=罚球圈 青=冲撞区 白=油漆区 绿=半场线 红=篮筐 灰=采用边线",
           f"共同斜率 m={m:.4f}(取自{'远端' if a.slope_src=='far' else a.slope_src}) 宽{d_m:.0f}px/m 长{d_l:.0f}px/m"]
    for i, s in enumerate(txt):
        cv2.putText(vis, s, (10, 26 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (0, 0, 0), 4)
        cv2.putText(vis, s, (10, 26 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (0, 255, 255), 2)
    op = OUT / f"{a.seg}_f{a.idx}_model_v7_{a.slope_src}.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")


if __name__ == "__main__":
    main()
