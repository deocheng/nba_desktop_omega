#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pilot_decision.py —— 汇总协议试点两轮，裁决「本 AI 能否当标注者」。

为什么需要它
------------
judge_pilot.py 每轮单独评分（n=25/18），单轮 CI 太宽、拒不动 90% 假设。
把两轮合并才有功效。但直接合并有两个必须处理的坑：

1) 🔴 代理真值自身有误差。truth 取自「两套同日标注一致」的 46 个样本（A4.11），
   它们只是**最可用的代理**，不是无误差真值。若代理真值错误率 = ε，则
   实测一致率 ≈ acc*(1-2ε) + ε（对 ε 一阶）。
   反解：acc = (measured - ε) / (1 - 2ε)。
   ⇒ 必须报「ε 取 0 / 5% / 10% / 15% / 20% 时反解出的 acc」，让结论对 ε 不敏感才算稳。
   （A4.11 盲判仲裁 9:1 支持 labels3，故 ε 远小于 20%；把 ε 往上顶只是为了看稳健性。）

2) 两轮必须**留出不重叠**（第二轮 --exclude-tag c1），否则第二轮拿已泄露真值自评。
   本脚本会校验两轮样本键不相交。

输出 measure/judge/pilot_decision.json
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

ROOT = Path(str(tactics_data_file("")))
JD = ROOT / "reports/milestone_05/measure/judge"
TARGET = 0.90


def binom_le(k, n, p):
    return sum(math.comb(n, i) * p**i * (1-p)**(n-i) for i in range(0, k+1))


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    ph = k/n
    d = 1 + z*z/n
    c = ph + z*z/(2*n)
    r = z*math.sqrt(ph*(1-ph)/n + z*z/(4*n*n))
    return ((c-r)/d, (c+r)/d)


def main():
    rounds = {}
    keys = {}
    for tag in ("c1", "c2"):
        sc = json.load(open(JD / f"pilot_{tag}_score.json"))
        ky = json.load(open(JD / f"pilot_{tag}_key.json"))
        rounds[tag] = sc
        keys[tag] = {(e["window"], e["frame"]) for e in ky["key"]}

    overlap = keys["c1"] & keys["c2"]
    print("=" * 74)
    print("协议试点汇总（judge_pilot: 三面板 + 隐藏帧号 + 固定判读顺序）")
    for tag in ("c1", "c2"):
        s = rounds[tag]
        print(f"  {tag}: 判对 {s['ok']} / 判错 {s['bad']} / 弃权 {s['unc']}"
              f"  ⇒ {s['acc']*100:.1f}%（{s['ok']}/{s['ok']+s['bad']}）"
              f"  过判 {s['over']} / 漏判 {s['under']}")
    print(f"  两轮样本重叠：{len(overlap)} 个  （应为 0，否则第二轮不是留出轮）")

    ok = sum(rounds[t]["ok"] for t in ("c1", "c2"))
    bad = sum(rounds[t]["bad"] for t in ("c1", "c2"))
    unc = sum(rounds[t]["unc"] for t in ("c1", "c2"))
    over = sum(rounds[t]["over"] for t in ("c1", "c2"))
    under = sum(rounds[t]["under"] for t in ("c1", "c2"))
    n = ok + bad
    acc = ok/n
    lo, hi = wilson(ok, n)
    pv = binom_le(ok, n, TARGET)

    print("-" * 74)
    print(f"  合并：判对 {ok} / 判错 {bad} / 弃权 {unc}（弃权率 {unc/(n+unc)*100:.1f}%）")
    print(f"  ⇒ 实测与代理真值一致率 {acc*100:.1f}%（{ok}/{n}）  Wilson 95%CI [{lo*100:.1f}%, {hi*100:.1f}%]")
    print(f"  偏差方向：过度判球 {over} : 漏判 {under}  =  {over/max(under,1):.2f} : 1"
          f"   （{'系统性过判（与 A4.11 一致）' if over > under else '无系统方向'}）")
    print(f"  单侧精确二项 H0: acc >= {TARGET:.2f}  →  p = {pv:.5f}"
          f"   {'❌ 拒绝 H0（显著低于 90%）' if pv < 0.05 else '⚠️ 未拒绝 H0'}")

    # 代理真值误差敏感性：反解真实能力上界
    print("-" * 74)
    print("  代理真值误差 ε 敏感性（acc = (measured - ε)/(1 - 2ε)）")
    sens = []
    for eps in (0.0, 0.05, 0.10, 0.15, 0.20):
        a = (acc - eps) / (1 - 2*eps)
        reach = a >= TARGET
        sens.append({"eps": eps, "acc_reconstructed": a, "reaches_90": reach})
        print(f"    ε={eps*100:4.0f}%  ⇒  我的真实能力 ≈ {a*100:5.1f}%   "
              f"{'✅ 可到 90%' if reach else '❌ 仍 < 90%'}")
    # 🔴 ε→50% 时分母 (1-2ε)→0，反解爆炸（会印出 >100% 的非物理值）。
    #    ε >= 25% 已在悬崖边（反解 >100%）⇒ 只报区间不报点值，避免"假精确"。
    print("    ε>=25%  : 反解公式进入失效区间（分母 1-2ε <= 0.5，会给出 >100% 的非物理值）"
          "—— 不再报点值。")
    eps_need = (acc - TARGET) / (1 - 2*TARGET) if abs(1 - 2*TARGET) > 1e-9 else float("nan")
    print(f"  ⇒ 要把 {acc*100:.1f}% 的实测一致率解释成「真实能力 90%」，"
          f"代理真值必须有 ε ≈ {eps_need*100:.1f}% 的错误率")
    print("     （A4.11 记录：两套标注冲突 14/60 且单向、盲判 9:1 支持 labels3，"
          "故一致子集的 ε 远低于此值 ⇒ 该解释不成立）")

    verdict = "REJECT_SELF_AS_ANNOTATOR" if hi < TARGET else (
        "PASS" if lo >= TARGET else "INCONCLUSIVE")
    print("=" * 74)
    print(f"裁决：{verdict}   （95%CI 上界 {hi*100:.1f}% "
          f"{'<' if hi < TARGET else '>='} 90% 目标线）")

    json.dump({"rounds": {t: {k: rounds[t][k] for k in
                              ("ok", "bad", "unc", "acc", "over", "under",
                               "binom_p_le", "errs")} for t in ("c1", "c2")},
               "overlap": sorted(map(list, overlap)), "n": n, "ok": ok, "bad": bad,
               "unc": unc, "acc": acc, "wilson_lo": lo, "wilson_hi": hi,
               "over": over, "under": under, "binom_p_le": pv,
               "target": TARGET, "eps_sensitivity": sens,
               "eps_needed_to_claim_90": eps_need, "verdict": verdict},
              open(JD / "pilot_decision.json", "w"), ensure_ascii=False, indent=1)
    print(f"→ {JD}/pilot_decision.json")


if __name__ == "__main__":
    main()
