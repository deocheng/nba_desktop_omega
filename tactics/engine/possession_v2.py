#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球权链 v2 —— 以 PBP 语义为权威，用目视确认的球位做交叉验证。

═══ 为什么要重做（推翻旧结论）════════════════════════════════════
旧记录写的是「球权转移链**低于随机**：我们 6 次转移实测命中 1 次 = 17%，
±1s 随机基线 28%」。

这个结论的问题不在数字，在**前提**：
  ① 那「6 次转移」是**旧视觉管线自己声称的**，而旧管线的 73 个球位里
     **79% 落在 y>580 的地板带**（中位 y=620）——它追的根本不是球。
     所以那 6 次「转移」是噪声，不是观测。
  ② 拿噪声去对真值算命中率，再和随机基线比——**两边都不是对的东西**。
     结论「低于随机」只能说明「噪声不与真值对齐」，这是废话，不是发现。

本脚本改用**能站得住的观测**：
  · 权威侧：PBP 事件（`nba@5433`，gameid=22500843，period=4）
  · 观测侧：**经 ≥6.3x 目视确认**的真球位置（`ball_truth.json` 的 verified 集合）
  然后问一个**可以被证伪**的具体问题：
      「每一次 PBP 动作（出手/篮板/失误/盖帽）前后 ±1.5s 内，我们是否真的看到了球？」
  并附上严格的随机基线：p_rand = Σ(2×容差) / 窗口长度。

═══ 窗口内 PBP 实况（8 个事件，5 段球权）══════════════════════════
  482  84.0 SAS  D. Fox            Made Shot    Driving Floating Jump Shot 10ft
  483  69.0 TOR  R. Barrett         Missed Shot  3-pt from 25 ft        ← 动作①
  484  66.0 SAS  J. Champagnie      Rebound                             ← 动作②
  485  48.4 SAS  D. Fox             Turnover     Lost Ball              ← 动作③
  486  48.4 TOR  S. Barnes          Steal
  487  43.9 TOR  J. Poeltl          Missed Shot  Running Reverse Layup 2ft ← 动作④
  488  43.9 SAS  V. Wembanyama      Block                               ← 动作⑤
  489  41.1 SAS  V. Wembanyama      Rebound

  球权时间线：TOR(84.0→69.0) → 松散(69.0→66.0) → SAS(66.0→48.4)
              → TOR(48.4→43.9) → 松散(43.9→41.1) → SAS(41.1→…)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_ACTIONS = [
    {"n": "①", "eventnum": 483, "clock": 69.0, "team": "TOR", "player": "R. Barrett",
     "kind": "Missed Shot", "detail": "3-pt from 25 ft"},
    {"n": "②", "eventnum": 484, "clock": 66.0, "team": "SAS", "player": "J. Champagnie",
     "kind": "Rebound", "detail": "篮板"},
    {"n": "③", "eventnum": 485, "clock": 48.4, "team": "SAS", "player": "D. Fox",
     "kind": "Turnover", "detail": "Lost Ball（S. Barnes 抢断）"},
    {"n": "④", "eventnum": 487, "clock": 43.9, "team": "TOR", "player": "J. Poeltl",
     "kind": "Missed Shot", "detail": "Running Reverse Layup 2 ft"},
    {"n": "⑤", "eventnum": 488, "clock": 43.9, "team": "SAS", "player": "V. Wembanyama",
     "kind": "Block", "detail": "封盖（随后 41.1 自己抢下防守篮板）"},
]

# 球权时间线（由上面 8 个事件直接读出；clock 递减）
POSSESSION = [
    {"team": "TOR", "clock_from": 84.0, "clock_to": 69.0,
     "why": "D. Fox 命中后 TOR 发球进攻"},
    {"team": "LOOSE", "clock_from": 69.0, "clock_to": 66.0, "why": "Barrett 三分不中，球在空中"},
    {"team": "SAS", "clock_from": 66.0, "clock_to": 48.4, "why": "Champagnie 抢下篮板"},
    {"team": "TOR", "clock_from": 48.4, "clock_to": 43.9, "why": "S. Barnes 抢断"},
    {"team": "LOOSE", "clock_from": 43.9, "clock_to": 41.1, "why": "Poeltl 上篮被 Wembanyama 封盖"},
    {"team": "SAS", "clock_from": 41.1, "clock_to": 0.0, "why": "Wembanyama 防守篮板"},
]


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def clock_at(t, ct):
    """用逐帧时钟表 t → clock_sec（首选），退化到线性模型。"""
    if not ct:
        return None
    ks = sorted(ct.keys())
    best = min(ks, key=lambda k: abs(float(k) - t))
    return ct[best]


def team_at(clock):
    for p in POSSESSION:
        if p["clock_to"] <= clock <= p["clock_from"]:
            return p["team"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clock-table", required=True)
    ap.add_argument("--truth", required=True, help="ball_truth.json")
    ap.add_argument("--tight-cands", required=True, help="tight_candidates.json")
    ap.add_argument("--calib", required=True, help="ball_track_calibrated.json")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--t0", type=float, default=204.5)
    ap.add_argument("--t1", type=float, default=247.9)
    ap.add_argument("--tol", type=float, default=1.5)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    # clock_table.json 结构：{"frames":[{"frame":i,"clock_disp":"1:23","clock_sec":83.0},...]}
    # frame i ↔ t = t0 + (i-1)/fps（seg_possession 段为 2fps，故步长 0.5s）
    raw = load_json(a.clock_table) or {}
    frames = raw.get("frames", [])
    ct = {str(round(a.t0 + (f["frame"] - 1) * 0.5, 2)): float(f["clock_sec"])
          for f in frames if "clock_sec" in f}
    print(f"时钟表：{len(ct)} 帧  （源：{str(raw.get('source', '?'))[:46]}）")
    assert ct, "时钟表为空"

    truth = load_json(a.truth)
    vb = truth["method"]["verified_balls_6x"]
    ts = truth["method"]["targeted_suspicious_6x"]
    cb = truth["method"].get("census_judged_ball_4p2x", {"real": []})
    tier1 = set(vb["real"]) | set(ts["real"])
    tier2 = set(cb.get("real", [])) - tier1
    tc = load_json(a.tight_cands)

    def build(ids, tier):
        return [{"n": i, "t": z["t"], "x": z["cx"], "y": z["cy"], "d": z["d"],
                 "tier": tier} for i, z in enumerate(tc, 1) if i in ids]

    VERIFIED = build(tier1, "6.3x_adjudicated")
    CENSUS = build(tier2, "4.2x_census")
    ALL = sorted(VERIFIED + CENSUS, key=lambda z: z["t"])

    span = a.t1 - a.t0
    print("=" * 92)
    print("球权链 v2 —— PBP 语义为权威 + 目视确认球位交叉验证")
    print("=" * 92)
    print(f"窗口 t={a.t0}–{a.t1}（{span:.1f}s）  容差 ±{a.tol}s")
    print(f"目视确认真球位置：6.3x 终审层 {len(VERIFIED)} 个"
          f" + 4.2x 普查层 {len(CENSUS)} 个 = {len(ALL)} 个")
    print("  ⚠️ 两层置信度不同：6.3x 层可信；4.2x 层的误判率未知但非零（实测 12.5%）\n")

    print("── PBP 球权时间线 ──")
    for p in POSSESSION:
        t_from = None
        for k, v in ct.items():
            if abs(float(v) - p["clock_from"]) < 0.05 and t_from is None:
                t_from = k
        print(f"  {p['team']:<6} clock {p['clock_from']:>5.1f} → {p['clock_to']:>5.1f}"
              f"   （{p['why']}）")

    z = 1.96

    def wilson(k, n):
        if n == 0:
            return 0.0, (0.0, 0.0)
        p = k / n
        d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d
        h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        return p, (max(0.0, c - h), min(1.0, c + h))

    def action_test(pool, label):
        print(f"\n── 动作级命中检验 [{label}]：每次 PBP 动作 ±{a.tol}s 内是否目视看到球？──")
        hits, rows_ = [], []
        for ac in DEFAULT_ACTIONS:
            best_k, best_d = None, 9e9
            for k, v in ct.items():
                if abs(v - ac["clock"]) < best_d:
                    best_d, best_k = abs(v - ac["clock"]), k
            t_ac = float(best_k)
            near = [z for z in pool if abs(z["t"] - t_ac) <= a.tol]
            rows_.append({"action": ac, "t_event": t_ac, "n_near": len(near),
                          "near": [{"t": z["t"], "x": z["x"], "y": z["y"],
                                    "tier": z["tier"]} for z in near]})
            hits.append(1 if near else 0)
            mk = "✅" if near else "❌"
            print(f"  {ac['n']} {ac['kind']:<13} clock {ac['clock']:>5.1f} → t={t_ac:>6.1f}s  "
                  f"{mk} {len(near)} 个"
                  + (f"  最近 t={near[0]['t']:.1f}s ({near[0]['x']:.0f},{near[0]['y']:.0f})"
                     f" [{near[0]['tier']}]" if near else ""))
        k_, n_ = sum(hits), len(hits)
        ph_, (lo, hi) = wilson(k_, n_)
        print(f"    命中 {k_}/{n_} = {ph_*100:.0f}%  （95% CI {lo*100:.0f}–{hi*100:.0f}%）"
              f"  随机基线 {p_rand*100:.1f}%  → "
              + ("✅ 显著高于随机" if lo > p_rand else "⚠️ 未显著高于随机"))
        return {"rows": rows_, "n_hit": k_, "n_actions": n_, "rate": round(ph_, 3),
                "ci95": [round(lo, 3), round(hi, 3)], "p_rand": round(p_rand, 3),
                "significant": bool(lo > p_rand)}

    p_rand = min(1.0, (2 * a.tol * len(DEFAULT_ACTIONS)) / span)
    res_t1 = action_test(VERIFIED, "仅 6.3x 终审层")
    res_all = action_test(ALL, "6.3x + 4.2x 合并层")

    # ── 反向检验：目视球位落在哪个球权段 ────────────────────
    print("\n── 反向检验：目视确认球位落在哪些球权段 ──")
    buckets = {}
    for z in ALL:
        ck = clock_at(z["t"], ct)
        tm = team_at(ck) if ck is not None else None
        buckets.setdefault(tm, []).append(z)
        z["clock"] = ck
        z["team_expected"] = tm
    for tm in ("TOR", "SAS", "LOOSE", None):
        if tm in buckets:
            zs = buckets[tm]
            print(f"  {str(tm):<6} {len(zs):>3} 个目视球位   t "
                  f"{min(z['t'] for z in zs):.1f}–{max(z['t'] for z in zs):.1f}s")
    exp = sum(len(v) for k, v in buckets.items() if k in ("TOR", "SAS"))
    loose = len(buckets.get("LOOSE", []))
    print(f"  落在明确球权段 {exp} 个，落在「松散球」段 {loose} 个")

    # ── 覆盖度偏差检验（重要：必须报告，不能只看命中率）──────
    print("\n── ⚠️ 覆盖度偏差检验（决定上面的命中率能不能用）──")
    per = []
    for p_ in POSSESSION:
        zs = [z for z in ALL if z["clock"] is not None
              and p_["clock_to"] <= z["clock"] <= p_["clock_from"]]
        dur = p_["clock_from"] - p_["clock_to"]
        per.append({"team": p_["team"], "clock_from": p_["clock_from"],
                    "clock_to": p_["clock_to"], "dur_sec": round(dur, 1),
                    "n_ball": len(zs), "rate_per_sec": round(len(zs) / dur, 2) if dur else None})
        print(f"  {p_['team']:<6} clock {p_['clock_from']:>5.1f}→{p_['clock_to']:>5.1f}"
              f"  {dur:>5.1f}s  {len(zs):>3} 个球位  {len(zs)/dur if dur else 0:>5.2f} 个/秒")
    rates = [x["rate_per_sec"] for x in per if x["rate_per_sec"] is not None]
    if len(rates) >= 2 and min(rates) > 0:
        print(f"  最高/最低检出率比 = {max(rates)/min(rates):.1f}x"
              f" → {'⚠️ 检出率高度依赖球所处区域，命中率被覆盖度偏差污染' if max(rates)/min(rates) > 3 else '✅ 检出率较均匀'}")
    elif min(rates or [1]) == 0:
        print(f"  有 {sum(1 for r in rates if r == 0)} 段检出率=0 →"
              f" ⚠️ 命中率被覆盖度偏差污染（不是检测器的正确性证据）")

    # ── 置换检验（针对覆盖度偏差的严格控制）────────────────
    # 直觉：检测器只在部分时段/区域开火（实测 42.6x 不均匀）。
    # 那么「动作 ±tol 内有球位」这件事可能只是因为动作恰好落在高检出时段里。
    # 控制方法：把**整条球位时间序列做循环位移**（保持时间序列的内部结构、
    # 检出密度剖面完全不变，只破坏「与 PBP 动作的时间对齐」），重复 N 次，
    # 得到 null 分布。p = P(位移后命中数 ≥ 实际命中数)。
    import random
    random.seed(20260923)
    times = sorted(z["t"] for z in ALL)
    t_actions = []
    for ac in DEFAULT_ACTIONS:
        _, bk = min(((abs(v - ac["clock"]), k) for k, v in ct.items()))
        t_actions.append(float(bk))
    W = span

    def hits_for(shifted):
        k = 0
        for ta in t_actions:
            for s in shifted:
                if abs(s - ta) <= a.tol:
                    k += 1
                    break
        return k

    obs = hits_for(times)
    NULL = []
    for _ in range(2000):
        d = random.uniform(-W / 2, W / 2)

        def sh(x, d=d):
            y = x + d
            while y < a.t0:
                y += W
            while y > a.t1:
                y -= W
            return y
        NULL.append(hits_for([sh(x) for x in times]))
    ge = sum(1 for v in NULL if v >= obs)
    p_perm = (ge + 1) / (len(NULL) + 1)
    print("\n── 置换检验：循环位移 2000 次（保持检出密度剖面，只破坏与动作的时间对齐）──")
    print(f"  实际命中 {obs}/5   置换 null 均值 {sum(NULL)/len(NULL):.2f}"
          f"   null 分布 {dict(sorted({v: NULL.count(v) for v in set(NULL)}.items()))}")
    print(f"  p = P(null ≥ 实际) = {p_perm:.4f}  → "
          + ("✅ 显著（p<0.05），对齐不是覆盖度偏差造成的"
             if p_perm < 0.05 else "⚠️ 不显著，命中率无法与覆盖度偏差区分"))
    print(f"  ⚠️ 同时必须报告：各球权段检出率 {[x['rate_per_sec'] for x in per]}"
          f"（最高/最低 {max(rates)/min(rates):.1f}x）—— 检测器的**响应率**仍高度不均，"
          f"这不影响本置换检验的结论，但意味着不能把「有球位」当作「每帧都能看到球」。")

    # ── 与旧结论对照 ─────────────────────────────────────
    old = {
        "claim": "球权转移链低于随机：6 次转移实测 1/6 = 17%，随机基线 28%",
        "why_invalid": [
            "①「6 次转移」出自旧视觉管线自身，而该管线 73 个球位中 79% 落在 y>580 地板带"
            "（中位 y=620，t=219.5 旧球位 (1016,669) 距真球 334.5px）——追的不是球，是地板；",
            "② 用未被验证的噪声观测去对真值算命中率，再与随机基线相比 —— 两边都不可靠；",
            "③ 因此「低于随机」只等价于「噪声不与真值对齐」，不构成对方法的证据。",
        ],
        "corrected": {
            "n_actions_tested": res_all["n_actions"],
            "hit": res_all["n_hit"],
            "rate": res_all["rate"],
            "ci95": res_all["ci95"],
            "p_rand": res_all["p_rand"],
            "significant": res_all["significant"],
            "note": "用「经目视确认的球位」替换旧噪声观测后重测。关键结论不是命中率本身，"
                    "而是**覆盖度偏差检验**：旧结论的两边（观测与基线）都不可靠，"
                    "因此旧结论作废；新结论受覆盖度偏差限制，只在受限范围内成立。",
        },
    }
    print("\n── 旧结论处置 ──")
    print(f"  作废：{old['claim']}")
    for w in old["why_invalid"]:
        print(f"    {w}")
    print(f"  修正后：动作命中 {res_all['n_hit']}/{res_all['n_actions']} = "
          f"{res_all['rate']*100:.0f}%（基线 {res_all['p_rand']*100:.1f}%，"
          f"CI {res_all['ci95'][0]*100:.0f}–{res_all['ci95'][1]*100:.0f}%）")

    out = {
        "window": {"t0": a.t0, "t1": a.t1, "span_sec": round(span, 1), "tol_sec": a.tol},
        "pbp_possession_timeline": POSSESSION,
        "pbp_actions": DEFAULT_ACTIONS,
        "action_test_tier1_6p3x": res_t1,
        "action_test_all": res_all,
        "coverage_bias": {"per_possession": per,
                          "max_over_min_rate": (round(max(rates) / min(rates), 2)
                                                if rates and min(rates) > 0 else None)},
        "permutation_test": {"n_perm": 2000, "observed_hits": obs,
                             "null_mean": round(sum(NULL) / len(NULL), 3),
                             "p_value": round(p_perm, 4),
                             "significant": bool(p_perm < 0.05),
                             "method": "循环位移整条球位时间序列（保持检出密度剖面不变，"
                                       "只破坏与 PBP 动作的时间对齐）"},
        "verified_ball_positions": ALL,
        "possession_buckets": {str(k): len(v) for k, v in buckets.items()},
        "old_claim_superseded": old,
    }
    p = os.path.join(a.outdir, "possession_v2.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n[out] {p}")


if __name__ == "__main__":
    main()
