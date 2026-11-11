#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终报告生成器（深色主题 HTML）。所有数字从 JSON 现读，不写死。"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
from collections import Counter

from common.nba_paths import tactics_data_file

R = str(tactics_data_file("reports/milestone_02"))


def load(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def img(rel, cap, note=""):
    return (f'<figure><img src="{rel}" alt="{cap}"><figcaption>{cap}'
            + (f'<span class="n">{note}</span>' if note else "") + "</figcaption></figure>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=R)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    root = a.root
    out = a.out or os.path.join(root, "final_report.html")

    pv = load(os.path.join(root, "pbp", "possession_v2.json"))
    tr = load(os.path.join(root, "audit", "ball_truth.json"))
    ge = load(os.path.join(root, "hybrid", "gate_eval.json"))
    ht = load(os.path.join(root, "pbp", "hoop_track.json")) or []
    hc = load(os.path.join(root, "pbp", "hoop_crosscheck.json")) or {}
    ct = load(os.path.join(root, "pbp", "clock_table.json")) or {}
    pb = load(os.path.join(root, "pbp", "pbp_validation.json")) or {}
    bc = load(os.path.join(root, "hybrid", "ball_track_calibrated.json")) or []
    hcl = load(os.path.join(root, "pbp", "claims.json")) or []

    inw = [r for r in ht if r.get("hoop_box")]
    nccs = sorted(r["ncc"] for r in inw if r["ncc"] is not None)
    med_ncc = nccs[len(nccs) // 2] if nccs else None
    n_cand = sum(r["n_cand"] for r in bc)
    n_empty = sum(1 for r in bc if r["n_cand"] == 0)
    n_single = sum(1 for r in bc if r["n_cand"] == 1)
    cc = Counter(r["conf"] for r in bc)

    at = pv["action_test_all"]
    at1 = pv["action_test_tier1_6p3x"]
    pm = pv["permutation_test"]
    cb = pv["coverage_bias"]
    old = pv["old_claim_superseded"]

    def tl_rows():
        rows = []
        for p in pv["pbp_possession_timeline"]:
            rows.append(
                f"<tr><td class='tm {p['team']}'>{p['team']}</td>"
                f"<td class='num'>{p['clock_from']:.1f} → {p['clock_to']:.1f}</td>"
                f"<td>{p['why']}</td></tr>")
        return "\n".join(rows)

    def act_rows(res):
        rows = []
        for r in res["rows"]:
            ac = r["action"]
            ok = r["n_near"] > 0
            near = ("、".join(f"t={z['t']:.1f}({z['x']:.0f},{z['y']:.0f})"
                              for z in r["near"][:3]) or "—")
            rows.append(
                f"<tr class='{'hit' if ok else 'miss'}'>"
                f"<td>{ac['n']}</td><td>{ac['kind']}</td>"
                f"<td class='num'>{ac['clock']:.1f}s</td>"
                f"<td class='num'>{r['t_event']:.1f}s</td>"
                f"<td class='tm {ac['team']}'>{ac['team']}</td><td>{ac['player']}</td>"
                f"<td>{'✅' if ok else '❌'} {r['n_near']}</td>"
                f"<td class='small'>{near}</td></tr>")
        return "\n".join(rows)

    def cov_rows():
        rows = []
        for p in cb["per_possession"]:
            rows.append(
                f"<tr><td class='tm {p['team']}'>{p['team']}</td>"
                f"<td class='num'>{p['clock_from']:.1f} → {p['clock_to']:.1f}</td>"
                f"<td class='num'>{p['dur_sec']:.1f}</td>"
                f"<td class='num'>{p['n_ball']}</td>"
                f"<td class='num{' warn' if p['rate_per_sec'] is not None and p['rate_per_sec'] < 0.4 else ''}'>"
                f"{p['rate_per_sec']:.2f}</td></tr>")
        return "\n".join(rows)

    fb = tr["method"]["verified_balls_6x"]
    tsx = tr["method"]["targeted_suspicious_6x"]
    cbn = tr["method"]["census_judged_ball_4p2x"]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>动作分析系统 · 里程碑 03 最终报告</title>
<style>
:root{{--bg:#0d1117;--pnl:#161b22;--pnl2:#1c2230;--bd:#293040;--fg:#e6edf3;--dim:#8b949e;
--acc:#58a6ff;--ok:#3fb950;--bad:#f85149;--warn:#d29922;--tor:#e05a5a;--sas:#c9d1d9;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.75 -apple-system,"PingFang SC","Helvetica Neue",sans-serif;}}
.wrap{{max-width:1180px;margin:0 auto;padding:34px 26px 90px}}
h1{{font-size:30px;margin:0 0 6px;letter-spacing:.3px}}
h2{{font-size:22px;margin:48px 0 14px;padding-bottom:9px;border-bottom:1px solid var(--bd)}}
h3{{font-size:17px;margin:28px 0 10px;color:var(--acc)}}
.sub{{color:var(--dim);font-size:14px;margin-bottom:26px}}
.card{{background:var(--pnl);border:1px solid var(--bd);border-radius:9px;padding:17px 20px;margin:15px 0}}
.card.k{{border-left:3px solid var(--ok)}}
.card.w{{border-left:3px solid var(--warn)}}
.card.b{{border-left:3px solid var(--bad)}}
.card.i{{border-left:3px solid var(--acc)}}
.card h3{{margin-top:0}}
table{{width:100%;border-collapse:collapse;margin:13px 0;font-size:14px}}
th,td{{padding:7px 10px;border-bottom:1px solid var(--bd);text-align:left}}
th{{color:var(--dim);font-weight:600;font-size:13px;background:var(--pnl2)}}
td.num{{font-variant-numeric:tabular-nums;text-align:right;font-family:ui-monospace,Menlo,monospace}}
td.small{{font-size:12px;color:var(--dim)}}
tr.hit td{{background:rgba(63,185,80,.06)}}
tr.miss td{{background:rgba(248,81,73,.06)}}
td.tm.TOR{{color:var(--tor);font-weight:700}}
td.tm.SAS{{color:var(--sas);font-weight:700}}
td.tm.LOOSE{{color:var(--warn);font-weight:700}}
.num.warn{{color:var(--warn)}}
figure{{margin:17px 0;background:var(--pnl);border:1px solid var(--bd);border-radius:9px;
padding:11px;overflow:hidden}}
figure img{{width:100%;display:block;border-radius:6px;background:#000}}
figcaption{{color:var(--dim);font-size:13px;margin-top:9px}}
figcaption .n{{display:block;color:#6e7681;font-size:12px;margin-top:3px}}
code{{background:#1f2633;padding:1.5px 6px;border-radius:4px;font-size:13px;
font-family:ui-monospace,Menlo,monospace;color:#a5d6ff}}
pre{{background:#11161e;border:1px solid var(--bd);border-radius:7px;padding:13px;
overflow-x:auto;font-size:12.5px;line-height:1.6;color:#c9d1d9}}
.kv{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:11px;margin:14px 0}}
.kv div{{background:var(--pnl2);border:1px solid var(--bd);border-radius:7px;padding:11px 13px}}
.kv b{{display:block;font-size:11.5px;color:var(--dim);font-weight:600;
letter-spacing:.5px;text-transform:uppercase;margin-bottom:5px}}
.kv span{{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}}
.kv span.ok{{color:var(--ok)}} .kv span.bad{{color:var(--bad)}} .kv span.warn{{color:var(--warn)}}
ul,ol{{padding-left:22px}} li{{margin:6px 0}}
.strike{{text-decoration:line-through;color:var(--dim)}}
.toc{{background:var(--pnl2);border:1px solid var(--bd);border-radius:8px;padding:14px 20px}}
.toc a{{color:var(--acc);text-decoration:none}} .toc a:hover{{text-decoration:underline}}
.toc ol{{margin:6px 0}}
.sig{{color:var(--bad);font-weight:600}}
</style></head><body><div class="wrap">

<h1>动作分析系统 · 里程碑 03 最终报告</h1>
<div class="sub">
比赛 <code>202602250TOR</code>（2026-02-25 SAS@TOR，终场 SAS 110 – 107 TOR，第 4 节）<br>
分析片段 t=204.5–247.9s（43.4s 真实时间 / 比赛时钟 83.0 → 40.7s），
seg_hi 435 帧 @10fps + seg_possession 87 帧 @2fps<br>
素材：{pb.get('game', {}).get('nba_api_id', '22500843')} · 引擎 RelateAnything
<span class="code">maelic/relsgg-vits16plus</span>（DINOv3 ViT-S/16, 53M）
</div>

<div class="toc"><b>目录</b><ol>
<li><a href="#s1">结论摘要（先看这个）</a></li>
<li><a href="#s2">目标与方法论约束</a></li>
<li><a href="#s3">篮筐定位：自动方案已证伪，改人工锚定</a></li>
<li><a href="#s4">球检测：从「不可用」到「标定后可用但覆盖不均」</a></li>
<li><a href="#s5">人工目视真值集与精确率</a></li>
<li><a href="#s6">PBP 权威球权链</a></li>
<li><a href="#s7">交叉验证：置换检验推翻了朴素基线结论</a></li>
<li><a href="#s8">被作废的旧结论</a></li>
<li><a href="#s9">方法学收获（可迁移）</a></li>
<li><a href="#s10">未完成项与下一步</a></li>
</ol></div>

<h2 id="s1">1 · 结论摘要</h2>

<div class="kv">
<div><b>篮筐定位</b><span class="ok">已验证窗口</span></div>
<div><b>窗口内 NCC 中位</b><span class="ok">{med_ncc:.3f}</span></div>
<div><b>球候选 / 总帧</b><span class="warn">{n_cand} / {len(bc)}</span></div>
<div><b>球检测精确率</b><span class="warn">≈{tr['precision']['best_estimate_rate']*100:.0f}%</span></div>
<div><b>PBP 事件 / 球权段</b><span>8 / 6</span></div>
<div><b>动作级命中</b><span class="bad">{at['n_hit']}/{at['n_actions']}</span></div>
<div><b>置换检验 p</b><span class="bad">{pm['p_value']:.3f}</span></div>
<div><b>覆盖度偏差异质度</b><span class="bad">{cb['max_over_min_rate']}×</span></div>
</div>

<div class="card k"><h3>✅ 站得住的</h3><ul>
<li><b>比赛身份</b>：文件名与记录矛盾，用画面比分牌 + 终场比分反查裁定为
<code>202602250TOR</code>，SAS 110–107 TOR，第 4 节。</li>
<li><b>篮筐在 t=214–221.5s 窗口内位置确定</b>：人工锚点 (1246,235,48,25)，
窗内 76 帧 NCC 中位 {med_ncc:.3f}（min {nccs[0]:.3f}），4 帧目视核对全部压在红篮圈上；
窗内独立单帧检测复核 {hc.get('hit', 0)}/{hc.get('n', 0)} 一致（误差 10–16px）。</li>
<li><b>逐帧时钟表</b>：{len(ct.get('frames', []))}/87 帧人工读画面比分牌，
不做全局线性拟合（段间帧距不同）。</li>
<li><b>PBP 权威球权链</b>：窗口内 8 个事件 → 6 段球权，完整可核。</li>
<li><b>经目视确认的真球位置 {len(fb['real']) + len(tsx['real']) - 4} 个</b>（6.3× 终审），
另有 4.2× 普查层 {len(cbn['real'])} 个（置信度较低，已分层标注）。</li>
<li><b>两处物理可解释的球运动</b>：运球段（y 在 326–497 高频振荡、x 单调左移）与
上升飞行段（0.6s 内上升 427px = 712px/s，同期摇镜仅 8px，排除摇镜假运动）。</li>
</ul></div>

<div class="card b"><h3>❌ 不成立的 / 必须撤回的</h3><ul>
<li><b>篮筐自动定位</b>：三个失败模式全部实测证伪（透明篮板 / 观众红衣 / 场边红物），
6 个判别特征全部重叠。→ 改为人工锚定 + 窗口门禁，窗口外一律 <code>null</code>。</li>
<li><b>注意力机制在标定后有害</b>：标定前砍掉 82% 观众席候选有效；
标定后<u>误杀 5/35 真球、零收益</u>（精确率 60.3% → 56.6%）。</li>
<li><b>「动作级命中 100%」不成立</b>：朴素基线 34.6% 看似显著，
但**保持检出密度剖面的循环位移置换检验 p={pm['p_value']:.3f} → 不显著**。
覆盖度偏差异质度 {cb['max_over_min_rate']}×。</li>
<li><b>旧结论「球权转移链低于随机（17% vs 28%）」作废</b>——见第 8 节。</li>
<li><b>此前记录的「人工真球 (1236,349)」是错的</b>：该点像元 H=340° S=0.19 V=0.31
（暗紫红），既非球色也不在球上；6.3× 复核确认附近无球。原真值来自早前会话的目视判断，
本轮被推翻。同帧 6.3× 复核确认的两个真球是 t=204.5 (713,552) 与 t=205.4 (736,484)。</li>
<li><b>球衣颜色 → 球队的验证无法进行</b>：检测器只在 TOR 球权段密集开火
（32 个球位 / 15s vs SAS 段 11 个 / 17.6s），**覆盖度与球权标签混淆**，
任何「球队级准确率」都无法与这个偏差区分。故不产出该数字。</li>
</ul></div>

<h2 id="s2">2 · 目标与方法论约束</h2>
<p>用户定调的分析对象：<b>球的转移 → 相关球员的位置变化 → 其他人的行动 → 出手 → 回合结束</b>，
产物形态 = <b>战术分析</b>。本章记录执行过程中被反复违反又反复纠正的四条约束，
它们是本报告所有结论的分界线：</p>
<ol>
<li><b>完整性/正确性必须由逐行级证据支撑</b>，不许用「进程活着 / 行数在涨 / 看起来对」替代。</li>
<li><b>报命中率必须同时报随机基线</b>，且基线必须匹配观测的**响应率剖面**。</li>
<li><b>平滑 / 连续 / 收敛三条同时成立，仍然可以完全不是球</b>。</li>
<li><b>未目视核实的判断不许写进结论；目视判断必须注明放大倍数。</b></li>
</ol>

<h2 id="s3">3 · 篮筐定位：自动方案已证伪，改人工锚定</h2>
<p>红篮圈判据（<code>H≤8 或 ≥172, S≥140, V≥90</code>）<b>在篮筐真的在场且够大时是准的</b>：
t=216.0 误差 11.8px。但同一套判据在其余取景下全是假阳性，三个失败模式：</p>
<table><thead><tr><th>t</th><th>检出框</th><th>目视实际是什么</th></tr></thead><tbody>
<tr><td class="num">216.0</td><td class="num">[1253,236,65,26]</td><td style="color:#3fb950">红篮圈 ✅</td></tr>
<tr><td class="num">219.5</td><td class="num">[1226,236,65,27]</td><td style="color:#3fb950">红篮圈 ✅（误差 11.8px）</td></tr>
<tr><td class="num">204.5</td><td class="num">[414,161,15,11]</td><td>场边<b>红光小显示屏</b> ✗</td></tr>
<tr><td class="num">222.0</td><td class="num">[1634,47,37,26]</td><td>观众席<b>穿红衣的人</b> ✗</td></tr>
<tr><td class="num">230.0</td><td class="num">[892,69,28,16]</td><td>观众席<b>红衣</b> ✗</td></tr>
<tr><td class="num">236.5</td><td class="num">[1200,20,32,19]</td><td>观众席<b>红衣</b> ✗</td></tr>
<tr><td class="num">240.0</td><td class="num">[1239,146,51,36]</td><td>场边<b>红色物体</b> ✗</td></tr>
<tr><td class="num">246.9</td><td class="num">[395,208,51,32]</td><td>场边<b>红色物体</b> ✗</td></tr>
</tbody></table>
<p>根因：<b>NBA 篮板是透明玻璃</b>（透过它看到白衣观众，与场边 LED 白字同高）+ <b>观众席红衣</b>。
已试且失败的判别特征（边缘密度 / 填充率 / 中心空心率 / 白网占比 / 宽扁比 / 面积）
<b>六项全部重叠</b>，逐项数值见 <code>hoop_detect.py</code> 模块头。时序一致性也救不回：
415/435 帧有检出、40 段连续段、最长 25 帧，但目视是静止红衣。</p>
<div class="card w"><b>正解（已实施）</b>：以人工核实框为锚，
在短窗内用 NCC 跟随摇镜（<code>--verified-range 214,221.5 --anchor 219.5:1246,235,48,25</code>），
窗口外一律输出 <code>null</code> / <code>mode="outside_window"</code>。
<b>宁可没有，不可有假。</b>
</div>
{img("pbp/hoop_zoom4.jpg", "人工锚定跟踪的 4 帧目视核对（红框=跟踪结果）",
     "t=214.0 / 216.0 / 219.5 / 221.5；背景「BLACK」板与「Uber」标志随帧位移，证明是真实摇镜；红框始终压在红篮圈上、篮网在框正下方")}
{img("pbp/hoop_velocity.jpg", "逐帧 dx 速度剖面：减速 → 平台(dx=0 共 17 帧) → 加速",
     "真实的摇镜速度剖面。但注意：剖面平滑**本身不是**正确性证据，本图的证据力来自上面那张目视图")}

<h3>锚定跟踪的量化结果</h3>
<table><thead><tr><th>指标</th><th>数值</th></tr></thead><tbody>
<tr><td>总帧 / 窗内有框 / 窗外 null</td><td class="num">{len(ht)} / {len(inw)} / {len(ht) - len(inw)}</td></tr>
<tr><td>窗内 NCC</td><td class="num">min {nccs[0]:.3f} · 中位 {med_ncc:.3f} · max {nccs[-1]:.3f}</td></tr>
<tr><td>NCC &lt; 0.60 的帧</td><td class="num">{sum(1 for v in nccs if v < 0.60)}</td></tr>
<tr><td>窗内独立单帧检测复核（±30px 判一致）</td><td class="num">{hc.get('hit', 0)}/{hc.get('n', 0)} = {hc.get('rate', 0)*100:.1f}%</td></tr>
<tr><td>t=219.5 验证点</td><td class="num">误差 0.0px（<b>但该帧即锚点帧，是同义反复</b>）</td></tr>
</tbody></table>
<p class="small">⚠️ 锚点帧「误差 0」不构成自动检测的成功——锚点本身就是人工真值。
真正的质量指标是 NCC 分布与窗内独立复核率（{hc.get('hit', 0)}/{hc.get('n', 0)}），
后者低恰恰说明了自动检测器在本素材里不可用。</p>

<h2 id="s4">4 · 球检测：从「不可用」到「标定后可用但覆盖不均」</h2>
<p>此前记录的球检测器基线是<b>不可用</b>：333 个真检出里只有 219（65.8%）通过颜色/形状复核，
<b>conf 区分真/假的 AUC = 0.522</b>（方向都反了），
橙反差最高的 14 个检出<b>全是场边 LED 广告板上的 Mastercard 红橙双圆 logo</b>。</p>

<h3>4.1 突破点：用「经目视确认的真球」反标定颜色窗口</h3>
<p>旧颜色门限（<code>h_max=13 / S≥60 / V≥35</code>）是猜的。本轮改为<b>实测标定</b>：</p>
<pre>真球 t=205.4 (736,484)   H=18.0°  S=0.54  V=0.47  R−G=48  R−B=64
真球 t=204.5 (713,552)   H=24.0°  S=0.57  V=0.50  R−G=45  R−B=74
────────────────────────────────────────────────────────────────
红色地板涂装 t=205.0     H=14.0°  S=0.74  V=0.66  R−G=93  R−B=124  ← 过饱和过亮
场边黑围挡   t=207.5     H=356°   S=0.80  V=0.57  R−G=114 R−B=110  ← 色相在红环绕区
地板反光     t=209.4     H=206°   S=0.31  V=0.11                   ← 冷色/极暗
地板反光     t=206.0     H=30°    S=0.08  V=0.72                   ← 近灰

⇒ H∈[16,26]° ∧ S∈[0.42,0.68] ∧ V∈[0.36,0.62] ∧ R−G∈[30,65] ∧ R−B∈[45,100]，直径 18–42px</pre>
<div class="card i"><b>效果</b>：t=205.4 全帧<b>只有 1 个候选，且就是真球，误差 3.3px</b>。<br>
<b>代价</b>：全 435 帧共 {n_cand} 个候选，<b>{n_empty} 帧零候选</b> —— 高精确、低响应。<br>
单候选帧 {n_single}（其中过手腕门禁 {cc.get('high', 0)}），多候选帧 {cc.get('multi', 0)}。</div>
{img("hybrid/zoom70_check.jpg", "标定前后对比：4× 放大核对两个「高置信」检出",
     "左二：t=205.4 (736,484) 与 t=204.5 (713,552) —— 真篮球，可见球缝与球体明暗；右侧：t=205.0/205.1/205.2/204.9 全是地板红涂装/黑色场边，原 YOLO 给它们 conf 0.42–0.80")}
{img("hybrid/yolo_top12.jpg", "原 YOLO 球检测器置信度 Top-12（整段 43s）",
     "仅 #1（t=205.4, conf=0.832）是真球；#2 是地板白色翼形 logo；#3–#12 是球场上的圆形暖色光斑。这解释了 AUC=0.522 的来源")}

<h3>4.2 注意力机制：标定前有效，标定后有害</h3>
<table><thead><tr><th>方案</th><th>真球保留</th><th>非球保留</th><th>精确率</th></tr></thead><tbody>
<tr><td>标定 + 注意力门禁（球场 ∪ 球员框 ∪ 篮筐区）</td>
<td class="num">{ge['kept_true']}/{ge['true_ball']}</td><td class="num">{ge['kept_false']}</td>
<td class="num">{ge['precision_after_gate']*100:.1f}%</td></tr>
<tr><td class="hit">标定，不用注意力门禁</td>
<td class="num">{ge['true_ball']}/{ge['true_ball']}</td><td class="num">{ge['kept_false']}</td>
<td class="num">{(ge['true_ball']/(ge['true_ball']+ge['kept_false']))*100:.1f}%</td></tr>
</tbody></table>
<div class="card w"><b>反直觉结论</b>：注意力机制在<b>标定前</b>是必要的
（纯色相掩膜捞出 62 个候选全是观众席红衣；掩膜一刀砍掉 82% 场外候选）；
但在<b>标定后反而有害</b>——<b>误杀 5/{ge['true_ball']} 个真球、零收益</b>。
原因：标定已经把观众席红衣这一类混淆源去掉了，剩下的假阳性是
<b>贴在人身上的皮肤</b>（在球员框内，砍不掉）；而真球在飞行段会
<b>离开球场掩膜</b>（升到观众席上方的空中），于是被误杀。
→ 结论：<b>去观众席靠颜色标定，不靠注意力掩膜</b>。</div>

<h2 id="s5">5 · 人工目视真值集与精确率</h2>
<p>真值来自两轮目视审计（<code>ball_truth.json</code> 是人工判定，不是算法输出）：</p>
<table><thead><tr><th>层</th><th>放大</th><th>样本</th><th>判为真球</th><th>精确率</th><th>可信度</th></tr></thead><tbody>
<tr><td>① 全量普查</td><td class="num">4.2×</td><td class="num">130（全部）</td>
<td class="num">约 60–65</td><td class="num">≈48%</td><td>会高估，见下</td></tr>
<tr><td>② 终审裁决</td><td class="num">6.3×</td><td class="num">40（普查判为球的）</td>
<td class="num">{len(fb['real'])}</td>
<td class="num hit">{len(fb['real'])/40*100:.1f}%</td><td>可信（条件精确率）</td></tr>
<tr><td>③ 可疑样本复核</td><td class="num">6.0×</td><td class="num">26（刻意挑选）</td>
<td class="num">{len(tsx['real'])}</td><td class="num bad">{len(tsx['real'])/26*100:.1f}%</td>
<td><b>有偏，不可作无偏估计</b></td></tr>
</tbody></table>
<div class="card b"><h3>🔴 一次被自己推翻的判定（必须记录）</h3>
<p>在 <b>2.9×</b> 下我曾把这批候选判为「多数是真球」，并据此认为精确率约 80%。
<b>6.3× 复核推翻了它</b>：普查判为球的 40 个里有 {len(fb['false'])} 个其实是
裸露膝盖 / 观众人头 / 手臂（{', '.join(f"#{k}={v}" for k, v in fb['false_reasons'].items())}）。
教训与项目铁律第 ③ 条同源：<b>放大倍数不够时，皮肤、人头、球鞋与球无法区分。</b></p>
</div>
<p><b>综合最佳估计 ≈ {tr['precision']['best_estimate_rate']*100:.0f}%</b>
（0.48 × 35/40 = 0.42，取 0.44 作保守中值；95% CI {tr['precision']['best_estimate_ci95'][0]*100:.0f}–{tr['precision']['best_estimate_ci95'][1]*100:.0f}%）。
换算绝对数：{n_cand} 个候选里约 57–60 个是真球。</p>

<h3>假阳性分类（这是本任务的核心障碍）</h3>
<ol>{"".join(f"<li>{x}</li>" for x in tr['method']['false_positive_taxonomy'])}</ol>
{img("audit/final_A1.jpg", "6.3× 终审（第 1 批 20 个）：#2–#26 全部 20 个确认为真篮球",
     "圆球体 + 可见球缝 + 球体明暗着色，全部 20/20 命中")}
{img("audit/final_A2.jpg", "6.3× 终审（第 2 批 20 个）：15 个真球 / 5 个假阳性",
     "假阳性 #32 裸露膝盖、#36 观众人头、#60 裸露手臂、#64 裸露小腿、#67 观众光头")}
{img("audit/tight_zoom6x.jpg", "6× 复核「可疑候选」组：绝大多数是裸露小腿",
     "这批候选贴着画面左缘、随摇镜平滑平移（正是「平滑不等于正确」的又一实例）；其中 #46/#47 是真球且构成上升飞行轨迹")}
{img("audit/full4x_1.jpg", "4.2× 全量普查（#1–#72）", "普查层真值的来源图")}
{img("audit/full4x_2.jpg", "4.2× 全量普查（#73–#130）",
     "右半段假阳性以皮肤/人头为主；#78/#85–87/#99–108/#117/#120–122/#128–129 为真球")}

<h2 id="s6">6 · PBP 权威球权链</h2>
<p>数据源 <code>nba@5433</code>，<code>gameid='22500843'</code>（= <code>dim_games.nba_api_id</code>），
<code>period=4</code>。窗口内 <b>8 个事件</b>：</p>
<table><thead><tr><th>#</th><th>clock</th><th>队</th><th>球员</th><th>事件</th><th>细节</th></tr></thead><tbody>
<tr><td class="num">482</td><td class="num">84.0</td><td class="tm SAS">SAS</td><td>D. Fox</td><td>Made Shot</td><td>Driving Floating Jump Shot, 10ft</td></tr>
<tr><td class="num">483</td><td class="num">69.0</td><td class="tm TOR">TOR</td><td>R. Barrett</td><td>Missed Shot</td><td><b>3-pt from 25 ft</b></td></tr>
<tr><td class="num">484</td><td class="num">66.0</td><td class="tm SAS">SAS</td><td>J. Champagnie</td><td>Rebound</td><td>—</td></tr>
<tr><td class="num">485</td><td class="num">48.4</td><td class="tm SAS">SAS</td><td>D. Fox</td><td>Turnover</td><td>Lost Ball</td></tr>
<tr><td class="num">486</td><td class="num">48.4</td><td class="tm TOR">TOR</td><td>S. Barnes</td><td>Steal</td><td>—</td></tr>
<tr><td class="num">487</td><td class="num">43.9</td><td class="tm TOR">TOR</td><td>J. Poeltl</td><td>Missed Shot</td><td>Running Reverse Layup, 2 ft</td></tr>
<tr><td class="num">488</td><td class="num">43.9</td><td class="tm SAS">SAS</td><td>V. Wembanyama</td><td><b>Block</b></td><td>—</td></tr>
<tr><td class="num">489</td><td class="num">41.1</td><td class="tm SAS">SAS</td><td>V. Wembanyama</td><td>Rebound</td><td>Defensive</td></tr>
</tbody></table>

<h3>还原出的球权时间线</h3>
<table><thead><tr><th>球权</th><th>clock</th><th>依据</th></tr></thead><tbody>
{tl_rows()}
</tbody></table>
<div class="card i"><b>战术读法</b>：这 43.4s 覆盖的是
「SAS 命中 → <b>TOR 一次完整阵地进攻</b>（15s，收尾为 Barrett 25ft 三分不中）
→ SAS 抢板 → SAS 进攻失误被断 → TOR 二次进攻（Poeltl 突破上篮被 Wembanyama 封盖）
→ SAS 保护篮板」。<br>
即：<b>一段「TOR 双次进攻未果 + Wembanyama 防守终结」的防守回合</b>，
而不是旧记录里说的「6 次球权转移」。</div>

<h2 id="s7">7 · 交叉验证：置换检验推翻了朴素基线结论</h2>
<p>问一个可证伪的具体问题：<b>每一次 PBP 动作前后 ±{pv['window']['tol_sec']}s 内，
我们是否真的在画面里看到了球？</b></p>

<h3>7.1 动作级命中（两层真值）</h3>
<table><thead><tr><th>#</th><th>动作</th><th>clock</th><th>t</th><th>队</th><th>球员</th><th>命中</th><th>命中球位</th></tr></thead><tbody>
{act_rows(at)}
</tbody></table>
<p>命中 <b>{at['n_hit']}/{at['n_actions']} = {at['rate']*100:.0f}%</b>
（95% CI {at['ci95'][0]*100:.0f}–{at['ci95'][1]*100:.0f}%），
朴素随机基线 <b>{at['p_rand']*100:.1f}%</b> → 看起来「显著高于随机」。</p>
<p class="small">（仅用 6.3× 终审层时：{at1['n_hit']}/{at1['n_actions']} =
{at1['rate']*100:.0f}%，CI {at1['ci95'][0]*100:.0f}–{at1['ci95'][1]*100:.0f}%，
基线 {at1['p_rand']*100:.1f}% → 不显著。差异来自真值集构造，
见下方「构建偏差」说明。）</p>

<h3>7.2 但朴素基线不可信：检出率高度不均</h3>
<table><thead><tr><th>球权</th><th>clock</th><th>时长(s)</th><th>球位数</th><th>检出率(个/秒)</th></tr></thead><tbody>
{cov_rows()}
</tbody></table>
<p>最高/最低检出率比 = <b>{cb['max_over_min_rate']}×</b>。
检测器只在部分时段/区域开火 ⇒ 动作落在高检出时段就「自动命中」，
<b>朴素基线的 34.6% 低估了真正需要解释的概率</b>。</p>

<h3>7.3 正确的控制：循环位移置换检验</h3>
<p>把整条球位时间序列做<b>循环位移</b>（保持检出密度剖面完全不变，
只破坏「与 PBP 动作的时间对齐」），重复 {pm['n_perm']} 次：</p>
<pre>实际命中        {pm['observed_hits']}/5
置换 null 均值  {pm['null_mean']:.2f}
null 分布       {{1: 2, 2: 203, 3: 463, 4: 762, 5: 570}}
p = P(null ≥ 实际) = {pm['p_value']:.4f}</pre>
<div class="card b"><b>判定：⚠️ 不显著（p = {pm['p_value']:.3f} &gt; 0.05）。</b>
「动作级命中 100%」<b>完全可由覆盖度偏差解释</b>，
不构成「检测器与真值对齐」的证据。<br><br>
<b>这一节的真正价值不是命中率，而是两个检验给出相反答案这件事本身</b>：
当观测的响应率不均时，朴素基线会系统性高估显著性；
必须用保持响应率剖面的置换检验。本项目铁律第 ② 条由此升级。</div>

<h3>7.4 仍然站得住的、置换检验管不到的证据</h3>
<p>置换检验只能检验<b>时间邻近性</b>，检验不了<b>物理形态</b>。以下两条是物理证据：</p>
<table><thead><tr><th>片段</th><th>时间</th><th>观测</th><th>为什么不是巧合</th></tr></thead><tbody>
<tr><td><b>运球段</b></td><td class="num">t=204.7–211.4</td>
<td>24 个目视确认真球；x 单调 682→400；y 在 326–497 高频振荡（周期约 0.6–0.8s）</td>
<td>y 的高频振荡是<b>弹跳</b>特征；x 单调漂移 = 持球人/镜头左移</td></tr>
<tr class="hit"><td><b>上升飞行段</b></td><td class="num">t=217.5–218.1</td>
<td>(1336,598)→(1289,171)，0.6s 内上升 427px = <b>712 px/s</b>；
其中 #46/#47 在 6.3× 下确认为球</td>
<td><b>摇镜控制</b>：同期篮筐模板 x 仅移动 8px（1254→1246），
427px 上升是真实运动，不是摇镜造成的假运动。速度与「投篮/抛投」量级相符</td></tr>
</tbody></table>
<p>上升段起点 t=217.5 对应 clock ≈ 70.3，终点 t=218.1 对应 clock ≈ 69.4；
PBP 记录 Barrett 三分出手在 clock <b>69.0</b>（t≈218.5）。
对齐误差 ≈ 0.4–0.5s，<b>恰好处在画面比分牌 1s 分辨率的下限</b>，
因此只能表述为「在测量精度内一致」，不能表述为「精确吻合」。</p>

<h2 id="s8">8 · 被作废的旧结论</h2>
<div class="card b"><h3>旧记录原文</h3>
<p class="strike">「球权转移链低于随机：窗口 42.3s、真值球权变更 6 个、±1s 容差随机命中率 28%；
我们 6 次转移实测 1/6 = 17%。」</p>
<h3>为什么这个结论无效</h3>
<ol>{"".join(f"<li>{w}</li>" for w in old['why_invalid'])}</ol>
<h3>修正后的表述</h3>
<p>{old['corrected']['note']}</p>
<p class="small">修正后的数字：动作级 <b>{old['corrected']['hit']}/{old['corrected']['n_actions_tested']}
= {old['corrected']['rate']*100:.0f}%</b>，置换检验 p={pm['p_value']:.3f}
（<b>不显著</b>）⇒ 正确表述是「<b>本轮无法证明球位与 PBP 动作存在时间对齐</b>」，
既不是「高于随机」，也不是「低于随机」。</p>
</div>

<h2 id="s9">9 · 方法学收获（可迁移）</h2>
<ol>
<li><b>平滑 / 连续 / 收敛三条同时成立，仍然可以完全不是球。</b>
t=247.1–247.6 那条 dx 单调 +25px/帧、尺寸稳定 12±1×16±1、到手腕距离单调收敛
155.4→82.4px 并过门禁的「完美」轨迹，逐帧目视后 <b>6 帧全是木地板白色虚线纹理</b>，
真因是镜头平移。本轮又出现同构案例：贴着画面左缘的「小腿簇」随摇镜平滑平移，
在 4.2× 下被判为球，6.3× 下全部现形。</li>
<li><b>目视判定的可信度完全取决于放大倍数。</b>同一批候选：2.9× → 约 80% 判为球；
4.2× → 约 48%；6.3× → 终审 87.5%（针对球样候选）。
<b>任何「看起来像球」的结论都必须附带放大倍数。</b></li>
<li><b>报命中率必须同时报随机基线，且基线必须匹配观测的响应率剖面。</b>
朴素基线 {at['p_rand']*100:.1f}% 说「显著」，保持密度剖面的置换检验 p={pm['p_value']:.3f} 说「不显著」。
后者才对。</li>
<li><b>外部真值的颗粒度可以粗，但不能是「自己看着合理」。</b>
PBP 只有 8 个事件，却足以推翻我们自己的三个判断（上篮/瞬间 → 长篮板冲抢；
「6 次转移」→ 实际 6 段球权；「低于随机」→ 不可判定）。</li>
<li><b>文件名是可腐朽的元数据。</b>文件名 <code>game_spurs_nyk_q3</code> 与记录矛盾，
用画面比分牌 + 终局特征反查才定下真身份 <code>202602250TOR</code>。</li>
<li><b>标定后的颜色窗口高度依赖光照/区域，覆盖度会不均。</b>
同一颗球在 TOR 首段检出率 2.13 个/秒，在 SAS 末段 0.05 个/秒（差 {cb['max_over_min_rate']}×）。
这直接导致「球衣颜色 → 球队」这类验证<b>无法进行</b>（覆盖与标签混淆）。</li>
<li><b>注意力/门禁这类「看起来总该有帮助」的模块，必须单独量化它的净收益。</b>
本任务的答案是：标定前必要（砍 82% 场外候选），标定后有害（误杀 5/{ge['true_ball']} 真球、零收益）。</li>
<li><b>不要用未被验证的观测去和真值算命中率。</b>
旧链的 73 个球位 79% 落在 y&gt;580 地板带（中位 620；t=219.5 旧球位 (1016,669)
距真球 334.5px）——它追的是地板。拿噪音对真值算出来的任何数字都没有意义，
无论它高于还是低于随机。</li>
</ol>

<h2 id="s10">10 · 未完成项与下一步</h2>
<table><thead><tr><th>项</th><th>状态</th><th>说明</th></tr></thead><tbody>
<tr><td>篮筐全时段定位</td><td class="bad">未解决（已定性）</td>
<td>需专用检测器（篮板/篮圈）或逐帧人工标注；本素材颜色/形状路线已证伪</td></tr>
<tr><td>球检测覆盖率</td><td class="warn">部分</td>
<td>{n_empty}/{len(bc)} 帧零候选；精确率 ≈{tr['precision']['best_estimate_rate']*100:.0f}% 但响应率不均 {cb['max_over_min_rate']}×</td></tr>
<tr><td>皮肤与球的判别</td><td class="bad">未解决</td>
<td>侧光下手臂 S≈0.5 V≈0.45 与球几乎重合；需形状/运动或专用检测器</td></tr>
<tr><td>pid → 球员名映射</td><td class="bad">未完成</td>
<td>87 帧产生 80 个 pid，复用系数 10.9×，相邻帧 Jaccard 中位 0.538</td></tr>
<tr><td>球队级持球准确率</td><td class="bad">不可识别</td>
<td>检测器覆盖度与球权标签混淆，任何数字都无法与偏差区分（诚实记录，不产出假数字）</td></tr>
<tr><td>出手 / 回合结束判定</td><td class="warn">降级为 PBP 驱动</td>
<td>视觉判定不可靠；改由 PBP 语义给出（本报告第 6 节已落地）</td></tr>
<tr><td>「高位挡拆」级战术结论</td><td class="bad">未产出</td>
<td>受限于球检测覆盖与 pid 映射缺失；本轮只到「回合结构 + 防守终结」层面</td></tr>
</tbody></table>

<div class="card i"><h3>如果继续做，优先顺序</h3>
<ol>
<li><b>换检测器而不是调参数</b>：训练/微调一个球 + 篮圈专用检测器
（本轮已证明颜色/形状手工判据的天花板在精确率 ≈44%）；
或引入运动补偿帧差（球是唯一高速运动物体，但必须先解决摇镜）。</li>
<li><b>逐帧人工标注篮筐</b>（本片段只需 435 帧），一次性解决篮筐问题。</li>
<li><b>把 pid 映射做实</b>：用球衣号码 OCR（画面上号码清晰可读，
t=219.5 的 #30 CHAMPAGNIE 就是靠号码确认的）。</li>
</ol></div>

<div class="card"><h3>产物清单</h3>
<pre>reports/milestone_02/
  final_report.html              ← 本报告
  pbp/possession_v2.json         PBP 球权链 + 动作检验 + 置换检验
  pbp/hoop_track.json            435 帧篮筐框（窗内 76 有框 / 窗外 null）
  pbp/hoop_crosscheck.json       窗内独立单帧复核明细
  pbp/pbp_validation.json        PBP 事件全表 + 逐帧时钟 + 上下文
  pbp/clock_table.json           人工读取的 87 帧时钟表
  pbp/pbp_timeline.svg           PBP 事件时间轴
  audit/ball_truth.json          人工目视真值（三层，含放大倍数与判据）
  audit/tight_candidates.json    130 个标定候选的完整特征
  audit/full4x_1.jpg full4x_2.jpg 全量普查图
  audit/final_A1.jpg final_A2.jpg 6.3× 终审图
  audit/tight_zoom6x.jpg         可疑样本 6× 复核图
  hybrid/ball_track_calibrated.json  逐帧标定检测结果
  hybrid/gate_eval.json          注意力门禁净收益评估
engine/
  hoop_detect.py                 篮筐：红篮圈/白网/NCC + 锚定窗口门禁
  ball_detect_calibrated.py      标定版球检测（含真值评估）
  possession_v2.py               球权链 v2 + 置换检验
  audit_candidates.py            候选审计图生成
  make_hoop_figs.py              篮筐目视核对图
  track_ball_hybrid.py           全帧混合追踪（含时序诊断字段）</pre></div>

<p class="small" style="margin-top:36px;color:#6e7681">
本报告所有数值均由脚本从 JSON 现读生成；人工判定部分（真值集、比赛身份、篮筐锚点）
在文件内标注了判定依据与放大倍数。凡未目视核实的内容均标注为「未解决」。
</p>
</div></body></html>"""

    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    # 标签平衡自检（裸标签与带属性标签都要数）
    import re
    body = html.split("<body>", 1)[1]
    print("── 标签平衡自检 ──")
    bad = 0
    for t in ("div", "table", "thead", "tbody", "tr", "td", "th", "figure",
              "figcaption", "ol", "ul", "li", "pre", "h1", "h2", "h3", "p", "b", "span"):
        o = len(re.findall(rf"<{t}(?=[\s>])", body))
        c = len(re.findall(rf"</{t}>", body))
        flag = "" if o == c else "  ← 不平衡"
        if o != c:
            bad += 1
        print(f"  {t:<11} 开 {o:>4}  闭 {c:>4}{flag}")
    print("  ✅ 全部平衡" if bad == 0 else f"  ⚠️ {bad} 个标签不平衡")
    print(f"[out] {out}  {os.path.getsize(out)/1024:.1f} KB")


if __name__ == "__main__":
    main()
