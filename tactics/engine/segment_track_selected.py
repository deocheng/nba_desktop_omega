#!/usr/bin/env python3
"""第 5.5 层：对「已选中的 10 人」做二次追踪，给跨帧稳定身份。

为什么要有这一层：
  第一遍追踪是在 30–47 个 person（含观众/替补/裁判）上做的，噪声极大，
  实测碎裂成 373 条轨迹（平均每条只覆盖 2–7 帧），无法支撑时序聚合 ——
  而「同一对球员的关系是否持续」正是战术分析的核心问题。

  但**遴选后的每帧只有 10 个干净目标**（观众已被剔除），
  在这个小集合上重新匹配，正确率会高得多。

做法：
  在选中的 10 人上跑一次匈牙利匹配，代价 = 脚点距离 + 尺寸对数比，
  门控放开到 0.14×画面高（2fps 下球员最多跑 ~60px，100px 门控足够）。
  匹配不上则新建 ID；某 ID 连续 miss 超限即结束。

输出 `tracks_sel.json`：每帧 10 人带稳定 `pid`（跨帧身份）。

用法：
  segment_track_selected.py <players.json> <outdir> [--gate 0.14] [--max-missed 3]
"""
from __future__ import annotations

import argparse
import json
import math
import os

import numpy as np
from scipy.optimize import linear_sum_assignment


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("players_json")
    ap.add_argument("outdir")
    ap.add_argument("--gate", type=float, default=0.14, help="脚点位移门控 / 画面高")
    ap.add_argument("--size-gate", type=float, default=0.55, help="|log(h1/h2)| 上限")
    ap.add_argument("--max-missed", type=int, default=3)
    ap.add_argument("--img-h", type=float, default=1080.0)
    a = ap.parse_args()

    d = json.load(open(a.players_json))
    frames = d["frames"]
    gate = a.gate * a.img_h

    tracks: dict[int, dict] = {}
    nxt = 1
    out = []

    for f in frames:
        pls = f["players"]
        live = {t: v for t, v in tracks.items() if v["missed"] <= a.max_missed}
        tids = list(live)

        matched = []
        if tids and pls:
            C = np.full((len(tids), len(pls)), 1e6)
            for i, tid in enumerate(tids):
                v = live[tid]
                fx, fy = v["foot"]
                vh = max(v["h"], 1.0)
                for j, p in enumerate(pls):
                    px, py = p["foot"]
                    dp = math.hypot(px - fx, py - fy)
                    ds = abs(math.log(vh / max(p["h"], 1.0)))
                    if dp > gate or ds > a.size_gate:
                        continue
                    C[i, j] = dp / gate + 0.5 * ds
            ri, ci = linear_sum_assignment(C)
            matched = [(tids[i], ci[k]) for k, i in enumerate(ri) if C[i, ci[k]] < 1e5]

        used_p, used_t = set(), set()
        assign: dict[int, int] = {}
        for tid, pj in matched:
            used_t.add(tid)
            used_p.add(pj)
            tr = tracks[tid]
            p = pls[pj]
            tr["foot"] = p["foot"]
            tr["box"] = p["box"]
            tr["h"] = p["h"]
            tr["conf"] = p["conf"]
            tr["missed"] = 0
            tr["frames"].append(f["idx"])
            assign[pj] = tid

        for tid in tids:
            if tid not in used_t:
                tracks[tid]["missed"] += 1

        for pj, p in enumerate(pls):
            if pj in used_p:
                continue
            tracks[nxt] = {"foot": p["foot"], "box": p["box"], "h": p["h"],
                           "conf": p["conf"], "missed": 0, "frames": [f["idx"]]}
            assign[pj] = nxt
            nxt += 1

        out.append({"idx": f["idx"], "t": f["t"],
                    "players": [{"pid": assign[j], **p} for j, p in enumerate(pls)],
                    "ball": f.get("ball")})

    ln = [len(v["frames"]) for v in tracks.values()]
    hist: dict[int, int] = {}
    for x in ln:
        hist[x] = hist.get(x, 0) + 1
    long_tracks = {t: len(v["frames"]) for t, v in tracks.items() if len(v["frames"]) >= 15}

    meta = {"n_frames": len(frames), "n_tracks": len(tracks),
            "track_len": {"min": min(ln), "median": sorted(ln)[len(ln) // 2], "max": max(ln)},
            "n_tracks_ge_15f": len(long_tracks),
            "n_tracks_ge_30f": sum(1 for v in ln if v >= 30),
            "coverage_of_selected": round(sum(ln) / max(sum(len(f["players"]) for f in frames), 1), 2),
            "gate_px": round(gate, 1)}
    os.makedirs(a.outdir, exist_ok=True)
    with open(os.path.join(a.outdir, "tracks_sel.json"), "w") as fp:
        json.dump({"meta": meta, "frames": out,
                   "track_len": {str(k): v for k, v in sorted(hist.items())}},
                  fp, ensure_ascii=False, indent=1)

    print(f"[reid] {len(frames)} 帧 | 二次追踪 -> {meta['n_tracks']} 条身份")
    print(f"[轨迹长度] min={meta['track_len']['min']} 中位={meta['track_len']['median']} "
          f"max={meta['track_len']['max']}  (跨 {len(frames)} 帧)")
    print(f"[长轨迹] ≥15 帧 {meta['n_tracks_ge_15f']} 条 | ≥30 帧 {meta['n_tracks_ge_30f']} 条")
    print(f"[身份复用率] {meta['coverage_of_selected']} "
          f"(选中总数 / 身份数；越低说明碎裂越少)")
    print(f"[out] {os.path.join(a.outdir, 'tracks_sel.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
