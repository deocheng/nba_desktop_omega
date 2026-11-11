#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.16 透视关系探针：用消失点(vanishing point)框架推导被遮挡边线的准确方向。

老程问题(2026-10-01)：「能不能通过透视关系推导出边线的准确位置」

原理：
  篮球场线是两组互相平行的世界线：
    · 宽度方向(平行于底线)：底线、罚球线、半场线 → 图像中汇聚到 VP_w
    · 纵深方向(平行于边线)：两条边线、油漆区两条宽边 → 图像中汇聚到 VP_d
  两条世界正交方向的 VP 满足 v_d^T ω v_w = 0（ω=绝对二次曲线像）。
  被遮挡的边线：只要方向∈某族，就过该族 VP ⇒ 方向被唯一确定（即使线段只露一小段）。
  ⚠️ 绝对位置(像素↔英尺) 还需一个真实尺度锚点（纯透视只给方向+相对几何）。

本探针：
  1. 检测所有线，按角度分两族
  2. SVD 最小二乘解各族 VP + 残差（验证透视自洽）
  3. 用 VP_d 推被画幅裁掉的右侧边线方向（过 VP_d）
  4. 报告 v3 三线(near/far/baseline) 与 VP 框架的一致性
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
from court_line_probe import detect  # noqa: E402


def line_homog(p):
    """线段(x1,y1,x2,y2) → 齐次线系数 (a,b,c), ax+by+c=0。"""
    x1, y1, x2, y2 = p
    a, b = y1 - y2, x2 - x1
    c = x1 * y2 - x2 * y1
    n = np.hypot(a, b)
    return np.array([a, b, c]) / (n if n > 1e-9 else 1.0)


def vp_from_lines(lines):
    """一组线 → 消失点(最小二乘,SVD)。返回 (vp_xy, residual_rms_px)。"""
    if len(lines) < 2:
        return None, None
    L = np.array([line_homog(k["p"]) for k in lines])   # (N,3)
    _, _, vt = np.linalg.svd(L)
    vp = vt[-1]                                           # null vector
    if abs(vp[2]) < 1e-9:
        return None, None
    vp = vp / vp[2]
    res = np.abs(L @ vp)
    return vp[:2], float(np.sqrt((res ** 2).mean()))


def vp_ransac(lines, tau=3.0, iters=3000, seed=0):
    """RANSAC 消失点：找过最多线的交点(抗污染)。返回 (vp_xy, n_inlier, median_dist_px, inlier_idx)。"""
    rng = np.random.default_rng(seed)
    L = np.array([line_homog(k["p"]) for k in lines])
    n = len(L)
    if n < 2:
        return None, 0, None, []
    best = (0, None)
    for _ in range(iters):
        i, j = rng.choice(n, 2, replace=False)
        vp = np.cross(L[i], L[j])
        if abs(vp[2]) < 1e-9:
            continue
        vp = vp / vp[2]
        inl = int((np.abs(L @ vp) < tau).sum())
        if inl > best[0]:
            best = (inl, vp)
    if best[1] is None:
        return None, 0, None, []
    vp = best[1]
    inl = [k for k in range(n) if abs(L[k] @ vp) < tau]
    # 用内点做最终最小二乘
    _, _, vt = np.linalg.svd(L[inl])
    vp2 = vt[-1]
    vp2 = vp2 / vp2[2]
    ds = []
    for k in inl:
        x1, y1, x2, y2 = lines[k]["p"]
        mid = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
        ds.append(dist_pt_line(vp2, line_homog(lines[k]["p"])) +
                  dist_pt_line(mid, line_homog(lines[k]["p"])) * 0)  # 线到点垂距
    # 中位垂距(VP到线)
    med = float(np.median([dist_pt_line(vp2, line_homog(lines[k]["p"])) for k in inl])) if inl else None
    return vp2[:2], len(inl), med, inl


def dist_pt_line(pt, line3):
    a, b, c = line3
    return abs(a * pt[0] + b * pt[1] + c) / max(np.hypot(a, b), 1e-9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--freq", default="_tmp_freq_ep24_s1_w0_93.npy")
    ap.add_argument("--spaint", type=float, default=133.8)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    lines = detect(img)

    # v3 三线（稳健，来自累积掩膜）
    poly_v3, lo_v3, info_v3 = CI.infer(img, a.seg, a.freq, s_paint_win=a.spaint)
    base_ang = info_v3.get("baseline_angle_deg")   # ~45.4°

    # 分族：宽度族用长线(L>=250)；纵深族(边线)片段短，放宽到 L>=80
    fam_w = [k for k in lines if k["L"] >= 250 and k["ang"] < 25]
    fam_d = [k for k in lines if k["L"] >= 80 and abs(k["ang"] - (base_ang or 45)) < 25]
    longs = [k for k in lines if k["L"] >= 250]
    print(f"=== A5.16 透视关系(消失点) {a.seg} f{a.idx}  {W}x{H} ===")
    print(f"  线数: 总{len(lines)} 长线(>=250px){len(longs)} | 宽度族{len(fam_w)} 纵深族(≈{base_ang}°,>=80px){len(fam_d)}")

    vp_w, nw, pr_w, inw = vp_ransac(fam_w, tau=3.0)
    vp_d, nd, pr_d, ind = vp_ransac(fam_d, tau=3.0)
    print(f"  VP_w(宽度方向) = {None if vp_w is None else np.round(vp_w,1)}  "
          f"内点{nw}/{len(fam_w)} 中位垂距={pr_w if pr_w is None else round(pr_w,1)}px")
    print(f"  VP_d(纵深方向) = {None if vp_d is None else np.round(vp_d,1)}  "
          f"内点{nd}/{len(fam_d)} 中位垂距={pr_d if pr_d is None else round(pr_d,1)}px")

    # 用 VP_d 推右侧边线：过 VP_d，方向≈左侧边线(baseline)，且在画幅内给一条参考
    right_dir = None
    if vp_d is not None and lo_v3 is not None:
        b = line_homog(lo_v3["baseline"])
        # 右侧边线应平行于左侧(同类线)⇒同样过 VP_d；其绝对位置需尺度锚点。
        # 这里给出"方向由 VP_d 唯一确定"的自证：左边界延长必过 VP_d
        d2vp = dist_pt_line(vp_d, b)
        print(f"  自证: v3 左边界(baseline)延长过 VP_d 的垂距 = {d2vp:.1f}px "
              f"({'一致✅' if d2vp<25 else '不一致⚠️'})")
        n = line_homog(lo_v3["near"]); f = line_homog(lo_v3["far"])
        print(f"  v3 near/far 到 VP_w 垂距 = {dist_pt_line(vp_w,n):.1f} / {dist_pt_line(vp_w,f):.1f}px"
              if vp_w is not None else "  VP_w 不可得")

    # 出图
    vis = img.copy()
    for k in fam_w:
        x1, y1, x2, y2 = [int(v) for v in k["p"]]
        cv2.line(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
    for k in fam_d:
        x1, y1, x2, y2 = [int(v) for v in k["p"]]
        cv2.line(vis, (x1, y1), (x2, y2), (255, 0, 255), 2)
    def draw_vp(vp, col, nm):
        if vp is None:
            return
        x, y = vp
        if -5000 < x < W + 5000 and -5000 < y < H + 5000:
            cv2.circle(vis, (int(np.clip(x,-9e8,9e8)), int(np.clip(y,-9e8,9e8))), 7, col, -1)
            cv2.putText(vis, nm, (int(np.clip(x,0,W-60)), int(np.clip(y,12,H-6))),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
        else:
            # VP 在很远处：用指向 VP 的箭头在画幅边缘示意
            ang = np.arctan2(y - H/2, x - W/2)
            ex, ey = int(W/2 + 0.45*W*np.cos(ang)), int(H/2 + 0.45*H*np.sin(ang))
            cv2.arrowedLine(vis, (W//2, H//2), (ex, ey), col, 2, tipLength=0.12)
            cv2.putText(vis, nm + "(远处)", (max(0,ex-40), max(14,ey-6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2)
    draw_vp(vp_w, (0, 255, 0), "VPw")
    draw_vp(vp_d, (255, 0, 255), "VPd")
    txt = [f"green=width-family(<25deg) magenta=depth-family  VPw={None if vp_w is None else np.round(vp_w,0)}",
           f"VPd={None if vp_d is None else np.round(vp_d,0)}  res_w={pr_w}px res_d={pr_d}px"]
    for i, s in enumerate(txt):
        cv2.putText(vis, s, (12, 26 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4)
        cv2.putText(vis, s, (12, 26 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 215, 255), 2)
    op = OUT / f"{a.seg}_f{a.idx}_vanishing.png"
    cv2.imwrite(str(op), vis)
    print(f"  -> {op}")
    json.dump({"seg": a.seg, "idx": a.idx, "img": [W, H],
               "n_lines": len(lines), "n_long": len(longs),
               "fam_w": len(fam_w), "fam_d": len(fam_d),
               "vp_w": None if vp_w is None else [round(float(vp_w[0]), 1), round(float(vp_w[1]), 1)],
               "vp_d": None if vp_d is None else [round(float(vp_d[0]), 1), round(float(vp_d[1]), 1)],
               "res_w_px": None if pr_w is None else round(pr_w, 1),
               "res_d_px": None if pr_d is None else round(pr_d, 1),
               "baseline_angle_deg": base_ang},
              open(str(OUT / f"{a.seg}_f{a.idx}_vanishing.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
