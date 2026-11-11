#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战术特征（player-movement 信号，不依赖球权/队色）—— 掩护(screen)候选检测。

纯运动学代理（无 team ID，仅作候选，需队色/球场掩膜后方能确认攻防两侧）：
  · 接触(contact)   = 两名球员框心距离 < D_SCREEN（≈1.4m），逐帧成对
  · 静止成员        = 接触时段内其中一人中位速度 < V_STAT（≈站立设挡）
  · 掩护候选        = 一对球员持续接触 ≥ MIN_FRAMES（≈0.5s），且至少一方近静止
                      （另一方即“利用掩护者”，可能为持球人/空切者）

输出: action_work/tactical_screen.json + reports/milestone_05/tactical_screen.html
用法: tactical_screen.py [--d 132] [--vstat 90] [--min 5] [--gap 2]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
WINS = ["w1", "w2", "w3", "w4"]
DIAG = (1920 ** 2 + 1080 ** 2) ** 0.5
D_DEF = 132.0     # px，≈1.4m（真实掩护身体接触 ~1m，含框宽度略放宽）
V_STAT_DEF = 90.0  # px/s，≈1.14m/s，低于即视为“近静止设挡”
MIN_DEF = 5       # 帧（@10fps≈0.5s，真实掩护持续 0.5–2s）
GAP_DEF = 2       # 帧间隔容忍（遮挡/重识别短暂丢失不切断）


def med5(xs):
    out = []
    for i in range(len(xs)):
        seg = [v for v in xs[max(0, i - 2):i + 3] if v is not None]
        out.append(st.median(seg) if seg else None)
    return out


def load_frames(w):
    """返回 (frames, t0, dt, n, frame_spd)。frames[i] = tr[i]（含 players 列表）。
    frame_spd[i][tid] = 中位平滑后速度(px/s) 或 None。"""
    tr = json.loads((AW / f"{w}_poss_tile" / "ball_tracks.json").read_text())
    pm = json.loads((AW / w / "pose_motion.json").read_text())
    series = pm["series"]
    t0 = min(s["t"] for s in series if s["t"] is not None)
    t1 = max(s["t"] for s in series if s["t"] is not None)
    n = len(tr)
    dt = (t1 - t0) / (n - 1) if n > 1 else 0.1

    traj = {}
    for i, fr in enumerate(tr):
        t = t0 + i * dt
        for p in fr.get("players", []):
            traj.setdefault(p["track_id"], []).append(
                (i, t, (p["bbox"][0] + p["bbox"][2]) / 2.0,
                 (p["bbox"][1] + p["bbox"][3]) / 2.0))
    frame_spd = [dict() for _ in range(n)]
    for tid, pts in traj.items():
        raw = [None] * len(pts)
        for k in range(1, len(pts)):
            gi_prev, t_prev, px_prev, py_prev = pts[k - 1]
            gi_cur, t_cur, px_cur, py_cur = pts[k]
            if gi_cur == gi_prev + 1:
                d = ((px_cur - px_prev) ** 2 + (py_cur - py_prev) ** 2) ** 0.5
                raw[k] = d / (t_cur - t_prev)
        sm = med5(raw)
        for k, (gi, _, _, _) in enumerate(pts):
            frame_spd[gi][tid] = sm[k]
    return tr, t0, dt, n, frame_spd


def window_speed_median(frame_spd, tid, i0, i1):
    vals = [frame_spd[i].get(tid) for i in range(i0, i1 + 1)]
    vals = [v for v in vals if v is not None]
    return st.median(vals) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--d", type=float, default=D_DEF)
    ap.add_argument("--vstat", type=float, default=V_STAT_DEF)
    ap.add_argument("--min", type=int, default=MIN_DEF)
    ap.add_argument("--gap", type=int, default=GAP_DEF)
    ap.add_argument("--out-json", default=str(AW / "tactical_screen.json"))
    ap.add_argument("--out-html", default=str(AW.parent / "reports" / "milestone_05" / "tactical_screen.html"))
    a = ap.parse_args()

    wins = []
    for w in WINS:
        tr, t0, dt, n, frame_spd = load_frames(w)
        contact_pairs = []
        for i, fr in enumerate(tr):
            players = fr.get("players", [])
            pairs = set()
            for aa in range(len(players)):
                for bb in range(aa + 1, len(players)):
                    ax = (players[aa]["bbox"][0] + players[aa]["bbox"][2]) / 2.0
                    ay = (players[aa]["bbox"][1] + players[aa]["bbox"][3]) / 2.0
                    bx = (players[bb]["bbox"][0] + players[bb]["bbox"][2]) / 2.0
                    by = (players[bb]["bbox"][1] + players[bb]["bbox"][3]) / 2.0
                    if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < a.d:
                        pairs.add(tuple(sorted((players[aa]["track_id"], players[bb]["track_id"]))))
            contact_pairs.append(pairs)

        active, done = {}, []
        for i, pairs in enumerate(contact_pairs):
            for pr in pairs:
                if pr in active:
                    active[pr]["end"], active[pr]["gap"] = i, 0
                else:
                    active[pr] = {"pair": pr, "start": i, "end": i, "gap": 0}
            for pr in list(active):
                if pr not in pairs:
                    active[pr]["gap"] += 1
                    if active[pr]["gap"] > a.gap:
                        done.append(active.pop(pr))
        for seg in active.values():
            done.append(seg)

        eps = []
        for seg in done:
            i0, i1 = seg["start"], seg["end"]
            dur = i1 - i0 + 1
            if dur < a.min:
                continue
            ta, tb = seg["pair"]
            sa = window_speed_median(frame_spd, ta, i0, i1)
            sb = window_speed_median(frame_spd, tb, i0, i1)
            if sa is None or sb is None:
                continue
            # 静止成员 = 速度较低者；另一方=利用者
            if sa <= sb:
                screener, user, ss, us = ta, tb, sa, sb
            else:
                screener, user, ss, us = tb, ta, sb, sa
            if ss > a.vstat:
                continue  # 双方都在动 → 非设挡（可能是争抢/包夹），剔除
            eps.append({
                "screener": screener, "user": user,
                "start_t": round(t0 + i0 * dt, 2), "end_t": round(t0 + i1 * dt, 2),
                "dur_frames": dur, "dur_s": round(dur * dt, 2),
                "screener_speed": round(ss, 1), "user_speed": round(us, 1),
            })
        eps.sort(key=lambda e: -e["dur_frames"])
        durs = [e["dur_s"] for e in eps]
        wins.append({
            "name": w, "t0": round(t0, 1), "t1": round(t0 + (n - 1) * dt, 1),
            "n_frames": n, "n_candidates": len(eps),
            "median_dur_s": round(st.median(durs), 2) if durs else None,
            "mean_screener_speed": round(st.mean([e["screener_speed"] for e in eps]), 1) if eps else None,
            "mean_user_speed": round(st.mean([e["user_speed"] for e in eps]), 1) if eps else None,
            "episodes": eps[:12],
        })

    payload = {"d_screen": a.d, "v_stat": a.vstat, "min_frames": a.min,
               "gap_tol": a.gap, "diag": round(DIAG, 1), "windows": wins}
    Path(a.out_json).write_text(json.dumps(payload, indent=1, ensure_ascii=False))

    tbl = ""
    for wd in wins:
        rows = "".join(
            f"<tr><td>{e['screener']}</td><td>{e['user']}</td><td>{e['start_t']}</td>"
            f"<td>{e['end_t']}</td><td>{e['dur_s']}s</td><td>{e['screener_speed']}</td>"
            f"<td>{e['user_speed']}</td></tr>"
            for e in wd["episodes"])
        tbl += f"""<h3>{wd['name']}  (t {wd['t0']:.1f}–{wd['t1']:.1f}s)</h3>
        <p>掩护候选 <b>{wd['n_candidates']}</b> ｜ 中位持续 <b>{wd['median_dur_s']}</b>s
           ｜ 设挡者均速 <b>{wd['mean_screener_speed']}</b>px/s ｜ 利用者均速 <b>{wd['mean_user_speed']}</b>px/s</p>
        <table border="1" style="border-collapse:collapse;font-size:12px;color:#c9d1d9">
          <tr style="background:#161b22"><th>设挡者</th><th>利用者</th><th>起始</th><th>结束</th><th>持续</th><th>设挡速</th><th>利用速</th></tr>
          {rows}</table><br>"""
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>战术特征 · 掩护候选</title></head><body style="background:#010409;color:#c9d1d9;font-family:system-ui,sans-serif;padding:24px">
<h1>战术特征：掩护(screen)候选检测（player-movement 运动学代理）</h1>
<p style="color:#8b949e">占有权线程已裁定弱-阴性。本页用 tracking 100% 召回的运动学信号，不依赖球权/队色。
接触 = 两名球员框心距离 &lt; {a.d:.0f}px(≈{a.d*1.27/100:.1f}m)；静止成员中位速度 &lt; {a.vstat:.0f}px/s；
持续 ≥ {a.min}帧(≈{a.min*0.1:.1f}s) 即记为候选。⚠️ 无 team ID，<b>不能区分攻防两侧</b>——
“设挡/利用”是相对速度划分，确属掩护需队色/球场掩膜确认（可能为低位要位、卡位、包夹）。</p>
<h2>逐窗口 · 掩护候选（top 12，按持续时长）</h2>{tbl}
</body></html>"""
    Path(a.out_html).write_text(html)
    print(f"[写] {a.out_json}\n[写] {a.out_html}")
    for wd in wins:
        print(f"  {wd['name']}: 候选 {wd['n_candidates']}  中位 {wd['median_dur_s']}s  "
              f"设挡速 {wd['mean_screener_speed']}px/s 利用速 {wd['mean_user_speed']}px/s")


if __name__ == "__main__":
    raise SystemExit(main())
