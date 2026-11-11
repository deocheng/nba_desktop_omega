#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""operating_point.py — 可交付工作点 / 标注预算 / 覆盖风险（现场重算）。

为什么需要它
------------
`ball_strict_eval.py` 用**逐窗**阈值做 STRICT 标定，得"4 窗 1 达标"。
但用户的门禁是「识别准确率 ≥ 90%」——**这是一个能交付的单一工作点问题**，
不是"每个窗口各自达标"的问题。逐窗口径把 324 个样本切成 4 份，
每份只有 21–35 个被选中样本 ⇒ 每窗 CI ±11–13 点 ⇒ 裁定不可分辨（见 `strict_power.py`）。

本脚本改为回答可交付问题：
  Q1 用**单一全局阈值**（池化口径）时，P̂ 与 R 是多少？95%CI 是多少？90% 是否落在 CI 内？
  Q2 P̂≥0.90 的最大召回工作点是哪个阈值？该点的 CI 与召回？
  Q3 **覆盖风险**：在完整候选池（4748）上该阈值会"宣称"多少个球？
      其中有多少落在人工标注库内（有真值）？库外部分 = 精度未知区。
      ⇒ 若库外占比高，则"P=0.89"只在库内成立，**不可外推**。
  Q4 **标注预算**：要把 CI 半宽压到 ±3 点 / 要让 90% 可被确立，需补多少标注？
      （按当前选择率与库外宣称量换算，给出"还需人工判读多少个候选"。）

输入: action_work/ball_cand_scores_v2.json, reports/milestone_05/measure/labels_bank.json
输出: reports/milestone_05/measure/operating_point.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
import os

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
AW = os.path.join(ROOT, "action_work")
MS = os.path.join(ROOT, "reports", "milestone_05", "measure")
WINS = ("w1", "w2", "w3", "w4")
Z = 1.959963984540054


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def wilson(k, n, z=Z):
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def main():
    scores = json.load(open(os.path.join(AW, "ball_cand_scores_v2.json")))
    bank = [r for r in json.load(open(os.path.join(MS, "labels_bank.json")))
            if r["label"] in ("TP", "FP")]

    # ---- 1) 给每条标注行找回它的 LOWO 分数 ----
    recs, miss = [], 0
    for r in bank:
        cs = scores.get(r["window"], {}).get(r["frame"], [])
        best, bp = None, -1.0
        for c in cs:
            v = iou(c["bbox"], r["bbox"])
            if v > bp:
                bp, best = v, c
        if best is None or bp < 0.5:
            miss += 1
            continue
        recs.append({"win": r["window"], "frame": r["frame"],
                     "y": 1 if r["label"] == "TP" else 0,
                     "p": float(best["prob"])})
    n, ntp = len(recs), sum(x["y"] for x in recs)
    print(f"标注行对齐：{n}（未匹配 {miss}）  TP={ntp} FP={n-ntp}")

    ps = [x["p"] for x in recs]
    ys = [x["y"] for x in recs]
    # 分数分布（判断窄带/可分性）
    sp = sorted(ps)
    q = lambda f: sp[min(len(sp)-1, int(f*(len(sp)-1)))]
    print(f"LOWO 概率分布：min {sp[0]:.3f} / p25 {q(.25):.3f} / 中位 {q(.5):.3f} "
          f"/ p75 {q(.75):.3f} / max {sp[-1]:.3f}")
    tp_p = sorted(p for p, y in zip(ps, ys) if y == 1)
    fp_p = sorted(p for p, y in zip(ps, ys) if y == 0)
    print(f"  TP 中位 {tp_p[len(tp_p)//2]:.3f}   FP 中位 {fp_p[len(fp_p)//2]:.3f}")

    # ---- 2) 全局阈值扫描 ----
    grid = [round(0.40 + 0.0025*i, 4) for i in range(int((0.999-0.40)/0.0025)+1)]
    curve, best90 = [], None
    for th in grid:
        sel = [(p, y) for p, y in zip(ps, ys) if p > th]
        k = len(sel)
        if k == 0:
            continue
        tp = sum(1 for _, y in sel if y == 1)
        P = tp / k
        R = tp / ntp if ntp else 0.0
        lo, hi = wilson(tp, k)
        curve.append({"th": th, "n": k, "tp": tp, "P": P, "R": R, "ci_lo": lo, "ci_hi": hi})
        if P >= 0.90 and (best90 is None or R > best90["R"]):
            best90 = curve[-1]

    pool = None
    if ntp:
        sel = list(zip(ps, ys))
        k = len(sel); tp = ntp; P = tp/k
        lo, hi = wilson(tp, k)
        pool = {"n": k, "tp": tp, "fp": k-tp, "P": P, "R": 1.0,
                "ci_lo": lo, "ci_hi": hi}
    print(f"\n池化（不加阈值，全选）：n={pool['n']} P={pool['P']:.3f} "
          f"CI[{pool['ci_lo']:.3f},{pool['ci_hi']:.3f}] R=1.0")
    if best90:
        print(f"全局最大召回工作点：th={best90['th']:.4f}  "
              f"P={best90['P']:.3f} R={best90['R']:.3f}  选中 n={best90['n']} "
              f"CI[{best90['ci_lo']:.3f},{best90['ci_hi']:.3f}]")
        print(f"  ⇒ 90% 是否落在 CI 内："
              f"{'是（未确立）' if best90['ci_lo'] <= 0.90 <= best90['ci_hi'] else '否'}")
    else:
        print("⚠️ 全局口径下**不存在** P̂≥0.90 的工作点（点估计都达不到）")

    # ---- 3) 覆盖风险：全候选池宣称量 vs 库内覆盖 ----
    print("\n--- 覆盖风险（阈值取全局最大召回工作点）---")
    th_use = best90["th"] if best90 else 0.95
    cov = {}
    tot_claim = tot_covered = 0
    for w in WINS:
        frames = scores.get(w, {})
        n_cand = sum(len(v) for v in frames.values())
        claims = [(f, c["bbox"]) for f, cs in frames.items() for c in cs if c["prob"] > th_use]
        bank_w = [r for r in bank if r["window"] == w]
        covered = 0
        for f, bb in claims:
            for r in bank_w:
                if r["frame"] == f and iou(bb, r["bbox"]) >= 0.5:
                    covered += 1
                    break
        cov[w] = {"n_cand": n_cand, "n_claim": len(claims),
                  "n_frames": len(frames),
                  "claim_per_frame": len(claims)/max(1, len(frames)),
                  "n_covered_by_bank": covered,
                  "coverage": covered/max(1, len(claims))}
        tot_claim += len(claims); tot_covered += covered
        print(f"  {w}: 候选 {n_cand} → 宣称 {len(claims)}"
              f"（{len(claims)/max(1,len(frames)):.2f} 个/帧，共 {len(frames)} 帧）"
              f"  库内覆盖 {covered} = {covered/max(1,len(claims))*100:.1f}%")
    print(f"  合计宣称 {tot_claim}，库内覆盖 {tot_covered} = "
          f"{tot_covered/max(1,tot_claim)*100:.1f}%  ⇒ "
          f"**库外 {tot_claim-tot_covered} 个宣称无真值，精度不可外推**")

    # ---- 4) 标注预算 ----
    half = lambda p_, n_: (wilson(int(round(p_*n_)), n_)[1] - wilson(int(round(p_*n_)), n_)[0]) / 2
    p_hat = best90["P"] if best90 else pool["P"]
    budget = []
    for target_hw in (0.05, 0.04, 0.03, 0.02):
        nb = None
        for m in range(30, 4000):
            if half(p_hat, m) <= target_hw:
                nb = m
                break
        budget.append({"halfwidth": target_hw, "n_selected_needed": nb,
                       "extra_vs_now": (nb - tot_covered) if nb else None})
    print("\n--- 标注预算（达到该 CI 半宽所需的『有真值的宣称样本数』）---")
    for b in budget:
        print(f"  CI ±{b['halfwidth']*100:.0f} 点 → 需 {b['n_selected_needed']} 个"
              f"（当前库内覆盖 {tot_covered}，还需补 ~{max(0,b['extra_vs_now'] or 0)} 个）")

    out = {"aligned": n, "unmatched": miss, "TP": ntp, "FP": n-ntp,
           "score_dist": {"min": sp[0], "p25": q(.25), "med": q(.5), "p75": q(.75), "max": sp[-1]},
           "tp_med": tp_p[len(tp_p)//2], "fp_med": fp_p[len(fp_p)//2],
           "pooled_nothreshold": pool, "best_global_90": best90,
           "curve_len": len(curve), "coverage": cov,
           "total_claim": tot_claim, "total_covered": tot_covered,
           "budget": budget}
    # 精简曲线（每 0.01 存一点）便于复查
    thin = [c for c in curve if abs(round(c["th"]*100) - c["th"]*100) < 1e-9]
    out["curve_thin"] = thin
    json.dump(out, open(os.path.join(MS, "operating_point.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"\n→ {os.path.join(MS, 'operating_point.json')}")


if __name__ == "__main__":
    main()
