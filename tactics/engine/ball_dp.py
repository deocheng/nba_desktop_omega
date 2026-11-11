#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球轨迹 DP（tracking-by-detection）—— 用物理连续性从全部候选中选一条自洽链。

动机（实测）
----------
RF-DETR 每帧给 <=4 个候选（mean 0.86），Phase 1.5 只取「conf 最大」→ conf 翻转即
"瞬移"：w1 相邻帧位移 med=70px、p90=606px、**38% 的步长 >200px**（球不会瞬移）。
纯提阈值不是答案：conf>=0.65 只剩 28% 帧（w1）。

算法
----
逐帧节点 = {每个候选, "缺失"}；最小费用路径：
    emission:  -log(conf)            （越可信越便宜）
    missing:   +miss_pen 每帧        （代价可控地允许空洞）
    trans:     w_d * max(0, d - d0)  （d0 内自由：允许真实快速移动；超出按 L1 罚）
    跨"缺失"的转移不施加运动约束。
输出：选定路径 + 相对原始 top-1 的位移分布对比。

用法: ball_dp.py <window> [--d0 60] [--w-d 0.012] [--miss-pen 1.0] [--out json]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
BIG = 1e18

def ctr(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)

def run(win, d0, w_d, miss_pen, inp=None):
    rf = json.loads(Path(inp).read_text() if inp else (AW / f"{win}_rfdetr.json").read_text())
    files = sorted(rf.keys())
    n = len(files)
    # 节点：0..k-1 为候选，最后一个为"缺失"
    nodes = []
    for f in files:
        nodes.append([(k, c) for k, c in enumerate(rf[f])] + [None])
    # DP
    cost = np.full(len(nodes[0]), 0.0)      # 首帧：缺失免费（避免强开）
    cost = np.zeros(len(nodes[0]))
    back = [None] * n
    for i in range(1, n):
        prev = nodes[i - 1]; cur = nodes[i]
        ncost = np.full(len(cur), BIG); nback = np.full(len(cur), -1, int)
        for j, cj in enumerate(cur):
            if cj is None:
                e = miss_pen
                # 从任何前一状态都可转到"缺失"，不施加运动约束
                k = int(np.argmin(cost))
                ncost[j] = cost[k] + e; nback[j] = k
                continue
            _, c = cj
            e = -np.log(max(c["conf"], 1e-6))
            p = np.array(ctr(c["bbox"]))
            for k, ck in enumerate(prev):
                if cost[k] >= BIG:
                    continue
                t = 0.0
                if ck is not None:
                    q = np.array(ctr(ck[1]["bbox"]))
                    d = float(np.hypot(*(p - q)))
                    t = w_d * max(0.0, d - d0)
                v = cost[k] + e + t
                if v < ncost[j]:
                    ncost[j] = v; nback[j] = k
        cost = ncost; back[i] = nback
    # 回溯
    j = int(np.argmin(cost))
    path = [None] * n
    for i in range(n - 1, -1, -1):
        cj = nodes[i][j]
        path[i] = (files[i], cj[1] if cj is not None else None,
                   (cj[1]["conf"] if cj is not None else None))
        j = int(back[i][j]) if i > 0 else j
    return files, rf, path

def steps(path):
    pts = {}
    for f, c, _ in path:
        if c is not None:
            pts[f] = ctr(c["bbox"])
    ks = sorted(pts); s = []
    for a, b in zip(ks, ks[1:]):
        if int(b[1:6]) - int(a[1:6]) != 1:
            continue
        s.append(float(np.hypot(pts[b][0] - pts[a][0], pts[b][1] - pts[a][1])))
    return np.array(s), pts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("window")
    ap.add_argument("--d0", type=float, default=60.0)
    ap.add_argument("--w-d", type=float, default=0.012)
    ap.add_argument("--miss-pen", type=float, default=1.0)
    ap.add_argument("--in", dest="inp", default=None, help="候选检测 json（默认 <win>_rfdetr.json）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--out-poss", default=None,
                    help="输出可被 ball_possession.py --ball-json 消费的 {file:[{bbox,conf}]}")
    a = ap.parse_args()
    files, rf, path = run(a.window, a.d0, a.w_d, a.miss_pen, a.inp)
    # 原始 top-1
    raw = []
    for f in files:
        cs = rf[f]
        if cs:
            c = max(cs, key=lambda x: x["conf"])
            raw.append((f, c, c["conf"]))
        else:
            raw.append((f, None, None))
    for name, p in (("raw-top1", raw), ("DP", path)):
        s, pts = steps(p)
        cov = len(pts) / len(files)
        print(f"[{a.window}] {name:9s} 覆盖 {cov*100:5.1f}%  相邻位移 med={np.median(s):6.1f}px "
              f"p90={np.percentile(s,90):6.1f}px  >200px={np.mean(s>200)*100:4.0f}%  "
              f">400px={np.mean(s>400)*100:4.0f}%")
    if a.out:
        Path(a.out).write_text(json.dumps(
            {"window": a.window, "params": {"d0": a.d0, "w_d": a.w_d, "miss_pen": a.miss_pen},
             "path": [{"file": f, "bbox": c["bbox"] if c else None,
                       "conf": c["conf"] if c else None} for f, c, _ in path]}, indent=0))
        print("[out]", a.out)
    if a.out_poss:
        # 喂 ball_possession.py --ball-json：{filename:[{bbox,conf}]}（DP 选定的一颗球/帧）
        poss_map = {}
        for f, c, conf in path:
            poss_map[f] = [{"bbox": c["bbox"], "conf": conf}] if c is not None else []
        Path(a.out_poss).write_text(json.dumps(poss_map))
        n_with = sum(1 for v in poss_map.values() if v)
        print(f"[out-poss] {a.out_poss}  帧={len(poss_map)} 有球={n_with}"
              f"({n_with/len(poss_map)*100:.1f}%)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
