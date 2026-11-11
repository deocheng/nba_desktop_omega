#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第 6.6 层：球权转移的可信度复核（对抗性自检）

── 为什么需要这一层 ──────────────────────────────────────────────
`segment_possession_gated.py` 给出的"球权转移"建立在一个隐含假设上：
**pid 变化 ⟹ 球换了人**。

但实测发现这个假设可能是错的：
  · 同一时刻存在的 pid 有 15–24 个，而场上只有 10 个球员；
  · pid 编号单调递增（早期 1–23、中期 27–43、晚期 50–78），
    是"不断新建身份"的典型特征，而不是稳定追踪。

如果同一个真实球员在不同时刻被赋予不同 pid，那么"pid 变了"就只是
**标签变了**，不是球转移了。本层用两个可测量的判据把这个区分开。

── 判据 ①：球的实际位移 ────────────────────────────────────────
真传球/运球推进 ⟹ 球心在转移前后有明显位移。
标签切换       ⟹ 球心几乎不动（因为人没动）。

  ball_move_norm = |球心(t_B) - 球心(t_A)| / 中位身高
  · >= 1.0   → 球真的动了，支持"真转移"
  · <  0.5   → 球几乎没动，**标签切换嫌疑**

── 判据 ②：新老持球人的距离 ────────────────────────────────────
真转移 ⟹ 新持球人通常与老持球人有可分辨的距离（球飞过去/带过去）。
标签切换 ⟹ 新老 pid 的脚点几乎重合（本来就是同一个人）。

  holder_dist_norm = |脚点(A) - 脚点(B)| / 中位身高
  · >= 0.8   → 两个人确实分得开，支持"真转移"
  · <  0.4   → 脚点几乎重合，**重复身份嫌疑**

── 判据 ③：身份重复率 ──────────────────────────────────────────
逐帧统计"脚点距离 < 0.5 倍身高的 pid 对"数量。这些对几乎不可能是
两个不同的球员（人不会被别人站着重叠），只能是重复编号。
"""
import argparse
import json
import math
import os
import statistics
from collections import defaultdict

EXPECTED_PLAYERS = 10          # 场上应有 10 名球员
DUP_DIST = 0.5                 # 脚点距离 < 0.5 身高 → 重复身份嫌疑


def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def players_at(sel, idx):
    fr = sel["frames"][idx]
    out = []
    for p in fr["players"]:
        foot = p.get("foot")
        if not foot:
            b = p.get("box")
            if not b:
                continue
            foot = [(b[0] + b[2]) / 2.0, b[3]]
        h = p.get("h") or max(p["box"][3] - p["box"][1], 1.0)
        out.append({"pid": p["pid"], "foot": foot, "h": h, "conf": p.get("conf", 0)})
    return out


def median_h(sel, idx):
    ps = players_at(sel, idx)
    return statistics.median([p["h"] for p in ps]) if ps else 180.0


def index_of_t(sel):
    return {round(fr["t"], 1): i for i, fr in enumerate(sel["frames"])}


# ── 判据 ③：身份重复率 ──
def duplication(sel):
    rows = []
    for i, fr in enumerate(sel["frames"]):
        ps = players_at(sel, i)
        if len(ps) < 2:
            rows.append({"idx": i, "t": fr["t"], "n_pid": len(ps), "n_dup_pairs": 0})
            continue
        mh = statistics.median([p["h"] for p in ps])
        n = 0
        for a in range(len(ps)):
            for b in range(a + 1, len(ps)):
                d = math.hypot(ps[a]["foot"][0] - ps[b]["foot"][0],
                               ps[a]["foot"][1] - ps[b]["foot"][1]) / max(mh, 1.0)
                if d < DUP_DIST:
                    n += 1
        rows.append({"idx": i, "t": fr["t"], "n_pid": len(ps), "n_dup_pairs": n})
    npids = [r["n_pid"] for r in rows]
    dups = [r["n_dup_pairs"] for r in rows]

    # 身份连续性：相邻帧 pid 集合的重合率
    # （比"脚点重合"更可靠——脚点近也可能是挡拆/背打，属真实贴近）
    ov = []
    for i in range(len(sel["frames"]) - 1):
        a = {p["pid"] for p in players_at(sel, i)}
        b = {p["pid"] for p in players_at(sel, i + 1)}
        if a and b:
            ov.append(len(a & b) / len(a | b))
    allp = set()
    for i in range(len(sel["frames"])):
        allp |= {p["pid"] for p in players_at(sel, i)}

    return {
        "expected_players": EXPECTED_PLAYERS,
        "n_frames": len(rows),
        "distinct_pids_total": len(allp),
        "pid_slots_total": sum(npids),
        "pid_reuse_factor": round(sum(npids) / len(allp), 1) if allp else 0,
        "n_pid_median": statistics.median(npids) if npids else 0,
        "n_pid_min": min(npids) if npids else 0,
        "n_pid_max": max(npids) if npids else 0,
        "excess_median": round(statistics.median(npids) - EXPECTED_PLAYERS, 1) if npids else 0,
        "adjacent_jaccard_median": round(statistics.median(ov), 3) if ov else 0,
        "adjacent_jaccard_mean": round(statistics.mean(ov), 3) if ov else 0,
        "dup_pair_median": statistics.median(dups) if dups else 0,
        "dup_pair_mean": round(statistics.mean(dups), 2) if dups else 0,
        "frames_with_dup": sum(1 for d in dups if d > 0),
        "dup_ratio_pct": round(sum(1 for d in dups if d > 0) / len(dups) * 100, 1) if dups else 0,
        "_dup_pair_caveat": ("脚点重合只是一个『嫌疑』判据，不是定论："
                             "挡拆、背打、贴身防守时两名真实球员本就会重叠。"
                             "身份连续性看 adjacent_jaccard_median 更可靠。"),
        "rows": rows,
    }


# ── 判据 ①&②：逐次转移的球位移与人的距离 ──
def audit_transfers(gd, sel):
    idx_t = index_of_t(sel)
    tl = {r["idx"]: r for r in gd["timeline"]}
    ev = gd["events"]
    spans = gd["spans"]

    def span_of(idx):
        for s in spans:
            if s["start_idx"] <= idx <= s["end_idx"]:
                return s
        return None

    out = []
    for e in ev:
        if e["kind"] != "transfer":
            continue
        # 事件自带段索引（生成时写入），精确取 A 段末帧 / B 段首帧
        iA = e.get("from_end_idx")
        iB = e.get("to_start_idx")
        if iA is None or iB is None or iA not in tl or iB not in tl:
            continue
        bA = tl[iA]["ball_pt"]
        bB = tl[iB]["ball_pt"]
        mh = median_h(sel, iA)
        # 判据 ① 球位移
        ball_move = (math.hypot(bB[0] - bA[0], bB[1] - bA[1]) / max(mh, 1.0)
                     if bA and bB else None)
        # 判据 ② 新老持球人脚点距离
        pA = next((p for p in players_at(sel, iA) if p["pid"] == e["from"]), None)
        pB = next((p for p in players_at(sel, iB) if p["pid"] == e["to"]), None)
        holder_dist = None
        if pA and pB:
            holder_dist = (math.hypot(pB["foot"][0] - pA["foot"][0],
                                      pB["foot"][1] - pA["foot"][1]) / max(mh, 1.0))

        # 判定
        if ball_move is None or holder_dist is None:
            verdict = "unverifiable"
        elif ball_move < 0.5 and holder_dist < 0.4:
            verdict = "identity_swap_suspect"      # 球没动、人也重合 → 标签切换
        elif ball_move >= 1.0 and holder_dist >= 0.8:
            verdict = "supported_transfer"         # 球动了、人也分得开
        else:
            verdict = "weak_transfer"
        # 位移方向一致性：球动方向 vs 新持球人相对旧持球人的方向
        out.append({
            "t": e["t"], "from": e["from"], "to": e["to"],
            "gap_sec": e["gap_sec"],
            "ball_move_norm": round(ball_move, 3) if ball_move is not None else None,
            "holder_dist_norm": round(holder_dist, 3) if holder_dist is not None else None,
            "from_ball_conf": tl[iA]["ball_conf"], "to_ball_conf": tl[iB]["ball_conf"],
            "verdict": verdict,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gated", required=True, help="possession_gated.json")
    ap.add_argument("--sel", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    gd = load(a.gated)
    sel = load(a.sel)
    os.makedirs(a.outdir, exist_ok=True)

    dup = duplication(sel)
    tra = audit_transfers(gd, sel)

    vc = defaultdict(int)
    for t in tra:
        vc[t["verdict"]] += 1

    out = {
        "meta": {
            "dup_dist_thr": DUP_DIST,
            "n_transfers_audited": len(tra),
            "verdict_counts": dict(vc),
            "note": ("本层是对球权转移的对抗性自检：pid 变化不等于球权转移，"
                     "需要用『球是否真的动了』『新老持球人是否真的分得开』来区分"
                     "真转移与追踪标签切换。"),
        },
        "identity_duplication": {k: v for k, v in dup.items() if k != "rows"},
        "identity_duplication_rows": dup["rows"],
        "transfer_audit": tra,
    }
    p = os.path.join(a.outdir, "transfer_audit.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("=" * 62)
    print("判据 ③ 身份稳定性（场上应 10 人）")
    print("=" * 62)
    print(f"  逐帧 pid 数：中位 {dup['n_pid_median']:.0f}"
          f"  范围 {dup['n_pid_min']}–{dup['n_pid_max']}"
          f"（超出应有 +{dup['excess_median']:.0f}）")
    print(f"  全程不同 pid 总数：{dup['distinct_pids_total']}"
          f"  /  pid 槽位总数 {dup['pid_slots_total']}"
          f"  → 复用系数 {dup['pid_reuse_factor']}")
    print(f"  🔴 相邻帧身份重合（Jaccard）：中位 {dup['adjacent_jaccard_median']:.3f}"
          f"  均 {dup['adjacent_jaccard_mean']:.3f}")
    print(f"  脚点重合嫌疑（<0.5 身高）：{dup['frames_with_dup']}/{dup['n_frames']}"
          f" = {dup['dup_ratio_pct']}%（此项含真实贴身，仅作参考）")
    print()
    print("=" * 62)
    print("判据 ①&② 逐次转移复核")
    print("=" * 62)
    sym = {"supported_transfer": "✅ 支持",
           "weak_transfer": "⚠️  弱",
           "identity_swap_suspect": "❌ 疑标签切换",
           "unverifiable": "⬜ 不可验"}
    for t in tra:
        print(f"  {sym[t['verdict']]}  t={t['t']:>6.1f}  {t['from']:>3} → {t['to']:<3}"
              f"  球位移={t['ball_move_norm'] if t['ball_move_norm'] is not None else 'NA':>6}"
              f"  人距={t['holder_dist_norm'] if t['holder_dist_norm'] is not None else 'NA':>6}"
              f"  conf {t['from_ball_conf']}/{t['to_ball_conf']}")
    print()
    print(f"[汇总] {dict(vc)}")
    print(f"[out] {p}")


if __name__ == "__main__":
    main()
