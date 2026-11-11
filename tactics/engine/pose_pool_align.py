#!/usr/bin/env python3
"""跨窗口池化对齐检验 —— 扩样本的核心统计。

为什么必须池化
--------------
里程碑 03 只有 1 个窗口 / 5 个 PBP 事件，检验力不足；参数扫描 15 格只有 1 格显著
（6.7% vs α=0.05 期望 5%）⇒ 「物理线索，非统计结论」。本脚本把 4 个窗口
（W1 已有 + W2/W3/W4 新扩）的动作事件与 PBP 事件**池化**后重做检验。

池化的正确姿势（不是把所有时刻倒进一个池子）：
  - 每个**窗口内部**做循环平移（保持该窗口的跳跃数量与间隔结构）；
  - 统计量 = 各窗口命中数之和；
  - null 分布由「每窗口独立平移」的联合重复构成。
  这样窗口间的时钟映射误差不会互相污染，窗口内的时间结构也保留。

同时输出：
  - 逐窗口命中明细（哪个 PBP 事件被命中、被哪次跳跃命中）
  - **参数扫描**（half-win × air × reach 三维中取 half-win × air 二维，
    reach 单独扫）—— 第 9 铁律：单格显著不算结论。

用法:
  pose_pool_align.py <w1_out.json> <w2_out.json> ... [--half-win 1.5]
                     [--n-perm 2000] [--sweep] [--out pooled.json]
"""
from __future__ import annotations

import argparse
import json
import random
import statistics


def load_window(path):
    d = json.load(open(path))
    ts = [s["t"] for s in d["series"] if s["t"] is not None]
    return {
        "path": path,
        "t0": min(ts), "t1": max(ts),
        "jumps": sorted(d["jumps"], key=lambda z: z["t"]),
        "contests": sorted(d["contests"], key=lambda z: z["t"]),
        "events": sorted(d["events"], key=lambda z: z["t"]),
        "counts": d["counts"],
    }


def hit_stat(events, jump_ts, hw):
    return sum(1 for e in events if any(abs(j - e["t"]) <= hw for j in jump_ts))


def pooled_perm(wins, key, hw, n_perm, seed=20260924):
    obs = sum(hit_stat(w["events"], [j["t"] for j in w[key]], hw) for w in wins)
    rnd = random.Random(seed)
    null = []
    for _ in range(n_perm):
        tot = 0
        for w in wins:
            W = w["t1"] - w["t0"]
            d = rnd.uniform(-W / 2, W / 2)
            js = [(j["t"] - w["t0"] + d) % W + w["t0"] for j in w[key]]
            tot += hit_stat(w["events"], js, hw)
        null.append(tot)
    ge = sum(1 for x in null if x >= obs)
    p = (ge + 1) / (len(null) + 1)
    return {"observed_hits": obs, "n_events": sum(len(w["events"]) for w in wins),
            "n_actions": sum(len(w[key]) for w in wins),
            "null_mean": round(statistics.fmean(null), 3),
            "null_p90": round(sorted(null)[int(0.9 * len(null))], 3),
            "p_value": round(p, 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("windows", nargs="+")
    ap.add_argument("--half-win", type=float, default=1.5)
    ap.add_argument("--n-perm", type=int, default=2000)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    wins = [load_window(p) for p in a.windows]
    print(f"[载入] {len(wins)} 窗口")
    for w in wins:
        print(f"  {w['path'].split('/')[-2]:<4} t {w['t0']:.1f}-{w['t1']:.1f}s "
              f"({w['t1']-w['t0']:.1f}s)  跳跃 {len(w['jumps'])}  争抢 {len(w['contests'])}"
              f"  PBP {len(w['events'])}")

    hw = a.half_win
    res = {"half_win": hw, "n_perm": a.n_perm, "windows": []}
    for w in wins:
        rj = hit_stat(w["events"], [j["t"] for j in w["jumps"]], hw)
        res["windows"].append({
            "path": w["path"], "n_events": len(w["events"]),
            "n_jumps": len(w["jumps"]), "hits_jumps": rj,
            "events_hit": [{"t": e["t"], "clock": e["clock"], "kind": e["kind"],
                            "player": e["player"],
                            "nearest_jump_sec": round(min((abs(j["t"] - e["t"])
                                                           for j in w["jumps"]),
                                                          default=-1), 2)}
                           for e in w["events"]]})
        print(f"\n== 逐窗口 {w['path'].split('/')[-2]} ==")
        for e, eh in zip(w["events"], res["windows"][-1]["events_hit"]):
            near = eh["nearest_jump_sec"]
            mark = "✅" if 0 <= near <= hw else ("🟡" if 0 <= near <= 2 * hw else "·")
            print(f"  {mark} clock={e['clock']:>6.1f} t={e['t']:>6.1f}  "
                  f"{e['player']:<16} {e['kind']:<12} 最近跳跃 {near}s")

    print(f"\n===== 池化检验（half-win ±{hw}s）=====")
    for key, label in (("jumps", "跳跃"), ("contests", "争抢/封盖")):
        r = pooled_perm(wins, key, hw, a.n_perm)
        res[f"pooled_{key}"] = r
        verdict = "✅ 显著" if r["p_value"] < 0.05 else "⚠️ 不显著"
        print(f"[{label}] 命中 {r['observed_hits']}/{r['n_events']}  "
              f"动作 {r['n_actions']} 次  null 均值 {r['null_mean']}  "
              f"null p90 {r['null_p90']}  p={r['p_value']:.4f}  {verdict}")

    if a.sweep:
        print("\n===== 参数扫描（half-win × air，reach 固定 0.10）=====")
        half_wins = [1.0, 1.5, 2.0, 2.5, 3.0]
        airs = [0.10, 0.15, 0.20]
        cells = []
        for h in half_wins:
            row = []
            for air in airs:
                # air 阈值影响跳跃检测 → 需要重跑 pose_motion；这里只扫 hw 的部分
                # 用「air 阈值改变跳跃集合」的近似：以默认 air=0.15 的跳跃集合，
                # 按 air_dyn≥air 过滤（air_dyn 已存在每条跳跃里）
                sub = []
                for w in wins:
                    w2 = dict(w)
                    w2["jumps"] = [j for j in w["jumps"] if j["air_dyn"] >= air]
                    sub.append(w2)
                r = pooled_perm(sub, "jumps", h, a.n_perm,
                                seed=20260924 + int(h * 10) + int(air * 100))
                row.append(r)
                cells.append({"half_win": h, "air": air, **r})
                print(f"  hw=±{h}  air>={air}  命中 {r['observed_hits']}/{r['n_events']}"
                      f"  null {r['null_mean']}  p={r['p_value']:.4f}"
                      f"  {'✅' if r['p_value'] < 0.05 else '·'}")
        nsig = sum(1 for c in cells if c["p_value"] < 0.05)
        res["sweep"] = {
            "cells": cells, "n_cells": len(cells), "n_significant": nsig,
            "significant_share": round(nsig / len(cells), 3),
            "expected_share_under_alpha0.05": 0.05,
            "verdict": ("稳健" if nsig / len(cells) >= 0.30
                        else "⚠️ 不稳健：显著格数与 α=0.05 下的偶然期望无实质差别"),
        }
        print(f"[扫描] {nsig}/{len(cells)} 格显著 "
              f"（比例 {nsig/len(cells):.3f}，α=0.05 下期望 0.05）")
        print(f"[判定] {res['sweep']['verdict']}")

    if a.out:
        json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=1)
        print(f"\n[out] {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
