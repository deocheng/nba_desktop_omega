#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.13c 虚拟边线 v2：**双向修正**（补缺口 + 切掉吞进的观众席）。

老程：「画面的下一方，球场的一条边线，被观众挡住了，你应该加一条虚拟边线」

v1 的根因（本脚本要修的）：
  `col_low(x)`（每列地板最低有效行）**不是一条直线**：
    - 左侧：值是「被前排观众头啃掉的位置」→ 任意，不反映球场几何
    - 右侧：值是「真实近端边线」→ 反映透视
  两种语义混在一根曲线里 ⇒ RANSAC 只能拟合出「平均线」（v1 内点率仅 43.9%、救回 0）。

v2 做法：
  1. `col_low` → 中值滤波(窗口 41)去锯齿
  2. RANSAC 直线拟合 + **斜率约束 |a| ≤ 0.30**（近端边线在广播视角里近水平）
  3. **双向修正**（相对拟合线 line(x)，容差 tol）：
       - low[x] < line(x) - tol  → **被啃掉的缺口** → 补到 line(x)
       - low[x] > line(x) + tol  → **掩膜吞进了观众席** → 切到 line(x)（删 line(x) 以下）
       - low[x] == -1（该列无地板）→ 若左右 ±(L)px 内有地板列，视为遮挡缺口 → 补到 line(x)
  4. 面积合理性守卫：修正后面积须落在 [AREA_LO, AREA_HI]，否则放弃修正

用法:
  court_virtual_baseline2.py --seg ep24_s1 --idx 70        # 单帧
  court_virtual_baseline2.py --seg ep24_s1 --all           # 全段统计
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
from court_filter import _foot, court_mask  # noqa: E402

AREA_LO, AREA_HI = 0.12, 0.80
WOOD_LO, WOOD_HI = (10, 45, 140), (38, 255, 255)


def wood_ratio(img, x, y, r=9):
    H, W = img.shape[:2]
    x0, x1 = max(0, x - r), min(W, x + r)
    y0, y1 = max(0, y - r), min(H, y + r)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    return float((cv2.inRange(hsv, WOOD_LO, WOOD_HI) > 0).mean())


def col_low(m, min_pix=25):
    H, W = m.shape
    colpix = (m > 0).sum(axis=0)
    ys = np.where(m > 0)
    low = np.full(W, -1, dtype=np.int32)
    order = np.argsort(ys[1], kind="stable")
    xs_sorted = ys[1][order]
    ys_sorted = ys[0][order]
    start = 0
    for x in range(W):
        end = np.searchsorted(xs_sorted, x, side="right")
        if end - start >= min_pix and end > start:
            low[x] = int(ys_sorted[start:end].max())
        start = end
    return low


def med_smooth(low, win=41):
    """只对有效列做中值平滑（无效列跳过）。"""
    out = low.copy()
    valid = low >= 0
    xs = np.where(valid)[0]
    if len(xs) == 0:
        return out
    arr = low[xs].astype(np.float64)
    k = win if win % 2 == 1 else win + 1
    pad = k // 2
    ap = np.pad(arr, pad, mode="edge")
    sm = np.array([np.median(ap[i:i + k]) for i in range(len(arr))])
    out[xs] = sm.astype(np.int32)
    return out


def ransac_line(pts, iters=4000, tol=12.0, seed=0, max_slope=0.30):
    rng = np.random.default_rng(seed)
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 8:
        return None, None, None
    best = (None, None, None, -1)
    for _ in range(iters):
        i, j = rng.choice(len(pts), 2, replace=False)
        (x1, y1), (x2, y2) = pts[i], pts[j]
        if abs(x2 - x1) < 40:
            continue
        a = (y2 - y1) / (x2 - x1)
        if abs(a) > max_slope:
            continue
        b = y1 - a * x1
        pred = a * pts[:, 0] + b
        inl = np.abs(pred - pts[:, 1]) < tol
        n = int(inl.sum())
        if n > best[3]:
            best = (a, b, inl, n)
    a, b, inl, n = best
    if a is None:
        return None, None, None
    P = pts[inl]
    a2, b2 = np.polyfit(P[:, 0], P[:, 1], 1)
    return float(a2), float(b2), inl


def fit_binned(low, nb=16, q=50):
    """分箱分位 + 加权最小二乘。

    🔴 v1/v2 用 RANSAC-over-all 是**错的**：f70 只给出 a=0.0150（实测真实 ≈0.077–0.125），
    因为中间 x∈[160,800] 的大量列 low≈607 主导了内点，右段真实下移点被当离群点丢弃
    （多数压制少数）。分箱后每箱取分位，右段不再被压制 ⇒ 与全点 LSQ 独立收敛到 a≈0.124。
    """
    W = len(low)
    xs = np.where(low >= 0)[0]
    if len(xs) < 40:
        return None, None, None
    edges = np.linspace(0, W, nb + 1).astype(int)
    px, py, pw = [], [], []
    for i in range(nb):
        sel = xs[(xs >= edges[i]) & (xs < edges[i + 1])]
        if len(sel) < 8:
            continue
        px.append(0.5 * (edges[i] + edges[i + 1]))
        py.append(np.percentile(low[sel], q))
        pw.append(len(sel))
    if len(px) < 4:
        return None, None, None
    px, py, pw = np.array(px, float), np.array(py, float), np.array(pw, float)
    M = np.vstack([px, np.ones_like(px)]).T * pw[:, None]
    sol, *_ = np.linalg.lstsq(M, py * pw, rcond=None)
    return float(sol[0]), float(sol[1]), len(px)


def fit_hough_guided(img, low, mid=(400, 900), ang_lo=2.0, ang_hi=8.0,
                     minlen=140, verbose=False):
    """Hough 引导：用画面里**真实存在的球场边线族**定斜率，用中段 low 对齐定截距。

    🔴 为什么必须这样（f70 实测）：
      - A) RANSAC-over-all → a=0.0150（0.9°）**偏平 5×**
      - B) 分箱中位       → a=0.1250（7.1°）**偏陡 2×**
      - 真值来自 Hough：`#6`(4.4°) `#9`(3.9°) `#11`(4.6°) `#2/#5/#8`(3.5–3.6°)
        —— 一整族 ~4° 的平行线（球场边线方向）⇒ tan(4.4°)=0.077
      另注：Hough 在 y=660 / y≈700 检出的两条**水平**线是**字幕条上/下边框**，不是球场线。
    截距用中段 (x∈mid) 对齐：那里掩膜与边线基本一致（f70 中段 low≈610，线 0.077*650+560≈610 ✓）。
    """
    if img is None:
        return None, None, None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape[:2]
    cand = []
    for lo, hi in [(40, 120), (80, 200)]:
        e = cv2.dilate(cv2.Canny(gray, lo, hi), np.ones((3, 3), np.uint8), 1)
        ls = cv2.HoughLinesP(e, 1, np.pi / 360, threshold=70,
                             minLineLength=minlen, maxLineGap=40)
        if ls is None:
            continue
        for l in ls:
            x1, y1, x2, y2 = [int(v) for v in np.asarray(l).reshape(-1)]
            L = float(np.hypot(x2 - x1, y2 - y1))
            ang = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            if ang > 90:
                ang = 180 - ang
            if not (ang_lo <= ang <= ang_hi):
                continue
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            dx, dy = x2 - x1, y2 - y1
            n = np.hypot(dx, dy)
            px, py = -dy / n, dx / n
            o = 16
            p1 = (int(mx + px * o), int(my + py * o))
            p2 = (int(mx - px * o), int(my - py * o))
            if not (0 <= p1[0] < W and 0 <= p1[1] < H and 0 <= p2[0] < W and 0 <= p2[1] < H):
                continue
            r1, r2 = wood_ratio(img, *p1), wood_ratio(img, *p2)
            # 一侧明显木地板、另一侧明显不是 ⇒ 地板边界
            if (r1 >= 0.35 and r2 <= 0.15) or (r2 >= 0.35 and r1 <= 0.15):
                cand.append((np.tan(np.radians(ang)), L))
    if len(cand) < 2:
        return None, None, None
    sw = sum(a * L for a, L in cand)
    ww = sum(L for _, L in cand)
    A = sw / ww
    xs = [x for x in range(*mid) if low[x] >= 0]
    if len(xs) < 30:
        xs = [x for x in range(W) if low[x] >= 0]
    B = float(np.median([low[x] - A * x for x in xs]))
    if verbose:
        print(f"  [hough] {len(cand)} 条边线族，加权斜率 a={A:.4f} ({np.degrees(np.arctan(A)):.1f}°)，截距 b={B:.1f}")
    return A, B, len(cand)


def virtual_court(m, tol=14.0, iters=4000, minpix=25, neigh=60, verbose=True,
                  fit="binned", img=None):
    """返回 (m2, info)。m2=双向修正后的地板掩膜。"""
    H, W = m.shape
    info = {}
    low = col_low(m, minpix)
    ls = med_smooth(low, 41)
    xs = np.where(ls >= 0)[0]
    if len(xs) < 40:
        return m.copy(), {"ok": False, "why": "有效列不足"}
    if fit == "ransac":
        pts = [(float(x), float(ls[x])) for x in xs]
        A, B, inl = ransac_line(pts, iters, 12.0, 0, 0.30)
        if A is None:
            return m.copy(), {"ok": False, "why": "拟合失败"}
        ncol = len(pts)
        info["inlier"] = round(float(np.mean(inl)), 3)
    elif fit == "hough":
        A, B, ncand = fit_hough_guided(img, ls, verbose=verbose)
        if A is None:
            return m.copy(), {"ok": False, "why": "hough 无候选"}
        ncol = ncand
    else:
        A, B, nb = fit_binned(ls, 16, 50)
        if A is None:
            return m.copy(), {"ok": False, "why": "拟合失败"}
        ncol = len(xs)
    info.update(line=(round(A, 5), round(B, 2)), ncol=ncol, fit=fit)

    m2 = m.copy()
    n_add = n_cut = 0
    for x in range(W):
        yl = int(round(A * x + B))
        yl = max(0, min(yl, H - 1))
        lo = ls[x]
        if lo < 0:
            # 无地板列：看左右是否有地板（遮挡缺口）
            l0, r0 = max(0, x - neigh), min(W, x + neigh + 1)
            nb = ls[l0:r0]
            nb = nb[nb >= 0]
            if len(nb) >= 5:
                y0 = int(np.median(nb))
                y1_ = min(yl, y0 + 260)   # 缺口补全上限 260px，防外推失控
                if y1_ > y0:
                    m2[y0 + 1:y1_ + 1, x] = 255
                    n_add += int((m[ y0 + 1:y1_ + 1, x] == 0).sum())
        elif lo < yl - tol:
            m2[lo + 1: yl + 1, x] = 255
            n_add += int((m[lo + 1: yl + 1, x] == 0).sum())
        elif lo > yl + tol:
            m2[yl + 1: lo + 1, x] = 0
            n_cut += int((m[yl + 1: lo + 1, x] > 0).sum())

    a1, a2 = m.mean() / 255, m2.mean() / 255
    info.update(area_before=round(a1, 3), area_after=round(a2, 3),
                n_add=n_add, n_cut=n_cut)
    if not (AREA_LO <= a2 <= AREA_HI):
        info["ok"] = False
        info["why"] = f"面积越界 {a2:.3f}"
        return m.copy(), info
    info["ok"] = True
    if verbose:
        extra = f" 内点{info['inlier']*100:.1f}%" if "inlier" in info else f" [{info.get('ncol')}列]"
        print(f"  虚拟边线[{fit}] y={A:.4f}x{B:+.1f}{extra} "
              f"补{n_add}px 切{n_cut}px 面积 {a1:.3f}->{a2:.3f}")
    return m2, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tol", type=float, default=14.0)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--fit", choices=["binned", "ransac", "hough"], default="hough")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    d = SEGD / a.seg
    frames = sorted((d / "frames").glob("f*.jpg"))
    cache = json.load(open(ROOT / "action_work" / f"_detcache_{a.seg}_1280.json"))

    if a.all:
        print(f"=== 全段门1 对比 {a.seg}（{len(frames)} 帧）===")
        rows = []
        n_rescue_tot = n_kill_tot = 0
        fails = 0
        for i, fp in enumerate(frames):
            img = cv2.imread(str(fp))
            H, W = img.shape[:2]
            r = court_mask(img)
            if r is None or r[0] is None:
                fails += 1
                continue
            m = r[0]
            m2, info = virtual_court(m, a.tol, verbose=False, fit=a.fit, img=img)
            dets = [bb for (cls, cf, bb) in cache[i] if cf >= a.conf]
            nin = nin2 = 0
            rescue = []
            for bb in dets:
                fx, fy = _foot(bb)
                if not (0 <= fx < W and 0 <= fy < H):
                    continue
                o1 = m[fy, fx] > 0
                o2 = m2[fy, fx] > 0
                nin += int(o1); nin2 += int(o2)
                if o2 and not o1:
                    rescue.append({"box": [round(float(v), 1) for v in bb],
                                   "h": round(float(bb[3] - bb[1]), 1), "foot_y": int(fy)})
                if o1 and not o2:
                    n_kill_tot += 1
            n_rescue_tot += len(rescue)
            rows.append({"idx": i, "ok": info.get("ok", False), "nin": nin, "nin2": nin2,
                         "d": nin2 - nin, "rescue": rescue, "area": info.get("area_after")})
        ok = [r for r in rows if r["ok"]]
        print(f"修正可用 {len(ok)}/{len(rows)} 帧（court_mask 失败 {fails}）")
        d_ = [r["d"] for r in ok]
        print(f"门1 保留数变化: 中位 {int(np.median(d_))}  范围 [{min(d_)},{max(d_)}]")
        print(f"总救回 {n_rescue_tot} 框 / 总新增误杀 {n_kill_tot} 框")
        big = sorted([r for r in ok if r["rescue"]], key=lambda r: -max(o["h"] for o in r["rescue"]))[:10]
        print("\n-- 救回框最大（框高）的前 10 帧 --")
        for r in big:
            top = max(r["rescue"], key=lambda o: o["h"])
            print(f"  帧{r['idx']:>3} 救{len(r['rescue'])}个 最大{top['h']:.0f}px 脚y{top['foot_y']}")
        op = OUT / f"vbaseline2_scan_{a.seg}.json"
        json.dump(rows, open(op, "w"), ensure_ascii=False)
        print(f"\n-> {op}")
        return

    # 单帧
    img = cv2.imread(str(frames[a.idx]))
    H, W = img.shape[:2]
    r = court_mask(img)
    if r is None or r[0] is None:
        print("court_mask 不可用"); return
    m = r[0]
    print(f"=== {a.seg} f{a.idx} 虚拟边线 v2 ===")
    m2, info = virtual_court(m, a.tol, verbose=True, fit=a.fit, img=img)
    print("info:", info)

    def oncourt(mm, box):
        fx, fy = _foot(box)
        return bool(0 <= fx < W and 0 <= fy < H and mm[fy, fx] > 0)

    jp = OUT / f"{a.seg}_f{a.idx}.json"
    vis = img.copy()
    ov = vis.copy()
    ov[m2 > 0] = (0.45 * ov[m2 > 0] + 0.55 * np.array([30, 190, 40])).astype(np.uint8)
    vis = cv2.addWeighted(ov, 0.5, vis, 0.5, 0)
    if info.get("ok"):
        A, B = info["line"]
        cv2.line(vis, (0, int(round(B))), (W - 1, int(round(A * (W - 1) + B))), (0, 230, 255), 3)
    # 逐列 low 曲线（青点）与修正后 low（品红点）
    low = col_low(m); low2 = col_low(m2)
    for x in range(W):
        if low[x] >= 0:
            cv2.circle(vis, (x, int(low[x])), 1, (255, 255, 0), -1)
        if low2[x] >= 0:
            cv2.circle(vis, (x, int(low2[x])), 1, (255, 0, 255), -1)
    cv2.putText(vis, f"v2 line y={info.get('line',('?','?'))[0]}x{info.get('line',(0,0))[1]:+.1f}",
                (12, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 230, 255), 2)
    n_res = 0
    if jp.exists():
        items = json.load(open(jp))
        for it in items:
            x1, y1, x2, y2 = [int(v) for v in it["box"]]
            o1, o2 = oncourt(m, it["box"]), oncourt(m2, it["box"])
            if o2 and not o1:
                n_res += 1
            col = (0, 220, 0) if o2 else (0, 0, 225)
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, 3 if o2 else 2)
            tag = f"#{it['no']}" + (" [救]" if (o2 and not o1) else (" [丢]" if not o2 else ""))
            cv2.putText(vis, tag, (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 4)
            cv2.putText(vis, tag, (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, col, 2)
    print(f"共救回 {n_res} 个框")
    op = OUT / f"{a.seg}_f{a.idx}_vbaseline2.png"
    cv2.imwrite(str(op), vis)
    print(f"-> {op}")


if __name__ == "__main__":
    main()
