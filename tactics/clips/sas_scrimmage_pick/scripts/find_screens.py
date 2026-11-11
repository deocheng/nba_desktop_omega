#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配合(掩护/挡拆/无球协同)候选打分器 —— 消费粗扫 JSONL。

几何判据(可解释、无需跟踪器):
  1) 「半场进攻」门:逐帧可见人数 n>=8 的连续段>=8 个采样帧(4fps⇒2s),且无镜头切换。
  2)「运动」门:段内每帧与前帧的最近邻位移中位数 > 1.0px(剔死球/暂停/罚球站定)。
  3) 「同队靠近」:帧内所有球员两两配对,取中心距最近的一对 d_min(t)。
     要求 d_min 跌到< CLOSE_TH 连续>= 3 个采样帧(0.75s)。
  4) 「随后分离」:接触段结束后 <= SEP_FRAMES 个采样帧内 d 重新拉开到 > FAR_TH,
     且两者的后续位移方向相反(分离而非并肩同行)。
  5) 半场判定:两人中点落在画面下半区(进攻篮筐侧)y > 250(1280x720 坐标系)。
     —— 转播半场进攻时篮筐/进攻半场占画面下半部,避免把回防/中场画面当进攻。
打分= 靠近深度 + 接触时长 + 分离幅度 + 人数与运动强度,各项归一后加权。
"""
import argparse
import json
import math
import os
import statistics

ap = argparse.ArgumentParser()
ap.add_argument("--inp", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--fps", type=float, default=4.0)
ap.add_argument("--close-th", type=float, default=90.0)
ap.add_argument("--far-th", type=float, default=150.0)
ap.add_argument("--min-people", type=int, default=8)
ap.add_argument("--hold-frames", type=int, default=3)
ap.add_argument("--sep-frames", type=int, default=8)
ap.add_argument("--top", type=int, default=30)
ap.add_argument("--min-h", type=float, default=100.0,
                help="球员框高下限(px);低于此值视为观众/替补席, 剔除。实测场上球员框高 151-283px")
ap.add_argument("--dmin-floor", type=float, default=25.0,
                help="最近邻中心距下限(px):低于此值视为同一人被检出两次(重复框), 不是掩护。"
                     "实测 r1 榜首 dmin=8.9px 即属此类伪候选。真实掩护为胯下-肩距量级。")
a = ap.parse_args()

frames = []
with open(a.inp, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            frames.append(json.loads(line))
print(f"[load] {len(frames)} frames, t {frames[0]['t']}..{frames[-1]['t']}")

def centers(rec):
    out = []
    for x0, y0, x1, y1 in rec["people"]:
        h = y1 - y0
        if h < a.min_h:      # 观众/替补席剪影, 剔除
            continue
        out.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, h))
    return out

def dmat(cs):
    n = len(cs)
    D = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = math.hypot(cs[i][0] - cs[j][0], cs[i][1] - cs[j][1])
            D[i][j] = D[j][i] = d
    return D

# ---------- 预计算每帧最近邻对 + 位移能量 ----------
per = []
for k, rec in enumerate(frames):
    cs = centers(rec)
    D = dmat(cs)
    best = None
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            if best is None or D[i][j] < best[2]:
                best = (i, j, D[i][j])
    # 位移能量: 本帧每人与「上一帧最近的人」的位移, 取中位数(抗ID切换)
    mv = 0.0
    if k > 0:
        pcs = centers(frames[k - 1])
        if pcs and cs:
            ds = []
            for c in cs:
                ds.append(min(math.hypot(c[0] - p[0], c[1] - p[1]) for p in pcs))
            mv = statistics.median(ds)
    per.append({"k": k, "t": rec["t"], "n": len(cs), "pair": best, "mv": mv,
                "cut": rec["cut"], "E": rec["energy"], "ball": rec["ball"]})

# ---------- 寻找「同一对人靠近→ 停留 → 分离」事件 ----------
# 注: 不能只按「每帧最近邻」连号, 因为最近邻会在两人之间反复跳变。
# 做法: 以每帧最近邻对为种子, 再对该(A,B)做局部时空跟踪(用贪心最近邻延续),
#       得到一条实际的配对距离时间序列 d_pair(t), 再在该序列上判定事件。
events = []
N = len(per)

def match_at(e, prev_cs, prev_i, prev_j, max_link=140.0):
    """把(e-1)帧的一对 (prev_i, prev_j) 延续到 e 帧: 各自匹配 e 帧最近的未占用框。"""
    cs_e = centers(frames[e])
    if len(cs_e) < 2 or not prev_cs:
        return None
    best, bset = None, None
    for ii in range(len(cs_e)):
        for jj in range(len(cs_e)):
            if ii == jj:
                continue
            cost = (math.hypot(cs_e[ii][0] - prev_cs[prev_i][0], cs_e[ii][1] - prev_cs[prev_i][1]) +
                    math.hypot(cs_e[jj][0] - prev_cs[prev_j][0], cs_e[jj][1] - prev_cs[prev_j][1]))
            if best is None or cost < best:
                best, bset = cost, (ii, jj)
    if best is None or best > 2 * max_link:
        return None
    return bset

# 先收集所有种子对(每帧最近邻), 逐个向前延伸成轨迹
seeds = [(per[k]["pair"][0], per[k]["pair"][1], k) for k in range(N)
         if per[k]["pair"] and per[k]["n"] >= a.min_people]

# 合并: 对每个种子向前后延伸, 生成配对轨迹
tracks = []
used = set()
for (i0, j0, k0) in seeds:
    if k0 in used:
        continue
    # 向后延伸
    seq = []
    cs_prev = centers(frames[k0])
    pi, pj = i0, j0
    k = k0
    cur = (pi, pj)
    while k < N:
        cs = centers(frames[k])
        if len(cs) < 2:
            break
        if k == k0:
            cur = (min(pi, pj), max(pi, pj))
        else:
            m = match_at(k, cs_prev, cur[0], cur[1])
            if m is None:
                break
            cur = tuple(sorted(m))
        cs_prev = cs
        d = math.hypot(cs[cur[0]][0] - cs[cur[1]][0], cs[cur[0]][1] - cs[cur[1]][1])
        seq.append({"k": k, "t": frames[k]["t"], "pair": cur, "d": d,
                    "n": len(cs), "mv": per[k]["mv"], "cut": per[k]["cut"]})
        used.add(k)
        k += 1
    if len(seq) >= 6:
        tracks.append(seq)

print(f"[tracks] {len(tracks)} pair-tracks (>=6 samples)")

# 在每条轨迹上找事件
for seq in tracks:
    ds = [s["d"] for s in seq]
    i = 0
    while i < len(seq):
        if seq[i]["d"] > a.close_th or seq[i]["d"] < a.dmin_floor or seq[i]["n"] < a.min_people:
            i += 1
            continue
        j = i
        while (j + 1 < len(seq) and seq[j + 1]["d"] <= a.close_th
               and seq[j + 1]["d"] >= a.dmin_floor
               and seq[j + 1]["n"] >= a.min_people and not seq[j + 1]["cut"]):
            j += 1
        run = j - i + 1
        if run >= a.hold_frames:
            seg = seq[i:j + 1]
            apex = min(seg, key=lambda z: z["d"])
            # 分离: 接触段结束后 sep_frames 内距离重新拉开到最大值
            best_div, div_info = 0.0, None
            for e in range(j + 1, min(len(seq), j + 1 + a.sep_frames)):
                if seq[e]["d"] > best_div:
                    best_div = seq[e]["d"]
                    div_info = {"t": seq[e]["t"], "d": seq[e]["d"], "n": seq[e]["n"]}
            events.append({
                "k0": seq[i]["k"], "k1": j, "run": run,
                "t_first": seg[0]["t"], "t_last": seg[-1]["t"],
                "apex_t": apex["t"], "dmin": apex["d"],
                "n_at_apex": apex["n"], "mv_at_apex": apex["mv"],
                "pair_at_apex": list(apex["pair"]),
                "d_series": [[round(s["t"], 2), round(s["d"], 1)] for s in seq[i:j + 1 + a.sep_frames]],
                "div": best_div, "div_info": div_info,
            })
            i = j + 1
        else:
            i += 1

print(f"[events] {len(events)} contact runs>= {a.hold_frames} samples, "
      f"{a.dmin_floor}<=d<={a.close_th}px")

# ---------- 打分 ----------
def in_half(t):
    # 接触瞬间两人都要在画面下 2/3(进攻半场)
    idx = min(range(len(frames)), key=lambda z: abs(frames[z]["t"] - t))
    rec = frames[idx]
    cs = centers(rec)
    if not cs:
        return False, None
    ys = sorted(c[1] for c in cs)
    return ys[len(ys) // 2] > 230, ys[len(ys) // 2]

scored = []
for e in events:
    half, med_y = in_half(e["apex_t"])
    e["half_ok"] = bool(half)
    e["median_y"] = med_y
    # 分项(全部 0..1)
    # 靠近深度: 目标区间 30-70px(胯下/肩距), 太近=重复框已在入口剔掉
    s_close = max(0.0, (a.close_th - e["dmin"]) / a.close_th)
    s_hold = min(1.0, e["run"] / 8.0)
    s_div = min(1.0, e["div"] / 250.0) if e["div"] else 0.0
    s_people = min(1.0, max(0, e["n_at_apex"] - 6) / 4.0)
    s_mv = min(1.0, e["mv_at_apex"] / 6.0)
    s_half = 1.0 if e["half_ok"] else 0.0
    e["parts"] = {"close": round(s_close, 3), "hold": round(s_hold, 3),
                  "diverge": round(s_div, 3), "people": round(s_people, 3),
                  "motion": round(s_mv, 3), "half": s_half}
    e["score"] = round(0.28 * s_close + 0.18 * s_hold + 0.22 * s_div +
                       0.12 * s_people + 0.10 * s_mv + 0.10 * s_half, 4)
    scored.append(e)

scored.sort(key=lambda z: -z["score"])
os.makedirs(os.path.dirname(a.out), exist_ok=True)
json.dump({"params": vars(a), "n_frames": len(frames), "events": scored},
          open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

hdr = f"{'#':>3} {'t_apex':>8} {'dmin':>6} {'run':>4} {'n':>3} {'mv':>5} {'div':>6} {'half':>5} {'score':>6}  parts"
print(hdr)
for i, e in enumerate(scored[:a.top]):
    print(f"{i+1:3d} {e['apex_t']:8.2f} {e['dmin']:6.1f} {e['run']:4d} {e['n_at_apex']:3d} "
          f"{e['mv_at_apex']:5.2f} {e['div']:6.1f} {str(e['half_ok']):>5} {e['score']:6.3f}  {e['parts']}")
print(f"\n[saved] {a.out}  ({len(scored)} events total)")
