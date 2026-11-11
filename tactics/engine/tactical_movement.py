#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战术特征（player-movement 信号，不依赖球权验证）—— 速度/空切 + 全场 spacing。

素材 tracking 100% 召回、BotSort persist（本片段 cuts=0，ID 段内稳定）。
纯运动学，无需 team ID：
  · 球员速度      = 框心相邻帧位移 / dt，滚动中位(窗5)去 ID 抖动
  · 空切(cutter)  = 速度 > CUT_THRESH(px/s) 的帧（无球球员的高速移动）
  · 全场 spacing  = 每帧所有球员两两距离均值（阵型松紧代理）
  · off-ball 流动 = 非持球球员的均速（无球侧活跃度）

持球者沿用 tactical_pressure 的 pad=0.5 松端定义（仅用于划分 on/off-ball）。
输出: action_work/tactical_movement.json + reports/milestone_05/tactical_movement.html
用法: tactical_movement.py [--cut 250]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import statistics as st
from pathlib import Path

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
WINS = ["w1", "w2", "w3", "w4"]
DIAG = (1920 ** 2 + 1080 ** 2) ** 0.5
PAD = 0.5
CUT_DEF = 250.0  # px/s，约 jog/sprint 边界（court 2203px≈28m → 1px≈1.27cm）


def handler_id(fr, pad):
    b = fr.get("ball")
    if not (b and "bbox" in b):
        return None
    bx = (b["bbox"][0] + b["bbox"][2]) / 2.0
    by = (b["bbox"][1] + b["bbox"][3]) / 2.0
    for p in fr.get("players", []):
        x1, y1, x2, y2 = p["bbox"]
        w, h = x2 - x1, y2 - y1
        x1 -= pad * w; x2 += pad * w; y1 -= pad * h; y2 += pad * h
        if x1 <= bx <= x2 and y1 <= by <= y2:
            return p["track_id"]
    return None


def med5(xs):
    out = []
    for i in range(len(xs)):
        seg = [v for v in xs[max(0, i - 2):i + 3] if v is not None]
        out.append(st.median(seg) if seg else None)
    return out


POSS_SUFFIX = "_poss_tile"   # A4.19：可切 "_poss_tile_fp"（FP 过滤后的占有权层）


def load_window(w, cut):
    tr = json.loads((AW / f"{w}{POSS_SUFFIX}" / "ball_tracks.json").read_text())
    pm = json.loads((AW / w / "pose_motion.json").read_text())
    series = pm["series"]
    t0 = min(s["t"] for s in series if s["t"] is not None)
    t1 = max(s["t"] for s in series if s["t"] is not None)
    n = len(tr)
    dt = (t1 - t0) / (n - 1) if n > 1 else 0.1
    evs = [{"t": e["t"], "clock": e.get("clock"), "player": e.get("player"),
            "kind": e.get("kind")} for e in pm.get("events", [])]

    # 框心轨迹（按 track_id），记录全局帧序 gi
    traj = {}  # tid -> [(gi, t, cx, cy)]
    for i, fr in enumerate(tr):
        t = t0 + i * dt
        for p in fr.get("players", []):
            traj.setdefault(p["track_id"], []).append(
                (i, t, (p["bbox"][0] + p["bbox"][2]) / 2.0,
                 (p["bbox"][1] + p["bbox"][3]) / 2.0))

    # 速度（px/s）+ 滚动中位平滑，对齐到全局帧索引
    frame_spd = [dict() for _ in range(n)]  # frame_spd[i][tid] = spd|None
    cut_frames = {}  # tid -> int
    for tid, pts in traj.items():
        raw = [None] * len(pts)
        for k in range(1, len(pts)):
            gi_prev, t_prev, px_prev, py_prev = pts[k - 1]
            gi_cur, t_cur, px_cur, py_cur = pts[k]
            if gi_cur == gi_prev + 1:  # 仅相邻帧算速度，跳过遮挡/重识别间隔
                d = ((px_cur - px_prev) ** 2 + (py_cur - py_prev) ** 2) ** 0.5
                raw[k] = d / (t_cur - t_prev)
        sm = med5(raw)
        cut_frames[tid] = sum(1 for s in sm if s is not None and s > cut)
        for k, (gi, _, _, _) in enumerate(pts):
            frame_spd[gi][tid] = sm[k]

    # 逐帧：持球者 / spacing / off-ball 均速
    spacing_rows, offball_rows = [], []
    per_frame_handler = [handler_id(fr, PAD) for fr in tr]
    for i, fr in enumerate(tr):
        players = fr.get("players", [])
        if len(players) >= 2:
            ds = []
            for a in range(len(players)):
                for b in range(a + 1, len(players)):
                    ax = (players[a]["bbox"][0] + players[a]["bbox"][2]) / 2.0
                    ay = (players[a]["bbox"][1] + players[a]["bbox"][3]) / 2.0
                    bx = (players[b]["bbox"][0] + players[b]["bbox"][2]) / 2.0
                    by = (players[b]["bbox"][1] + players[b]["bbox"][3]) / 2.0
                    ds.append(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)
            spacing_rows.append((t0 + i * dt, st.mean(ds)))
        hid = per_frame_handler[i]
        off = []
        for p in players:
            if p["track_id"] == hid:
                continue
            s = frame_spd[i].get(p["track_id"])
            if s is not None:
                off.append(s)
        offball_rows.append((t0 + i * dt, st.mean(off) if off else None))

    # 逐球员速度汇总（从 frame_spd 聚合）
    track_spd = {}
    for fd in frame_spd:
        for tid, v in fd.items():
            if v is not None:
                track_spd.setdefault(tid, []).append(v)

    # 逐球员汇总
    players_summary = []
    for tid, pts in traj.items():
        sp = track_spd.get(tid, [])
        if not sp:
            continue
        players_summary.append({
            "track_id": tid, "n_frames": len(pts),
            "mean_speed": round(st.mean(sp), 1),
            "peak_speed": round(max(sp), 1),
            "cut_frames": cut_frames[tid],
            "cut_pct": round(100 * cut_frames[tid] / len(pts), 1),
        })
    players_summary.sort(key=lambda d: -d["cut_frames"])

    return {
        "name": w, "t0": round(t0, 1), "t1": round(t1, 1), "n_frames": n,
        "dt": round(dt, 3), "cut_thresh": cut,
        "mean_spacing": round(st.mean([d for _, d in spacing_rows]), 1) if spacing_rows else None,
        "mean_offball": round(st.mean([d for _, d in offball_rows if d is not None]), 1) if offball_rows else None,
        "players": players_summary,
        "spacing": [(round(t, 2), round(d, 1)) for t, d in spacing_rows],
        "offball": [(round(t, 2), round(d, 1) if d is not None else None) for t, d in offball_rows],
        "events": evs,
    }


def build_svg(series, key, color, label, events=None):
    pts = [(t, v) for wd in series for t, v in wd[key] if v is not None]
    if not pts:
        return ""
    tmin = min(p[0] for p in pts); tmax = max(p[0] for p in pts)
    vmax = max(p[1] for p in pts)
    W, H = 920, 240
    pl, pr, pt, pb = 50, 20, 20, 30
    X = lambda t: pl + (t - tmin) / (tmax - tmin + 1e-9) * (W - pl - pr)
    Y = lambda v: H - pb - v / (vmax + 1e-9) * (H - pt - pb)
    svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="background:#0d1117">']
    svg.append(f'<line x1="{pl}" y1="{H-pb}" x2="{W-pr}" y2="{H-pb}" stroke="#30363d"/>')
    svg.append(f'<line x1="{pl}" y1="{pt}" x2="{pl}" y2="{H-pb}" stroke="#30363d"/>')
    svg.append(f'<text x="{pl}" y="{pt-6}" fill="#8b949e" font-size="12">{label} (max {vmax:.0f})</text>')
    # PBP 事件标记（紫色虚线）
    for e in (events or []):
        x = X(e["t"])
        svg.append(f'<line x1="{x:.1f}" y1="{pt}" x2="{x:.1f}" y2="{H-pb}" stroke="#6e40c9" stroke-dasharray="3 3" opacity="0.6"/>')
        svg.append(f'<text x="{x:.1f}" y="{H-pb+16}" fill="#a371f7" font-size="9" transform="rotate(45 {x:.1f} {H-pb+16})">{(e.get("kind") or "")[-6:]}</text>')
    pal = ["#58a6ff", "#3fb950", "#f0883e", "#db61a2", "#e3b341", "#ff7b72", "#a371f7", "#39c5cf"]
    for k, wd in enumerate(series):
        seg = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in wd[key] if v is not None)
        # 原按窗口名硬取色 ⇒ 新片段名(sas_*)会 KeyError；改为有名则映射、无名则用调色板轮转
        c = {"w1": "#58a6ff", "w2": "#3fb950", "w3": "#f0883e", "w4": "#db61a2"}.get(
            wd["name"], pal[k % len(pal)])
        svg.append(f'<polyline points="{seg}" fill="none" stroke="{c}" stroke-width="1.1" opacity="0.85"/>')
    svg.append('</svg>')
    return "\n".join(svg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut", type=float, default=CUT_DEF)
    ap.add_argument("--windows", nargs="*", default=WINS,
                    help="窗口/片段名（默认 w1..w4；可传 sas_hou 等已具备 *_poss_tile 的片段）")
    ap.add_argument("--out-json", default=str(AW / "tactical_movement.json"))
    ap.add_argument("--out-html", default=str(AW.parent / "reports" / "milestone_05" / "tactical_movement.html"))
    ap.add_argument("--poss-suffix", default="_poss_tile",
                    help="占有权层目录后缀；A4.19 FP 过滤后用 _poss_tile_fp")
    a = ap.parse_args()

    global POSS_SUFFIX
    POSS_SUFFIX = a.poss_suffix

    wins = [load_window(w, a.cut) for w in a.windows]
    payload = {"cut_thresh": a.cut, "diag": round(DIAG, 1), "poss_suffix": POSS_SUFFIX,
               "windows": wins}
    Path(a.out_json).write_text(json.dumps(payload, indent=1, ensure_ascii=False))

    all_events = [e for wd in wins for e in wd["events"]]
    svg_space = build_svg(wins, "spacing", "#58a6ff", "全场 spacing (px，越大=阵型越散)", all_events)
    svg_off = build_svg(wins, "offball", "#3fb950", "off-ball 均速 (px/s，无球侧活跃度)", all_events)

    tbl = ""
    for wd in wins:
        rows = "".join(
            f"<tr><td>{p['track_id']}</td><td>{p['n_frames']}</td><td>{p['mean_speed']}</td>"
            f"<td>{p['peak_speed']}</td><td>{p['cut_frames']}</td><td>{p['cut_pct']}%</td></tr>"
            for p in wd["players"][:8])
        tbl += f"""<h3>{wd['name']}  (t {wd['t0']:.1f}–{wd['t1']:.1f}s)</h3>
        <p>均值 spacing <b>{wd['mean_spacing']}</b>px ｜ 均值 off-ball 速度 <b>{wd['mean_offball']}</b>px/s
           ｜ 空切阈值 {wd['cut_thresh']:.0f}px/s</p>
        <table border="1" style="border-collapse:collapse;font-size:12px;color:#c9d1d9">
          <tr style="background:#161b22"><th>track_id</th><th>帧数</th><th>均速</th><th>峰值速</th><th>空切帧</th><th>空切%</th></tr>
          {rows}</table><br>"""
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>战术特征 · 速度/空切 + spacing</title></head><body style="background:#010409;color:#c9d1d9;font-family:system-ui,sans-serif;padding:24px">
<h1>战术特征：球员速度 / 空切 + 全场 spacing（player-movement 信号）</h1>
<p style="color:#8b949e">占有权线程已裁定弱-阴性（round-2 假阳性已推翻）。本页用 tracking 100% 召回的运动学信号，
不依赖球权/队色。空切 = 速度 &gt; {a.cut:.0f}px/s 的帧；spacing = 每帧球员两两距离均值；off-ball = 非持球球员均速。</p>
<h2>全场 spacing 时序</h2>{svg_space}
<h2>off-ball 流动时序</h2>{svg_off}
<h2>逐窗口 · 空切最多的球员（top 8）</h2>{tbl}
<p style="color:#8b949e;font-size:12px">注：track_id 为窗口内局部 ID（BotSort persist，段内稳定）；跨窗口不连通。
无 team ID，故「空切」是运动学定义（高速无球移动），非战术角色判定。需队色/球场掩膜后方可区分攻防两侧。</p>
</body></html>"""
    Path(a.out_html).write_text(html)
    print(f"[写] {a.out_json}\n[写] {a.out_html}")
    for wd in wins:
        print(f"  {wd['name']}: spacing {wd['mean_spacing']}px  off-ball {wd['mean_offball']}px/s  "
              f"top-cutter tid={wd['players'][0]['track_id']} 空切{wd['players'][0]['cut_frames']}帧({wd['players'][0]['cut_pct']}%)")


if __name__ == "__main__":
    raise SystemExit(main())
