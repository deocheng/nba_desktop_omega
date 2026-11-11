#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第 6.5 层：带质量门禁的持球归属与球权转移分析（球为主线）

── 为什么必须重做持球归属 ──────────────────────────────────────────
上一版 `segment_tactics.py` 的球权归属建立在 seg_possession/tracks.json 的球线上，
而那条球线是 **2fps** 的：实测 ball_conf 中位数 = 0.000，
即绝大多数帧的球位置是**线性外推**出来的，不是真检出。

10.2% 的帧间位移 > 150px，且外推链会沿直线**跑出画面**
（实测 x 到 -453.9、y 到 896.3），重捕获时再猛跳回来（单体跳变达 3297.6px）。
在这种球位上谈"谁持球"，等于在噪声上做决策。

── 本层的做法 ──────────────────────────────────────────────────
三层门禁，只保留可信球位：
  ① `pred == False`      —— 必须是真检出，排除外推
  ② `conf >= 阈值`        —— 置信度下限（默认 0.10）
  ③ 球心在画面内          —— 排除外推跑出画面的位置

对每个 **2fps 球员帧**，在 ±0.25s 邻域内找最近的可信球位；
找不到就判"无证据"，**不猜**（这一帧计入 unknown，不计入归属）。

持球人判定：`dist_norm = |球心 - 脚点| / 框高 < 1.2`，取最近者。
（1.2 倍身高的半径 ≈ 持球/紧贴防守的合理范围）

球权转移：门禁后的持球序列上做去抖——同一持球人连续 >= `--debounce` 帧才认账，
用于剔除"球在两人之间抖"造成的假转移。

── 输入 / 输出 ─────────────────────────────────────────────────
in : seg_hi/ball_hi.json        （10fps 球专线）
     seg_possession/select_tracks.json （2fps 球员遴选+追踪）
     seg_possession/relations.json     （关系三元组，用于弱证据层）
out: <outdir>/possession_gated.json
"""
import argparse
import json
import math
import os
import statistics
from collections import Counter, defaultdict

IMG_W, IMG_H = 1920, 1080


# ─────────────────────────── 载入 ───────────────────────────
def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ball_ok(b, conf_thr, vmap=None):
    """球位门禁。

    ⚠️ 关键修正（2026-09-23 实测）：**conf 不能当门禁**。
    对 333 个真检出做颜色/形状复核后发现，conf 区分"真球 vs 非球"的
    AUC 仅 0.522（0.5 = 无区分力）——真球 conf 中位 0.208、非球 0.215，
    假球反而略高。所以必须改用**颜色判据**（篮球是橙色圆形）：
    `vmap` 由 `verify_ball_detections.py` 产出，只放行 verdict=ball_like 的帧。
    """
    if b.get("pred"):
        return False
    c = b.get("center")
    if not c:
        return False
    if not (0 <= c[0] <= IMG_W and 0 <= c[1] <= IMG_H):
        return False
    if vmap is not None:
        return vmap.get(round(b["t"], 2)) == "ball_like"
    return b.get("conf", 0.0) >= conf_thr


def player_frame(sel, idx):
    """取 2fps 第 idx 帧的球员（含 foot / h）。"""
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
        out.append({"pid": p["pid"], "foot": foot, "h": h,
                    "conf": p.get("conf", 0.0), "box": p.get("box")})
    return out


# ─────────────────────── 持球归属 ───────────────────────
def attribute(players, ball_pt, thresh=1.2):
    if not players or not ball_pt:
        return None, None
    best, bd = None, 1e9
    for p in players:
        h = max(p["h"], 1.0)
        d = math.hypot(ball_pt[0] - p["foot"][0], ball_pt[1] - p["foot"][1]) / h
        if d < bd:
            bd, best = d, p
    if best is None or bd >= thresh:
        return None, bd
    return best["pid"], bd


def build_timeline(sel, ball, conf_thr, win=0.25, thresh=1.2, vmap=None):
    """逐 2fps 帧做门禁持球归属。"""
    rows = []
    for i, fr in enumerate(sel["frames"]):
        t = fr["t"]
        near = [b for b in ball if abs(b["t"] - t) <= win]
        valid = [b for b in near if ball_ok(b, conf_thr, vmap)]
        if not valid:
            # 无可信球位 → 无证据
            rows.append({"idx": i, "t": t, "holder": None, "dist": None,
                         "ball_conf": None, "ball_pt": None,
                         "evidence": "none", "n_ball_near": len(near)})
            continue
        b = min(valid, key=lambda x: abs(x["t"] - t))
        pool = player_frame(sel, i)
        pid, d = attribute(pool, b["center"], thresh)
        rows.append({"idx": i, "t": t, "holder": pid,
                     "dist": round(d, 3) if d is not None else None,
                     "ball_conf": round(b.get("conf", 0.0), 3),
                     "ball_pt": [round(b["center"][0], 1), round(b["center"][1], 1)],
                     "evidence": "detected",
                     "n_ball_near": len(near), "n_valid": len(valid),
                     "n_players": len(pool)})
    return rows


# ─────────────────── 球权转移（去抖） ───────────────────
def transfers(rows, debounce):
    """同一持球人连续 >= debounce 帧才认账；unknown 中断当前段但不产生转移。"""
    ev, cur, run = [], None, []
    for r in rows:
        h = r["holder"]
        if h is None:
            run = []          # 证据中断，段结束但不结算转移
            cur = None
            continue
        if h == cur:
            run.append(r)
        else:
            if cur is not None and len(run) >= debounce:
                ev.append({"pid": cur, "start_idx": run[0]["idx"],
                           "end_idx": run[-1]["idx"],
                           "start_t": run[0]["t"], "end_t": run[-1]["t"],
                           "n": len(run), "dur_sec": round(run[-1]["t"] - run[0]["t"] + 0.5, 1),
                           "mean_conf": round(statistics.mean([x["ball_conf"] for x in run]), 3),
                           "mean_dist": round(statistics.mean([x["dist"] for x in run]), 3)})
            cur, run = h, [r]
    if cur is not None and len(run) >= debounce:
        ev.append({"pid": cur, "start_idx": run[0]["idx"], "end_idx": run[-1]["idx"],
                   "start_t": run[0]["t"], "end_t": run[-1]["t"], "n": len(run),
                   "dur_sec": round(run[-1]["t"] - run[0]["t"] + 0.5, 1),
                   "mean_conf": round(statistics.mean([x["ball_conf"] for x in run]), 3),
                   "mean_dist": round(statistics.mean([x["dist"] for x in run]), 3)})
    return ev


def grade_span(s):
    """持球段置信分级：证据强度直接由『球检出的平均置信度 × 持续帧数』决定。"""
    c, n = s["mean_conf"], s["n"]
    if c >= 0.25 and n >= 4:
        return "strong"
    if c >= 0.15 and n >= 2:
        return "medium"
    return "weak"


def link_transfers(holds):
    """相邻两段持球 → 事件。

    关键区分：`from == to` 说明持球人没变、只是中间证据断了又续上，
    这是**续持（resume）**，不是球权转移（transfer）。两者必须分开计，
    否则转移次数会被"证据空洞"虚增。
    """
    out = []
    for a, b in zip(holds, holds[1:]):
        same = a["pid"] == b["pid"]
        out.append({"t": b["start_t"], "from": a["pid"], "to": b["pid"],
                    "kind": "resume" if same else "transfer",
                    "from_end_idx": a["end_idx"], "to_start_idx": b["start_idx"],
                    "gap_sec": round(b["start_t"] - a["end_t"], 1),
                    "from_dur": a["dur_sec"], "to_dur": b["dur_sec"],
                    "from_conf": a["mean_conf"], "to_conf": b["mean_conf"]})
    return out


def merged_possessions(holds, max_gap=6.0):
    """把『同一持球人、被证据空洞打断』的相邻段并成一个**控球期**。

    这是球为主线叙事的基本单位：读者关心的是"谁控了多久"，
    而不是"模型在哪些秒恰好检到了球"。
    """
    out, cur = [], []
    for s in holds:
        if cur and (s["pid"] != cur[-1]["pid"]
                    or s["start_t"] - cur[-1]["end_t"] > max_gap):
            out.append(cur)
            cur = []
        cur.append(s)
    if cur:
        out.append(cur)
    res = []
    for i, grp in enumerate(out):
        confs = [g["mean_conf"] for g in grp]
        n_ev = sum(g["n"] for g in grp)
        grades = [g["grade"] for g in grp]
        g = "strong" if "strong" in grades and n_ev >= 4 else (
            "medium" if "medium" in grades else "weak")
        res.append({
            "seq": i + 1, "pid": grp[0]["pid"],
            "start_t": grp[0]["start_t"], "end_t": grp[-1]["end_t"],
            "dur_sec": round(grp[-1]["end_t"] - grp[0]["start_t"] + 0.5, 1),
            "n_spans": len(grp), "n_evidence_frames": n_ev,
            "mean_conf": round(statistics.mean(confs), 3),
            "best_conf": round(max(confs), 3),
            "grade": g,
        })
    return res


def phases(holds, max_gap=6.0):
    """把时间上相邻（间隔 <= max_gap 秒）的持球段聚成一个宏观回合。

    注意：这只是**基于时间的粗聚簇**，不是真正的回合切分——
    真正的回合边界需要出手/失误判定（本层未实现）。
    """
    out, cur = [], []
    for s in holds:
        if cur and s["start_t"] - cur[-1]["end_t"] > max_gap:
            out.append(cur)
            cur = []
        cur.append(s)
    if cur:
        out.append(cur)
    res = []
    for i, grp in enumerate(out):
        chain = [g["pid"] for g in grp]
        res.append({
            "phase": i + 1,
            "start_t": grp[0]["start_t"], "end_t": grp[-1]["end_t"],
            "dur_sec": round(grp[-1]["end_t"] - grp[0]["start_t"] + 1.0, 1),
            "n_spans": len(grp), "holder_chain": chain,
            "n_handoffs": sum(1 for a, b in zip(chain, chain[1:]) if a != b),
            "grades": [grade_span(g) for g in grp],
        })
    return res


# ─────────────── 转移窗口内的球员位移（相关球员位置变化） ───────────────
def foot_map(sel):
    m = defaultdict(dict)          # pid -> {idx: (fx, fy, h)}
    for i, fr in enumerate(sel["frames"]):
        for p in player_frame(sel, i):
            m[p["pid"]][i] = (p["foot"][0], p["foot"][1], p["h"])
    return m


def window_motion(fm, t_center, t0, t1, sel, win=1.5):
    """转移时刻 ±win 秒内各球员位移（画面比例归一）。"""
    idx_of = {round(fr["t"], 1): i for i, fr in enumerate(sel["frames"])}
    i0 = min([i for t, i in idx_of.items() if t >= t_center - win] or [0])
    i1 = max([i for t, i in idx_of.items() if t <= t_center + win] or [len(sel["frames"]) - 1])
    med_h = statistics.median([p["h"] for p in player_frame(sel, i0)]) if player_frame(sel, i0) else 180.0
    res = []
    for pid, pts in fm.items():
        keys = sorted(k for k in pts if i0 <= k <= i1)
        if len(keys) < 2:
            continue
        a, b = pts[keys[0]], pts[keys[-1]]
        d = math.hypot(b[0] - a[0], b[1] - a[1]) / max(med_h, 1.0)
        res.append({"pid": pid, "frames": len(keys),
                    "disp_norm": round(d, 3),
                    "dir": "→" if b[0] > a[0] else "←"})
    res.sort(key=lambda x: -x["disp_norm"])
    return {"i0": i0, "i1": i1, "med_h": round(med_h, 1), "movers": res}


# ─────────────────── 近邻结构（其他人行动·几何层） ───────────────────
def structure(sel, rows, cluster_dist=1.3):
    out = []
    near_idx = [i for i, r in enumerate(rows) if r["holder"] is not None]
    for i in near_idx:
        ps = player_frame(sel, i)
        if len(ps) < 2:
            out.append({"idx": i, "t": sel["frames"][i]["t"], "n_near_pairs": 0,
                        "near_pairs": [], "min_dist": None})
            continue
        med_h = statistics.median([p["h"] for p in ps])
        pairs = []
        for a in range(len(ps)):
            for b in range(a + 1, len(ps)):
                pa, pb = ps[a], ps[b]
                d = math.hypot(pa["foot"][0] - pb["foot"][0],
                               pa["foot"][1] - pb["foot"][1]) / max(med_h, 1.0)
                if d <= cluster_dist:
                    pairs.append({"a": pa["pid"], "b": pb["pid"], "d": round(d, 3)})
        pairs.sort(key=lambda x: x["d"])
        out.append({"idx": i, "t": sel["frames"][i]["t"],
                    "n_near_pairs": len(pairs), "near_pairs": pairs[:8],
                    "min_dist": pairs[0]["d"] if pairs else None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ball-hi", required=True)
    ap.add_argument("--sel", required=True)
    ap.add_argument("--relations", default=None)
    ap.add_argument("--ball-verify", default=None,
                    help="ball_verify.json；给了就用颜色/形状门禁替代 conf 门禁")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--conf-thr", type=float, default=0.10)
    ap.add_argument("--win", type=float, default=0.25)
    ap.add_argument("--thresh", type=float, default=1.2)
    ap.add_argument("--debounce", type=int, default=2)
    ap.add_argument("--cluster-dist", type=float, default=1.3)
    ap.add_argument("--max-gap", type=float, default=6.0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    ball = load(a.ball_hi)["ball_track"]
    sel = load(a.sel)
    rel = load(a.relations) if a.relations and os.path.exists(a.relations) else None

    # ---- 颜色/形状复核表（可选，但强烈建议；conf 已被证明无区分力）----
    vmap = None
    vmeta = None
    if a.ball_verify and os.path.exists(a.ball_verify):
        vb = load(a.ball_verify)
        vmeta = vb.get("meta")
        vmap = {round(r["t"], 2): r.get("verdict")
                for r in vb["rows"] if not r.get("pred")}

    # ---- 门禁统计 ----
    n_ok = sum(1 for b in ball if ball_ok(b, a.conf_thr, vmap))
    n_det = sum(1 for b in ball if not b.get("pred"))
    n_inframe = sum(1 for b in ball if not b.get("pred") and b.get("center")
                    and (0 <= b["center"][0] <= IMG_W and 0 <= b["center"][1] <= IMG_H))
    gate = {
        "ball_frames_total": len(ball),
        "ball_detected": n_det,
        "ball_detected_and_inframe": n_inframe,
        "ball_passed_gate": n_ok,
        "ball_pass_rate_pct": round(n_ok / len(ball) * 100, 1),
        "gate_mode": "color_shape(ball_like)" if vmap is not None else f"conf>={a.conf_thr}",
        "reason_rejected": {
            "extrapolated(pred=True)": len(ball) - n_det,
            "off_screen_or_nocenter": n_det - n_inframe,
            "failed_color_shape": n_inframe - n_ok if vmap is not None
            else sum(1 for b in ball if not b.get("pred") and b.get("center")
                     and (0 <= b["center"][0] <= IMG_W and 0 <= b["center"][1] <= IMG_H)
                     and b.get("conf", 0) < a.conf_thr),
        },
        "ball_verify_meta": vmeta,
    }

    rows = build_timeline(sel, ball, a.conf_thr, a.win, a.thresh, vmap)
    holds = transfers(rows, a.debounce)
    for s in holds:
        s["grade"] = grade_span(s)
    trs = link_transfers(holds)
    real = [t for t in trs if t["kind"] == "transfer"]
    resu = [t for t in trs if t["kind"] == "resume"]
    ph = phases(holds, a.max_gap)
    mrg = merged_possessions(holds, a.max_gap)

    fm = foot_map(sel)
    for tr in trs:
        tr["motion"] = window_motion(fm, tr["t"], None, None, sel)

    st = structure(sel, rows, a.cluster_dist)

    have = [r for r in rows if r["holder"] is not None]
    coverage = len(have) / len(rows) if rows else 0.0

    # 关系弱证据层
    weak = None
    if rel:
        segs = rel.get("segments") or []
        pc = Counter()
        for s in segs:
            pc[s.get("pred")] += s.get("n_frames", 0)
        weak = {"n_segments": len(segs),
                "predicate_frames": dict(pc.most_common(12))}

    out = {
        "meta": {
            "n_player_frames": len(rows),
            "holder_coverage": round(coverage, 3),
            "n_holder_frames": len(have),
            "n_unknown_frames": len(rows) - len(have),
            "n_possession_spans": len(holds),
            "n_merged_possessions": len(mrg),
            "n_events": len(trs),
            "n_transfers": len(real),
            "n_resumes": len(resu),
            "n_phases": len(ph),
            "span_grades": dict(Counter(s["grade"] for s in holds)),
            "debounce_frames": a.debounce,
            "holder_radius_norm": a.thresh,
            "neighbor_window_sec": a.win,
            "cluster_dist": a.cluster_dist,
            "max_gap_sec": a.max_gap,
            "note": ("门禁只保留『真检出 + 置信度达标 + 画面内』的球位；"
                     "无证据帧计入 unknown，不做猜测。"
                     "transfer=持球人真变了；resume=同一人、中间证据断了又续。"),
        },
        "ball_gate": gate,
        "timeline": rows,
        "spans": holds,
        "merged": mrg,
        "events": trs,
        "transfers": real,
        "resumes": resu,
        "phases": ph,
        "structure": st,
        "relations_weak": weak,
    }
    p = os.path.join(a.outdir, "possession_gated.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # ---- 控制台报告 ----
    print(f"[门禁] 模式={gate['gate_mode']}")
    print(f"        球帧 {gate['ball_frames_total']} → 通过 {n_ok} ({gate['ball_pass_rate_pct']}%)")
    print(f"        排除：外推 {gate['reason_rejected']['extrapolated(pred=True)']}"
          f" / 出画或无心 {gate['reason_rejected']['off_screen_or_nocenter']}"
          f" / 颜色形状不过 {gate['reason_rejected']['failed_color_shape']}")
    print(f"[持球] 覆盖 {coverage*100:.1f}% ({len(have)}/{len(rows)} 帧)"
          f" | unknown {len(rows)-len(have)} 帧")
    print(f"[持球段] {len(holds)} 段（去抖 >= {a.debounce} 帧）"
          f" | 分级 {dict(Counter(s['grade'] for s in holds))}")
    print(f"[控球期] 合并同人相邻段 → {len(mrg)} 个控球期")
    print(f"[球权] 真转移 {len(real)} 次 | 续持 {len(resu)} 次 | 宏观回合 {len(ph)} 个")
    print()
    print("[控球期 · 球为主线]")
    gsym = {"strong": "★★★", "medium": "★★ ", "weak": "★  "}
    for m in mrg:
        gap_txt = f"{m['n_spans']}段/{m['n_evidence_frames']}证据帧" if m["n_spans"] > 1 else f"{m['n_evidence_frames']}证据帧"
        print(f"   {gsym[m['grade']]} {m['seq']:>2}. pid{m['pid']:<3}"
              f" t={m['start_t']:>6.1f}~{m['end_t']:>6.1f}"
              f"  时长 {m['dur_sec']:>4.1f}s  {gap_txt}"
              f"  conf 均{m['mean_conf']:.3f}/峰{m['best_conf']:.3f}")
    print()
    print("[原始持球段（保留证据粒度）]")
    for s in holds:
        print(f"   {gsym[s['grade']]} t={s['start_t']:>6.1f}~{s['end_t']:>6.1f}"
              f" ({s['dur_sec']:>4.1f}s, {s['n']:>2}帧)"
              f"  pid{s['pid']:<3} ball_conf={s['mean_conf']:.3f} dist={s['mean_dist']:.2f}")
    print()
    print("[宏观回合（按时间粗聚簇，非真实回合边界）]")
    for phx in ph:
        chain = " → ".join(f"pid{x}" for x in phx["holder_chain"])
        print(f"   回合{phx['phase']}  t={phx['start_t']:.1f}~{phx['end_t']:.1f} ({phx['dur_sec']}s)"
              f"  交接 {phx['n_handoffs']} 次  |  {chain}")
    print()
    print(f"[球权转移]（真转移 {len(real)} 次；resume 已单列，不计入）")
    for i, t in enumerate(real):
        mv = t["motion"]["movers"][:3]
        mvs = "  ".join(f"pid{m['pid']}:{m['disp_norm']:.2f}{m['dir']}" for m in mv)
        print(f"   {i+1:>2}. t={t['t']:>6.1f}  {t['from']} → {t['to']}"
              f"  gap={t['gap_sec']:>4.1f}s  | 位移 top3: {mvs}")
    if resu:
        print("   [resume] " + "  ".join(f"t={t['t']:.1f} pid{t['from']}(未变)" for t in resu))
    print()
    print(f"[结构] 有效帧 {len(st)} | 近邻对中位 "
          f"{statistics.median([s['n_near_pairs'] for s in st]) if st else 0}")
    print(f"\n[out] {p}")


if __name__ == "__main__":
    main()
