#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 P0 广播像素原生修正的可视化报告（自包含 HTML，含 SVG 柱状图 + 标注表）。
复用 run_p0_broadcast_native 的加载/统计/标注 + tactic_match.detect_primitives。
输出 norm_calib/p0_fix_report.html（present_files 浏览器预览）。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import importlib.util
import json
import os
import sys

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(tactics_data_file("engine")))
from tactic_match import detect_primitives

R0 = str(tactics_data_file("action_work/run_p0_broadcast_native.py"))
spec = importlib.util.spec_from_file_location("r0", R0)
r0 = importlib.util.module_from_spec(spec); spec.loader.exec_module(r0)

BASE = str(tactics_data_file("action_work"))
rf = json.load(open(f"{BASE}/norm_calib/routing_final.json", encoding="utf-8"))
ast = rf["buckets"]["A_STEP_FINAL"]["detail"]
clusters = []
for txt in ast:
    import re
    m = re.match(r"(ep\d+_s\d+)#(\d+)-(\d+)\((\d+)帧\)", txt)
    clusters.append((m.group(1), int(m.group(2)), int(m.group(3))))
ids = rf["buckets"]["A_STEP_FINAL"]["clusters"]
items = [(cid, seg, s, e) for (cid, (seg, s, e)) in zip(ids, clusters) if cid != 3]

PANS = [0, 15, 30, 45, 60, 75, 90]
# 每簇每 pan 的 (CROSS, DOWN)
per_cluster = {cid: {} for cid, *_ in items}
agg = {}
for pan in PANS:
    b = {"f_l": [0, 0], "f_r": [0, 0], "cut": 0}
    for cid, seg, s, e in items:
        vis = r0.VIS[cid]
        bw = r0.bw_of(vis, pan)
        frames = r0.load_window(seg, s, e)
        if len(frames) < 5:
            continue
        dm, md = r0.cluster_stats(frames)
        ev = detect_primitives(frames, disp_med=dm, med_diag=md, orient=bw)
        c = d = 0
        for evv in ev:
            if evv["type"] == "SCREEN":
                if evv["sub"] == "CROSS": c += 1
                elif evv["sub"] == "DOWN": d += 1
            elif evv["type"] == "CUT": b["cut"] += 1
        per_cluster[cid][pan] = (c, d)
        b[vis][0] += c; b[vis][1] += d
    agg[pan] = (b["f_l"][0] + b["f_r"][0], b["f_l"][1] + b["f_r"][1], b["cut"],
                tuple(b["f_l"]), tuple(b["f_r"]))

# ---------- SVG 柱状图 ----------
W, H = 760, 340
maxv = max((agg[p][0] + agg[p][1]) for p in PANS) or 1
pad_l, pad_b = 48, 36
plot_w, plot_h = W - pad_l - 16, H - pad_b - 20
gw = plot_w / len(PANS)
bw_bar = gw * 0.32
def sx(i): return pad_l + i * gw + gw * 0.18
def sy(v): return pad_b + plot_h - (v / maxv) * plot_h
svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="background:#0f1115;border-radius:8px">']
svg.append(f'<line x1="{pad_l}" y1="{pad_b}" x2="{pad_l}" y2="{pad_b+plot_h}" stroke="#3a4150"/>')
svg.append(f'<line x1="{pad_l}" y1="{pad_b+plot_h}" x2="{pad_l+plot_w}" y2="{pad_b+plot_h}" stroke="#3a4150"/>')
for i, pan in enumerate(PANS):
    C, D, _, _, _ = agg[pan]
    x1 = sx(i)
    yC = sy(C); yD = sy(D)
    svg.append(f'<rect x="{x1:.1f}" y="{yC:.1f}" width="{bw_bar:.1f}" height="{pad_b+plot_h-yC:.1f}" fill="#e06b6b"/>')
    svg.append(f'<rect x="{x1+bw_bar+4:.1f}" y="{yD:.1f}" width="{bw_bar:.1f}" height="{pad_b+plot_h-yD:.1f}" fill="#5ec98a"/>')
    svg.append(f'<text x="{x1+bw_bar:.1f}" y="{yC-4:.1f}" fill="#e0a0a0" font-size="10" text-anchor="middle">{C}</text>')
    svg.append(f'<text x="{x1+2*bw_bar+4:.1f}" y="{yD-4:.1f}" fill="#a0e0c0" font-size="10" text-anchor="middle">{D}</text>')
    svg.append(f'<text x="{x1+gw/2:.1f}" y="{pad_b+plot_h+16:.1f}" fill="#9aa3b2" font-size="11" text-anchor="middle">PAN{pan}</text>')
svg.append(f'<text x="14" y="{pad_b+plot_h/2:.1f}" fill="#9aa3b2" font-size="11" transform="rotate(-90 14 {pad_b+plot_h/2:.1f})" text-anchor="middle">掩护计数</text>')
svg.append('</svg>')
svg_html = "".join(svg)

# ---------- HTML ----------
anchors = json.load(open(f"{BASE}/norm_calib/orient_anchors.json", encoding="utf-8"))["anchors"]
rows_ann = ""
for cid, seg, s, e in items:
    a = anchors[str(cid)]
    rows_ann += (f"<tr><td>#{cid}</td><td>{seg}#{s}-{e}</td><td>{a['visible_far_corner']}</td>"
                 f"<td>[{a['basket_ward'][0]:.3f}, {a['basket_ward'][1]:.3f}]</td></tr>")
rows_scan = ""
for pan in PANS:
    C, D, cut, fl, fr = agg[pan]
    ratio = f"{D/max(C,1):.2f}x" if C else ("∞" if D else "-")
    rows_scan += (f"<tr><td>{pan}</td><td>{C}:{D}</td><td><b style='color:#5ec98a'>{ratio}</b></td>"
                  f"<td>{fl[0]}:{fl[1]}</td><td>{fr[0]}:{fr[1]}</td><td>{cut}</td></tr>")

html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>P0 广播像素原生修正 · 可视化报告</title>
<style>body{{font-family:system-ui,"PingFang SC",sans-serif;margin:0;background:#0f1115;color:#e6e6e6;padding:20px}}
h1{{font-size:18px}}h2{{font-size:14px;color:#9aa3b2;margin-top:24px}}
.box{{background:#171a21;border:1px solid #2a2f3a;border-radius:8px;padding:14px;margin:10px 0}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #2a2f3a;padding:5px 8px;text-align:center}}
th{{background:#1d212b;color:#9aa3b2}}.k{{color:#e06b6b}}.g{{color:#5ec98a}}
.note{{font-size:12px;color:#9aa3b2;line-height:1.7}}</style></head><body>
<h1>P0 广播像素原生修正 · 可视化报告</h1>
<div class="box note">
<b>根因</b>：原 <code>tactic_match.py</code> 硬假设俯视竖直 y 轴（y 减小=朝筐），但 13 个真实战术板簇是广播半场像素、且近边线/侧翼视角，朝筐向量≈水平。
导致「沿篮筐的下掩护(DOWN)」被正确位移在像素里偏横 → 被误标成 CROSS，形成 A3 那个 <span class="k">CROSS 52 : DOWN 10</span> 反转。<br>
<b>修法</b>：<code>detect_primitives</code> 增 <code>orient=(bx,by)</code> 朝筐向量，位移投影到(朝筐/侧向)两轴再判 CROSS·DOWN 与朝筐加速。朝筐向量来自老程逐簇角点标注（远左 f_l / 远右 f_r）+ pan 角。<br>
<b>结论</b>：pan≈45° 翻转，pan 75–90° 既分类数最多(~54)又 DOWN 占优(~6.7x)。已锁 <b>pan=80</b> 落 <code>orient_anchors.json</code>。
图：红=误标 CROSS，绿=修正后 DOWN；可见 PAN0 红高绿低 → PAN75+ 绿高红低，反转肉眼可见。
</div>
<h2>① 全13簇标注（朝筐向量 @ pan=80）</h2>
<table><tr><th>簇</th><th>窗口</th><th>可见远角</th><th>basket_ward</th></tr>{rows_ann}</table>
<h2>② 扫描 PAN：全13簇 CROSS:DOWN（红:绿 翻转）</h2>
{svg_html}
<table style="margin-top:10px"><tr><th>PAN</th><th>CROSS:DOWN</th><th>DOWN占比(倍)</th><th>f_l(远左)</th><th>f_r(远右)</th><th>CUT</th></tr>{rows_scan}</table>
<div class="note" style="margin-top:14px">旧代码=PAN0：<span class="k">0.15x DOWN</span>（反转）。修正后 PAN80：<span class="g">6.7x DOWN</span>。
总掩护数在 PAN0/75/90 均≈54（恒定），证明是坐标轴重解释、非漏检。中间 PAN(45/60) 因位移近对角线、_screen_sub 判 None 偏多。</div>
</body></html>"""
open(f"{BASE}/norm_calib/p0_fix_report.html", "w", encoding="utf-8").write(html)

# 文本表（stdout，确保聊天可见）
print("PAN | 全13 CROSS:DOWN | DOWN倍 | f_l | f_r | CUT")
for pan in PANS:
    C, D, cut, fl, fr = agg[pan]
    print(f"{pan:>3} | {C:>2}:{D:<2}        | {D/max(C,1):.2f}x | {fl[0]}:{fl[1]} | {fr[0]}:{fr[1]} | {cut}")
print(f"\n[report] 写入 {BASE}/norm_calib/p0_fix_report.html")
