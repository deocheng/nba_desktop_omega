#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜头分割（L1）—— 先把"窗口"切成真正的单镜头连续片段。

为什么必须先做
--------------
`action_work/w{1..4}/` 是按**时间**切出来的"窗口"，实测**内部含镜头切换**：
w1 前 405 帧是同一广角摇镜、末 30 帧切到球员特写。此后所有工序
（逐帧位姿 / 局部稳定化中值底板 / 帧到帧累积）都隐含**单镜头连续**假设。

两路信号，**主判据只有一路**（2026-09-24 实测修正）
---------------------------------------------------
  A. **画幅内容突变（主判据）**：缩略灰度直方图相关 `hcorr`。实测三类清楚分开：
     · 真切点 hcorr ∈ {0.030, 0.071, 0.288, 0.373, 0.387, 0.478, 0.479}
     · **光照/曝光突变**（相机没动）hcorr ∈ {0.639, 0.645, 0.759, 0.765, 0.840, 0.850}
     · 正常帧对 hcorr ≥ 0.99
     ⇒ **间隙 = [0.479, 0.639]**，`HCUT=0.55` 落在正中。
     ⚠️ 光照突变那类**必须排除**，否则会误判成切镜头（第一版把阈值放到 0.75 就踩了这个坑）。
     判据补充：光照突变的**几何位移只有 2–4px**、内点从 ~1800 掉到 ~750，
     而真切点的位移/内容都是断崖式改变。
  B. **几何配准是否成立（仅作辅助标记，不作切点判据）**：
     🔴 第一版把"配准失败"当切点，被目视验收推翻两处：
       · w1 434→435、w4 1→2 **配准失败但不是切点** —— 低纹理/虚化特写本来就配不出单应；
       · w2 99→100 与 w3 43→44 **是切点但配准成功**（400–760 内点、铺开 0.92×0.89）——
         因为**两张不同机位拍的是同一块平面（球场）**，平面视图之间**本来就有合法单应**；
       · w4 194→195、w3 81→82 **是光照/曝光突变**（整块地板均匀变色、位移仅 2–4px），也不是切点。
     ⇒ 结论：`geo_ok=False` 只说明"这对帧配不准"（对对齐工序重要），**不等于换了镜头**。

用法:
  python engine/shot_segment.py --win w1
  python engine/shot_segment.py --win all --sheets
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
AW = Path(str(tactics_data_file("action_work")))

SC = 0.5
# 静态叠加图形（广播台比分板 / 台标）。**必须在特征检测之前**涂黑。
OVERLAY_BOXES = [(60, 880, 580, 1020)]
HCUT = 0.55          # 实测间隙 [0.479, 0.639] 的中点；切点判据（唯一主判据）
GAP_LO, GAP_HI = 0.50, 0.63   # 用于自动报告"间隙是否干净"
MIN_INL = 60
MIN_SPREAD = (0.25, 0.20)   # 内点包围盒 宽/高 占画幅比

_ORB = cv2.ORB_create(nfeatures=4000, scaleFactor=1.2, nlevels=8,
                      fastThreshold=12, edgeThreshold=19)


def gray_masked(p):
    g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    for x0, y0, x1, y1 in OVERLAY_BOXES:
        g[y0:y1, x0:x1] = 0
    return cv2.resize(g, None, fx=SC, fy=SC, interpolation=cv2.INTER_AREA)


def hist_corr_path(p):
    g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    g = cv2.resize(g, (160, 90), interpolation=cv2.INTER_AREA)
    h = cv2.calcHist([g], [0], None, [64], [0, 256]).ravel()
    return h / max(1.0, h.sum()), g


def detect(g):
    return _ORB.detectAndCompute(g, None)


def match_geo(da, db, thr=3.0):
    """返回 (ok, inlier, spread_w, spread_h)。铺开门禁是**必需**的。"""
    if da[1] is None or db[1] is None or len(da[1]) < 12 or len(db[1]) < 12:
        return False, 0, 0.0, 0.0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    ms = bf.match(da[1], db[1])
    if len(ms) < 12:
        return False, 0, 0.0, 0.0
    ms = sorted(ms, key=lambda m: m.distance)
    keep = [m for m in ms if m.distance <= max(1.4 * ms[0].distance, 28)]
    if len(keep) < 12:
        keep = ms[: max(12, len(ms) // 2)]
    src = np.float32([da[0][m.queryIdx].pt for m in keep])
    dst = np.float32([db[0][m.trainIdx].pt for m in keep])
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, thr * SC, maxIters=4000,
                                confidence=0.995)
    if H is None or inl is None or int(inl.sum()) < MIN_INL:
        return False, int(0 if inl is None else inl.sum()), 0.0, 0.0
    sel = inl.ravel().astype(bool)
    P = src[sel] * 2
    bw = float(P[:, 0].max() - P[:, 0].min()) / 1920.0
    bh = float(P[:, 1].max() - P[:, 1].min()) / 1080.0
    ok = bw >= MIN_SPREAD[0] and bh >= MIN_SPREAD[1]
    return ok, int(inl.sum()), bw, bh


def run(win, verbose=True):
    fs = sorted((AW / win).glob("f*.jpg"))
    t0 = time.time()
    prev_h, prev_g = hist_corr_path(fs[0])
    prev_f = detect(gray_masked(fs[0]))
    rows = []
    for i in range(1, len(fs)):
        h, g = hist_corr_path(fs[i])
        hc = float(np.corrcoef(prev_h, h)[0, 1])
        mad = float(np.abs(prev_g.astype(np.float32) - g.astype(np.float32)).mean())
        cur_f = detect(gray_masked(fs[i]))
        ok, inl, bw, bh = match_geo(prev_f, cur_f)
        cut = hc < HCUT            # 唯一主判据；geo 失败只作辅助标记
        rows.append({"i": i, "hcorr": round(hc, 4), "mad": round(mad, 2),
                     "geo_ok": bool(ok), "inl": inl,
                     "spread_w": round(bw, 3), "spread_h": round(bh, 3),
                     "cut": bool(cut)})
        prev_h, prev_g, prev_f = h, g, cur_f
        if verbose and i % 100 == 0:
            print(f"  {win} {i}/{len(fs)-1}  {time.time()-t0:.0f}s", flush=True)
    cuts = [r["i"] for r in rows if r["cut"]]
    geofail = [r["i"] for r in rows if not r["geo_ok"]]
    bounds = [0] + cuts + [len(fs)]
    segs = [{"start": bounds[k] + 1, "end": bounds[k + 1], "len": bounds[k + 1] - bounds[k]}
            for k in range(len(bounds) - 1) if bounds[k + 1] - bounds[k] >= 1]
    hc = np.array([r["hcorr"] for r in rows])
    in_gap = int(((hc > GAP_LO) & (hc < GAP_HI)).sum())
    print(f"[{win}] {len(fs)} 帧  {time.time()-t0:.0f}s")
    print(f"  hcorr: min={hc.min():.3f} p1={np.percentile(hc,1):.3f} median={np.median(hc):.3f}"
          f"  | <{HCUT} 的 {int((hc<HCUT).sum())}  落在间隙({GAP_LO},{GAP_HI}) 的 {in_gap}"
          f"  ⇒ 间隙{'干净 ✓' if in_gap <= 2 else '不干净 ⚠️（阈值需重标）'}")
    print(f"  几何配准不通过（辅助信息，非切点）: {geofail}")
    print(f"  切点: {cuts}")
    outer = [s for s in segs if s["len"] >= 10]
    print(f"  片段 {len(segs)} 段；其中 ≥10 帧的 {len(outer)} 段: " +
          ", ".join(f"[{s['start']}..{s['end']}]({s['len']})" for s in outer[:8]) +
          (" …" if len(outer) > 8 else ""))
    return {"win": win, "n": len(fs), "cuts": cuts, "segments": segs,
            "geo_fail_pairs": geofail, "hcut": HCUT,
            "gap_clean": bool(in_gap <= 2), "rows": rows}


def sheet(win, tag=None, k=16):
    fs = sorted((AW / win).glob("f*.jpg"))
    idx = np.linspace(0, len(fs) - 1, k).astype(int)
    tiles = []
    for j in idx:
        im = cv2.imread(str(fs[j]))
        im = cv2.resize(im, (480, 270))
        cv2.putText(im, f"#{j+1}", (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (0, 255, 255), 2, cv2.LINE_AA)
        tiles.append(im)
    rows = [np.hstack(tiles[r * 4:(r + 1) * 4]) for r in range(4)]
    out = MS / f"contact_{tag or win}_16.jpg"
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"  [sheet] {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", default="all")
    ap.add_argument("--sheets", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    wins = ["w1", "w2", "w3", "w4"] if a.win == "all" else [a.win]
    res = {}
    for w in wins:
        if a.sheets:
            sheet(w)
        res[w] = run(w)
    out = Path(a.out) if a.out else MS / "shot_segments.json"
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"[out] {out}")


if __name__ == "__main__":
    main()
