#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_resolve.py — 用人工判读结果把 A/B 区间收口成**单点精度**。

方法（分层比例估计）
------------------
设标注库 n 帧，旧口径命中 same_TP 帧（新 top-1 与旧框一致且旧框是 TP）。
变化帧分两层：
  层 A = 原标注 TP 的变化帧，共 nA 个，**全判**，命中 cA 个（新框是球）
  层 B = 原标注 FP 的变化帧，共 nB 个，判读 mB 个（抽样），其中 cB 个新框是球
层 B 的命中数估计  ĉB = cB * nB / mB

新口径精度  P̂_new = (same_TP + cA + ĉB) / n
区间         [ (same_TP+cA)/n , (same_TP+cA+nB)/n ]   ← 与 allcand_ab.json 的 lo/hi 一致（校验用）
层 B 的抽样误差用 Wilson 区间传播到 P̂_new。

用法:
  python engine/ab_resolve.py            # 读 measure/judge/judge_{key,verdicts}.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
from pathlib import Path

from common.nba_paths import tactics_data_file

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
JD = MS / "judge"
Z = 1.959963984540054


def wilson(k, n, z=Z):
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def main():
    key = json.load(open(JD / "judge_key.json"))
    ver = json.load(open(JD / "judge_verdicts.json"))
    n = key["n_bank"]
    same_tp = key["same_TP"]
    gs = key["group_sizes"]
    nA, nB = gs["changed_oldTP"], gs["changed_oldFP"]

    cA = cB = mA = mB = 0
    unc = 0
    for e in key["key"]:
        v = ver.get(str(e["idx"]))
        if not v:
            continue
        if v == "UNC":
            unc += 1
            continue
        hit = 1 if v == "BALL" else 0
        if e["label"] == "TP":
            cA += hit; mA += 1
        else:
            cB += hit; mB += 1

    est_B = (cB * nB / mB) if mB else 0.0
    C = cA + est_B
    P = (same_tp + C) / n
    lo_hard = (same_tp + cA) / n
    hi_hard = (same_tp + cA + nB) / n

    # 抽样误差传播（层 B 命中率的 Wilson → 映射到 P̂ 的区间）
    if mB:
        blo, bhi = wilson(cB, mB)
        P_lo_s = (same_tp + cA + blo * nB) / n
        P_hi_s = (same_tp + cA + bhi * nB) / n
    else:
        P_lo_s = P_hi_s = P

    old = key["oldP"] / 100.0
    print("=" * 72)
    print("全候选重排 A/B 收口（人工判读）")
    print("=" * 72)
    print(f"标注库 n = {n}    旧口径（conf top-1）精度 = {old*100:.1f}%")
    print(f"不变帧命中 same_TP = {same_tp}（旧框即新 top-1）")
    print(f"层A 原TP变化帧 {nA}：全判 {mA}，判为球 {cA}"
          f"  ⇒ 贡献 {cA}（此层是**下行风险**）")
    print(f"层B 原FP变化帧 {nB}：抽判 {mB}，判为球 {cB}"
          f"（{cB/mB*100 if mB else 0:.0f}%）⇒ 估计贡献 ĉB = {est_B:.1f}")
    print(f"未判/看不清 {unc}")
    print("-" * 72)
    print(f"新口径精度 P̂ = ({same_tp} + {cA} + {est_B:.1f}) / {n} = **{P*100:.1f}%**")
    print(f"硬区间（层B全错/全对）   [{lo_hard*100:.1f}%, {hi_hard*100:.1f}%]")
    print(f"含抽样误差 95%          [{P_lo_s*100:.1f}%, {P_hi_s*100:.1f}%]")
    print("-" * 72)
    d = P - old
    print(f"相对旧口径 Δ = {d*100:+.1f} 点 "
          f"⇒ {'提升' if d > 0.005 else ('下降' if d < -0.005 else '基本不变')}")
    print(f"是否达 90%：{'✅ 达到' if P >= 0.90 else '❌ 未达到'}（差 {abs(P-0.90)*100:.1f} 点）")
    print(f"90% 是否在含抽样误差区间内："
          f"{'是 ⇒ 仍不可裁定' if P_lo_s <= 0.90 <= P_hi_s else '否'}")
    print("=" * 72)

    json.dump({"n": n, "oldP": old, "same_TP": same_tp,
               "layerA": {"n": nA, "judged": mA, "hit": cA},
               "layerB": {"n": nB, "judged": mB, "hit": cB, "est": est_B},
               "unc": unc, "P_new": P,
               "hard_interval": [lo_hard, hi_hard],
               "ci_with_sampling": [P_lo_s, P_hi_s],
               "delta_vs_old": d, "passes_90": bool(P >= 0.90)},
              open(MS / "ab_resolved.json", "w"), ensure_ascii=False, indent=1)
    print(f"→ {MS/'ab_resolved.json'}")


if __name__ == "__main__":
    main()
