#!/usr/bin/env python3
"""关系层 × PBP 事件的**时间对齐**检验 —— 并修正里程碑 03 的一处时间戳错误。

🔴 为什么要写这个脚本（自我纠错记录）：
    里程碑 03 报告与 `make_rel_figs.py` 里，我把窗口内 4 个 PBP 转换点的时间标成
    218.5 / 221.1 / 223.4 / 224.6 s，并据此断言「watching 占比在转换点上没有任何结构变化」。
    事后核对 `clock_table.json`（画面比分牌逐帧读秒）发现：
        ① clock 69.0 → t = 218.5  ✅ 对
        ② clock 66.0 → t = 221.5  （我标 221.1，偏 0.4s）
        ③ clock 48.4 → t = 239.8  （我标 223.4 —— **错 16.4 秒**）
        ④ clock 43.9 → t = 244.3  （我标 224.6 —— **错 19.7 秒**）
    ⇒ 图上的 ③④ 两个红/绿虚线画在了完全无关的时刻上，且被写进结论。
    **教训：事件时间必须由数据（读秒表）插值得到，绝不允许手写常量。**

本脚本把事件时间**完全从 clock_table 推导**，然后正式检验：
    watching 占比（以及每帧不同谓词数）在真实事件时刻的邻域内，
    是否显著偏离该片段自身的滑动窗口分布（置换/秩检验，避免又犯单点比较的错）。

用法:
  rel_event_align.py <relations_full.json> <clock_table.json> <possession_v2.json> <out.json>
                     [--half-win 2.5] [--n-perm 2000]
"""
from __future__ import annotations

import argparse
import json
import random
import statistics


def t_of_clock(ct_pairs, c):
    """在 (t, clock) 序列上线性插值反查。clock 递减。"""
    for i in range(len(ct_pairs) - 1):
        t1, c1 = ct_pairs[i]
        t2, c2 = ct_pairs[i + 1]
        if (c1 - c) * (c2 - c) <= 0 and c1 != c2:
            return t1 + (t2 - t1) * (c1 - c) / (c1 - c2)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("relations_json")
    ap.add_argument("clock_table")
    ap.add_argument("possession_json")
    ap.add_argument("out_json")
    ap.add_argument("--half-win", type=float, default=2.5)
    ap.add_argument("--n-perm", type=int, default=2000)
    a = ap.parse_args()

    rel = json.load(open(a.relations_json))
    frames = rel["frames"]
    ts = [f["t"] for f in frames]
    watch = [sum(1 for t in f["triples"] if t["pred"] == "watching") /
             max(len(f["triples"]), 1) for f in frames]
    ndist = [len({t["pred"] for t in f["triples"]}) for f in frames]
    # 逐帧谓词熵（归一化）：退化越严重熵越低
    import math
    ent = []
    for f in frames:
        preds = [t["pred"] for t in f["triples"]]
        n = len(preds) or 1
        h = -sum((c / n) * math.log(c / n, 2) for c in
                 {p: preds.count(p) for p in set(preds)}.values())
        ent.append(h / math.log(len(set(preds)) or 2, 2) if len(set(preds)) > 1 else 0.0)

    # ---- 事件时间：完全从读秒表推导 ----
    # 🔴 帧号→时间的换算常数必须是【源帧间隔 dt】，不是采样间隔。
    #    `clock_table.json` 的 `frames[].frame` 是**源帧号**（实测 step=5，覆盖 frame 1..431），
    #    而该表自身以 2fps 采样（87 条）。早先此处写死 `* 0.5`（＝采样间隔），
    #    等于把事件时间**放大 5 倍**：clock 69.0 算出 t=274.5，正确值 t=218.5
    #    （218.5 与旧 `rel_event_align.json` 一致，且落在关系层窗口 204.5–247.9 内）。
    #    dt 由两条独立路线交叉验证：① clock_table 自带 dt=0.1；
    #    ② frame1→83.0s、frame431→40.7s ⇒ 430 帧跨 42.3s ⇒ 0.0984 s/帧。
    ct_raw = json.load(open(a.clock_table))
    t0w = frames[0]["t"]
    dt_ct = float(ct_raw.get("dt", 0.1))
    t0_ct = ct_raw.get("t0", t0w)
    if abs(float(t0_ct) - float(t0w)) > 0.05:
        print(f"[warn] clock_table.t0={t0_ct} 与 relations.t0={t0w} 不一致，"
              f"按 relations 栅格对齐（以 relations 为时间基准）")
    # 自洽性检查：源帧跨度 × dt 应与关系层时间跨度一致
    frs = [f["frame"] for f in ct_raw["frames"] if "clock_sec" in f]
    span_ct = (max(frs) - min(frs)) * dt_ct
    span_rel = ts[-1] - ts[0]
    if abs(span_ct - span_rel) > 0.15 * max(span_rel, 1.0):
        print(f"[warn] 时间跨度不自洽：clock_table {span_ct:.1f}s vs relations {span_rel:.1f}s"
              f"（dt={dt_ct}）")
    pairs = []
    for f in ct_raw["frames"]:
        if "clock_sec" in f:
            pairs.append((round(t0w + (f["frame"] - 1) * dt_ct, 2), float(f["clock_sec"])))
    pairs.sort()
    pos = json.load(open(a.possession_json))
    events = []
    for act in pos["pbp_actions"]:
        t = t_of_clock(pairs, act["clock"])
        if t is None:
            continue
        events.append({"n": act["n"], "eventnum": act["eventnum"],
                       "clock": act["clock"], "team": act["team"],
                       "player": act["player"], "kind": act["kind"],
                       "detail": act["detail"], "t": round(t, 1)})
    print("=== PBP 事件时间（由画面读秒插值，非手写）===")
    for e in events:
        print(f"  {e['n']} clock {e['clock']:>5.1f} → t = {e['t']:>6.1f} s   "
              f"{e['team']} {e['player']} {e['kind']} ({e['detail']})")

    # ---- 检验：事件邻域 vs 该片段所有同宽滑动窗口 ----
    hw = a.half_win
    lo, hi = ts[0] + hw, ts[-1] - hw

    def win_mean(series, center):
        v = [series[i] for i, t in enumerate(ts) if abs(t - center) <= hw]
        return statistics.fmean(v) if v else None

    ev_centers = [e["t"] for e in events if lo <= e["t"] <= hi]
    all_centers = [t for t in ts if lo <= t <= hi]

    out = {"events": events, "half_win": hw,
           "n_event_centers_in_range": len(ev_centers),
           "metrics": {}}
    rnd = random.Random(20260925)
    for name, series, direction in (("watching_share", watch, "down"),
                                    ("n_distinct_predicates", ndist, "down"),
                                    ("predicate_entropy_norm", ent, "down")):
        ev_means = [m for m in (win_mean(series, c) for c in ev_centers) if m is not None]
        if not ev_means:
            continue
        observed = statistics.fmean(ev_means)
        null_all = [m for m in (win_mean(series, c) for c in all_centers) if m is not None]
        # 置换：从窗口中心池里随机抽同样多的中心
        nulls = []
        for _ in range(a.n_perm):
            pick = rnd.sample(all_centers, len(ev_centers))
            ms = [m for m in (win_mean(series, c) for c in pick) if m is not None]
            if ms:
                nulls.append(statistics.fmean(ms))
        nulls.sort()
        # 单侧 p（down 表示事件处偏低才算"有反应"）
        if direction == "down":
            ge = sum(1 for x in nulls if x <= observed)
        else:
            ge = sum(1 for x in nulls if x >= observed)
        p = (ge + 1) / (len(nulls) + 1)
        pct = sum(1 for x in nulls if x <= observed) / len(nulls)
        out["metrics"][name] = {
            "observed_event_mean": round(observed, 4),
            "null_mean": round(statistics.fmean(nulls), 4),
            "null_p05": round(nulls[int(len(nulls) * 0.05)], 4),
            "null_p95": round(nulls[int(len(nulls) * 0.95)], 4),
            "p_one_sided": round(p, 4),
            "percentile": round(pct, 4),
            "significant_at_0.05": p < 0.05,
            "per_event": [{"t": c, "mean": round(m, 4)}
                          for c, m in zip(ev_centers, ev_means)],
            "n_perm": len(nulls),
        }
        m = out["metrics"][name]
        print(f"[{name}] 事件邻域均值 {m['observed_event_mean']:.4f}  "
              f"null 均值 {m['null_mean']:.4f} [{m['null_p05']:.4f},{m['null_p95']:.4f}]  "
              f"p={m['p_one_sided']:.4f}  分位={m['percentile']:.3f}  "
              f"{'✅ 显著' if m['significant_at_0.05'] else '⚠️ 不显著'}")

    # 逐事件明细（watching）
    out["per_event_watching"] = []
    print("=== 逐事件 watching 占比（事件时刻 ±{}s）===".format(hw))
    for e in events:
        c = e["t"]
        v = [watch[i] for i, t in enumerate(ts) if abs(t - c) <= hw]
        at = min(range(len(ts)), key=lambda i: abs(ts[i] - c))
        m = statistics.fmean(v) if v else None
        out["per_event_watching"].append({
            "n": e["n"], "clock": e["clock"], "t": c, "player": e["player"],
            "kind": e["kind"], "watching_at_frame": round(watch[at], 4),
            "watching_mean_win": None if m is None else round(m, 4),
            "in_range": ts[0] <= c <= ts[-1]})
        tag = "" if ts[0] <= c <= ts[-1] else "  ⚠️ 落在窗口外"
        print(f"  {e['n']} t={c:>6.1f}s  {e['player']:<16} {e['kind']:<12} "
              f"帧值={watch[at]:.3f}  窗口均值={'—' if m is None else f'{m:.3f}'}{tag}")

    with open(a.out_json, "w") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(f"[out] {a.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
