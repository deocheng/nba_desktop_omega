#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strict_power.py — 检验 STRICT 裁定的统计功效。

动机：`ball_strict_eval.py` 给出「4 窗仅 1 窗 P≥90%」的裁定。
但每窗**被选中**的样本只有 30–35 个（tp+fp）。在 n=35 上，
P=0.857 与 P=0.900 的 Wilson 置信区间几乎完全重叠 ⇒ 该裁定可能是**把噪声当失败**。

本脚本回答三个问题（全部现场重算，不手抄）：
  Q1 每窗留出 P 的 95% Wilson CI 是多少？是否包含 0.90？
  Q2 单侧精确二项检验：H0: P≤0.90，观测值能否拒绝 H0？（即"未达标"是否被证实）
  Q3 若要把 CI 半宽压到 ±3 点 / 要让 90% 可被确立，需要多少**被选中**样本？
      换算成还需人工标注多少候选（按当前选择率）。

输入：reports/milestone_05/measure/strict_eval_v2.json
输出：reports/milestone_05/measure/strict_power.json（+ 终端表格）
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEAS = os.path.join(ROOT, "reports", "milestone_05", "measure")
STRICT = os.path.join(MEAS, "strict_eval_v2.json")
BANK = os.path.join(MEAS, "labels_bank.json")
OUT = os.path.join(MEAS, "strict_power.json")

Z = 1.959963984540054  # 95%


# ---------- 统计原语（不依赖 scipy） ----------
def wilson(k, n, z=Z):
    """Wilson score interval（比 Wald 在小 n 下稳）。"""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def binom_sf_le(k, n, p):
    """P(X <= k | n, p) —— 精确二项，n 小直接求和。"""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))


def binom_cdf_ge(k, n, p):
    """P(X >= k | n, p)"""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def n_for_halfwidth(p, hw, z=Z):
    """估计 p 下，使 Wilson 近似半宽 <= hw 所需的 n。"""
    if not (0 < p < 1) or hw <= 0:
        return None
    n = 1
    while n < 200000:
        lo, hi = wilson(round(p * n), n, z)
        if (hi - lo) / 2 <= hw:
            return n
        n += 1
    return None


def n_to_establish(p_true, p0=0.90, z=Z):
    """
    若真值 P=p_true，需要多少 n 才能让 95% CI 下界 > p0？
    （即"确立达标"所需的样本量）
    """
    if p_true <= p0:
        return None
    n = 1
    while n < 500000:
        lo, _ = wilson(int(round(p_true * n)), n, z)
        if lo > p0:
            return n
        n += 1
    return None


def main():
    strict = json.load(open(STRICT))
    bank = json.load(open(BANK))

    # 真值库分窗统计（用于把"被选中样本数"换算成"还需标注数"）
    bank_cnt = {}
    for r in bank:
        w = r.get("window", "?")
        d = bank_cnt.setdefault(w, {"TP": 0, "FP": 0, "unc": 0, "other": 0})
        lab = r.get("label", "other")
        d[lab if lab in d else "other"] += 1

    rows = []
    tot_tp = tot_fp = 0
    for e in strict["per_win"]:
        w, tp, fp, n_bank = e["win"], e["tp"], e["fp"], e["n"]
        k = tp + fp  # 被选中样本数
        tot_tp += tp
        tot_fp += fp
        P = tp / k if k else float("nan")
        lo, hi = wilson(tp, k)
        # 单侧检验 H0: P <= 0.90（"未达标"为原假设）
        # p 值 = P(X <= tp | k, 0.90)；小 ⇒ 观测显著低于 90%
        p_lt = binom_sf_le(tp, k, 0.90)
        # 另一侧：H0: P >= 0.90，p 值 = P(X >= tp | k, 0.90)
        p_ge = binom_cdf_ge(tp, k, 0.90)
        rows.append({
            "win": w, "th": e["th"], "innerP": e["innerP"],
            "n_selected": k, "TP": tp, "FP": fp, "P": P,
            "ci_lo": lo, "ci_hi": hi,
            "ci_contains_090": bool(lo <= 0.90 <= hi),
            "p_value_low": p_lt,      # 显著低于 0.90？
            "proven_below": bool(p_lt < 0.05),
            "p_value_high": p_ge,     # 显著高于 0.90？
            "proven_above": bool(p_ge < 0.05),
            "bank": bank_cnt.get(w, {}),
            "R": e["R"], "auc": e["auc"],
        })

    k_tot = tot_tp + tot_fp
    P_tot = tot_tp / k_tot
    lo_tot, hi_tot = wilson(tot_tp, k_tot)
    pool = {
        "n_selected": k_tot, "TP": tot_tp, "FP": tot_fp, "P": P_tot,
        "R_pooled": sum(e["tp"] for e in strict["per_win"]) /
                    max(1, sum(bank_cnt.get(e["win"], {}).get("TP", 0) for e in strict["per_win"])),
        "ci_lo": lo_tot, "ci_hi": hi_tot,
        "ci_contains_090": bool(lo_tot <= 0.90 <= hi_tot),
        "p_value_low": binom_sf_le(tot_tp, k_tot, 0.90),
        "proven_below": bool(binom_sf_le(tot_tp, k_tot, 0.90) < 0.05),
        "p_value_high": binom_cdf_ge(tot_tp, k_tot, 0.90),
        "proven_above": bool(binom_cdf_ge(tot_tp, k_tot, 0.90) < 0.05),
    }

    n_hw3 = n_for_halfwidth(P_tot, 0.03)
    n_hw2 = n_for_halfwidth(P_tot, 0.02)
    n_est_93 = n_to_establish(0.93)
    n_est_92 = n_to_establish(0.92)

    res = {
        "per_win": rows,
        "pooled": pool,
        "power": {
            "halfwidth_3pt_n": n_hw3,
            "halfwidth_2pt_n": n_est_92 and n_hw2,
            "establish_92_n": n_est_92,
            "establish_93_n": n_est_93,
            "note": "n = 需在阈值处被选中的样本数（TP+FP）",
        },
        "bank_by_window": bank_cnt,
        "target_p": strict["target_p"],
    }
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)

    # ---------- 打印 ----------
    print("=" * 78)
    print("STRICT 裁定 · 统计功效复核（现场重算）")
    print("=" * 78)
    print(f"{'窗':<4}{'th':>7}{'选中n':>7}{'TP':>5}{'FP':>4}{'P':>8}{'95%CI':>18}{'含0.90':>8}{'证伪<.90':>9}{'证立>.90':>9}")
    for r in rows:
        print(f"{r['win']:<4}{r['th']:>7.3f}{r['n_selected']:>7}{r['TP']:>5}{r['FP']:>4}"
              f"{r['P']:>8.3f}  [{r['ci_lo']:.3f},{r['ci_hi']:.3f}]"
              f"{('是' if r['ci_contains_090'] else '否'):>8}"
              f"{('是' if r['proven_below'] else '否'):>9}"
              f"{('是' if r['proven_above'] else '否'):>9}")
    print("-" * 78)
    print(f"{'池化':<4}{'':>7}{pool['n_selected']:>7}{pool['TP']:>5}{pool['FP']:>4}"
          f"{pool['P']:>8.3f}  [{pool['ci_lo']:.3f},{pool['ci_hi']:.3f}]"
          f"{('是' if pool['ci_contains_090'] else '否'):>8}"
          f"{('是' if pool['proven_below'] else '否'):>9}"
          f"{('是' if pool['proven_above'] else '否'):>9}")
    print(f"池化召回 = {pool['R_pooled']:.3f}"
          f"（{pool['TP']}/{sum(bank_cnt.get(e['win'],{}).get('TP',0) for e in rows)} TP）")
    print("-" * 78)
    print("功效（被选中样本数）："
          f"CI 半宽≤3点 → n≈{n_hw3}；"
          f"确立 P≥92% → n≈{n_est_92}；"
          f"确立 P≥93% → n≈{n_est_93}")
    print("真值库分窗：", json.dumps(bank_cnt, ensure_ascii=False))
    print(f"\n→ {OUT}")
    # 结论一句话
    n_below_proven = sum(1 for r in rows if r["proven_below"])
    print("=" * 78)
    if n_below_proven == 0:
        print("裁定：**没有任何一窗被统计证伪为 P<90%**。"
              "「1/4 达标」是点估计读数，不是可确立的结论。")
    else:
        print(f"裁定：{n_below_proven}/4 窗被统计证伪为 P<90%。")
    if pool["ci_contains_090"]:
        print("池化口径 90% 落在 95%CI 内 ⇒ **当前样本量不足以裁定「达标/未达标」**。")
    print("=" * 78)


if __name__ == "__main__":
    sys.exit(main())
