#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定点选单位归并（只读）——把 47 个镜头窗口并为「同机位簇」

判据来源（shot_cluster_verify.py 实测标定的两级分离）
--------------------------------------------------
  · 背景相关 ≥0.85 的对：ORB 内点率 0.80–1.00、单应位移 0.0–1.0px
    ⇒ 同一固定机位（像素级对齐，跨越 ep13/15/16/17/18/19 六期）
  · 相关 0.45–0.60 的对：内点率 0.02–0.18、位移 200–540px
    · 相关 <0.20 的对：同上                          ⇒ 不同机位
  两档之间无重叠 ⇒ 门限稳。

几何判据：ratio ≥ 0.45 **且** 位移 ≤ 5px（640×360 尺度 ≲ 0.8% 画幅）

产物
----
  action_work/norm_calib/calib_units.json        点选单位清单
  reports/milestone_05/measure/cluster_XX.jpg    每簇目视核实拼图
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
ROOT = AW.parent
SEGBASE = AW / "tactic_notes_batch_full" / "segments"
MS = ROOT / "reports" / "milestone_05" / "measure"
BW, BH = 640, 360
BG_N = 20
_OVERLAY = (40, 587, 387, 680)
SAME_RATIO = 0.45
SAME_SHIFT = 5.0
MIN_LEN = 10          # 低于此帧数的窗口不值得单独标定

_ORB = cv2.ORB_create(nfeatures=4000, scaleFactor=1.2, nlevels=8,
                      fastThreshold=12, edgeThreshold=19)


def bg_of(seg, s, e, n=BG_N):
    d = SEGBASE / seg / "frames"
    fs = sorted(d.glob("*.jpg"))
    idx = np.linspace(s, e, min(n, e - s + 1)).astype(int)
    st = []
    for i in idx:
        g = cv2.imread(str(fs[i]), cv2.IMREAD_GRAYSCALE)
        x0, y0, x1, y1 = _OVERLAY
        g[y0:y1, x0:x1] = 0
        st.append(cv2.resize(g, (BW, BH), interpolation=cv2.INTER_AREA))
    return np.median(np.stack(st), axis=0).astype(np.uint8)


def feats_of(w):
    bg = bg_of(w["seg"], w["start"], w["end"])
    k, d = _ORB.detectAndCompute(bg, None)
    return bg, k, d


def pair_stat(i, j, bgs, fs):
    ka, da = fs[i]
    kb, db = fs[j]
    if da is None or db is None or min(len(da), len(db)) < 20:
        return False, 0, 0.0, 1e9
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    ms = bf.match(da, db)
    if len(ms) < 20:
        return False, 0, 0.0, 1e9
    ms = sorted(ms, key=lambda m: m.distance)[:400]
    src = np.float32([ka[m.queryIdx].pt for m in ms]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in ms]).reshape(-1, 1, 2)
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0, maxIters=8000,
                                confidence=0.999)
    if H is None or inl is None:
        return False, 0, 0.0, 1e9
    n_inl = int(inl.sum())
    ratio = n_inl / len(ms)
    probes = np.float32([[0, 0], [BW, 0], [BW, BH], [0, BH], [BW / 2, BH / 2]]) \
        .reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(probes, H).reshape(-1, 2)
    shift = float(np.median(np.linalg.norm(mapped - probes.reshape(-1, 2), axis=1)))
    same = (ratio >= SAME_RATIO) and (shift <= SAME_SHIFT)
    return same, n_inl, round(ratio, 3), round(shift, 2)


class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def f(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def u(self, a, b):
        ra, rb = self.f(a), self.f(b)
        if ra != rb:
            self.p[rb] = ra


def main():
    MS.mkdir(parents=True, exist_ok=True)
    d = json.load(open(AW / "norm_calib" / "shot_clusters_clean14.json"))
    W = [w for w in d["windows"] if w["len"] >= MIN_LEN]
    dropped = [w for w in d["windows"] if w["len"] < MIN_LEN]
    n = len(W)
    print(f"窗口 {len(d['windows'])} ；其中 ≥{MIN_LEN} 帧的 {n} 个参与归并"
          f"（丢弃 {len(dropped)} 个碎窗）")

    with ThreadPoolExecutor(max_workers=6) as ex:
        got = list(ex.map(feats_of, W))
    bgs = [g[0] for g in got]
    fs = [(g[1], g[2]) for g in got]

    todos = [(i, j) for i in range(n) for j in range(i + 1, n)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        stats = list(ex.map(lambda t: pair_stat(t[0], t[1], bgs, fs), todos))

    uf = UF(n)
    edges = []
    for (i, j), (same, inl, ratio, shift) in zip(todos, stats):
        if same:
            uf.u(i, j)
            edges.append({"a": i, "b": j, "inl": inl, "ratio": ratio, "shift": shift})

    groups = {}
    for i in range(n):
        groups.setdefault(uf.f(i), []).append(i)
    clusters = sorted(groups.values(), key=lambda g: -sum(W[i]["len"] for i in g))

    total_frames = sum(W[i]["len"] for i in range(n))
    print(f"\n总帧 {total_frames} → 机位簇 {len(clusters)} 个\n")
    out = []
    for ci, g in enumerate(clusters):
        frames = sum(W[i]["len"] for i in g)
        members = [{"seg": W[i]["seg"], "start": W[i]["start"],
                    "end": W[i]["end"], "len": W[i]["len"]} for i in g]
        eps = sorted({W[i]["seg"].split("_")[0] for i in g})
        out.append({"cluster": ci, "n_windows": len(g), "frames": frames,
                    "frac": round(frames / total_frames, 3),
                    "episodes": eps, "members": members,
                    "pick_point": {"seg": None, "start": None}})   # 待老程点选后填
        print(f"簇{ci:<2} 窗{len(g):>2} 帧{frames:>4} ({frames/total_frames:>5.1%})  "
              f"跨 {len(eps)} 期 {','.join(eps)}")
        for m in members:
            print(f"      {m['seg']}#{m['start']}-{m['end']}({m['len']})")

    # 目视核实拼图：每簇把成员背景帧两列排布，标题写明 redundancy
    for ci, g in enumerate(clusters):
        tiles = []
        for i in g[:8]:
            im = cv2.cvtColor(bgs[i], cv2.COLOR_GRAY2BGR)
            cv2.putText(im, f"{W[i]['seg']}#{W[i]['start']}-{W[i]['end']}",
                        (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2,
                        cv2.LINE_AA)
            tiles.append(cv2.resize(im, (320, 180)))
        while len(tiles) % 2:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[r:r + 2]) for r in range(0, len(tiles), 2)]
        img = np.vstack(rows)
        cv2.imwrite(str(MS / f"calib_cluster_{ci}.jpg"), img,
                    [cv2.IMWRITE_JPEG_QUALITY, 88])

    # 累积覆盖：按簇帧数降序，标前 k 个簇能覆盖多少
    cum, acc = [], 0
    for ci, g in enumerate(clusters):
        acc += sum(W[i]["len"] for i in g)
        cum.append(round(acc / total_frames, 3))
    print("\n标前 k 个簇的累计帧覆盖: " + ", ".join(f"k={k+1}:{c:.0%}" for k, c in enumerate(cum)))

    res = {"total_windows": len(d["windows"]), "windows_used": n,
           "dropped_short": dropped, "total_frames": total_frames,
           "judge": {"ratio_min": SAME_RATIO, "shift_max_px": SAME_SHIFT},
           "clusters": out, "cum_coverage": cum,
           "same_edges": [{"a": W[e["a"]]["seg"] + "#" + str(W[e["a"]]["start"]),
                           "b": W[e["b"]]["seg"] + "#" + str(W[e["b"]]["start"]),
                           **{k: e[k] for k in ("inl", "ratio", "shift")}}
                          for e in edges]}
    dst = AW / "norm_calib" / "calib_units.json"
    dst.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nwrote", dst)
    print("拼图:", MS / "calib_cluster_*.jpg")


if __name__ == "__main__":
    main()
