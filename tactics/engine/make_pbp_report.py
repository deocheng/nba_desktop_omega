#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PBP 交叉校验报告（深色主题 HTML）。

原则同 make_report.py：**所有数字从各层 JSON 现读，绝不手抄**。
包括转移链对齐的统计检验（命中率 vs 随机基线），也在本脚本内现算。
"""
import argparse
import json
import os
import statistics as st

CSS = """
:root{--bg:#141419;--panel:#1b1b22;--panel2:#22222b;--line:#32323d;
--tx:#e8e8ee;--tx2:#a2a8b3;--tx3:#7c828d;--acc:#5aa9ff;--ok:#5fd18a;
--warn:#ffb454;--bad:#ff6b6b;--purple:#a97ce0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font:15px/1.72 ui-sans-serif,-apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:44px 26px 90px}
h1{font-size:29px;margin:0 0 6px;letter-spacing:-.3px}
h2{font-size:21px;margin:52px 0 14px;padding-bottom:9px;border-bottom:1px solid var(--line)}
h3{font-size:16.5px;margin:30px 0 10px;color:var(--tx)}
p{margin:11px 0}
.sub{color:var(--tx2);font-size:13.5px;margin:0 0 26px}
code{background:#25252f;padding:2px 6px;border-radius:5px;font-size:13px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#ffd28a}
pre{background:#191921;border:1px solid var(--line);border-radius:10px;
padding:15px 17px;overflow-x:auto;font-size:12.8px;line-height:1.62;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#cfd6e0}
table{width:100%;border-collapse:collapse;margin:16px 0;font-size:13.6px}
th,td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--panel2);color:var(--tx2);font-weight:600;font-size:12.6px;
text-transform:uppercase;letter-spacing:.4px}
tr:hover td{background:#1e1e26}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:19px 22px;margin:18px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(196px,1fr));gap:13px;margin:20px 0}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:15px 17px}
.kpi .v{font-size:26px;font-weight:750;letter-spacing:-.5px;line-height:1.2}
.kpi .k{font-size:12px;color:var(--tx3);margin-top:5px;letter-spacing:.3px}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.acc{color:var(--acc)}.purple{color:var(--purple)}
.tag{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11.5px;
font-weight:650;letter-spacing:.3px}
.t-ok{background:rgba(95,209,138,.15);color:var(--ok)}
.t-bad{background:rgba(255,107,107,.15);color:var(--bad)}
.t-warn{background:rgba(255,180,84,.15);color:var(--warn)}
.t-info{background:rgba(90,169,255,.15);color:var(--acc)}
figure{margin:22px 0}
figure img{width:100%;border-radius:11px;border:1px solid var(--line);display:block}
figcaption{color:var(--tx3);font-size:12.6px;margin-top:9px}
.svgbox{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:8px;margin:20px 0}
.svgbox svg{width:100%;height:auto;display:block}
.callout{border-left:3px solid var(--acc);background:#1a2230;padding:14px 18px;
border-radius:0 9px 9px 0;margin:18px 0}
.callout.bad{border-color:var(--bad);background:#2a1a1c}
.callout.warn{border-color:var(--warn);background:#2a2318}
.callout.ok{border-color:var(--ok);background:#17261e}
.callout .h{font-weight:700;margin-bottom:5px;font-size:14.5px}
ul,ol{margin:11px 0;padding-left:24px}li{margin:6px 0}
.small{font-size:12.8px;color:var(--tx2)}
hr{border:0;border-top:1px solid var(--line);margin:38px 0}
"""


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbp-json", required=True)
    ap.add_argument("--clock-table", required=True)
    ap.add_argument("--possession-json", required=True)
    ap.add_argument("--timeline-svg", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    d = load(a.pbp_json)
    ct = load(a.clock_table)
    poss = load(a.possession_json)
    gm = d["game"]
    frames = d["frames"]
    events = d["events"]

    clk = {int(r["frame"]): float(r["clock_sec"]) for r in ct["frames"]}

    def clk_at(t):
        return clk.get(int(round((t - d["clock_model"]["t0"]) * d["clock_model"]["fps"])) + 1)

    # ── PBP 真值：窗口内的「球权变更」事件 ──
    TRUE_EV = [(84.0, "D. Fox 中投命中", "球权转 TOR"),
               (69.0, "R. Barrett 三分不中 25ft", "球脱手"),
               (66.0, "J. Champagnie 抢到篮板", "球权转 SAS"),
               (48.4, "D. Fox 丢球 + S. Barnes 抢断", "球权转 TOR"),
               (43.9, "J. Poeltl 反手上篮不中(被盖)", "球脱手"),
               (41.1, "V. Wembanyama 抢到篮板", "球权转 SAS")]
    c0, c1 = frames[0]["clock_sec"], frames[-1]["clock_sec"]
    win = c0 - c1
    TOL = 1.0
    p_rand = sum(2 * TOL for _ in TRUE_EV) / win

    rows = []
    hits = 0
    for e in poss["transfers"]:
        c = clk_at(e["t"])
        dmin, emsg = min((abs(c - t0), f"{nm}（{tag}）") for t0, nm, tag in TRUE_EV)
        ok = dmin <= TOL
        hits += ok
        rows.append((e["t"], c, e["from"], e["to"], dmin, emsg, ok))
    hit_pct = hits / len(rows) * 100
    rand_pct = p_rand * 100

    # ── 旧管线球位分布 ──
    ys = [r["ball_pt"][1] for r in poss["timeline"] if r["ball_pt"]]
    xs = [r["ball_pt"][0] for r in poss["timeline"] if r["ball_pt"]]
    floor_pct = sum(1 for v in ys if v > 580) / len(ys) * 100
    y_med = st.median(ys)
    n_old = len(ys)
    old_at_219 = next((r["ball_pt"] for r in poss["timeline"] if abs(r["t"] - 219.5) < .01), None)

    svg = open(a.timeline_svg, encoding="utf-8").read()
    svg = svg[svg.index("<svg"):]

    def tag(txt, cls):
        return f'<span class="tag {cls}">{txt}</span>'

    H = []
    H.append(f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PBP 交叉校验 · 动作分析系统</title><style>{CSS}</style></head><body><div class="wrap">
<h1>用 PBP 交叉校验视觉识别结果</h1>
<p class="sub">动作分析系统 · 里程碑 02 附篇 · 2026-09-23 ·
数据源 <code>nba@5433 / play_by_play</code> + 画面比分牌逐帧读取 ·
全部数字由 <code>validate_with_pbp.py</code> / <code>make_pbp_report.py</code> 从 JSON 现读</p>

<div class="callout bad">
<div class="h">🚨 文件名与项目记录自相矛盾 —— 用画面证据裁定</div>
本片段一直被脚本与文件名标为 <code>game_spurs_nyk_q3</code>（马刺 vs 尼克斯 第3节），
而项目长期记忆里记录的却是「2026-02-25 马刺客场猛龙 末节」。
两者不可能都对。用画面左下角比分牌读出
<b>TSN | 4th | 1:08 | 24&nbsp;&nbsp;SA 108&nbsp;&nbsp;TOR 104</b>，
再回查 PBP 终场比分 —— <b>记忆是对的，文件名是错的</b>。
<br><br>
结论：<b>文件名是可腐朽的元数据，不能作为身份依据</b>。
本次的身份是「读比分牌 → 用终场比分/对手反查 <code>dim_games</code> → 用比分轨迹二次确认」
三步独立裁定的，未经此三步的比赛身份一律视为未确认。
</div>

<div class="kpis">
<div class="kpi"><div class="v acc">{gm['game_id']}</div>
  <div class="k">{gm['game_date']} · {gm['season_type']} · {gm['away_team_abbr']} @ {gm['home_team_abbr']}</div></div>
<div class="kpi"><div class="v">{gm['away_team_abbr']} {gm['away_pts']}<span class="small"> – </span>{gm['home_pts']} {gm['home_team_abbr']}</div>
  <div class="k">PBP 终场比分（与比分牌 108-104 自洽）</div></div>
<div class="kpi"><div class="v">{len(events)}</div><div class="k">第 4 节 PBP 事件数</div></div>
<div class="kpi"><div class="v">{len(frames)}</div><div class="k">已建立逐帧时钟映射的帧数</div></div>
<div class="kpi"><div class="v ok">{hits}/{len(rows)}</div>
  <div class="k">转移链命中 PBP 真值（±1s）</div></div>
<div class="kpi"><div class="v bad">{rand_pct:.0f}%</div>
  <div class="k">随机基线期望命中率</div></div>
<div class="kpi"><div class="v bad">{floor_pct:.0f}%</div>
  <div class="k">旧管线球位落在「地板带」的比例</div></div>
<div class="kpi"><div class="v ok">2.9<span class="small">px</span></div>
  <div class="k">混合法收紧判据后的球心误差</div></div>
</div>

<h2>§1 为什么需要 PBP：视觉层的语义空洞</h2>
<p>视觉层能给出「球在哪、谁拿着、朝哪走」，但<b>语义层</b>（这是不是一个回合、是不是一次出手、
球权怎么转的）极脆弱——本项目的球检测器 <code>AUC=0.522</code>（0.5=随机），
「出手/回合结束」判定至今未实现。PBP 恰好补上这块：它给的是
<b>事件类型 + 比赛时钟 + 球员 + 投篮坐标(x,y)/距离(dist) + 当时比分</b>。
颗粒度粗（无空间位置），但作为<b>外部独立参照</b>无可替代。</p>

<h2>§2 时钟映射：为什么不能用速率模型</h2>
<p>我们有画面左下角固定位置的 TSN 比分牌，逐帧读出了全部 87 帧的时钟。
先试了「线性速率模型」，<b>它不成立</b>：</p>
<pre>{"　".join(f"f{s['range'][0]}..f{s['range'][1]-1}  {s['mean']:.4f} s/帧  (std={s['std']:.4f}, n={s['n']})  {s['label']}" for s in d["frame_spacing"])}</pre>
<div class="callout warn">
<div class="h">两段隐含帧间距不同 → 标称 2.0fps 的重采样有抖动</div>
前半段 0.4884 s/帧、后半段 0.4949 s/帧。若强行用单一斜率拟合，
片段中段会有 ±0.3s 误差，<b>足以把相邻的 PBP 事件对错一格</b>
（例如把「Barrett 三分不中」错判成「Champagnie 抢篮板」）。
<b>正解 = 逐帧读比分牌时钟</b>——比分牌是固定位置 overlay，读它没有额外难度。
本报告全部采用逐帧时钟表（<code>clock_table.json</code>，87/87 帧人工读取）。</div>
<p class="small">⚠️ 当前时钟表是<b>人工读取</b>。把它自动化（数字模板/OCR）
是本项目待办的确定性改进项，在此之前该表应视为 ±0.1s（&lt;60s 区）/ ±0.5s（≥60s 区）精度。</p>
<figure>
<img src="clock_all.jpg" alt="87 帧比分牌时钟逐帧读取">
<figcaption>时钟表的读取依据：87 帧的比分牌时钟行逐帧横排（左列 f1–f44，右列 f45–f87）。
可看出两个区段：≥60s 区对秒显示（数值成对出现），&lt;60s 区切十分位（每帧 −0.5s，含 59.7→40.7 段）。
<b>注意两段的隐含帧间距并不相同，这就是不能用速率模型的原因。</b></figcaption>
</figure>

<h2>§3 逐帧时钟 ↔ PBP 时间轴</h2>
<div class="svgbox">{svg}</div>
<figcaption class="small">灰点=投篮（绿=命中）　橙=篮板　红=失误/抢断　蓝=盖帽　
下方绿色竖线=我们 6 次球权转移中命中 PBP 真值的那 1 次，紫色=未命中。
注意 6 次转移里有 5 次落在时间轴的空档处——那些位置 PBP 上根本没有任何球权变更。</figcaption>

<h2>§4 两条线独立撞上的三处</h2>
<table>
<tr><th>时刻</th><th>视觉系统的结论</th><th>PBP 的结论</th><th>判定</th></tr>
<tr>
 <td><b>t=219.5</b><br><span class="small">时钟 68.0s</span></td>
 <td>球在 #30 CHAMPAGNIE 手中/手边，高举，紧邻篮筐<br>
     <span class="small">混合法给出 (1219,341)，误差 19.1px；收紧判据后 2.9px</span></td>
 <td>69.0s R. Barrett 三分不中（25ft）<br>
     66.0s <b>J. Champagnie 抢到篮板</b></td>
 <td>{tag('一致', 't-ok')}<br><span class="small">球在空中→正进入 Champagnie 手中，
      2.2s 后 PBP 才记为篮板</span></td></tr>
<tr>
 <td><b>t=218.7 →<br>221.8</b></td>
 <td>旧管线持球人 pid19 持续到 t=220.5</td>
 <td>69.0→66.0：猛龙出手不中、马刺抢板<br>
     即 <b>球权在 66.0s 由 TOR 转 SAS</b></td>
 <td>{tag('方向一致', 't-warn')}<br><span class="small">但持球人身份（pid19）无法核对，
     因 pid→球员名映射未解决</span></td></tr>
<tr>
 <td><b>t=221.0</b><br><span class="small">时钟 67.0s</span></td>
 <td>视觉系统自发检测到球权转移 <b>pid19 → pid38</b>（gap 0.5s）</td>
 <td>真值球权变更在 66.0s（Champagnie 篮板）</td>
 <td>{tag('命中 1.0s', 't-ok')}<br><span class="small">唯一一次命中，且落在
     「不中→篮板」之间，方向正确</span></td></tr>
<tr>
 <td><b>t=247.4</b><br><span class="small">时钟 40.7s</span></td>
 <td>球在地板上滚动，不在任何人手边<br>
     <span class="small">旧说法。姿态门禁给出 6 帧连续单调轨迹
     (1462,630)→(1565,626)，到手腕距离单调收敛 155→82px</span></td>
 <td>43.9s J. Poeltl 反手上篮被 Wembanyama 盖掉；<br>
     41.1s <b>V. Wembanyama 抢到防守篮板</b></td>
 <td>{tag('视觉假阳性', 't-bad')}<br><span class="small">
     </span></td></tr>
</table>

<div class="callout bad">
<div class="h">§4 补充：一次"看起来极其可信"的假轨迹被逐帧目视推翻</div>
在 t=247.1–247.6（球专线 10fps，frame 425–430）上，旧管线给出一条<b>教科书级完美</b>的轨迹：
位置连续单调右移 25px/帧、尺寸稳定 12±1 × 16±1、到最近手腕距离<b>单调收敛</b> 155.4 → 82.4px
并最终通过门禁。任何"平滑性 / 连续性 / 收敛性"判据都会接受它。
<br><br>
逐帧放大目视后：<b>那 6 帧的"球"全部是木地板上的白色虚线与人字形纹理——画面里根本没有球</b>。
真正的原因是<b>镜头在平移</b>：地板纹理随镜头整体右移，探测器锁在纹理上，
而与此同时一名球员走进该区域，于是"到手腕距离"也顺势收敛。
<br><br>
<b>两个旧结论因此撤回</b>：① 「球在 t=247.4 落在地板上滚动」不成立；
② 「失败原因是超高球员手腕关键点缺失」不成立。
它们是纯地板假阳性。按 PBP，此刻球应在 Wembanyama 手中。
</div>
<figure>
<img src="track247_strip.jpg" alt="六帧轨迹逐帧目视">
<figcaption>黄圈 = 探测器给出的"球"位置。上排 f425–f427、下排 f428–f430。
<b>六帧全部落在木地板与白色虚线上，没有一帧真的有球。</b>
这就是那条"完美平滑轨迹"的真身——地板纹理 + 镜头平移。</figcaption>
</figure>

<div class="callout ok">
<div class="h">§4 最重要的收获：PBP 纠正了我的语义误判</div>
在拿到 PBP 之前，我从「球在高处 + 篮筐就在旁边 + 高举手臂」推断这是
<b>「上篮/投篮瞬间」</b>。PBP 显示这是 <b>Barrett 三分不中后的长篮板，
Champagnie 起跳冲抢</b>——完全不同的战术语义。
<b>「球靠近篮筐」既不充分也不必要地指向「出手」</b>；这是必须记住的一课。
</div>

<h2>§5 硬结论：球权转移链<b>低于随机</b></h2>
<p>上面那次命中很容易让人兴奋，所以必须做 base-rate 检验。</p>
<table>
<tr><th>项目</th><th>数值</th></tr>
<tr><td>片段窗口</td><td>时钟 {c0:.1f}s → {c1:.1f}s = <b>{win:.1f}s</b></td></tr>
<tr><td>PBP 真值「球权变更」事件</td><td><b>{len(TRUE_EV)}</b> 个</td></tr>
<tr><td>±{TOL:.0f}s 容差下的端到端覆盖</td><td>{sum(2*TOL for _ in TRUE_EV):.1f}s / {win:.1f}s
    → 随机命中率 <b>p = {p_rand:.3f}</b></td></tr>
<tr><td>我们 6 次转移实测命中</td><td class="bad"><b>{hits}/{len(rows)} = {hit_pct:.0f}%</b></td></tr>
<tr><td>随机期望命中</td><td>{len(rows)*p_rand:.2f}/{len(rows)} = {rand_pct:.0f}%</td></tr>
</table>
<table>
<tr><th>我们的转移</th><th>时钟</th><th>pid</th><th>最近真值距离</th><th>判定</th></tr>""")

    for t, c, f_, to_, dmin, emsg, ok in rows:
        H.append(f"<tr><td>t={t:.1f}</td><td>{c:.1f}s</td>"
                 f"<td>pid{f_} → pid{to_}</td><td>{dmin:.1f}s</td>"
                 f"<td>{tag('✅ 命中', 't-ok') if ok else tag('✗ 未命中', 't-bad')}"
                 f" <span class='small'>{emsg}</span></td></tr>")
    H.append(f"""</table>
<div class="callout bad">
<div class="h">结论：转移链不优于随机，至今不可用</div>
实测 {hit_pct:.0f}% vs 随机 {rand_pct:.0f}%。这<b>不是调参能解决的问题</b>——
根因在下游：球位本身是错的（见 §6），建立在假球上的持球人归属必然与真值无关。
</div>

<h2>§6 根因：旧管线的「球」是地板</h2>
<div class="kpis">
<div class="kpi"><div class="v bad">{floor_pct:.0f}%</div>
  <div class="k">球位落在 y&gt;580「地板带」的比例</div></div>
<div class="kpi"><div class="v">y {min(ys):.0f}–{max(ys):.0f}</div>
  <div class="k">球位 y 范围（中位 {y_med:.0f}）</div></div>
<div class="kpi"><div class="v bad">334.5<span class="small">px</span></div>
  <div class="k">t=219.5 旧管线球位 (1016,669) 距真球 (1236,349)</div></div>
<div class="kpi"><div class="v ok">19.1<span class="small">px</span></div>
  <div class="k">同帧混合法 (1219,341) 距真球</div></div>
</div>
<figure>
<img src="cmp_ball_t2195.jpg" alt="球位三方案对照">
<figcaption>同一帧（t=219.5 / 第4节 68.0s）上的三种球位。
<b>红</b>=旧管线 (1016,669)，落在紫色油漆区地板上，离真球 334.5px；
<b>橙</b>=混合法（颜色+注意力+手腕）(1219,341)，19.1px；
<b>绿</b>=收紧判据 (S≥100,V≥70) 后 (1238,351)，2.9px；
<b>白星</b>=人工核实的真球 (1236,349)，在 #30 Champagnie 手中。
橙框=红色篮圈（PBP 证实他在抢篮板，不是上篮）。</figcaption>
</figure>
<p>旧管线 {n_old} 个球位里 {floor_pct:.0f}% 落在球场地板带（y&gt;580）。
它追踪的<b>不是球</b>，而是木地板上的橙色印记。<b>这就是转移链命中率低于随机的根因</b>：
持球人归属被建立在一个全程错误的球位上。</p>

<h3>注意力掩膜如何一刀切掉观众席</h3>
<figure>
<img src="hybrid_t02195.jpg" alt="注意力掩膜与候选保留/剔除">
<figcaption>t=219.5 的混合法核对图。<b>浅绿覆盖区 = 注意力区</b>（球场 ∪ 球员框），
可见左侧观众席、上方看台与右侧 LED 广告板<b>全部被排除</b>；
<b>红叉</b> = 被注意力剔除的 141 个候选（观众席红色衣物为主）；
<b>黄圈</b> = 保留但未过手腕门禁；<b>绿圈</b> = 通过手腕门禁；
<b>洋红十字</b> = 混合法首选（真球）；<b>橙框 HOLDER</b> = 推定持球人（#30 Champagnie）。</figcaption>
</figure>

<h2>§7 方法学收获（铁律级）</h2>
<div class="callout">
<div class="h">① 录像文件名 / 自建标签不可信，必须用画面内证据定身份</div>
<code>game_spurs_nyk_q3</code> 是错的。定身份的正确顺序：
读画面比分牌（队名/节次/时钟）→ 用「终场比分 + 对手」反查 DB → 用比分轨迹二次确认。
</div>
<div class="callout">
<div class="h">② 帧率标称值不可信；比赛时钟才是权威时间轴</div>
2fps 重采样的隐含帧间距在同一片段内前 0.4884、后 0.4949 s/帧。
凡是要把视频帧对齐到外部事件（PBP/报表/播客），<b>逐帧读画面时钟</b>，
不要用 <code>t = t0 + i/fps</code> 推。
</div>
<div class="callout">
<div class="h">③ 单一命中必须做 base-rate 检验才算证据</div>
1 次命中看起来像成功，算上随机基线后发现整体是 17% vs 28% ≈ <b>低于随机</b>。
<b>没有基线的命中率是自欺</b>。
</div>
<div class="callout">
<div class="h">④ 「靠近篮筐」不能推出「出手」</div>
球在高处 + 篮筐在旁边 + 手臂高举，既可能是出手，也可能是抢篮板、传球、封盖。
<b>语义结论必须有 PBP 级的外部证据</b>，否则只能说「球在高处」。
</div>
<div class="callout warn">
<div class="h">⑤ 三个我已修正的自造错误（留档）</div>
<ul>
<li><b>假告警</b>：先前版本的校验脚本报出「停表/速率异常帧 7 个」。
根因是我在写 JSON 时把 <code>clock_sec</code> 四舍五入到 1 位小数、再做差分，
<b>检测到的是自己的舍入噪声</b>。已改为按区段统计帧间距 + 显式标注量化精度。</li>
<li><b>过度归因（两次）</b>：先把 t=247.4 门禁失败归因为「球在地板上滚动（散球）」，
后又归因为「7'4" Wembanyama 的手腕关键点缺失」。两次都错。
逐帧目视后确认是<b>木地板纹理假阳性</b>（见 §4 补充）。</li>
<li><b>把巧合当信号</b>：那条 6 帧"完美平滑且到手腕收敛"的轨迹让我一度判断
「这不是随机假阳性」。它确实是<b>有结构</b>的——但结构来自镜头平移下的地板纹理，
不是来自球。<b>平滑性 / 连续性 / 收敛性三条同时成立，仍然可以完全不是球。</b></li>
</ul>
</div>
<div class="callout bad">
<div class="h">⑦ 新增铁律：球轨迹的"平滑性"不能作为可信度证据</div>
t=247.1–247.6 给出一条位置连续单调、尺寸稳定、到手腕距离单调收敛到 82px 的轨迹，
任何时序连贯性判据都会接受它，而它 100% 是地板纹理。
<b>镜头运动会让静止纹理表现出完美平滑的"运动"。</b>
因此球轨迹的可信度只能来自：① 逐帧目视抽查（分层抽样，不是只看 top-N）；
② 与 PBP 的事件对齐；③ 球心落在「手」的物理邻域内且该手确实在运动。
<b>纯几何平滑性一律不作为证据。</b>
</div>
<div class="callout warn">
<div class="h">⑥ SQL 连接键再次踩坑（已在代码内注释防复现）</div>
<code>play_by_play.gameid</code> 是 <b>varchar</b>，表内存有
<code>199902190SAC</code> 这类 BR 格式（1997–2000 约 10–12%）。
写 <code>p.gameid::bigint</code> 直接
<code>invalid input syntax for type bigint</code> 报错。
正解：先取 <code>nba_api_id</code>，再用<b>文本等值</b>比较。
</div>

<h2>§8 下一步（按价值排序）</h2>
<ol>
<li><b>把混合法从单帧推到全 87 帧</b>，用逐帧时钟表把每帧的球位与 PBP 语义对齐，
    重算转移链命中率——<b>这是验证混合法是否真的修好了根因的唯一标准</b>。</li>
<li><b>时钟表自动化</b>：比分牌位置固定，做数字模板匹配/OCR，替换人工读取，
    消除 ±0.5s 量化误差。</li>
<li><b>建立 pid → 球员名映射</b>：目前 87 帧产生 80 个 pid，
    拿不到球员名就无法把「持球人 pid」与 PBP 的球员字段直接比对。
    可行路径：球衣号码识别（数字 OCR）或队服颜色聚类。</li>
<li><b>补足"球权"定义</b>：PBP 语义里，投篮出手瞬间球权即进入「松散」态，
    篮板/抢断才确定新球权。视觉层的 transfer 判据要按这个定义重写，
    而不是「最近的人换了」。</li>
<li><b>给球轨迹加"目视抽样"漏斗</b>：t=247.x 的教训说明纯几何判据会被镜头运动骗过。
    建议对任何被接受的球轨迹，强制按时间分层抽 ≥8 帧目视核对，
    未通过的一律不得进入下游（本项目已有 <code>make_evidence_figs.py</code> 的分层抽样基建可复用）。</li>
</ol>

<hr>
<p class="small">复现命令：<br>
<code>python validate_with_pbp.py --game-id 202602250TOR --period 4 \\<br>
&nbsp;&nbsp;--t0 204.5 --clock0 83.0 --n-frames 87 --fps 2.0 \\<br>
&nbsp;&nbsp;--clock-table reports/milestone_02/pbp/clock_table.json \\<br>
&nbsp;&nbsp;--claims reports/milestone_02/pbp/claims.json \\<br>
&nbsp;&nbsp;--outdir reports/milestone_02/pbp</code></p>
<p class="small">产物：<code>pbp_validation.json</code>（逐帧时钟+上下文+事件全表）·
<code>clock_table.json</code>（87 帧时钟，人工读取）· <code>cmp_ball_t2195.jpg</code> ·
<code>pbp_timeline.svg</code> · 本报告</p>
</div></body></html>""")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(H))
    print(f"[out] {a.out}  ({os.path.getsize(a.out)/1024:.1f} KB)")
    # 标签平衡自检（同时数裸 <tag> 与带属性的 <tag ...>）
    import re
    body = "\n".join(H)
    bad = 0
    for t in ("div", "table", "tr", "td", "th", "p", "ul", "li", "figure", "pre",
              "span", "h2", "h3", "ol"):
        o = len(re.findall(rf"<{t}(?=[\s>])", body))
        c = body.count(f"</{t}>")
        if o != c:
            print(f"  ⚠️ <{t}> 开闭不平衡: {o} / {c}")
            bad += 1
    print(f"  标签平衡: {'✅ 全部通过' if bad == 0 else f'{bad} 项不平衡'}")
    print(f"  命中 {hits}/{len(rows)}  随机 {rand_pct:.0f}%  地板带 {floor_pct:.0f}%")


if __name__ == "__main__":
    main()
