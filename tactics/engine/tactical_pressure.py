#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战术特征（player-movement 信号，不依赖已证不成立的球权验证）。

占有权线程（Phase 1.5c/d）裁定：严格球权无法验证对齐 PBP，松赋值仅有平凡相关。
故战术分析转 player-movement 信号（tracking+pose 100% 召回，solid）：

  on-ball 压力  = 持球者框心到「最近的其他球员」框心距离（≈盯防者贴近度）
  spacing       = 持球者到「第二近球员」距离（持球者周边空当代理）

持球者定义用 held 模式的松端（box_pad=0.5，即 round-3 出现弱信号的 regime）：
球心落在按 0.5 扩张的球员框内即判持球；松球/出手/传球时球在框外→无持球者→跳过。

输出：action_work/tactical_pressure.json + reports/milestone_05/tactical_pressure.html
用法: tactical_pressure.py [--pad 0.5]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import statistics
import statistics as st
from pathlib import Path

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
WINS = ["w1", "w2", "w3", "w4"]
DIAG = (1920 ** 2 + 1080 ** 2) ** 0.5


def handler_pressure(fr, pad):
    b = fr.get("ball")
    if not (b and "bbox" in b):
        return None, None, None
    bx = (b["bbox"][0] + b["bbox"][2]) / 2.0
    by = (b["bbox"][1] + b["bbox"][3]) / 2.0
    players = fr.get("players", [])
    if not players:
        return None, None, None
    handler = None
    for p in players:
        x1, y1, x2, y2 = p["bbox"]
        w, h = x2 - x1, y2 - y1
        x1 -= pad * w; x2 += pad * w; y1 -= pad * h; y2 += pad * h
        if x1 <= bx <= x2 and y1 <= by <= y2:
            handler = p
            break
    if handler is None:
        return None, None, None
    hc = ((handler["bbox"][0] + handler["bbox"][2]) / 2.0,
          (handler["bbox"][1] + handler["bbox"][3]) / 2.0)
    dists = sorted(((hc[0] - (p["bbox"][0] + p["bbox"][2]) / 2.0) ** 2 +
                    (hc[1] - (p["bbox"][1] + p["bbox"][3]) / 2.0) ** 2) ** 0.5
                   for p in players if p is not handler)
    pressure = dists[0] if dists else None
    spacing = dists[1] if len(dists) > 1 else None
    return handler["track_id"], pressure, spacing


def load_window(w, pad):
    tr = json.loads((AW / f"{w}_poss_tile" / "ball_tracks.json").read_text())
    pm = json.loads((AW / w / "pose_motion.json").read_text())
    series = pm["series"]
    t0 = min(s["t"] for s in series if s["t"] is not None)
    t1 = max(s["t"] for s in series if s["t"] is not None)
    n = len(tr)
    dt = (t1 - t0) / (n - 1) if n > 1 else 0.1
    rows = []
    for i, fr in enumerate(tr):
        hid, pr, sp = handler_pressure(fr, pad)
        rows.append((t0 + i * dt, hid, pr, sp))
    evs = []
    for e in pm["events"]:
        near = [pr for t, _, pr, _ in rows if pr is not None and abs(t - e["t"]) <= 2.0]
        evs.append({"n": e["n"], "t": e["t"], "clock": e["clock"],
                    "player": e["player"], "kind": e["kind"],
                    "pressure_mean": round(st.fmean(near), 1) if near else None,
                    "n_frames": len(near)})
    pressures = [pr for _, _, pr, _ in rows if pr is not None]
    spacings = [sp for _, _, _, sp in rows if sp is not None]
    return {
        "name": w, "t0": round(t0, 1), "t1": round(t1, 1), "n_frames": n,
        "n_handler": sum(1 for r in rows if r[1] is not None),
        "mean_pressure": round(st.fmean(pressures), 1) if pressures else None,
        "mean_spacing": round(st.fmean(spacings), 1) if spacings else None,
        "rows": [(round(t, 2), hid, round(pr, 1) if pr else None,
                  round(sp, 1) if sp else None) for t, hid, pr, sp in rows],
        "events": evs,
    }


def build_svg(wins):
    pts = []
    for wd in wins:
        for t, hid, pr, _ in wd["rows"]:
            if pr is not None:
                pts.append((t, pr, wd["name"]))
    if not pts:
        return ""
    tmin = min(p[0] for p in pts); tmax = max(p[0] for p in pts)
    pmax = max(p[1] for p in pts)
    W, H = 920, 320
    pad_l, pad_r, pad_t, pad_b = 50, 20, 20, 30
    def X(t): return pad_l + (t - tmin) / (tmax - tmin + 1e-9) * (W - pad_l - pad_r)
    def Y(p): return H - pad_b - p / (pmax + 1e-9) * (H - pad_t - pad_b)
    svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="background:#0d1117">']
    svg.append(f'<line x1="{pad_l}" y1="{H-pad_b}" x2="{W-pad_r}" y2="{H-pad_b}" stroke="#30363d"/>')
    svg.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{H-pad_b}" stroke="#30363d"/>')
    svg.append(f'<text x="{pad_l}" y="{pad_t-6}" fill="#8b949e" font-size="12">on-ball 压力 (px，越低=盯防越紧)</text>')
    # event markers
    for wd in wins:
        for e in wd["events"]:
            x = X(e["t"])
            svg.append(f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{H-pad_b}" stroke="#6e40c9" stroke-dasharray="3 3" opacity="0.6"/>')
            svg.append(f'<text x="{x:.1f}" y="{H-pad_b+16}" fill="#a371f7" font-size="9" transform="rotate(45 {x:.1f} {H-pad_b+16})">{e["kind"][:6]}</text>')
    # lines per window
    colors = {"w1": "#58a6ff", "w2": "#3fb950", "w3": "#f0883e", "w4": "#db61a2"}
    for wd in wins:
        seg = " ".join(f"{X(t):.1f},{Y(pr):.1f}" for t, _, pr, _ in wd["rows"] if pr is not None)
        svg.append(f'<polyline points="{seg}" fill="none" stroke="{colors[wd["name"]]}" stroke-width="1.2" opacity="0.85"/>')
    svg.append('</svg>')
    return "\n".join(svg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pad", type=float, default=0.5)
    ap.add_argument("--out-json", default=str(AW / "tactical_pressure.json"))
    ap.add_argument("--out-html", default=str(AW.parent / "reports" / "milestone_05" / "tactical_pressure.html"))
    a = ap.parse_args()

    wins = [load_window(w, a.pad) for w in WINS]
    payload = {"pad": a.pad, "diag": round(DIAG, 1), "windows": wins}
    Path(a.out_json).write_text(json.dumps(payload, indent=1, ensure_ascii=False))

    svg = build_svg(wins)
    rows_html = ""
    for wd in wins:
        ev_rows = "".join(
            f"<tr><td>{e['t']:.1f}</td><td>{e['clock']:.0f}</td><td>{e['player']}</td>"
            f"<td>{e['kind']}</td><td>{e['pressure_mean'] if e['pressure_mean'] else '—'}</td>"
            f"<td>{e['n_frames']}</td></tr>" for e in wd["events"])
        rows_html += f"""
        <h3>{wd['name']}  (t {wd['t0']:.1f}–{wd['t1']:.1f}s, {wd['n_frames']}帧, 持球 {wd['n_handler']}帧)</h3>
        <p>均值压力 <b>{wd['mean_pressure']}</b> px ｜ 均值 spacing <b>{wd['mean_spacing']}</b> px
           （框对角线 {DIAG:.0f}px 作参照；≤120px=紧贴盯防，≥350px=空位）</p>
        <table border="1" style="border-collapse:collapse;font-size:12px;color:#c9d1d9">
          <tr style="background:#161b22"><th>t(s)</th><th>clock</th><th>player</th><th>kind</th><th>压力均值(px)</th><th>帧数</th></tr>
          {ev_rows}
        </table><br>"""
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>战术特征 · on-ball 压力 / spacing</title></head><body style="background:#010409;color:#c9d1d9;font-family:system-ui,sans-serif;padding:24px">
<h1>战术特征：on-ball 压力 / spacing（player-movement 信号）</h1>
<p style="color:#8b949e">占有权线程（Phase 1.5c/d）已裁定：严格球权无法验证对齐 PBP，松赋值仅平凡相关。
本页改走 <b>tracking+pose（100% 召回，solid）</b> 的 player-movement 信号，不依赖球权验证。
持球者 = 球心落在按 pad={a.pad} 扩张的球员框内；压力 = 持球者到最近其他球员距离。</p>
<h2>压力时序（紫虚线 = PBP 事件）</h2>
{svg}
<h2>逐窗口 / 逐事件</h2>
{rows_html}
<p style="color:#8b949e;font-size:12px">注：本特征为描述性战术指标，未做 PBP 显著性验证；仅作片段战术画像。
team ID 缺失，故「最近其他球员」≈盯防者但可能含队友；需队色/球场掩膜后方可严格区分攻防。</p>
</body></html>"""
    Path(a.out_html).write_text(html)
    print(f"[写] {a.out_json}\n[写] {a.out_html}")
    for wd in wins:
        print(f"  {wd['name']}: 持球 {wd['n_handler']}/{wd['n_frames']}帧  "
              f"均值压力 {wd['mean_pressure']}px  均值spacing {wd['mean_spacing']}px")


if __name__ == "__main__":
    raise SystemExit(main())
