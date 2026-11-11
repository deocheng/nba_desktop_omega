#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场马赛克（L6 第一步）—— 分块中值 + 块间拼接，避开长链累积。

为什么不用"整段直接累乘"
------------------------
实测（`probe_pan.py`）：帧 1 与帧 50 / 433 之间的**远基线配准不可靠** ——
4 块静态纹理区给出的落点互相矛盾（位移 −1132/+1299/+172/−758，无一致的全局变换），
NCC 只有 0.43–0.57；而 1→2 帧的 NCC 是 0.77–0.97、尺度 1.00。
⇒ 远基线（≥50 帧）在本素材上**无法可信配准**，长链累乘（432 次复合）的尺度会漂。

本脚本的做法（把 432 次复合降到 ~11 次）
--------------------------------------
  1. 段内逐对配准（已含「检测前遮罩叠加图形 + 内点铺开门禁」），**只在块内累乘**
     —— 块内最多 block/2 次复合，漂移可忽略。
  2. 每块 warp 到块中心帧 → **逐像素中值**（移动球员被抹除，静止结构保留），
     同时输出**观测支撑率**（每像素真正被多少帧覆盖）。
  3. 块间用**块中值图**互相配准（此刻画面里已无移动球员，特征更干净）→ 顺序拼接。
  4. 输出马赛克 + 支撑图 + 每块对齐诊断；**必须目视验收**（线条是否锐利、有无重影）。

坐标约定（易错，写清）
--------------------
`global_align.match(a,b)` 返回的 H 定义在 **0.5 尺度**坐标上，方向 a→b。
故「把块 k 的全分辨率中值图 warp 到块 0 的全分辨率坐标」为
    M = S(2) · H_acc[k] · S(0.5),   S(s)=diag(s,s,1)
再加画布平移 T(−mn)。

用法:
  python engine/court_mosaic.py --win w1 --start 1 --end 433 --block 40
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
import global_align as GA

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
AW = Path(str(tactics_data_file("action_work")))


def S(s):
    return np.array([[s, 0, 0], [0, s, 0], [0, 0, 1]], float)


def detect_gray(img):
    small = cv2.resize(img, None, fx=GA.SC, fy=GA.SC, interpolation=cv2.INTER_AREA)
    return GA.detect(small)


def block_median(fs, a, b):
    """把 fs[a..b]（0-based 闭区间）warp 到块中心帧 → (中值图, 支撑图, 中心帧号, 失败帧)"""
    mid = (a + b) // 2
    feats = [GA.detect(GA.to_gray_small(fs[i])[0]) for i in range(a, b + 1)]
    m = mid - a
    Hrel = {m: np.eye(3)}
    fails = []
    Hc = np.eye(3)
    for i in range(m + 1, b - a + 1):
        H, _ = GA.match(feats[i - 1], feats[i])
        if H is None:
            fails.append(i + a + 1)
        else:
            Hc = H @ Hc
        Hrel[i] = Hc.copy()
    Hc = np.eye(3)
    for i in range(m - 1, -1, -1):
        H, _ = GA.match(feats[i + 1], feats[i])
        if H is None:
            fails.append(i + a + 1)
        else:
            Hc = H @ Hc
        Hrel[i] = Hc.copy()
    imgs = []
    for i in range(a, b + 1):
        g = cv2.imread(str(fs[i]), cv2.IMREAD_GRAYSCALE)
        M = S(2.0) @ Hrel[i - a] @ S(0.5)       # 全分辨率：帧 i → 中心帧
        imgs.append(cv2.warpPerspective(g, M, (g.shape[1], g.shape[0]),
                                        flags=cv2.INTER_LINEAR, borderValue=0))
    st = np.stack(imgs)
    med = np.median(st, axis=0).astype(np.uint8)
    sup = (st > 0).sum(axis=0).astype(np.uint8)
    return med, sup, mid + 1, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", default="w1")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=433)
    ap.add_argument("--block", type=int, default=40)
    a = ap.parse_args()
    fs = GA.frame_paths(a.win)
    print(f"[{a.win}] 段 [{a.start}..{a.end}] 共 {a.end - a.start + 1} 帧，块长 {a.block}")
    blocks = []
    t0 = time.time()
    i = a.start
    while i <= a.end:
        b = min(i + a.block - 1, a.end)
        med, sup, mid, fails = block_median(fs, i - 1, b - 1)
        n = b - i + 1
        cov = float((sup > 0).mean())
        good = float((sup >= max(3, n // 3)).mean())
        print(f"  块 [{i}..{b}] 中心帧 {mid}  覆盖 {cov*100:.1f}%  支撑≥1/3 {good*100:.1f}%"
              f"  配准失败 {fails}")
        blocks.append({"a": i, "b": b, "mid": mid, "med": med, "sup": sup,
                       "fails": fails, "cov": cov, "good": good})
        i = b + 1
    print(f"  分块完成 {len(blocks)} 块  {time.time() - t0:.0f}s")

    # ---- 块间拼接：用**尺度已强制=1 的链式累积**（块中值图之间的 ORB 匹配已证伪：
    #      4000x4000 特征只配出 7 对 —— 有用的特征几乎全在观众席，而观众席 0.4s 内就变样）。
    print("  计算全局链式累积（force_scale1=True ⇒ 尺度恒为 1，不会漂）:")
    feats = [GA.detect(GA.to_gray_small(f)[0]) for f in fs[a.start - 1:a.end]]
    Hch = {}
    Hc = np.eye(3)
    nfail = 0
    for i in range(1, len(feats)):
        H, _ = GA.match(feats[i - 1], feats[i])
        if H is None:
            nfail += 1
        else:
            Hc = H @ Hc
        Hch[a.start + i] = Hc.copy()
    Hch[a.start] = np.eye(3)
    print(f"    链式完成，配准失败 {nfail} 帧；"
          f"末帧累积尺度 {np.sqrt(abs(np.linalg.det(Hc[:2, :2]))):.6f}  "
          f"平移 ({Hc[0, 2] / GA.SC:+.0f},{Hc[1, 2] / GA.SC:+.0f})")
    H_acc = {k: Hch[blk["mid"]] for k, blk in enumerate(blocks)}

    corners = []
    for k in range(len(blocks)):
        M = S(2.0) @ H_acc[k] @ S(0.5)
        for (x, y) in [(0, 0), (1920, 0), (0, 1080), (1920, 1080)]:
            v = M @ np.array([x, y, 1.0])
            corners.append(v[:2] / v[2])
    corners = np.array(corners)
    mn = corners.min(axis=0) - 20
    mx = corners.max(axis=0) + 20
    Wc, Hc = int(mx[0] - mn[0]), int(mx[1] - mn[1])
    print(f"  画布 {Wc}x{Hc}（左上偏移 {mn[0]:.0f},{mn[1]:.0f}）")
    T = np.array([[1, 0, -mn[0]], [0, 1, -mn[1]], [0, 0, 1]], float)
    acc = np.zeros((Hc, Wc), np.float32)
    cnt = np.zeros((Hc, Wc), np.float32)
    for k, blk in enumerate(blocks):
        M = T @ S(2.0) @ H_acc[k] @ S(0.5)
        w = cv2.warpPerspective(blk["med"], M, (Wc, Hc), flags=cv2.INTER_LINEAR)
        m = cv2.warpPerspective((blk["sup"] > 0).astype(np.uint8) * 255, M, (Wc, Hc),
                                flags=cv2.INTER_NEAREST)
        v = m > 0
        acc[v] += w[v].astype(np.float32)
        cnt[v] += 1
    mos = np.where(cnt > 0, acc / np.maximum(cnt, 1), 0).astype(np.uint8)
    tag = f"{a.win}_{a.start}_{a.end}"
    cv2.imwrite(str(MS / f"mosaic_{tag}.jpg"), mos, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(MS / f"mosaic_support_{tag}.png"),
                (np.clip(cnt / max(1.0, cnt.max()), 0, 1) * 255).astype(np.uint8))
    json.dump({"win": a.win, "start": a.start, "end": a.end, "block": a.block,
               "n_blocks": len(blocks), "canvas": [Wc, Hc],
               "offset": [float(mn[0]), float(mn[1])],
               "blocks": [{"a": b["a"], "b": b["b"], "mid": b["mid"],
                           "cov": round(b["cov"], 4), "good": round(b["good"], 4),
                           "fails": b["fails"]} for b in blocks]},
              open(MS / f"mosaic_{tag}.json", "w"), ensure_ascii=False, indent=1)
    print(f"[out] {MS / f'mosaic_{tag}.jpg'}  ({Wc}x{Hc})")
    f = min(1.0, 1500 / max(1, Wc))
    th = cv2.resize(mos, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(MS / f"mosaic_thumb_{a.win}.jpg"), th, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"[out] thumb {th.shape}")


if __name__ == "__main__":
    main()
