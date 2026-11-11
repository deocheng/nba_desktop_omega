#!/usr/bin/env python3
"""姿态层 → 动作信号（第 5.7 层）：把 YOLO11n-pose 的骨架当动作识别用。

背景（回答「有没有引入第二个模型做动作识别辅助」）：
    项目里实际有两个模型在跑 —— RelateAnything（关系预测）与 YOLO11n / YOLO11n-pose
    （检测 + 姿态）。但姿态模型此前**只被当作几何提供者**（给球员框、给手腕坐标去卡球），
    从来没有拿它的**骨架运动**去识别动作。本脚本补上这一层。

🔴 三个必须显式处理的坑（否则数字全是假的）：
  1. **镜头在摇**（里程碑 02 已实测：上升段 0.6s 内篮筐模板移动 8px，确认真摇镜）。
     骨架 y 坐标的整体下移会被误读成"所有人同时起跳"。
  2. **没有跨帧身份**（pid→身份映射未解决）。⇒ 用贪心 IoU 关联建轨迹，
     并在输出里标注 `track_id` 只是**本脚本内的临时编号**，不是球员身份。
  3. **动作事件必须有基线**。跳/封盖是稀疏事件，若不加对照，
     "在事件附近找到一次起跳"毫无意义。⇒ 与关系层同款：**置换检验**
     （随机平移事件时刻、保持事件数量，重复 2000 次）。

⚠️⚠️ **v1 失败记录（2026-09-23，必须留档）**：
     v1 用「整条轨迹踝关节 y 的中位基线」+ 全局中位位移做摇镜补偿 + `--min-h 60`，
     结果 **194 次跳跃 / 43.4s = 4.47 次/秒**（10 个球员每 2 秒各跳一次，物理上不可能），
     且置换检验 p=1.0（null 均值同样饱和到 5.0）—— **指标饱和，零区分力**。
     诊断出的三条根因（实测数字）：
       ① 框中位高 219px、**p05 已是 124px** ⇒ `--min-h 60` 等于没过滤（100% 通过）；
       ② **46.6% 的框底 y<600**（画面上半部）⇒ 近半数检出是观众/替补，不是场上球员；
       ③ 贪心 IoU 把轨迹切得很碎（771 条里只有 **87 条** ≥15 帧），
          在短轨迹上取「整条中位数」当基线，任何抖动都被当成起跳。
     **v2 的三条修正**：① 滚动中位数（窗 11 帧）**去趋势**替代全局基线
     —— 跳是快事件、摇镜是慢漂移，局部去趋势一次性消掉摇镜，比显式的全局平移估计更稳；
     ② 轨迹必须**踝关节在 ≥70% 帧可用**（不用框底回退）且**脚点在画面下半部**；
     ③ 事件要求是**局部极大 + 上升下降完整**，而不是"超过阈值"。

动作判据（全部为**尺度无关**的归一化量，除以人物框高）：
  air_dyn    = (滚动中位踝 y − 当前踝 y) / 框高               正 = 相对近期姿态脚离地
  reach      = (肩 y − 手腕 y) / 框高                        正 = 手举过肩
  跳跃事件    = air_dyn 局部极大 ≥ 0.15 且上升+下降总时长 ≤ 1.0s
  争抢/封盖    = 跳跃 且 reach > 0.10

用法:
  pose_motion.py <pose_kpt_cache.json> <frames.json> <possession_v2.json> <clock_table.json> <out.json>
                 [--min-track 25] [--min-foot-y 550] [--min-ankle-conf-rate 0.7]
                 [--air 0.15] [--half-win 1.5] [--n-perm 2000]
"""
from __future__ import annotations

import argparse
import json
import random
import statistics

ANKLE = (15, 16)
KNEE = (13, 14)
HIP = (11, 12)
SHOULDER = (5, 6)
WRIST = (9, 10)
NOSE = 0
KF = 0.30          # 关键点置信度门限
DETREND_WIN = 11   # 滚动中位数窗（帧）；11 帧 ≈ 1.1s @10fps


def mean_y(kpt, idxs):
    v = [kpt[k][1] for k in idxs if kpt[k][2] >= KF]
    return statistics.fmean(v) if v else None


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def roll_median(vals, win):
    """逐点滚动中位数（奇数窗，边缘用可用邻域）。用于去趋势。"""
    n = len(vals)
    half = win // 2
    out = []
    for i in range(n):
        seg = [vals[j] for j in range(max(0, i - half), min(n, i + half + 1))
               if vals[j] is not None]
        out.append(statistics.median(seg) if seg else None)
    return out


def t_of_clock(pairs, c):
    for i in range(len(pairs) - 1):
        t1, c1 = pairs[i]
        t2, c2 = pairs[i + 1]
        if (c1 - c) * (c2 - c) <= 0 and c1 != c2:
            return t1 + (t2 - t1) * (c1 - c) / (c1 - c2)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pose_cache")
    ap.add_argument("frames_json")
    ap.add_argument("possession_json")
    ap.add_argument("clock_table")
    ap.add_argument("out_json")
    ap.add_argument("--min-track", type=int, default=25)
    ap.add_argument("--min-foot-y", type=float, default=550.0)
    ap.add_argument("--max-h", type=float, default=400.0)
    ap.add_argument("--min-ankle-conf-rate", type=float, default=0.7)
    ap.add_argument("--air", type=float, default=0.15)
    ap.add_argument("--reach-thr", type=float, default=0.10,
                    help="争抢/封盖判据的手过肩阈值；0.10 是里程碑03 的固定值，"
                         "实测仅 2.4%% 场上人次超过 —— 判据过严。"
                         "扩样本后建议按 reach 分布分位数选取")
    ap.add_argument("--half-win", type=float, default=1.5)
    ap.add_argument("--n-perm", type=int, default=2000)
    a = ap.parse_args()

    pc = json.load(open(a.pose_cache))
    frames = json.load(open(a.frames_json))
    ts = [f["t"] for f in frames]
    idxs = [f["idx"] for f in frames]
    # 帧间距由 frames.json 推导，不再硬编码 0.5s（旧值只对 2fps 抽帧成立；
    # 扩样本窗口是 10fps，硬编码会把全部事件时刻错一个量级）。
    dt_frame = (ts[-1] - ts[0]) / max(len(ts) - 1, 1)

    per_frame = [pc["frames"].get(str(f["idx"]), {}).get("persons", []) for f in frames]
    print(f"[载入] {len(frames)} 帧，人物框合计 {sum(len(s) for s in per_frame)}")

    # ---------- 贪心 IoU 轨迹关联 ----------
    tracks = {}          # tid -> list[(i, person)]
    next_tid = 1
    active = {}          # tid -> box（上一帧）
    for i, persons in enumerate(per_frame):
        used = set()
        assign = {}
        if active:
            cand = []
            for tid, pb in active.items():
                for j, p in enumerate(persons):
                    if j in used:
                        continue
                    v = iou(pb, p["box"])
                    if v > 0.3:
                        cand.append((v, tid, j))
            cand.sort(reverse=True)
            for v, tid, j in cand:
                if tid in assign or j in used:
                    continue
                assign[tid] = j
                used.add(j)
        new_active = {}
        for tid, j in assign.items():
            tracks.setdefault(tid, []).append((i, per_frame[i][j]))
            new_active[tid] = per_frame[i][j]["box"]
        for j, p in enumerate(persons):
            if j in used:
                continue
            tracks[next_tid] = [(i, p)]
            new_active[next_tid] = p["box"]
            next_tid += 1
        active = new_active

    good = {tid: v for tid, v in tracks.items() if len(v) >= a.min_track}
    print(f"[轨迹] 共 {len(tracks)} 条，长度 ≥{a.min_track} 帧的 {len(good)} 条")

    # ---------- v2 轨迹筛选：场上球员 + 踝关节可用 ----------
    kept, drop_reason = {}, {"foot": 0, "h": 0, "ankle": 0}
    for tid, seq in good.items():
        med_foot = statistics.median([p["box"][3] for _, p in seq])
        med_h = statistics.median([p["box"][3] - p["box"][1] for _, p in seq])
        ok_ankle = sum(1 for _, p in seq
                       if mean_y(p["kpt"], ANKLE) is not None) / len(seq)
        if med_foot < a.min_foot_y:
            drop_reason["foot"] += 1
            continue
        if med_h > a.max_h:
            drop_reason["h"] += 1
            continue
        if ok_ankle < a.min_ankle_conf_rate:
            drop_reason["ankle"] += 1
            continue
        kept[tid] = seq
    print(f"[筛选] 保留 {len(kept)} 条  （剔除：脚点过高 {drop_reason['foot']}、"
          f"框过大 {drop_reason['h']}、踝关节不可用 {drop_reason['ankle']}）")

    # ---------- v2 特征：滚动中位数去趋势（同时消掉摇镜）----------
    feats = {}
    for tid, seq in kept.items():
        seq = sorted(seq, key=lambda z: z[0])
        ann = [mean_y(p["kpt"], ANKLE) for _, p in seq]
        base = roll_median(ann, DETREND_WIN)
        for (i, p), av, bv in zip(seq, ann, base):
            if av is None or bv is None:
                continue                    # 该帧踝关节不可用 → 不产特征（不猜）
            h = max(p["box"][3] - p["box"][1], 1.0)
            sh = mean_y(p["kpt"], SHOULDER)
            wr = mean_y(p["kpt"], WRIST)
            nose = p["kpt"][NOSE][1] if p["kpt"][NOSE][2] >= KF else None
            reach = None
            if sh is not None and wr is not None:
                reach = round((sh - wr) / h, 4)
            above = None
            if wr is not None and nose is not None:
                above = wr < nose
            feats.setdefault(tid, {})[i] = {
                "air_dyn": round((bv - av) / h, 4),
                "reach": reach,
                "above_head": above,
                "h": round(h, 1),
            }

    # ---------- v2 事件：局部极大 + 完整上升下降 + 时长受限 ----------
    def find_events(d, key, thr, extra=None):
        evs = []
        ks = sorted(d)
        half = DETREND_WIN // 2
        for pos, i in enumerate(ks):
            v = d[i][key]
            if v is None or v < thr:
                continue
            lo = max(0, pos - half)
            hi = min(len(ks), pos + half + 1)
            if v < max(d[ks[j]][key] or -9 for j in range(lo, hi)):
                continue                              # 不是邻域极大
            # 上升下降范围：向左/右各找到 ≤0 为止
            li = pos
            while li - 1 >= 0 and (d[ks[li - 1]][key] or -9) > 0.3 * thr:
                li -= 1
            ri = pos
            while ri + 1 < len(ks) and (d[ks[ri + 1]][key] or -9) > 0.3 * thr:
                ri += 1
            span = (ri - li + 1) * dt_frame           # 秒（帧间距由 frames.json 推导）
            if span > 1.0:
                continue
            if extra and not extra(d[i]):
                continue
            evs.append({"track": tid, "idx": idxs[i], "t": ts[i],
                        key: round(v, 4), "span_sec": round(span, 2), "h": d[i]["h"]})
        return evs

    jumps = []
    for tid, d in feats.items():
        jumps.extend(find_events(d, "air_dyn", a.air))
    jumps = sorted({(j["track"], j["idx"]): j for j in jumps}.values(),
                   key=lambda z: z["t"])

    contests = []
    for tid, d in feats.items():
        contests.extend(find_events(
            d, "air_dyn", a.air,
            extra=lambda f: (f["reach"] is not None and f["reach"] > a.reach_thr)))
    contests = sorted({(c["track"], c["idx"]): c for c in contests}.values(),
                      key=lambda z: z["t"])

    # ---------- 事件时间（从读秒表推导）----------
    ct_raw = json.load(open(a.clock_table))
    pairs = sorted((round(ts[0] + (f["frame"] - 1) * dt_frame, 3), float(f["clock_sec"]))
                   for f in ct_raw["frames"] if "clock_sec" in f)
    pos = json.load(open(a.possession_json))
    events = []
    for act in pos["pbp_actions"]:
        t = t_of_clock(pairs, act["clock"])
        if t is not None:
            events.append({"n": act["n"], "clock": act["clock"], "t": round(t, 1),
                           "player": act["player"], "kind": act["kind"]})

    # ---------- 置换检验：动作事件是否聚集在 PBP 事件附近 ----------
    hw = a.half_win

    def hit_stat(evs, action_times):
        """命中数 = 有多少个 PBP 事件，其 ±half_win 邻域内至少落进一个动作事件。"""
        return sum(1 for s in evs
                   if any(abs(c - s["t"]) <= hw for c in action_times))

    obs_j = hit_stat(events, [z["t"] for z in jumps])
    obs_c = hit_stat(events, [z["t"] for z in contests])

    # null：把动作事件的**时刻**整体循环平移（保持数量与间隔结构，只破坏对齐）
    rnd = random.Random(20260926)
    W = ts[-1] - ts[0]
    null_j, null_c = [], []
    for _ in range(a.n_perm):
        d = rnd.uniform(-W / 2, W / 2)
        sj = [(s["t"] - ts[0] + d) % W + ts[0] for s in jumps]
        sc = [(s["t"] - ts[0] + d) % W + ts[0] for s in contests]
        null_j.append(hit_stat(events, sj))
        null_c.append(hit_stat(events, sc))

    def perm_p(obs, null):
        ge = sum(1 for x in null if x >= obs)
        return (ge + 1) / (len(null) + 1)

    # 逐帧汇总序列（供作图）：最大 air_dyn 与活跃轨迹数
    series = []
    for i in range(len(frames)):
        vals = [feats[tid][i]["air_dyn"] for tid in feats if i in feats[tid]]
        series.append({"t": ts[i],
                       "max_air": round(max(vals), 4) if vals else None,
                       "n_tracks": len(vals)})

    out = {
        "_about": "姿态骨架运动学 → 动作信号，并与 PBP 事件时刻做对齐检验。"
                  "事件时间由 clock_table 读秒插值推导，非手写。"
                  "v2：滚动中位数去趋势 + 场上球员/踝关节可用性筛选 + 局部极大事件。",
        "series": series,
        "params": {"min_track": a.min_track, "min_foot_y": a.min_foot_y,
                   "max_h": a.max_h, "min_ankle_conf_rate": a.min_ankle_conf_rate,
                   "air_thr": a.air, "detrend_win": DETREND_WIN,
                   "half_win": hw, "n_perm": a.n_perm},
        "v1_failure_record": {
            "what": "v1 用整条轨迹中位基线 + 全局中位位移摇镜补偿 + min_h=60",
            "result": "194 次跳跃 / 43.4s = 4.47 次/秒，置换检验 p=1.0（null 也饱和到 5.0）",
            "verdict": "指标饱和，零区分力",
            "root_causes": [
                "框中位高 219px、p05 已是 124px ⇒ min_h=60 等于没过滤（100% 通过）",
                "46.6% 的框底 y<600（画面上半部）⇒ 近半检出是观众/替补",
                "贪心 IoU 把轨迹切碎（771 条只剩 87 条 ≥15 帧），短轨迹取整条中位数当基线，抖动即被当起跳",
            ],
        },
        "track_filter": {"n_tracks": len(tracks), "n_len_ok": len(good),
                         "n_kept": len(kept), "dropped": drop_reason},
        "counts": {"n_frames": len(frames), "n_person": sum(len(s) for s in per_frame),
                   "n_jumps": len(jumps), "n_contests": len(contests)},
        "jump_rate_per_sec": round(len(jumps) / (ts[-1] - ts[0]), 3),
        "events": events,
        "alignment": {
            "jumps": {"observed_hits": obs_j, "n_jumps": len(jumps),
                      "null_mean": round(statistics.fmean(null_j), 3),
                      "p_value": round(perm_p(obs_j, null_j), 4),
                      "significant_at_0.05": perm_p(obs_j, null_j) < 0.05},
            "contests": {"observed_hits": obs_c, "n_contests": len(contests),
                         "null_mean": round(statistics.fmean(null_c), 3),
                         "p_value": round(perm_p(obs_c, null_c), 4),
                         "significant_at_0.05": perm_p(obs_c, null_c) < 0.05},
            "method": f"循环平移动作事件时刻（保持数量与间隔结构），重复 {a.n_perm} 次；"
                      f"命中判据 = 事件时刻 ±{hw}s 内存在动作事件",
            "saturation_note": "若 obs 与 null_mean 都接近事件总数（5），说明动作事件过密、"
                               "指标饱和 ⇒ 该检验没有区分力，必须先提高事件选择性",
        },
        "jumps": jumps,
        "contests": contests,
    }

    print(f"\n[动作 v2] 跳跃 {len(jumps)} 次（{out['jump_rate_per_sec']}/s）  "
          f"争抢/封盖 {len(contests)} 次")
    for key, d in (("jumps", out["alignment"]["jumps"]),
                   ("contests", out["alignment"]["contests"])):
        print(f"[对齐:{key}] 命中 {d['observed_hits']}/{len(events)} 个 PBP 事件邻域  "
              f"null 均值 {d['null_mean']}  p={d['p_value']:.4f}  "
              f"{'✅ 显著' if d['significant_at_0.05'] else '⚠️ 不显著'}")
    print("\n=== 跳跃事件明细（全部）===")
    for j in jumps:
        print(f"  t={j['t']:>6.1f}s  track#{j['track']:<4} air_dyn={j['air_dyn']:.3f}  "
              f"跨度={j['span_sec']}s  框高={j['h']}px")
    print("\n=== PBP 事件附近（±2s）的动作 ===")
    for e in events:
        jn = [j for j in jumps if abs(j["t"] - e["t"]) <= 2.0]
        cn = [c for c in contests if abs(c["t"] - e["t"]) <= 2.0]
        print(f"  {e['n']} t={e['t']:>6.1f}s {e['player']:<16} {e['kind']:<12} "
              f"跳跃 {len(jn)}  争抢 {len(cn)}")

    with open(a.out_json, "w") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(f"\n[out] {a.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
