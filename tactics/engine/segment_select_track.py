#!/usr/bin/env python3
"""第 4+5.5 层合并：**带时序一致性的场上球员遴选与追踪**。

═══════════════════════════════════════════════════════════════════════
为什么必须合并（这是本层存在的全部理由）
═══════════════════════════════════════════════════════════════════════
先做的两版都失败，且失败原因值得记下来：

  版本 1：每帧独立按检测质量取 top-10
      -> 球员置信度抖动一帧就掉出 top-10，被裁判或别的球员顶替，
         身份链**逐帧断开**：47–57 个目标上追踪碎裂成 373 条轨迹，
         在遴选后的 10 人上二次追踪也只降到 129 条（中位长度仅 3 帧）。
      -> 「同一对球员的关系是否持续」这个问题根本没法回答，
         而它恰恰是战术分析的核心。

  版本 2：先遴选、再对选中的 10 人做二次追踪
      -> 目标干净了，但**遴选本身不稳定**，断链发生在遴选这一步，
         二次追踪再准也救不回来。

  版本 3（本文件）：把「选谁上场」和「他是谁」放进**同一个匹配问题**里
      -> 每帧先取质量前 K 个候选（K=16，比 10 宽，给替补留位置），
         先用匈牙利匹配到**已有身份**（保连续性），
         落选的老身份进入 coasting，匹配不上的候选才新建身份。
         输出时按「检测质量 + 身份年龄」的复合分选前 10 ——
         于是稳定球员会被优先留住，抖动不再导致掉线。

已实测排除的其它判据（全部栽在「转播机位持续推拉摇移」上）：
  ✗ 固定球场多边形（44 秒内相机累计平移 2468px）
  ✗ 身高阈值（观众 92–285px vs 球员 115–215px，完全重叠）
  ✗ 时间共现（相机摇移把共现稀释到 27.6%）
  ✗ 相机补偿 + 时间共现（仍只提升到 42.5%）
  ✗ 躯干颜色聚类分球队/裁判（自动白平衡把白球衣也压到亮度 ~100，无干净间隙）

⚠️ 已知残留：每帧通常含 1–2 名裁判（同样在场上、全身可见、置信度高），未剔除。

输出 `select_tracks.json`：每帧 ≤10 名场上球员，带跨帧稳定 `pid`。

用法：
  segment_select_track.py <tracks.json> <outdir> [--pool 16] [--top-n 10]
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

H_MID, H_TOL = 165.0, 90.0          # 1080p 广角转播下球员典型框高与容差
PERSIST_W = 0.18                    # 身份年龄对遴选分的加成系数


def quality(p: dict, img_h: float) -> float:
    x1, y1, x2, y2 = p["box"]
    h = max(y2 - y1, 1.0)
    w = max(x2 - x1, 1.0)
    midh = 1.0 / (1.0 + abs(h - H_MID) / H_TOL)
    top_pen = 0.25 if y2 < 0.18 * img_h else 1.0
    return p["conf"] * midh * ((h * w) ** 0.25) * top_pen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tracks_json")
    ap.add_argument("outdir")
    ap.add_argument("--pool", type=int, default=16, help="每帧纳入匹配的候选池大小")
    ap.add_argument("--top-n", type=int, default=10, help="输出到下游的人数")
    ap.add_argument("--gate", type=float, default=0.15, help="脚点位移门控 / 画面高")
    ap.add_argument("--size-gate", type=float, default=0.60)
    ap.add_argument("--max-missed", type=int, default=3)
    ap.add_argument("--img-h", type=float, default=1080.0)
    a = ap.parse_args()

    d = json.load(open(a.tracks_json))
    frames = d["frames"]
    gate = a.gate * a.img_h

    tracks: dict[int, dict] = {}
    nxt = 1
    out = []

    for f in frames:
        # 归一化：上游 tracks.json 的 players 只有 {id,box,conf,h}，这里补出脚点
        for p in f["players"]:
            if "foot" not in p:
                x1, y1, x2, y2 = p["box"]
                p["foot"] = [round((x1 + x2) / 2, 1), round(y2, 1)]
        cands = sorted(f["players"], key=lambda z: -quality(z, a.img_h))[:a.pool]
        live = {t: v for t, v in tracks.items() if v["missed"] <= a.max_missed}
        tids = list(live)

        assign: dict[int, int] = {}          # 候选下标 -> pid
        matched = []
        if tids and cands:
            C = np.full((len(tids), len(cands)), 1e6)
            for i, tid in enumerate(tids):
                v = live[tid]
                fx, fy = v["foot"]
                vh = max(v["h"], 1.0)
                for j, p in enumerate(cands):
                    px, py = p["foot"]
                    dp = math.hypot(px - fx, py - fy)
                    ds = abs(math.log(vh / max(p["h"], 1.0)))
                    if dp > gate or ds > a.size_gate:
                        continue
                    C[i, j] = dp / gate + 0.5 * ds
            ri, ci = linear_sum_assignment(C)
            matched = [(tids[i], ci[k]) for k, i in enumerate(ri) if C[i, ci[k]] < 1e5]

        used_c, used_t = set(), set()
        for tid, cj in matched:
            used_t.add(tid)
            used_c.add(cj)
            tr = tracks[tid]
            p = cands[cj]
            tr["foot"] = p["foot"]
            tr["box"] = p["box"]
            tr["h"] = p["h"]
            tr["conf"] = p["conf"]
            tr["missed"] = 0
            tr["age"] += 1
            tr["frames"].append(f["idx"])
            assign[cj] = tid

        for tid in tids:
            if tid not in used_t:
                tracks[tid]["missed"] += 1

        for cj, p in enumerate(cands):
            if cj in used_c:
                continue
            assign[cj] = None            # 暂不建身份，等入选结果出来再定

        # 输出：复合分 = 质量 + 年龄加成
        roster = []
        for cj, p in enumerate(cands):
            pid = assign[cj]
            if pid is not None and tracks[pid]["missed"] > 0:
                continue
            age = tracks[pid]["age"] if pid is not None else 1
            comp = quality(p, a.img_h) * (1.0 + PERSIST_W * math.log1p(age))
            roster.append((comp, cj, p))
        roster.sort(key=lambda z: -z[0])
        roster = roster[:a.top_n]

        # 只为**真正入选**且此前无身份的候选新建 pid（避免身份表被池内垃圾撑爆）
        plist = []
        for r, (comp, cj, p) in enumerate(roster, 1):
            pid = assign[cj]
            if pid is None:
                pid = nxt
                tracks[pid] = {"foot": p["foot"], "box": p["box"], "h": p["h"],
                               "conf": p["conf"], "missed": 0, "age": 1,
                               "frames": [f["idx"]]}
                assign[cj] = pid
                nxt += 1
            plist.append({"rank": r, "pid": pid, "sel_id": f"p{r}",
                          "box": p["box"], "foot": p["foot"],
                          "h": p["h"], "conf": p["conf"],
                          "age": tracks[pid]["age"], "comp": round(comp, 4)})
        out.append({"idx": f["idx"], "t": f["t"], "n_det": f["n_person_det"],
                    "n_pool": len(cands), "players": plist,
                    "ball": f.get("ball")})

    ln = [len(v["frames"]) for v in tracks.values()]
    active = [v for v in tracks.values() if len(v["frames"]) >= 15]
    hist: dict[int, int] = defaultdict(int)
    for x in ln:
        hist[x] += 1

    meta = {"n_frames": len(frames), "n_pids": len(tracks),
            "track_len": {"min": min(ln), "median": sorted(ln)[len(ln) // 2], "max": max(ln)},
            "n_ge_15f": len(active),
            "n_ge_30f": sum(1 for x in ln if x >= 30),
            "n_ge_60f": sum(1 for x in ln if x >= 60),
            "pool": a.pool, "top_n": a.top_n, "gate_px": round(gate, 1),
            "known_issue": "每帧含约 1–2 名裁判（未剔除）",
            "track_len_hist": dict(sorted(hist.items()))}
    os.makedirs(a.outdir, exist_ok=True)
    with open(os.path.join(a.outdir, "select_tracks.json"), "w") as fp:
        json.dump({"meta": meta, "frames": out}, fp, ensure_ascii=False, indent=1)

    print(f"[select+track] {len(frames)} 帧 | 候选池 {a.pool} -> 输出 {a.top_n} | "
          f"身份 {meta['n_pids']} 条")
    print(f"[轨迹长度] min={meta['track_len']['min']} 中位={meta['track_len']['median']} "
          f"max={meta['track_len']['max']} / 共 {len(frames)} 帧")
    print(f"[长轨迹] ≥15帧 {meta['n_ge_15f']} | ≥30帧 {meta['n_ge_30f']} | "
          f"≥60帧 {meta['n_ge_60f']}")
    print(f"[⚠️ 已知] {meta['known_issue']}")
    print(f"[out] {os.path.join(a.outdir, 'select_tracks.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
