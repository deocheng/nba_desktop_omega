#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「顺畅进攻」挑选器（支持全量比赛窗扩展）
池: --pool a13   = 13 个 A 步簇(orient_anchors.json)
    --pool game20 = 20 个纯比赛窗(pure_game_windows.json, 合并相邻成员段)
老程方向: 只做轨迹层(球员+球移动标记)挑"顺畅进攻"，不做战术语义识别/命名。
纪律: 球检测这批不可靠 ⇒ 顺畅分只基于球员运动，球质量单独报告不进分。
静止门: mover = 净位移>25px 且 位移>1.5px的帧数≥5（持续移动，剔ID切换瞬移）；
       <3 movers 判定格/非进攻，剔出排名。
另载入老程逐簇目视裁定(a_step_verdict.json)并列显示 → 交叉验证本指标。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
import statistics
from collections import defaultdict

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
BASE = f"{ROOT}/action_work"
NC = f"{BASE}/norm_calib"
SEG = f"{BASE}/tactic_notes_batch_full/segments"

ap = argparse.ArgumentParser()
ap.add_argument("--pool", choices=["a13", "game20", "game20_gray", "merged"], default="game20")
ap.add_argument("--top-export", type=int, default=12)
# 🔧 老程复核(2026-10-05)：#11 起始 f0=替补席镜头、#22 起始 f51=过渡特效
# ⇒ 窗口边界会吃进开场包装内容，滑窗起点统一跳过前 N 帧。
ap.add_argument("--skip-start", type=int, default=8)
# 🔧 版本号支持(update_smooth_verdict.py 一键重跑用)：导出目录/JSON/HTML 加后缀(如 _v2)
ap.add_argument("--out-suffix", default="")
# 可选：命令行直接覆盖老程排除清单(默认读 smooth_verdict_laocheng.json)
ap.add_argument("--exclude-clusters", nargs="*", type=int, default=None)
a = ap.parse_args()
OUT = f"{NC}/smooth_tracks_{a.pool}{a.out_suffix}"

def load_segment(seg):
    """players: tid -> {frame:(cx,cy)}; hs: frame->[身高px]; pfn: 每帧同时可见人数。
    🔧 老程判据(2026-10-05)：「还是要看具体有多少人出现在画面中」
    —— 真实半场进攻场上 5v5(画面通常检出 10+ 人)，而特写/局部配合只有几人、替补席/讲解画面分布不同。
    ⚠️ 必须用「每帧同时可见数」，不能用累计 track_id 数（ID 碎片化会虚高到 40+）。"""
    tr = json.load(open(f"{SEG}/{seg}/tracks.json", encoding="utf-8"))
    players, ball = defaultdict(lambda: {}), []
    hs = defaultdict(list)
    pfn = []
    for i, f in enumerate(tr["frames"]):
        pl = f.get("players", [])
        pfn.append(len(pl))
        for p in pl:
            x0, y0, x1, y1 = p["box"]
            players[p["id"]][i] = ((x0 + x1) / 2, (y0 + y1) / 2)
            if p.get("h"):
                hs[i].append(p["h"])
        b = f.get("ball")
        if isinstance(b, dict) and b.get("box"):
            x0, y0, x1, y1 = b["box"]
            ball.append({"cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                         "conf": b.get("conf"), "pred": b.get("pred")})
        else:
            ball.append(None)
    return dict(players), ball, dict(hs), pfn

def score_window(players, ball, i0, i1, mover_net=25.0, mv_min_frames=5, mv_disp=1.5,
                 hs=None, pfn=None):
    n = i1 - i0
    # 老程判据：窗内「每帧同时可见人数」的中位与最小（真实进攻人多且稳定，特写/局部人少）
    med_people = min_people = None
    if pfn:
        seg_pfn = pfn[i0:i1]
        if seg_pfn:
            med_people = round(statistics.median(seg_pfn), 1)
            min_people = min(seg_pfn)
    # 镜头尺度代理：窗内球员框高中位(px)。特写/放大 → h 大；全场远景 → h 小。
    # 用于识别「局部放大/投篮特写」类非正常比赛机位(老程 DISREGARD 的常见理由)。
    scale_h = None
    if hs:
        vals = [h for k in range(i0, i1) for h in hs.get(k, [])]
        if vals:
            scale_h = round(statistics.median(vals), 1)
    cand = []
    for tid, pos in players.items():
        idx = sorted(k for k in pos if i0 <= k < i1)
        if len(idx) < 4:
            continue
        pts = [pos[k] for k in idx]
        disp = [(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1])
                for j in range(len(pts) - 1)]
        path = sum(math.hypot(*d) for d in disp)
        net = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
        moving = [d for d in disp if math.hypot(*d) > mv_disp]
        cand.append({"net": net, "path": path, "spans": len(idx) / n,
                     "straight": min(1.0, net / path) if path > 1e-6 else 0.0,
                     "idx": idx, "disp": disp, "moving": moving, "n_moving": len(moving)})
    movers = [c for c in cand if c["net"] > mover_net and c["n_moving"] >= mv_min_frames]
    if not movers:
        return None
    speeds, straight, spans = [], [], []
    unit_vecs = defaultdict(list)
    for c in movers:
        spans.append(c["spans"]); straight.append(c["straight"])
        for j, (dx, dy) in enumerate(c["disp"]):
            d = math.hypot(dx, dy)
            if d > mv_disp:
                speeds.append(d); unit_vecs[c["idx"][j]].append((dx / d, dy / d))
    if not speeds:
        return None
    co = []
    for _, vs in unit_vecs.items():
        sx = sum(v[0] for v in vs); sy = sum(v[1] for v in vs)
        co.append(math.hypot(sx, sy) / len(vs))
    med_speed = statistics.median(speeds)
    bs = [b for b in ball[i0:i1] if b]
    real = [b for b in bs if not b["pred"]]
    bpts = [(b["cx"], b["cy"]) for b in bs]
    bjump = sum(1 for j in range(len(bpts) - 1)
                if math.hypot(bpts[j + 1][0] - bpts[j][0], bpts[j + 1][1] - bpts[j][1]) > 60)
    return {"straightness": round(statistics.median(straight), 3),
            "coordination": round(statistics.median(co), 3),
            "stability": round(statistics.median(spans), 3),
            "median_speed_px": round(med_speed, 2),
            "camera_scale_h": scale_h,
            "median_people_per_frame": med_people,
            "min_people_per_frame": min_people,
            "n_movers": len(movers), "n_players_seen": len(cand),
            "ball_real_rate": round(len(real) / n, 3), "ball_teleports": bjump,
            "ball_coverage": round(len(bs) / n, 3)}

def composite(m, ref_speed=6.0):
    act = m["median_speed_px"] / ref_speed
    act_score = min(1.0, max(0.0, 1.0 - abs(math.log(act + 1e-6))))
    return round(0.35 * m["straightness"] + 0.30 * m["coordination"]
                 + 0.20 * m["stability"] + 0.15 * act_score, 4)

# ---------- 叙事角色标注（老程 2026-10-06 镜头语言规范）----------
# 🔴 教训：滑窗是**机械按时间**切的，不保证窗在"进攻叙事"里是什么角色。
#    定位再准，按时间切+对接 = 无意义产物（见 reports/milestone_05/镜头语言规范_叙事链剪辑法.md）。
#    一次完整进攻的叙事链 = [起]组织→[承]投篮→[转]抢篮板/转换→[合]转换后进攻→[尾]进球后3s。
#    ⇒ 转折段(transition) 只能作**连接件**，不能当独立训练片段。
# ⚠️ 本函数只用**运动形态**给"待人工确认"的角色提示，不是裁定；
#    角色判定与运动指标无关（运动分不清"比赛进攻 vs 讲解/庆祝"，已证伪），
#    最终由老程目视确认 → 确认后写 smooth_verdict_laocheng.json._narrative_role。
NARRATIVE_ROLES = ("origin", "transition", "result", "unknown")

# 🔴🔴 叙事角色判据 —— **实测证伪，当前不可用作自动分类器**（老程 2026-10-06）
# 真值样本：clips/sas_scrimmage_pick/poss_full_1958.2-1972.4.mp4
#   前5秒 = 老程目视确认「抢下篮板快速到前场」= 由守到攻转换（transition）
# 实测（verify_trans/poss_full_metrics.json，yolov8n + 本函数同口径）：
#     transition: n_mv=30 straight=0.895 coord=0.448 spd=6.57
#     origin    : n_mv=19 straight=0.704 coord=0.387 spd=4.76
#     result    : n_mv=12 straight=0.927 coord=0.826 spd=5.56
# 两条硬结论：
#  ① v1 的 transition 门(coord>=0.90) **方向反了** —— 真实转换的 coord 只有 0.448；
#     高 coordination(0.826) 对应投篮，因为大家朝同一个筐跑方向最一致。
#  ② 改用 straightness 同样**证伪**：转换 0.895 vs 投篮 0.927，投篮更高 ⇒
#     **转换与投篮在运动形态上不可分**（都是"多人直线冲向篮筐"）。
#     语料池 27 窗回放：v1/v2 的 transition 均为 **0**。
# ⇒ 结论：叙事角色**不是运动指标的函数**，靠球员运动分不出"抢篮板转换"与"投篮"，
#   二者唯一差别在**球权/比分语义**，而球检测这批已证不可靠(ball_real_rate 大量为0)。
#   ⇒ 本函数**一律返回 unknown**，角色由老程目视裁定（见规范 §5 待裁两问）。
#   保留下方常量与实测表，仅供后续拿到"球语义"后复用。
TRANS_MIN_MV, TRANS_MIN_STRAIGHT, TRANS_MIN_SPD = 3, 0.85, 6.5   # 收窄到 6.5 才躲开投篮
RESULT_MIN_SPD = 8.0
ORIGIN_MIN_COORD = 0.85
MEASURED_ROLES = {   # 实测标定表（唯一 n=1 的真值锚点）
    "transition": {"n_mv": 30, "straightness": 0.895, "coordination": 0.448, "median_speed_px": 6.57},
    "origin":     {"n_mv": 19, "straightness": 0.704, "coordination": 0.387, "median_speed_px": 4.76},
    "result":     {"n_mv": 12, "straightness": 0.927, "coordination": 0.826, "median_speed_px": 5.56},
}


def narrative_role(m, win_start, win_end, cluster_range):
    """🔴 已证伪 ⇒ **恒返回 unknown**（老程 2026-10-06）。
    真实转换与投篮在球员运动形态上不可分（straight 0.895 vs 0.927，投篮更高），
    区分需要球权/比分语义，而球检测这批不可靠。
    保留函数签名以免调用方报错；待拿到可靠球语义后再启用。"""
    return "unknown"
    return "unknown"

# ---------- 池 ----------
windows = []   # [{cluster, seg, start, end}]
if a.pool == "a13":
    anch = json.load(open(f"{NC}/orient_anchors.json", encoding="utf-8"))["anchors"]
    for cid, v in anch.items():
        windows.append({"cluster": int(cid), "seg": v["seg"], "start": v["start"], "end": v["end"]})
else:
    if a.pool == "merged":
        pg = []
        for src in (f"{NC}/pure_game_windows.json", f"{NC}/pure_game_windows_gray.json"):
            if os.path.exists(src):
                pg += json.load(open(src, encoding="utf-8"))["pure_game"]
    else:
        src = f"{NC}/pure_game_windows_gray.json" if a.pool == "game20_gray" else f"{NC}/pure_game_windows.json"
        pg = json.load(open(src, encoding="utf-8"))["pure_game"]
    for w in pg:
        byseg = defaultdict(list)
        for m in w["members"]:
            byseg[m["seg"]].append((m["start"], m["end"]))
        for seg, ranges in byseg.items():
            ranges.sort()
            m_ = []
            for s0, s1 in ranges:
                if m_ and s0 <= m_[-1][1] + 1:
                    m_[-1][1] = max(m_[-1][1], s1)
                else:
                    m_.append([s0, s1])
            for s0, s1 in m_:
                windows.append({"cluster": w["cluster"], "seg": seg, "start": s0, "end": s1})

# 老程目视裁定
vd = json.load(open(f"{NC}/a_step_verdict.json", encoding="utf-8"))
# 🔴 老程 2026-10-05 目视复核的排除清单：即使机器分高也强制剔出（裁定优先于打分）
LV = json.load(open(f"{NC}/smooth_verdict_laocheng.json", encoding="utf-8"))
EXCLUDE = set(a.exclude_clusters) if a.exclude_clusters else set(LV.get("exclude_clusters", []))
EXCLUDE_REASON = LV.get("_exclude_reason", {})
# 老程复核里带 "verdict" 的簇（如 #17 裁定 KEEP）覆盖原 a_step_verdict
OVERRIDE = {int(k): v for k, v in LV.get("reviews", {}).items() if "verdict" in v}
named = json.load(open(f"{NC}/a_step_named.json", encoding="utf-8")).get("clusters", {})

results, loaded = [], {}
for w in windows:
    seg, s0, s1 = w["seg"], w["start"], w["end"]
    if seg not in loaded:
        loaded[seg] = load_segment(seg)
    players, ball, hs, pfn = loaded[seg]
    L = s1 - s0 + 1
    # 跳过开场包装帧(替补席镜头/过渡特效/标题)，但不让窗口短于 MIN_WIN
    MIN_WIN = 12
    skip = min(int(a.skip_start), max(0, L - MIN_WIN))
    s0e = s0 + skip
    Le = s1 - s0e + 1
    if Le < MIN_WIN:
        s0e, Le = s0, L
    win = min(40, Le); step = max(8, win // 3)
    best = None
    for i0 in range(s0e, s1 - win + 2, step):
        m = score_window(players, ball, i0, i0 + win, hs=hs, pfn=pfn)
        if not m:
            continue
        m["smooth_score"] = composite(m)
        if best is None or m["smooth_score"] > best["smooth_score"]:
            best = dict(m); best.update({"win_start": i0, "win_end": i0 + win - 1})
    if best is not None:
        # 叙事角色提示(不参与评分/筛选，仅供老程目视确认) — 镜头语言规范 2026-10-06
        best["narrative_role"] = narrative_role(best, best["win_start"], best["win_end"],
                                                [s0e, s1])
        best["narrative_role_confirmed"] = False


    if best is None:
        m = score_window(players, ball, s0, s1, hs=hs, pfn=pfn)
        if not m:
            # 🔴 不静默丢弃：无任何有效运动也要留记录，便于老程目视核查。
            seg_pfn = pfn[s0:s1 + 1] if pfn else []
            m = {"straightness": 0.0, "coordination": 0.0, "stability": 0.0,
                 "median_speed_px": 0.0, "n_movers": 0, "n_players_seen": 0,
                 "camera_scale_h": None,
                 "median_people_per_frame": (round(statistics.median(seg_pfn), 1) if seg_pfn else None),
                 "min_people_per_frame": (min(seg_pfn) if seg_pfn else None),
                 "ball_real_rate": 0.0, "ball_teleports": 0, "ball_coverage": 0.0}
        m["smooth_score"] = composite(m); best = dict(m)
        best.update({"win_start": s0, "win_end": s1})
    v = vd.get(str(w["cluster"]), {})
    ov = OVERRIDE.get(w["cluster"])
    if ov:   # 老程复核裁定覆盖
        v = {"verdict": ov["verdict"], "reason": ov.get("confirm", ov.get("issue", ""))}
    best.update({"cluster": w["cluster"], "seg": seg, "cluster_range": [s0, s1],
                 "ep": seg.split("_")[0],
                 "laocheng_verdict": v.get("verdict", "未裁定"),
                 "verdict_reason": v.get("reason", ""),
                 "excluded_by_laocheng": w["cluster"] in EXCLUDE,
                 "exclude_reason": EXCLUDE_REASON.get(str(w["cluster"]), ""),
                 "asr_name": "+".join(g["name"] for g in
                                      named.get(str(w["cluster"]), {}).get("asr_tactic_names", []))})
    results.append(best)

STATIC_MIN_MOVERS = 3
for r in results:
    r["static"] = r["n_movers"] < STATIC_MIN_MOVERS
    # 叙事角色兜底：滑窗全无有效运动(best is None)的窗也必须带角色字段，
    # 否则下游会看到 MISSING —— 缺失比"unknown"更糟(无法区分"没判"与"判不出")
    r.setdefault("narrative_role", "unknown")
    r.setdefault("narrative_role_confirmed", False)
    if r["excluded_by_laocheng"]:
        r["verdict"] = "老程裁定剔出"
    else:
        r["verdict"] = ("顺畅候选" if not r["static"] else "静止/待核查(非进攻)")
# 老程排除清单先切走，剩下再按静止门分
pool = [r for r in results if not r["excluded_by_laocheng"]]
excluded = sorted([r for r in results if r["excluded_by_laocheng"]], key=lambda r: -r["smooth_score"])
smooth = sorted([r for r in pool if not r["static"]], key=lambda r: -r["smooth_score"])
static = sorted([r for r in pool if r["static"]], key=lambda r: -r["n_movers"])

json.dump({"pool": a.pool, "n_windows": len(windows), "skip_start": a.skip_start,
           "note": "顺畅分只基于球员运动(球不可靠,单列报告);老程目视裁定优先于机器分",
           "out_suffix": a.out_suffix,
           "excluded_by_laocheng": excluded, "smooth": smooth, "static": static},
          open(f"{NC}/smooth_picks_{a.pool}{a.out_suffix}.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# 导出轨迹
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.endswith(".json"):
        os.remove(os.path.join(OUT, f))
# 🔴 老程目视裁定优先于机器分：DISREGARD 的窗不进语料(哪怕机器分高)，单列展示。
exportable = [r for r in smooth if r["laocheng_verdict"] != "DISREGARD"]
for r in exportable[:a.top_export]:
    players, ball, hs, pfn = loaded[r["seg"]]
    i0, i1 = r["win_start"], r["win_end"]
    tr = {"pick_id": f"c{r['cluster']}", "seg": r["seg"], "ep": r["ep"],
          "asr_name": r["asr_name"], "win": [i0, i1], "smooth_score": r["smooth_score"],
          "laocheng_verdict": r["laocheng_verdict"], "players": {}, "ball": []}
    for tid, pos in players.items():
        pts = {str(k): [round(pos[k][0], 1), round(pos[k][1], 1)]
               for k in sorted(pos) if i0 <= k <= i1}
        if len(pts) >= 4:
            tr["players"][str(tid)] = pts
    for k in range(i0, i1 + 1):
        b = ball[k] if k < len(ball) else None
        tr["ball"].append(None if b is None else
                          {"xy": [round(b["cx"], 1), round(b["cy"], 1)],
                           "conf": b["conf"], "pred": b["pred"]})
    json.dump(tr, open(f"{OUT}/c{r['cluster']}_{r['seg']}_{i0}-{i1}.json", "w",
                       encoding="utf-8"), ensure_ascii=False)

# ---------- 摘要 ----------
print(f"顺畅进攻挑选 · 池={a.pool}（窗口数={len(windows)}）\n")
print(f"{'簇':<4}{'段':<10}{'窗':<12}{'顺畅分':<8}{'目的':<7}{'协同':<7}{'稳定':<7}{'跑动':<6}{'球真检':<8}{'镜头h':<8}{'人数/帧':<9}{'老程裁定'}")
for r in smooth:
    hh = r.get("camera_scale_h"); mp = r.get("median_people_per_frame")
    print(f"#{r['cluster']:<3}{r['seg']:<10}{r['win_start']}-{r['win_end']:<7}"
          f"{r['smooth_score']:<8}{r['straightness']:<7}{r['coordination']:<7}"
          f"{r['stability']:<7}{r['n_movers']:<6}{r['ball_real_rate']:<8}"
          f"{('—' if hh is None else f'{hh:.0f}'):<8}"
          f"{('—' if mp is None else f'{mp:.0f}'):<9}{r['laocheng_verdict']}")
print(f"\n── 静止/剔出（跑动者<{STATIC_MIN_MOVERS}）──")
for r in static:
    print(f"#{r['cluster']:<3}{r['seg']:<10}{r['win_start']}-{r['win_end']:<7}跑动者={r['n_movers']:<4}{r['laocheng_verdict']}")
print(f"\n── 老程裁定剔出（即使机器分高也不进语料，共 {len(excluded)} 条）──")
for r in excluded:
    print(f"#{r['cluster']:<3}{r['seg']:<10}{r['win_start']}-{r['win_end']:<7}分={r['smooth_score']:.3f} "
          f"跑动者={r['n_movers']}  理由={r['exclude_reason']}")
print(f"\n[导出] 顺畅候选(剔除老程DISREGARD后) 前{len(exportable[:a.top_export])}条 → {OUT}/")
print(f"[说明] 老程目视裁定优先级高于机器分：{len([r for r in smooth if r['laocheng_verdict']=='DISREGARD'])} 个 DISREGARD 窗已剔出不导出")

# 交叉验证：老程 DISREGARD 的簇机器打分如何
dis = [r for r in results if r["laocheng_verdict"] == "DISREGARD"]
if dis:
    print(f"\n[交叉验证] 老程裁定 DISREGARD 的 {len(dis)} 个窗，机器顺畅分：")
    for r in sorted(dis, key=lambda x: -x["smooth_score"]):
        print(f"    #{r['cluster']} {r['seg']} 分={r['smooth_score']:.3f} "
              f"跑动者={r['n_movers']} h={r.get('camera_scale_h')} ({r['verdict']})  理由={r['verdict_reason'][:28]}")
# 镜头尺度 h 对 KEEP / DISREGARD 的分离度
# 老程判据：每帧可见人数 vs KEEP/剔出
pk = [r["median_people_per_frame"] for r in results
      if r["laocheng_verdict"] == "KEEP" and r.get("median_people_per_frame") is not None]
pd_ = [r["median_people_per_frame"] for r in results
       if r.get("excluded_by_laocheng") and r.get("median_people_per_frame") is not None]
if pk and pd_:
    print("\n[人数判据 · 老程『看具体有多少人出现在画面中』]")
    print(f"  KEEP      每帧人数: {min(pk):.0f}~{max(pk):.0f} (中位{statistics.median(pk):.0f}, n={len(pk)})")
    print(f"  老程剔出  每帧人数: {min(pd_):.0f}~{max(pd_):.0f} (中位{statistics.median(pd_):.0f}, n={len(pd_)})")
    for r in sorted([x for x in results if x.get("median_people_per_frame") is not None],
                    key=lambda x: x["median_people_per_frame"]):
        tag = "剔出" if r.get("excluded_by_laocheng") else "KEEP"
        print(f"    #{r['cluster']:<3} 人数={r['median_people_per_frame']:>5.1f} h={r.get('camera_scale_h') or 0:>5.0f} "
              f"{tag}  {r['exclude_reason'][:22]}")

hk = [r["camera_scale_h"] for r in results
      if r["laocheng_verdict"] == "KEEP" and r.get("camera_scale_h")]
hd = [r["camera_scale_h"] for r in results
      if r["laocheng_verdict"] == "DISREGARD" and r.get("camera_scale_h")]
if hk and hd:
    print(f"\n[镜头尺度 h 分离度]  KEEP: {min(hk):.0f}~{max(hk):.0f} (中位{statistics.median(hk):.0f}, n={len(hk)})")
    print(f"                    DISREGARD: {min(hd):.0f}~{max(hd):.0f} (中位{statistics.median(hd):.0f}, n={len(hd)})")
    print("  ⇒ 阈值 h>170 可剔掉全部 DISREGARD，但会误伤老程 KEEP 的 #3(h≈194,篮下中近景确是真实比赛)")

# ---------- HTML ----------
def row(r, cls=""):
    hh = r.get("camera_scale_h"); mp = r.get("median_people_per_frame")
    return (f"<tr class='{cls}'><td>#{r['cluster']}</td><td>{r['seg']}</td><td>{r['win_start']}-{r['win_end']}</td>"
            f"<td class=hi>{r['smooth_score']:.3f}</td><td>{r['straightness']:.2f}</td>"
            f"<td>{r['coordination']:.2f}</td><td>{r['stability']:.2f}</td>"
            f"<td>{r['n_movers']}</td>"
            f"<td class={'k' if r['ball_real_rate']<0.3 else ''}>{r['ball_real_rate']:.0%}</td>"
            f"<td>{'—' if hh is None else f'{hh:.0f}'}</td>"
            f"<td>{'—' if mp is None else f'{mp:.0f}'}</td>"
            f"<td>{r['laocheng_verdict']}</td><td>{r['verdict']}</td><td>{r['asr_name']}</td></tr>")
hrows = ("".join(row(r) for r in smooth) + "".join(row(r, "k") for r in static)
         + "".join(row(r, "x") for r in excluded))
html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>顺畅进攻挑选 · {a.pool}</title><style>
body{{font-family:system-ui,"PingFang SC",sans-serif;background:#0f1115;color:#e6e6e6;padding:20px;margin:0}}
h1{{font-size:18px}}table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px}}
th,td{{border:1px solid #2a2f3a;padding:5px 7px;text-align:left}}
th{{background:#1a1e26;color:#9aa3b2}}.hi{{color:#5fbf7f;font-weight:600}}
tr.k td{{color:#e06b6b}}
tr.x td{{color:#8b7fd1;text-decoration:line-through}}
.note{{font-size:12px;color:#9aa3b2;line-height:1.7;background:#151821;padding:10px;border-radius:6px;margin:8px 0}}
</style></head><body>
<h1>「顺畅进攻」挑选 · 池={a.pool}（{len(windows)} 窗）</h1>
<div class=note>
只做轨迹层(球员+球移动)，<b>不做战术识别/命名</b>。球检测不可靠 ⇒ <b>球不进分</b>，单列「球真检」参考。<br>
顺畅分 = 0.35×目的性 + 0.30×协同性 + 0.20×稳定性 + 0.15×活跃度。
跑动者 = 净位移&gt;25px <b>且</b> 位移&gt;1.5px的帧数≥5（剔 ID 切换瞬移）；&lt;3 人判定格/非进攻（红行剔出）。<br>
<b>「老程裁定」列</b>用于交叉验证：机器打分是否与老程目视判断一致。
</div>
<table><tr><th>簇</th><th>段</th><th>窗口</th><th>顺畅分</th><th>目的</th><th>协同</th><th>稳定</th>
<th>跑动者</th><th>球真检</th><th>镜头h</th><th>人数/帧</th><th>老程裁定</th><th>本轮裁定</th><th>ASR名(对照)</th></tr>{hrows}</table>
<div class=note>🔴 <b>已知局限（交叉验证暴露）</b>：顺畅分只量「球员是否协同移动」，
<b>区分不了半场进攻 vs 场外/局部放大/投篮特写</b>——那些画面里球员照样在动，
故老程 DISREGARD 的窗也被打了中高分（如 #33 场外画面 0.753）。
「镜头h」=窗内球员框高中位(px)，可作机位尺度参考（特写→h 大、远景→h 小），
但<b>单靠它仍不足以替代老程目视裁定</b>。</div>
</body></html>"""
open(f"{NC}/smooth_picks_{a.pool}{a.out_suffix}_report.html", "w", encoding="utf-8").write(html)
print(f"[report] smooth_picks_{a.pool}{a.out_suffix}_report.html")
