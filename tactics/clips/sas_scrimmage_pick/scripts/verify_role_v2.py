#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 narrative_role 阈值的**离线回放验证**（不重跑检测，只用落盘指标）。
真值：poss_full 前5秒 = 老程目视确认 transition。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import json
from collections import Counter

from common.nba_paths import tactics_data_file

M = str(tactics_data_file("clips/sas_scrimmage_pick/verify_trans/poss_full_metrics.json"))
P = str(tactics_data_file("action_work/norm_calib/smooth_picks_merged_role.json"))

TRANS_MIN_MV, TRANS_MIN_STRAIGHT, TRANS_MIN_SPD = 3, 0.85, 4.5
RESULT_MIN_SPD = 8.0
ORIGIN_MIN_COORD = 0.85


def role(m):
    n_mv = m.get("n_movers", 0)
    spd = m.get("median_speed_px", 0.0)
    coord = m.get("coordination", 0.0)
    straight = m.get("straightness", 0.0)
    if n_mv >= TRANS_MIN_MV and straight >= TRANS_MIN_STRAIGHT and spd >= TRANS_MIN_SPD:
        return "transition"
    if n_mv >= 3 and coord >= ORIGIN_MIN_COORD and spd < 6.0:
        return "origin"
    if spd >= RESULT_MIN_SPD:
        return "result"
    return "unknown"


print("=== ① 真值回归：poss_full 三段 ===")
gt = json.load(open(M))
ok = True
for s in gt["segments"]:
    r = role(s["metrics"])
    good = (r == "transition") if s["expect"].startswith("transition") else None
    mark = "✅" if good else ("—" if good is None else "❌")
    m = s["metrics"]
    print(f"  {mark} {s['name']:<22} v1={s['current_gate']:<10} v2={r:<10} "
          f"straight={m['straightness']:<6} coord={m['coordination']:<6} "
          f"spd={m['median_speed_px']:<6} n_mv={m['n_movers']}")

print("\n=== ② 语料池 27 窗 v1 vs v2 分布 ===")
d = json.load(open(P))
allrows = d["smooth"] + d["static"] + d["excluded_by_laocheng"]
v1 = Counter(r.get("narrative_role") for r in allrows)
v2 = Counter(role(r) for r in allrows)
print(f"  总窗 = {len(allrows)} (声明 n_windows={d['n_windows']})")
print(f"  v1: {dict(sorted(v1.items()))}")
print(f"  v2: {dict(sorted(v2.items()))}")
print(f"  v1 transition = {v1.get('transition',0)}  →  v2 transition = {v2.get('transition',0)}")

print("\n=== ③ v2 判为 transition 的窗（需老程目视确认）===")
n = 0
for r in sorted(allrows, key=lambda x: -x.get("straightness", 0)):
    if role(r) != "transition":
        continue
    n += 1
    m = r
    print(f"  clus{m['cluster']:<4}{m['seg']:<10}win {m['win_start']}-{m['win_end']:<6}"
          f"straight={m['straightness']:<6}coord={m['coordination']:<6}spd={m['median_speed_px']:<6}"
          f"n_mv={m['n_movers']:<4}老程={m.get('laocheng_verdict')}")
if n == 0:
    print("  （无）")

print("\n=== ④ 变更明细（v1≠v2）===")
ch = 0
for r in allrows:
    a, b = r.get("narrative_role"), role(r)
    if a != b:
        ch += 1
        print(f"  clus{r['cluster']:<4}{r['seg']:<10}{a} -> {b}")
print(f"  变更 {ch}/{len(allrows)} 条")
