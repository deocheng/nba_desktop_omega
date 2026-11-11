#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「顺畅进攻」挑选器（老程新目标）：从干净比赛窗里挑出流畅的进攻片段，
只做**轨迹层**判定（球员移动 + 球移动），不做战术语义识别/命名（留待后训）。
纪律：球检测这批素材不可靠(conf~0.2、大量跨画面瞬移、真检出率 6.7%~59%)
     ⇒ **顺畅分只基于球员运动**(可靠)，球的质量单独报告，不进分。
指标(每窗)：straightness 运动目的性(净位移/路程,1=有目的,0=抖动)
          coordination 协同性(球员位移方向的平均单位向量长度,1=同向协同)
          stability 追踪稳定性(跨≥70%帧的球员占比)
          activity 活跃度(中位速度,归一化;太低=死球,太高=混乱)
输出：norm_calib/smooth_picks.json + smooth_picks_report.html + 轨迹导出 smooth_tracks/<id>.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
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
OUT = f"{NC}/smooth_tracks"

anch = json.load(open(f"{NC}/orient_anchors.json", encoding="utf-8"))["anchors"]
named = json.load(open(f"{NC}/a_step_named.json", encoding="utf-8"))["clusters"]

def load_segment(seg):
    """tracks.json → (players: tid->[(i,cx,cy)], ball: [dict|None])"""
    tr = json.load(open(f"{SEG}/{seg}/tracks.json", encoding="utf-8"))
    players = defaultdict(lambda: {})
    ball = []
    for i, f in enumerate(tr["frames"]):
        for p in f.get("players", []):
            x0, y0, x1, y1 = p["box"]
            players[p["id"]][i] = ((x0 + x1) / 2, (y0 + y1) / 2)
        b = f.get("ball")
        if isinstance(b, dict) and b.get("box"):
            x0, y0, x1, y1 = b["box"]
            ball.append({"cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                         "conf": b.get("conf"), "pred": b.get("pred")})
        else:
            ball.append(None)
    return dict(players), ball

def score_window(players, ball, i0, i1, mover_net=25.0, mv_min_frames=5, mv_disp=1.5):
    """🔧 篮球语义修正：半场里多数球员本就站着，用「全员中位速度」会误杀真实进攻；
    🔧 再修：只看 net>25px 会把**ID切换瞬移**(一次大跳+其余静止)误当成跑动者
    (实测 #29 以此冲到第一:中位速度0.16px/帧却net>25px)。
    ⇒ mover = 净位移>mover_net **且** 位移>mv_disp 的帧数 ≥ mv_min_frames(持续移动)，
    指标只取这些真实移动帧计算。"""
    n = i1 - i0
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
                     "idx": idx, "disp": disp, "moving": moving,
                     "n_moving": len(moving)})
    movers = [c for c in cand if c["net"] > mover_net and c["n_moving"] >= mv_min_frames]
    if not movers:
        return None
    speeds, straight, spans = [], [], []
    unit_vecs = defaultdict(list)
    for c in movers:
        spans.append(c["spans"]); straight.append(c["straight"])
        for j, (dx, dy) in enumerate(c["disp"]):
            d = math.hypot(dx, dy)
            if d > mv_disp:            # 只取真实移动帧
                speeds.append(d)
                unit_vecs[c["idx"][j]].append((dx / d, dy / d))
    if not speeds:
        return None
    # coordination: 每帧位移单位向量的平均长度(1=同向协同, 0=互相抵消)
    co = []
    for _, vs in unit_vecs.items():
        sx = sum(v[0] for v in vs); sy = sum(v[1] for v in vs)
        co.append(math.hypot(sx, sy) / len(vs))
    med_speed = statistics.median(speeds)
    # 球(仅报告)
    bs = [b for b in ball[i0:i1] if b]
    real = [b for b in bs if not b["pred"]]
    bpts = [(b["cx"], b["cy"]) for b in bs]
    bjump = sum(1 for j in range(len(bpts) - 1)
                if math.hypot(bpts[j + 1][0] - bpts[j][0], bpts[j + 1][1] - bpts[j][1]) > 60)
    return {
        "straightness": round(statistics.median(straight), 3) if straight else 0.0,
        "coordination": round(statistics.median(co), 3) if co else 0.0,
        "stability": round(statistics.median(spans), 3) if spans else 0.0,
        "median_speed_px": round(med_speed, 2),
        "n_movers": len(movers),
        "n_players_seen": len(cand),
        "ball_real_rate": round(len(real) / n, 3),
        "ball_teleports": bjump,
        "ball_coverage": round(len(bs) / n, 3),
    }

def composite(m, ref_speed=6.0):
    """活跃度归一化: 中位速度接近 ref_speed 最好(不僵死也不混乱)"""
    act = m["median_speed_px"] / ref_speed
    act_score = max(0.0, 1.0 - abs(math.log(act + 1e-6))) if act > 0 else 0.0
    act_score = min(1.0, max(0.0, act_score))
    return round(0.35 * m["straightness"] + 0.30 * m["coordination"]
                 + 0.20 * m["stability"] + 0.15 * act_score, 4)

results = []
loaded = {}
for cid_s in sorted(anch, key=lambda x: int(x)):
    a = anch[cid_s]; seg = a["seg"]; s0, s1 = a["start"], a["end"]
    if seg not in loaded:
        loaded[seg] = load_segment(seg)
    players, ball = loaded[seg]
    L = s1 - s0 + 1
    win = min(40, L); step = max(8, win // 3)
    best = None
    for i0 in range(s0, s1 - win + 2, step):
        m = score_window(players, ball, i0, i0 + win)
        if not m:
            continue
        m["smooth_score"] = composite(m)
        if best is None or m["smooth_score"] > best["smooth_score"]:
            best = dict(m); best.update({"win_start": i0, "win_end": i0 + win - 1})
    if best is None:
        m = score_window(players, ball, s0, s1)
        if not m:
            continue
        m["smooth_score"] = composite(m); best = dict(m)
        best.update({"win_start": s0, "win_end": s1})
    nm = named.get(cid_s, {})
    best.update({"cluster": int(cid_s), "seg": seg, "cluster_range": [s0, s1],
                 "ep": seg.split("_")[0],
                 "asr_name": "+".join(g["name"] for g in nm.get("asr_tactic_names", []))})
    results.append(best)

# 🔴 静止门：中位速度 < STATIC_MAX → 球员几乎不动(定格/静态图版)，不是"进攻"，
#    不参与顺畅排名(否则 stability=1.0 会把定格帧托到中游，属指标缺陷)。
STATIC_MIN_MOVERS = 3
for r in results:
    r["static"] = r["n_movers"] < STATIC_MIN_MOVERS
smooth = [r for r in results if not r["static"]]
static = [r for r in results if r["static"]]
smooth.sort(key=lambda r: -r["smooth_score"])
static.sort(key=lambda r: -r["median_speed_px"])
results = smooth + static
for i, r in enumerate(results):
    r["verdict"] = ("顺畅候选" if not r["static"] else "静止/待核查(非进攻)")
json.dump({"note": "顺畅分只基于球员运动(球检测不可靠,单独报告);不含战术语义",
           "picks": results}, open(f"{NC}/smooth_picks.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# 导出轨迹(球员+球)供后续训练 —— 只导顺畅候选(静止的不导)
# 🔴 先清空旧产物：否则上一轮被淘汰的簇(c12/c13/c16/c19/c29 等)会残留,污染语料(数据四性)。
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.endswith(".json"):
        os.remove(os.path.join(OUT, f))
for r in smooth[:8]:
    players, ball = loaded[r["seg"]]
    i0, i1 = r["win_start"], r["win_end"]
    tr = {"pick_id": f"c{r['cluster']}", "seg": r["seg"], "ep": r["ep"],
          "asr_name": r["asr_name"], "win": [i0, i1], "smooth_score": r["smooth_score"],
          "players": {}, "ball": []}
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

# ---- 摘要 ----
print("「顺畅进攻」挑选（球员运动打分；球质量单独报告）\n")
print(f"静止门: 跑动者 < {STATIC_MIN_MOVERS} 人 → 判定定格/非进攻，剔出排名")
print("跑动者 = 净位移>25px 且 位移>1.5px的帧数≥5（持续移动，剔除ID切换瞬移）\n")
print("── 顺畅候选（参与排名）──")
print(f"{'簇':<4}{'段':<10}{'窗':<12}{'顺畅分':<8}{'目的性':<8}{'协同':<7}{'稳定':<7}{'速度':<7}{'跑动者':<7}{'球真检':<8}{'球瞬移'}")
for r in smooth:
    print(f"#{r['cluster']:<3}{r['seg']:<10}{r['win_start']}-{r['win_end']:<7}"
          f"{r['smooth_score']:<8}{r['straightness']:<8}{r['coordination']:<7}"
          f"{r['stability']:<7}{r['median_speed_px']:<7}{r['n_movers']:<7}{r['ball_real_rate']:<8}{r['ball_teleports']}")
print("\n── 静止/待核查（剔出，非进攻运动）──")
print(f"{'簇':<4}{'段':<10}{'窗':<12}{'跑动者':<7}{'速度px/帧':<10}{'稳定':<7}")
for r in static:
    print(f"#{r['cluster']:<3}{r['seg']:<10}{r['win_start']}-{r['win_end']:<7}"
          f"{r['n_movers']:<7}{r['median_speed_px']:<10}{r['stability']:<7}")
print(f"\n[导出] 顺畅候选前8的球员+球轨迹 → {OUT}/")
print("[产物] smooth_picks.json")

# ---- HTML ----
hrows = ""
for r in results:
    st = r["static"]
    cls = "k" if st else ""
    hrows += (f"<tr class='{cls}'><td>#{r['cluster']}</td><td>{r['seg']}</td><td>{r['win_start']}-{r['win_end']}</td>"
              f"<td class=hi>{r['smooth_score']:.3f}</td><td>{r['straightness']:.2f}</td>"
              f"<td>{r['coordination']:.2f}</td><td>{r['stability']:.2f}</td>"
              f"<td>{r['median_speed_px']:.1f}</td>"
              f"<td class={'k' if r['ball_real_rate']<0.3 else ''}>{r['ball_real_rate']:.0%}</td>"
              f"<td class={'k' if r['ball_teleports']>2 else ''}>{r['ball_teleports']}</td>"
              f"<td>{r['verdict']}</td><td>{r['asr_name']}</td></tr>")
html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>顺畅进攻挑选</title><style>
body{{font-family:system-ui,"PingFang SC",sans-serif;background:#0f1115;color:#e6e6e6;padding:20px;margin:0}}
h1{{font-size:18px}}table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px}}
th,td{{border:1px solid #2a2f3a;padding:5px 7px;text-align:left}}
th{{background:#1a1e26;color:#9aa3b2}}.hi{{color:#5fbf7f;font-weight:600}}.k{{color:#e06b6b}}
.note{{font-size:12px;color:#9aa3b2;line-height:1.7;background:#151821;padding:10px;border-radius:6px;margin:8px 0}}
</style></head><body>
<h1>「顺畅进攻」挑选（轨迹层，不含战术语义）</h1>
<div class=note>
<b>口径</b>：只做球员+球的移动标记，<b>不做战术识别/命名</b>（战术名留待后训；此处 ASR 名仅作对照标签）。<br>
<b>为什么顺畅分只用球员运动</b>：这批素材球检测不可靠——真检出率仅 6.7%~59%、conf~0.2、且有 900+px 跨画面瞬移。
故<b>球的质量单独报告（球真检/球瞬移列），不进分</b>。<br>
顺畅分 = 0.35×目的性(净位移/路程) + 0.30×协同性(位移方向一致度) + 0.20×追踪稳定性 + 0.15×活跃度。<br>
🔴 <b>静止门</b>：跑动者 &lt; {STATIC_MIN_MOVERS} 人 ⇒ 判定<b>定格/非进攻</b>，<b>剔出顺畅排名</b>（红行）。
跑动者 = 净位移&gt;25px <b>且</b> 位移&gt;1.5px 的帧数≥5（持续移动）——双条件用于剔除 ID 切换瞬移
（一次大跳其余静止的假跑动）。
</div>
<table><tr><th>簇</th><th>段</th><th>窗口</th><th>顺畅分</th><th>目的性</th><th>协同</th><th>稳定</th>
<th>速度px/帧</th><th>球真检</th><th>球瞬移</th><th>裁定</th><th>ASR名(仅对照)</th></tr>{hrows}</table>
</body></html>"""
open(f"{NC}/smooth_picks_report.html", "w", encoding="utf-8").write(html)
print("[report] smooth_picks_report.html")
