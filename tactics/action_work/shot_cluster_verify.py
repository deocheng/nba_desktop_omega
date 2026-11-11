#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机位簇验证（只读）——「背景很像」到底能不能共用一套标定？

问题
----
shot_window_cluster.py 的**中位背景帧相关**出现跨期 0.89–0.94 的高相似对
（ep15_s0/ep17_s0/ep18_s0/ep16_s0/... 的最长窗口彼此都很像）。
但「整体明暗布局像」≠「同一个固定机位」——后者才能共用一套单应。

判据（措施：几何，不是外观）
----------------------------
若两窗口是**同一固定机位**，则其背景帧之间 ORB 配准出的单应应接近**单位阵**：
  · 四角 + 中心点经 H 映射的位移 ⇒ **中位位移应只有几像素**（三脚架抖动量级）
  · 内点应铺开整幅画（spread 大），而不是挤在一个局部平面
作为负对照：同一段内被真切镜隔开的两个窗口 ⇒ 位移必须远大于此。

用法: python3 action_work/shot_cluster_verify.py --pairs 25
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
SEGBASE = AW / "tactic_notes_batch_full" / "segments"
BW, BH = 640, 360           # 几何验证用分辨率（比聚类时高一档）
BG_N = 20
_OVERLAY = (40, 587, 387, 680)   # 1280x720 下的左下比分板（1920x1080 版等比换算）

_ORB = cv2.ORB_create(nfeatures=4000, scaleFactor=1.2, nlevels=8,
                      fastThreshold=12, edgeThreshold=19)

_bg_cache: dict = {}


def bg_of(seg, s, e, n=BG_N):
    key = (seg, s, e)
    if key in _bg_cache:
        return _bg_cache[key]
    d = SEGBASE / seg / "frames"
    fs = sorted(d.glob("*.jpg"))
    idx = np.linspace(s, e, min(n, e - s + 1)).astype(int)
    stack = []
    for i in idx:
        g = cv2.imread(str(fs[i]), cv2.IMREAD_GRAYSCALE)
        x0, y0, x1, y1 = _OVERLAY
        g[y0:y1, x0:x1] = 0
        stack.append(cv2.resize(g, (BW, BH), interpolation=cv2.INTER_AREA))
    bg = np.median(np.stack(stack), axis=0).astype(np.uint8)
    _bg_cache[key] = bg
    return bg


def geo_pair(pair):
    (la, wa), (lb, wb) = pair          # wa/wb = (seg, start, end)
    A, B = bg_of(*wa), bg_of(*wb)
    ka, da = _ORB.detectAndCompute(A, None)
    kb, db = _ORB.detectAndCompute(B, None)
    if da is None or db is None or min(len(da), len(db)) < 20:
        return {"ok": False, "inl": 0, "ratio": 0.0, "shift": None}
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    ms = bf.match(da, db)
    if len(ms) < 20:
        return {"ok": False, "inl": 0, "ratio": 0.0, "shift": None}
    ms = sorted(ms, key=lambda m: m.distance)[:400]
    src = np.float32([ka[m.queryIdx].pt for m in ms]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in ms]).reshape(-1, 1, 2)
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0, maxIters=8000,
                                confidence=0.999)
    if H is None or inl is None:
        return {"ok": False, "inl": 0, "ratio": 0.0, "shift": None}
    n_inl = int(inl.sum())
    ratio = n_inl / len(ms)
    # H 相对单位阵的偏离：单位正方形上的 5 个探针点
    probes = np.float32([[0, 0], [BW, 0], [BW, BH], [0, BH], [BW / 2, BH / 2]]) \
        .reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(probes, H).reshape(-1, 2)
    shift = float(np.median(np.linalg.norm(mapped - probes.reshape(-1, 2), axis=1)))
    return {"ok": True, "inl": n_inl, "ratio": round(ratio, 3), "shift": round(shift, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--high", type=int, default=20)
    ap.add_argument("--mid", type=int, default=20)
    ap.add_argument("--low", type=int, default=15)
    a = ap.parse_args()

    d = json.load(open(AW / "norm_calib" / "shot_clusters_clean14.json"))
    S = np.load(AW / "norm_calib" / "shot_bg_sim.npy")
    W = d["windows"]
    n = len(W)
    iw = [(W[i]["seg"], W[i]["start"], W[i]["end"]) for i in range(n)]

    def key(i):
        return (f"{W[i]['seg']}#{W[i]['start']}-{W[i]['end']}({W[i]['len']})", iw[i])

    cross = []
    for i in range(n):
        for j in range(i + 1, n):
            if W[i]["seg"] != W[j]["seg"]:
                cross.append((S[i][j], i, j))
    cross.sort(reverse=True)

    groups = {}
    groups["HIGH(相似>=0.85)"] = [(i, j) for c, i, j in cross if c >= 0.85][:a.high]
    pool = [(c, i, j) for c, i, j in cross if 0.45 <= c < 0.60]
    step = max(1, len(pool) // a.mid)
    groups["MID(0.45-0.60)"] = [(i, j) for _, i, j in pool[::step]][:a.mid]
    pool = [(c, i, j) for c, i, j in cross if c < 0.20]
    step = max(1, len(pool) // a.low)
    groups["LOW(<0.20)"] = [(i, j) for _, i, j in pool[::step]][:a.low]

    # 负对照：同段相邻窗口（真切镜隔开 ⇒ 一定不同机位）
    neg = []
    for i in range(n):
        for j in range(i + 1, n):
            if W[i]["seg"] == W[j]["seg"] and abs(W[i]["start"] - W[j]["start"]) <= 3 + max(
                    W[i]["len"], W[j]["len"]):
                neg.append((i, j))
                break
    groups["NEG(同段真切镜两侧)"] = neg[:a.low]

    out = {}
    for tag, pairs in groups.items():
        if not pairs:
            continue
        todo = [(key(i), key(j)) for i, j in pairs]
        print(f"\n=== {tag}  n={len(todo)} ===")
        with ThreadPoolExecutor(max_workers=6) as ex:
            res = list(ex.map(geo_pair, todo))
        shifts = [r["shift"] for r in res if r["ok"] and r["shift"] is not None]
        rows = []
        for (lab_i, _), (lab_j, _), r in zip([t[0] for t in todo], [t[1] for t in todo], res):
            rows.append({"a": lab_i, "b": lab_j, **r})
            print(f"  inl={r['inl']:>4} ratio={r.get('ratio',0):.2f} "
                  f"位移={str(r['shift']):>8}px   {lab_i} || {lab_j}")
        if shifts:
            sh = np.array(shifts)
            # 判据：同机位 ⇒ 位移 <= 5px（640x360 尺度下 ≲0.8% 画幅）
            n_same = int((sh <= 5.0).sum())
            print(f"  → 中位位移 {np.median(sh):.2f}px | 位移<=5px 的对 {n_same}/{len(sh)} "
                  f"即为「可共用标定」候选")
        out[tag] = rows

    dst = AW / "norm_calib" / "shot_cluster_verify.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nwrote", dst)


if __name__ == "__main__":
    main()
