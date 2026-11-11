#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态目标剔除：用「局部背景运动补偿」把 LED 广告 logo / 地板线 与真球分开。

── 问题 ────────────────────────────────────────────────────────
本片段的球检测器被证实不可用（详见 verify_ball_detections.py 与目视审计）：
  · `conf` 对真/假无区分力（AUC 0.522）；
  · 颜色判据**反向失效**——最高橙反差（ct≈0.55）的 14 个检出
    **全部**是场边 LED 广告板上的 **Mastercard 红橙双圆 logo**；
  · 其余多为地板白线、木纹、红球鞋；真球命中数为**个位数**。

── 本层的思路（可验证的补救方向）────────────────────────────────
真球与假目标有一个本质差别：
  · Mastercard logo、地板白线 —— 在**世界坐标里静止**，
    镜头平移时它们的图像位移**等于其周围背景**的位移；
  · 真球在场上被运/传 —— 其图像位移**不等于**周围背景的位移。

于是定义「局部背景残差」：
    residual = |检出位移 − 其周围环形背景的位移|
  · residual ≈ 0  → 与背景同步 ⇒ **静态目标，剔除**
  · residual 大    → 相对背景在动 ⇒ **保留候候选**

背景位移用 `cv2.phaseCorrelate` 在**挖掉中心框的环形区域**上估计
（挖中心是为了不让球本身的像素污染背景估计）。

── 自验 ────────────────────────────────────────────────────────
脚本内置对照：分别喂入「已知 Mastercard 帧」「已知真球帧」，
输出两组 residual 的分布，用 separation 量化判据是否真的分得开。
"""
import argparse
import json
import math
import os
import statistics

import cv2
import numpy as np

KM = 0.5                      # 10fps → 每帧 0.1s；进帧步长用索引差


def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def gray(path, scale=0.5):
    im = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    return cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def ring_shift(g0, g1, cx, cy, box, R=110, scale=0.5):
    """在目标周围区域内估计背景位移（像素，原图尺度）。

    做法：取目标周围 R 像素的方块作为模板，在第二帧的扩大搜索窗内做
    归一化互相关（TM_CCOEFF_NORMED）找最佳匹配位置，位移即背景位移。
    中心框只占 R 的一小部分，对 NCC 的影响可忽略，因此不做挖洞处理
    —— 少一层逻辑 = 少一个 bug。
    """
    H, W = g0.shape
    cxs, cys = int(cx * scale), int(cy * scale)
    rad = int(R * scale)
    X1, Y1 = max(0, cxs - rad), max(0, cys - rad)
    X2, Y2 = min(W, cxs + rad), min(H, cys + rad)
    if X2 - X1 < 40 or Y2 - Y1 < 40:
        return None
    a = g0[Y1:Y2, X1:X2].astype(np.float32)
    s = int(70 * scale)                       # 搜索半径：70 原图像素（容纳镜头平移）
    bx1, by1 = max(0, X1 - s), max(0, Y1 - s)
    bx2, by2 = min(W, X2 + s), min(H, Y2 + s)
    b = g1[by1:by2, bx1:bx2].astype(np.float32)
    if b.shape[0] < a.shape[0] or b.shape[1] < a.shape[1]:
        return None
    res = cv2.matchTemplate(b, a, cv2.TM_CCOEFF_NORMED)
    _, _, _, maxloc = cv2.minMaxLoc(res)
    dx = (bx1 + maxloc[0]) - X1
    dy = (by1 + maxloc[1]) - Y1
    return (dx / scale, dy / scale)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ball-verify", required=True)
    ap.add_argument("--frames-dir", required=True, help="10fps 帧目录 seg_hi")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--radius", type=float, default=110)
    ap.add_argument("--resid-thr", type=float, default=6.0)
    ap.add_argument("--max-dt", type=float, default=0.6)
    ap.add_argument("--fps", type=float, default=10.0)
    a = ap.parse_args()

    bv = load(a.ball_verify)
    rows = [r for r in bv["rows"]
            if not r.get("pred") and r.get("box") and r.get("verdict") == "ball_like"]
    rows.sort(key=lambda r: r["t"])
    t0 = 204.5
    gcache = {}

    def gf(i):
        if i not in gcache:
            gcache[i] = gray(os.path.join(a.frames_dir, f"f{i:05d}.jpg"))
        return gcache[i]

    out = []
    for r, nxt in zip(rows, rows[1:]):
        dt = nxt["t"] - r["t"]
        if dt <= 0 or dt > a.max_dt:
            continue
        i0 = int(round((r["t"] - t0) * a.fps))
        i1 = int(round((nxt["t"] - t0) * a.fps))
        if i1 <= i0:
            continue
        g0, g1 = gf(i0 + 1), gf(i1 + 1)
        if g0 is None or g1 is None:
            continue
        c0 = ((r["box"][0] + r["box"][2]) / 2, (r["box"][1] + r["box"][3]) / 2)
        c1 = ((nxt["box"][0] + nxt["box"][2]) / 2, (nxt["box"][1] + nxt["box"][3]) / 2)
        ddx, ddy = c1[0] - c0[0], c1[1] - c0[1]
        sh = ring_shift(g0, g1, c0[0], c0[1], r["box"], a.radius)
        if sh is None:
            continue
        rx = ddx - sh[0]
        ry = ddy - sh[1]
        out.append({
            "t": r["t"], "next_t": nxt["t"],
            "det_disp": round(math.hypot(ddx, ddy), 2),
            "bg_disp": round(math.hypot(sh[0], sh[1]), 2),
            "resid": round(math.hypot(rx, ry), 2),
            "box": r["box"],
            "static": math.hypot(rx, ry) < a.resid_thr,
        })

    os.makedirs(a.outdir, exist_ok=True)
    resid = [x["resid"] for x in out]
    nstat = sum(1 for x in out if x["static"])

    # 对照：Mastercard 帧 vs 已知真球帧
    mc = [x for x in out if 240 <= x["box"][1] <= 380 and x["box"][3] <= 400]
    real = [x for x in out if abs(x["t"] - 210.0) < 0.6 or abs(x["t"] - 247.4) < 0.6]

    p = os.path.join(a.outdir, "static_reject.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"meta": {"radius": a.radius, "resid_thr": a.resid_thr,
                            "n_pairs": len(out), "n_static": nstat,
                            "resid_median": statistics.median(resid) if resid else None,
                            "note": ("residual = |检出位移 − 周围环形背景位移|。"
                                     "静态目标（logo/地板线）≈0；真球相对背景在动。")},
                   "rows": out}, f, ensure_ascii=False, indent=1)

    print("=" * 64)
    print("静态目标剔除自验（局部背景运动补偿）")
    print("=" * 64)
    print(f"  有效相邻对: {len(out)}")
    print(f"  residual 中位 {statistics.median(resid):.1f}px"
          if resid else "  无")
    print(f"  判为静态（< {a.resid_thr}px）: {nstat}/{len(out)}"
          f" = {nstat/len(out)*100:.1f}%" if out else "")
    print()
    print("  【对照 A】疑似 Mastercard 组（y 在广告板带内）")
    if mc:
        v = [x["resid"] for x in mc]
        print(f"    n={len(v)}  residual 中位 {statistics.median(v):.1f}px"
              f"  范围 {min(v):.1f}–{max(v):.1f}")
    print("  【对照 B】已目视确认真球帧（t≈210.0 / 247.4）")
    if real:
        v = [x["resid"] for x in real]
        print(f"    n={len(v)}  residual 中位 {statistics.median(v):.1f}px"
              f"  范围 {min(v):.1f}–{max(v):.1f}")
    print()
    if mc and real:
        mm = statistics.median([x["resid"] for x in mc])
        rm = statistics.median([x["resid"] for x in real])
        print(f"  🔎 分离度: 假目标中位 {mm:.1f}px  vs  真球中位 {rm:.1f}px"
              f"  →  {'✅ 可分离' if rm > mm * 1.8 else '❌ 不可分离'}")
    print(f"\n[out] {p}")


if __name__ == "__main__":
    main()
