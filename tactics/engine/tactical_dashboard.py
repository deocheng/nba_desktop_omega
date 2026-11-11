#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战术总览 dashboard（player-movement 信号统一视图）—— 压力 + spacing + off-ball 共享 PBP 事件轴。

读取已产出的三份 JSON（tactical_pressure / tactical_movement / tactical_screen），
每个窗口渲染一张三联图：上=on-ball 压力、中=全场 spacing、下=off-ball 均速，
共享时间轴 + 紫色 PBP 事件虚线；并标注该窗口掩护候选数 / 中位持续。
不依赖球权/队色（占有权线程已裁定弱-阴性）。
输出: reports/milestone_05/tactical_dashboard.html
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
REP = Path(str(tactics_data_file("reports/milestone_05")))
COL = {"w1": "#58a6ff", "w2": "#3fb950", "w3": "#f0883e", "w4": "#db61a2"}


def load(name):
    return json.loads((AW / name).read_text())


def panel(series, name, color, label, tmin, tmax, y0, y1, h, events, vmax=None):
    """在 [y0,y1] 子区域内画一条归一化折线。series=[(t,v)]。"""
    pts = [(t, v) for t, v in series if v is not None]
    if not pts:
        return ""
    vmax = vmax or max(p[1] for p in pts)
    X = lambda t: 40 + (t - tmin) / (tmax - tmin + 1e-9) * 880
    Y = lambda v: y1 - v / (vmax + 1e-9) * (y1 - y0)
    seg = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in pts)
    svg = [f'<text x="6" y="{y0+12}" fill="#8b949e" font-size="11">{label} (≤{vmax:.0f})</text>']
    for e in events:
        x = X(e["t"])
        svg.append(f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y1}" stroke="#6e40c9" stroke-dasharray="3 3" opacity="0.45"/>')
    svg.append(f'<polyline points="{seg}" fill="none" stroke="{color}" stroke-width="1.1" opacity="0.9"/>')
    svg.append(f'<line x1="40" y1="{y1}" x2="920" y2="{y1}" stroke="#30363d"/>')
    return "\n".join(svg)


def main():
    pres = load("tactical_pressure.json")
    mov = load("tactical_movement.json")
    scr = load("tactical_screen.json")
    pw = {w["name"]: w for w in pres["windows"]}
    mw = {w["name"]: w for w in mov["windows"]}
    sw = {w["name"]: w for w in scr["windows"]}

    cards = ""
    for name in ["w1", "w2", "w3", "w4"]:
        p = pw[name]; m = mw[name]; s = sw[name]
        rows = {t: pr for t, _, pr, _ in p["rows"]}
        # 统一事件轴（用 movement 的 events）
        evs = m.get("events", [])
        allt = [t for t, _ in rows.items()] + [t for t, _ in m["spacing"]] + [t for t, _ in m["offball"] if t is not None]
        allt += [e["t"] for e in evs]
        tmin, tmax = min(allt), max(allt)
        # 三联图：压力[20,90] 间距[110,180] offball[200,270]
        H = 300
        body = panel([(t, rows.get(t)) for t in sorted(rows)], name, COL[name],
                     "on-ball 压力", tmin, tmax, 20, 90, H, evs)
        body += panel(m["spacing"], name, "#58a6ff", "spacing", tmin, tmax, 110, 180, H, evs)
        body += panel(m["offball"], name, "#3fb950", "off-ball", tmin, tmax, 200, 270, H, evs)
        # 事件标签
        for e in evs:
            x = 40 + (e["t"] - tmin) / (tmax - tmin + 1e-9) * 880
            body += f'<text x="{x:.1f}" y="293" fill="#a371f7" font-size="8" transform="rotate(45 {x:.1f} 293)">{(e.get("kind") or "")[-5:]}</text>'
        cards += f"""<div style="border:1px solid #21262d;border-radius:8px;padding:12px;margin:12px 0;background:#0d1117">
        <h3 style="margin:0 0 4px">{name}  ·  t {m['t0']:.1f}–{m['t1']:.1f}s  ·  掩护候选 <b>{s['n_candidates']}</b>（中位 {s['median_dur_s']}s）</h3>
        <svg viewBox="0 0 920 {H}" width="100%" style="background:#010409">{body}</svg></div>"""

    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>战术总览 · player-movement 三联图</title></head>
<body style="background:#010409;color:#c9d1d9;font-family:system-ui,sans-serif;padding:24px">
<h1>战术总览：on-ball 压力 / spacing / off-ball 共享 PBP 事件轴</h1>
<p style="color:#8b949e">占有权线程已裁定弱-阴性（round-2 假阳性已推翻）。本 dashboard 全部基于 tracking 100% 召回 +
pose 的纯运动学信号，不依赖球权/队色。紫色虚线 = PBP 事件时刻。掩护候选数来自战术掩护检测（运动学代理，
无 team ID，含低位要位/卡位/包夹等噪声）。</p>
{cards}
<p style="color:#8b949e;font-size:12px">读数：压力越低=盯防越紧；spacing 越大=阵型越散；off-ball 越高=无球侧越活跃。
事件附近出现压力骤降 + off-ball 抬升，通常对应挡拆后持球人突破 / 无球侧空切启动。</p>
</body></html>"""
    out = REP / "tactical_dashboard.html"
    out.write_text(html)
    print(f"[写] {out}  ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    raise SystemExit(main())
