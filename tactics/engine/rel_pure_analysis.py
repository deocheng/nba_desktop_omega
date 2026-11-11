#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 步配套分析：纯分 vs 旧口径（乘 conf）—— 谓词分布、top-K 重叠、6 帧分歧诊断。

为什么需要它
------------
1) 光有分数分布不够：里程碑 03 的**否定结论**建立在「谓词退化」与「事件对齐不显著」上，
   所以必须逐项重算这两件事，而不是只看 max 分数。
2) 保真自检报出 **6/435 帧 top-K 不一致**，必须判定性质：
   - 若是**浮点结合律/近似 tie** 造成的交换（`s*(a*b)` vs `(s*a)*b`）⇒ 良性，纯分变体可信；
   - 若是**真分歧**（选了不同的 pair）⇒ 重实现不忠实，A 的结论作废。
   判据：把两边的「conf 加权分」按各自 top-K 列出来，看被换掉的那一项差值是否 < 1e-9 量级。

输出 <outdir>/a_analysis.json（数字全部现算）。
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter


def hist(frames):
    c = Counter()
    for fr in frames:
        for t in fr["triples"]:
            c[t["pred"]] += 1
    return c


def per_frame_stats(frames):
    watch, ndist = [], []
    for fr in frames:
        ts = fr["triples"]
        if not ts:
            continue
        watch.append(sum(1 for t in ts if t["pred"] == "watching") / len(ts))
        ndist.append(len({t["pred"] for t in ts}))
    return watch, ndist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--pure", required=True)
    ap.add_argument("--confrank", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    O = json.load(open(a.old))
    P = json.load(open(a.pure))
    C = json.load(open(a.confrank))
    vari = {"old_confmul": O, "pure": P, "confrank": C}

    out = {"variants": {}, "histograms": {}, "fidelity": {}}

    print("=" * 78)
    print("A 步分析：纯模型分 vs 旧口径（报告分被乘了两个检测 conf）")
    print("=" * 78)
    print(f"{'变体':<14}{'三元组':>7}{'谓词种数':>9}{'watching占比':>13}{'过帧均谓词数':>13}"
          f"{'分数中位':>10}{'分数max':>10}")
    for name, D in vari.items():
        frs = D["frames"]
        h = hist(frs)
        watch, ndist = per_frame_stats(frs)
        sc = [t["score"] for fr in frs for t in fr["triples"]]
        n = sum(h.values())
        print(f"{name:<14}{n:>7}{len(h):>9}{statistics.fmean(watch)*100:>12.1f}%"
              f"{statistics.fmean(ndist):>13.2f}{statistics.median(sc):>10.4f}{max(sc):>10.4f}")
        out["variants"][name] = {
            "n_triples": n, "n_distinct_pred": len(h),
            "watching_share_mean": round(statistics.fmean(watch), 4),
            "n_distinct_pred_mean": round(statistics.fmean(ndist), 4),
            "score_median": round(statistics.median(sc), 6), "score_max": round(max(sc), 6),
        }
        out["histograms"][name] = dict(h.most_common())

    print("\n--- 谓词直方图（前 8）---")
    for name in vari:
        top = list(out["histograms"][name].items())[:8]
        tot = sum(out["histograms"][name].values())
        print(f"  {name:<12} " + "  ".join(f"{k}={v}({v/tot*100:.1f}%)" for k, v in top))

    # ---- 6 帧分歧诊断 ----
    print("\n--- 保真自检分歧帧诊断（old_confmul vs confrank 重实现）---")
    om = {fr["idx"]: fr for fr in O["frames"]}
    cm = {fr["idx"]: fr for fr in C["frames"]}
    bad = []
    for idx in sorted(set(om) & set(cm)):
        k1 = sorted((t["s"], t["o"], t["pred"]) for t in cm[idx]["triples"])
        k2 = sorted((t["s"], t["o"], t["pred"]) for t in om[idx]["triples"])
        if k1 != k2:
            bad.append(idx)
    print(f"  分歧帧数 {len(bad)} / {len(om)}：{bad}")
    details = []
    for idx in bad:
        s1 = {t["pred"]: (t["s"], t["o"]) for t in cm[idx]["triples"]}
        s2 = {t["pred"]: (t["s"], t["o"]) for t in om[idx]["triples"]}
        only_new = {k: v for k, v in s1.items() if v not in s2.values()}
        only_old = {k: v for k, v in s2.items() if v not in s1.values()}
        details.append({"idx": idx, "only_in_reimpl": only_new, "only_in_old": only_old})
        print(f"   帧 {idx}: 重实现多 {list(only_new.values())}  旧多 {list(only_old.values())}")
    out["fidelity"] = {"n_diff_frames": len(bad), "diff_frames": bad, "details": details}

    # ---- top-K 重叠（每帧集合 Jaccard 均值）----
    def jac(A, B):
        am = {fr["idx"]: {(t["s"], t["o"], t["pred"]) for t in fr["triples"]} for fr in A["frames"]}
        bm = {fr["idx"]: {(t["s"], t["o"], t["pred"]) for t in fr["triples"]} for fr in B["frames"]}
        vals = []
        for idx in set(am) & set(bm):
            u = am[idx] | bm[idx]
            if u:
                vals.append(len(am[idx] & bm[idx]) / len(u))
        return statistics.fmean(vals) if vals else None

    print("\n--- 逐帧 top-K 集合 Jaccard 均值 ---")
    pairs = [("old_confmul", "confrank"), ("old_confmul", "pure"), ("pure", "confrank")]
    out["jaccard"] = {}
    for x, y in pairs:
        j = jac(vari[x], vari[y])
        out["jaccard"][f"{x}__vs__{y}"] = round(j, 4)
        print(f"  {x:<12} vs {y:<10} {j:.4f}")

    with open(a.out, "w") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(f"\n[out] {a.out}")


if __name__ == "__main__":
    main()
