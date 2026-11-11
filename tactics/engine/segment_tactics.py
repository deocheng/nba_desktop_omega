#!/usr/bin/env python3
"""第 6 层：时序聚合 + 战术事件推导。

输入：relations.json（逐帧关系 + 几何）、select_tracks.json（稳定 pid）、frames.json

═══════════════════════════════════════════════════════════════════════
推导逻辑（球为主线 + 关系为骨架）
═══════════════════════════════════════════════════════════════════════
用户定调：战术回合的语义主线是「球的转移」——球在谁手上 → 传给谁
→ 相关球员怎么动 → 其他人怎么动 → 出手即回合结束。

本层按这个顺序做，但对每一步都标注**证据强度**，不把弱证据说成结论：

  A. 球的归属与转移
     球位来自高帧率球专线（10fps）。每帧把球归属给最近球员，得到「持球人序列」。
     持球人切换 = 球权转移候选。
     ⚠️ 球专线的可靠性有限（见模型报告），所以 A 的所有结论都带 confidence 字段。

  B. 持久关系段（战术骨架）
     对每一对球员，逐帧取 top-1 谓词；找出**连续 ≥min_len 帧**保持同一谓词且
     score ≥ 阈值的段。段越长，说明这个关系越稳定 —— 例如某人持续 beside 另一人
     就是掩护/包夹的形态，持续 watching 就是盯防。

  C. 聚簇与空间结构
     用几何量（脚点归一化距离）检测近邻对 -> 掩护/夹击候选；
     用 x 分布判断强弱侧；用球的位置判断球侧 / 弱侧。

  D. 谓词 -> 战术语义映射
     只映射官方 35 词里语义明确的那些，其余归为「空间/几何」不作战术解读。

⚠️ 不做的事（避免过度解读）：
   × 不从关系直接断定「这是高位挡拆」—— 单帧关系无法区分「掩护」与「站位重叠」，
     那需要时序上的接触-分离动力学，属下一阶段。
   × 不做命中/失误判定 —— 那需要进球检测。
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
from collections import Counter, defaultdict

from common.nba_paths import workspace_file

# 官方 35 词里可作战术解读的词（其余按几何处理）
TACTICAL_MAP = {
    "watching":       ("盯防/观察", "该球员持续看向目标 -> 对位盯防或协防注意力"),
    "looking at":     ("盯防/观察", "同上，语义更主动"),
    "beside":         ("并排站位", "两人并排 -> 掩护、双人夹击、或换防交接候选"),
    "standing beside": ("并排站位", "站定并排 -> 强掩护/包夹形态"),
    "holding":        ("持物",     "可能为持球人（需与球专线交叉验证）"),
    "carrying":       ("持物",     "同上"),
    "in front of":    ("前后位",   "绕前防守 / 背身卡位候选"),
    "behind":         ("前后位",   "背后追防 / 背身要球候选"),
    "leaning against": ("身体接触", "贴身对抗 -> 背身单打、卡位"),
    "walking past":   ("交叉移动", "无球交叉跑位 / 换防交接"),
    "talking to":     ("交流",     "沟通 -> 换防喊话、指挥（弱证据）"),
    "leaning on":     ("身体接触", "倚靠对抗"),
}
GEOMETRIC = {"to the left of", "to the right of", "above", "below", "on",
             "in", "inside", "part of", "at", "near", "with"}

SRC_DEFAULT = str(workspace_file("action_work/seg_possession"))


def norm_label(lab: str) -> str:
    return lab


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("srcdir", nargs="?", default=SRC_DEFAULT)
    ap.add_argument("--min-len", type=int, default=3, help="持久关系段最短帧数")
    ap.add_argument("--seg-thr", type=float, default=0.25, help="段内谓词最低分")
    ap.add_argument("--cluster-dist", type=float, default=1.3,
                    help="近邻判定：脚点距离 / 平均框高")
    a = ap.parse_args()

    R = json.load(open(os.path.join(a.srcdir, "relations.json")))
    ST = json.load(open(os.path.join(a.srcdir, "select_tracks.json")))
    TR = json.load(open(os.path.join(a.srcdir, "tracks.json")))
    frames = R["frames"]
    n_f = len(frames)
    by_idx = {f["idx"]: f for f in ST["frames"]}
    tr_idx = {f["idx"]: f for f in TR["frames"]}

    # ---------------- A. 球权与转移 ----------------
    def ball_center(ball: dict | None):
        """tracks.json 的 ball 只存 box/conf/pred，球心在此现算。"""
        if not ball:
            return None
        b = ball.get("box")
        if not b:
            return None
        return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)

    poss_seq = []
    for f in ST["frames"]:
        ball = f.get("ball") or {}
        c = ball_center(ball)
        holder, hd = None, None
        if c:
            bx, by = c
            best, bd = None, 1e9
            for p in f["players"]:
                x1, y1, x2, y2 = p["box"]
                hh = max(y2 - y1, 1.0)
                fx, fy = (x1 + x2) / 2, y2
                d = math.hypot(bx - fx, by - fy) / hh
                if d < bd:
                    bd, best = d, p["pid"]
            if bd is not None and bd < 1.2:
                holder, hd = best, round(bd, 3)
        poss_seq.append({"idx": f["idx"], "t": f["t"], "holder": holder,
                         "dist": hd,
                         "ball_pred": bool(ball.get("pred")),
                         "ball_conf": ball.get("conf", 0.0)})

    transfers = []
    for i in range(1, len(poss_seq)):
        p, c = poss_seq[i - 1], poss_seq[i]
        if p["holder"] and c["holder"] and p["holder"] != c["holder"]:
            transfers.append({"t": c["t"], "from": p["holder"], "to": c["holder"],
                              "gap_sec": round(c["t"] - p["t"], 2)})
    holder_cov = sum(1 for x in poss_seq if x["holder"]) / n_f

    # ---------------- B. 持久关系段 ----------------
    # 逐帧：对 (a,b) 取 top-1 谓词
    per_pair_frame: dict[tuple[str, str], dict[int, tuple[str, float]]] = defaultdict(dict)
    pred_counter = Counter()
    pred_score_sum = defaultdict(float)
    for f in frames:
        seen = {}
        for t in f["triples"]:
            key = tuple(sorted((t["s"], t["o"])))
            pred_counter[t["pred"]] += 1
            pred_score_sum[t["pred"]] += t["score"]
            if key not in seen or t["score"] > seen[key][1]:
                seen[key] = (t["pred"], t["score"])
        for k, v in seen.items():
            per_pair_frame[k][f["idx"]] = v

    segments = []
    for pair, fr_map in per_pair_frame.items():
        idxs = sorted(fr_map)
        run_p, run_start, run_sc, run_n = None, None, [], 0
        prev_i = None
        for i in idxs:
            pr, s = fr_map[i]
            ok = s >= a.seg_thr
            cont = prev_i is not None and i == prev_i + 1
            if ok and run_p == pr and cont:
                run_sc.append(s)
                run_n += 1
            else:
                if run_p is not None and run_n >= a.min_len:
                    segments.append({
                        "a": pair[0], "b": pair[1], "pred": run_p,
                        "n_frames": run_n, "start_idx": run_start, "end_idx": prev_i,
                        "start_t": None, "end_t": None,
                        "mean_score": round(sum(run_sc) / len(run_sc), 4)})
                if ok:
                    run_p, run_start, run_sc, run_n = pr, i, [s], 1
                else:
                    run_p, run_start, run_sc, run_n = None, None, [], 0
            prev_i = i
        if run_p is not None and run_n >= a.min_len:
            segments.append({"a": pair[0], "b": pair[1], "pred": run_p,
                             "n_frames": run_n, "start_idx": run_start,
                             "end_idx": prev_i,
                             "mean_score": round(sum(run_sc) / len(run_sc), 4)})

    tmap = {f["idx"]: f["t"] for f in frames}
    for s in segments:
        s["start_t"] = tmap.get(s["start_idx"])
        s["end_t"] = tmap.get(s["end_idx"])
        s["dur_sec"] = round((s["end_t"] or 0) - (s["start_t"] or 0) + 0.5, 2)
        s["semantic"] = TACTICAL_MAP.get(s["pred"], (None, None))[0]
        s["reading"] = TACTICAL_MAP.get(s["pred"], (None, None))[1]
    segments.sort(key=lambda z: (-z["n_frames"], -z["mean_score"]))

    # ---------------- C. 聚簇与空间结构 ----------------
    per_frame_struct = []
    for f in frames:
        pr = f["pairs"]
        near = [x for x in pr if x["dist_norm"] <= a.cluster_dist]
        lefts = [p for p in by_idx[f["idx"]]["players"]]
        xs = [p["foot"][0] for p in lefts]
        ball = ball_center(by_idx[f["idx"]].get("ball"))
        per_frame_struct.append({
            "idx": f["idx"], "t": f["t"],
            "n_near_pairs": len(near),
            "near_pairs": [[x["s"], x["o"], x["dist_norm"]] for x in near],
            "min_dist": min((x["dist_norm"] for x in pr), default=None),
            "x_spread": round(max(xs) - min(xs), 1) if xs else None,
            "x_mean": round(sum(xs) / len(xs), 1) if xs else None,
            "ball_x": round(ball[0], 1) if ball else None,
            "ball_y": round(ball[1], 1) if ball else None,
        })

    # 每帧 top-1 谓词的分布（看关系信号是否被单一谓词垄断）
    frame_top1 = Counter()
    for f in frames:
        seen = {}
        for t in f["triples"]:
            key = tuple(sorted((t["s"], t["o"])))
            if key not in seen or t["score"] > seen[key][1]:
                seen[key] = (t["pred"], t["score"])
        for pr, _s in seen.values():
            frame_top1[pr] += 1

    near_counts = [s["n_near_pairs"] for s in per_frame_struct]
    cluster_frames = [s for s in per_frame_struct if s["n_near_pairs"] >= 3]

    # ---------------- D. 输出 ----------------
    out = {
        "meta": {
            "n_frames": n_f,
            "duration_sec": round(tmap[max(tmap)] - tmap[min(tmap)], 1),
            "min_len": a.min_len, "seg_thr": a.seg_thr,
            "cluster_dist": a.cluster_dist,
            "holder_coverage": round(holder_cov, 3),
            "n_transfers": len(transfers),
            "n_segments": len(segments),
            "near_pairs_median": sorted(near_counts)[len(near_counts) // 2],
            "cluster_frames_ge3": len(cluster_frames),
        },
        "predicate_spectrum": [
            {"pred": k, "count": v,
             "share_pct": round(v / max(sum(pred_counter.values()), 1) * 100, 1),
             "top1_frames": frame_top1.get(k, 0),
             "mean_score": round(pred_score_sum[k] / v, 4),
             "semantic": TACTICAL_MAP.get(k, (None, "空间/几何，不作战术解读"))[0]}
            for k, v in pred_counter.most_common()
        ],
        "dominance": {
            "top1_total": sum(frame_top1.values()),
            "watching_share_of_top1": round(
                frame_top1.get("watching", 0) / max(sum(frame_top1.values()), 1) * 100, 1),
            "top5_top1": frame_top1.most_common(5),
            "_reading": "若单一谓词占 top-1 的绝大多数，说明关系信号被该谓词垄断、区分度低。"
                        "这是模型在域外场景（篮球广角转播）上的真实表现，不可当强证据使用。",
        },
        "possession": poss_seq,
        "transfers": transfers,
        "segments": segments,
        "structure": per_frame_struct,
    }
    os.makedirs(a.srcdir, exist_ok=True)
    with open(os.path.join(a.srcdir, "tactics.json"), "w") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)

    m = out["meta"]
    print(f"[tactics] {m['n_frames']} 帧 / {m['duration_sec']}s")
    print(f"[A 球权] 持球人归属覆盖 {m['holder_coverage']*100:.1f}% 帧 | "
          f"球权转移 {m['n_transfers']} 次")
    print(f"[B 关系段] ≥{a.min_len} 帧且 score≥{a.seg_thr} 的持久段 {m['n_segments']} 个")
    print(f"[C 聚簇] 近邻对中位 {m['near_pairs_median']} 对/帧 | "
          f"≥3 近邻对的帧 {m['cluster_frames_ge3']} 帧")
    print()
    print("谓词谱（前 12）:")
    for p in out["predicate_spectrum"][:12]:
        print(f"   {p['pred']:<20} {p['count']:>4} 次 ({p['share_pct']:>4.1f}%)  "
              f"top1 {p['top1_frames']:>3} 帧  均分 {p['mean_score']:.3f}   "
              f"{p['semantic'] or '几何'}")
    dm = out["dominance"]
    print(f"[垄断度] top-1 谓词总计 {dm['top1_total']} | watching 占 "
          f"{dm['watching_share_of_top1']}% | top5={dm['top5_top1']}")
    print()
    print("最长持久关系段（前 12）:")
    for s in segments[:12]:
        print(f"   {s['a']:>7} --{s['pred']:<18}--> {s['b']:<7} "
              f"{s['n_frames']:>2}帧/{s['dur_sec']:>5.1f}s  均分 {s['mean_score']:.3f}  "
              f"t={s['start_t']}~{s['end_t']}  {s['semantic'] or ''}")
    print()
    print(f"[out] {os.path.join(a.srcdir, 'tactics.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
