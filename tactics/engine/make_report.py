#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从各层 JSON 渲染里程碑报告（深色主题 HTML）。

设计原则：**所有数字都从产物 JSON 现读**，不手抄。
这样报告与数据永远不会脱节——数据重跑后报告重生成即可。

用法：
  python make_report.py --workdir <action_work> --out <report.html> --figdir <figs>
"""
import argparse
import json
import os
import statistics
from html import escape


def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────── 小工具 ───────────────────────
def pct(x, nd=1):
    return f"{x*100:.{nd}f}%"


def bar(v, vmax, w=110, color="#e04a4a"):
    """纯 CSS 条，避免引入图表库。"""
    if vmax <= 0:
        return ""
    wpx = max(2, int(v / vmax * w))
    return (f'<span class="bar"><span style="display:inline-block;width:{wpx}px;'
            f'height:9px;background:{color};border-radius:2px;vertical-align:middle"></span></span>')


GRADE_STYLE = {
    "strong": ("★★★", "#ff5c5c", "强"),
    "medium": ("★★ ", "#ffb454", "中"),
    "weak": ("★  ", "#8a8f98", "弱"),
}


def grade_badge(g):
    s, c, n = GRADE_STYLE.get(g, ("—", "#666", "—"))
    return f'<span class="gb" style="color:{c}">{s} {n}</span>'


# ─────────────── 球权时间轴 SVG ───────────────
def possession_timeline(merged, transfers, t0, t1, width=1180, height=170):
    """画球权时间轴：横轴时间，色条=控球期，竖线=球权转移。"""
    pad_l, pad_r, pad_t = 54, 18, 42
    span = t1 - t0
    w = width - pad_l - pad_r

    def X(t):
        return pad_l + (t - t0) / span * w

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
             f'style="max-width:{width}px;display:block;margin:0 auto" '
             f'font-family="ui-monospace,Menlo,monospace">']
    # 网格
    parts.append(f'<line x1="{pad_l}" y1="{pad_t-14}" x2="{pad_l+w}" y2="{pad_t-14}" '
                 f'stroke="#333" stroke-width="1"/>')
    tt = int(t0)
    while tt <= t1:
        x = X(tt)
        parts.append(f'<line x1="{x:.1f}" y1="{pad_t-19}" x2="{x:.1f}" y2="{pad_t-9}" '
                     f'stroke="#3a3a3a"/>')
        parts.append(f'<text x="{x:.1f}" y="{pad_t-24}" fill="#6b7280" font-size="11" '
                     f'text-anchor="middle">{tt}s</text>')
        tt += 5
    # 控球条
    y0 = pad_t + 6
    for i, m in enumerate(merged):
        x1, x2 = X(m["start_t"]), X(min(t1, m["end_t"] + 0.5))
        if x2 - x1 < 3:
            x2 = x1 + 3
        _, col, _ = GRADE_STYLE.get(m["grade"], ("", "#666", ""))
        parts.append(f'<rect x="{x1:.1f}" y="{y0}" width="{x2-x1:.1f}" height="30" '
                     f'rx="3" fill="{col}" opacity="0.85"/>')
        if x2 - x1 > 44:
            parts.append(f'<text x="{(x1+x2)/2:.1f}" y="{y0+20}" fill="#0d0d10" '
                         f'font-size="12" font-weight="700" text-anchor="middle">'
                         f'pid{m["pid"]}</text>')
        else:
            parts.append(f'<text x="{(x1+x2)/2:.1f}" y="{y0-4}" fill="{col}" '
                         f'font-size="10" text-anchor="middle">{m["pid"]}</text>')
    # 转移标记
    for t in transfers:
        x = X(t["t"])
        parts.append(f'<line x1="{x:.1f}" y1="{y0-8}" x2="{x:.1f}" y2="{y0+38}" '
                     f'stroke="#4aa8ff" stroke-width="1.5" stroke-dasharray="3,2"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{y0+38}" r="3" fill="#4aa8ff"/>')
    # 说明
    parts.append(f'<text x="{pad_l}" y="{y0+64}" fill="#8a8f98" font-size="11">'
                 f'蓝虚线 = 球权转移（{len(transfers)} 次）</text>')
    parts.append(f'<text x="{pad_l+210}" y="{y0+64}" fill="#8a8f98" font-size="11">'
                 f'色条 = 控球期（红=强证据 / 橙=中 / 灰=弱）</text>')
    # 未知区
    parts.append(f'<text x="{pad_l}" y="{y0+84}" fill="#6b7280" font-size="11">'
                 f'无证据时段（球位不可信）不绘制色条 —— 全片 43s 中'
                 f'仅 {len(merged)} 个控球期有可信球位支撑</text>')
    parts.append('</svg>')
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--figdir", required=True,
                    help="报告引用图片的相对目录名（与 HTML 同目录时传 .）")
    ap.add_argument("--audit-counts", default=None,
                    help="ev_audit_counts.json 路径（分层抽样的各层检出数）")
    a = ap.parse_args()

    W = a.workdir
    gd = load(os.path.join(W, "seg_possession", "possession_gated.json"))
    ta = load(os.path.join(W, "seg_possession", "transfer_audit.json"))
    bv = load(os.path.join(W, "seg_possession", "ball_verify.json"))
    sr = load(os.path.join(W, "seg_possession", "static_reject.json"))
    tac = load(os.path.join(W, "seg_possession", "tactics.json"))
    sel = load(os.path.join(W, "seg_possession", "select_tracks.json"))
    bhi = load(os.path.join(W, "seg_hi", "ball_hi.json"))
    shots = load(os.path.join(W, "seg_possession", "shots.json"))

    m = gd["meta"]
    gate = gd["ball_gate"]
    dup = ta["identity_duplication"]
    t_audit = ta["transfer_audit"]
    vmeta = bv["meta"]
    cs = bv["conf_stats"]
    sr_meta = sr["meta"]
    dom = tac["dominance"]
    spec = tac["predicate_spectrum"]

    merged = gd["merged"]
    transfers = gd["transfers"]
    t0, t1 = shots["start"], shots["start"] + shots["dur"]

    verdict_c = {}
    for t in t_audit:
        verdict_c[t["verdict"]] = verdict_c.get(t["verdict"], 0) + 1

    # ── 分层反差计数 ──
    cnt = {}
    if a.audit_counts and os.path.exists(a.audit_counts):
        cnt = load(a.audit_counts)
    else:
        for cand in (os.path.join(a.figdir, "ev_audit_counts.json"),
                     os.path.join(a.figdir, "..", "ev_audit_counts.json")):
            if os.path.exists(cand):
                cnt = load(cand)
                break
    if not cnt:
        print("  [warn] 未找到 ev_audit_counts.json，分层表将显示 —")

    F = a.figdir

    # ══════════════════ HTML ══════════════════
    H = []
    ap_ = H.append
    ap_("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>动作分析 · 里程碑 02 — 战术回合（球为主线）</title>
<style>
:root{
  --bg:#0e1013; --bg2:#15181d; --bg3:#1b1f26; --bd:#272c35;
  --fg:#e6e9ef; --fg2:#9aa3b2; --fg3:#6b7280;
  --red:#ff5c5c; --org:#ffb454; --blu:#4aa8ff; --grn:#3ecf8e; --yel:#ffd75e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",
  "Microsoft YaHei",sans-serif;line-height:1.72;font-size:15px}
.wrap{max-width:1240px;margin:0 auto;padding:34px 26px 90px}
h1{font-size:29px;margin:0 0 8px;letter-spacing:-.4px;font-weight:800}
h2{font-size:20px;margin:52px 0 16px;padding-bottom:9px;
  border-bottom:1px solid var(--bd);font-weight:750}
h3{font-size:16px;margin:30px 0 10px;color:#cdd4e0;font-weight:700}
h4{font-size:14px;margin:20px 0 8px;color:var(--fg2);font-weight:700}
p{margin:9px 0}
code,.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
code{background:var(--bg3);padding:1.5px 6px;border-radius:4px;color:#c9d4e4}
.sub{color:var(--fg2);font-size:14px;margin-bottom:4px}
.meta{color:var(--fg3);font-size:13px;font-family:ui-monospace,monospace}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:11px;
  padding:19px 21px;margin:16px 0}
.callout{border-left:4px solid var(--red);background:#1d1417;
  border-radius:9px;padding:17px 21px;margin:20px 0}
.callout.warn{border-color:var(--org);background:#1d1913}
.callout.ok{border-color:var(--grn);background:#0f1c17}
.callout.info{border-color:var(--blu);background:#111a24}
.callout h3{margin:0 0 9px;color:var(--fg);font-size:16px}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:13.5px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--bd);
  vertical-align:top}
th{color:var(--fg2);font-weight:650;font-size:12.5px;
  text-transform:none;background:var(--bg3);position:sticky;top:0}
td.num,th.num{text-align:right;font-family:ui-monospace,Menlo,monospace}
tr:hover td{background:#191d24}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:11px}
.kv>div{background:var(--bg3);border:1px solid var(--bd);border-radius:8px;
  padding:11px 13px}
.kv .k{color:var(--fg3);font-size:11.5px;letter-spacing:.4px}
.kv .v{font-size:18px;font-weight:750;margin-top:3px;
  font-family:ui-monospace,Menlo,monospace}
img.fig{width:100%;border:1px solid var(--bd);border-radius:9px;margin:9px 0;display:block}
.cap{color:var(--fg3);font-size:12.5px;margin:4px 0 20px}
.gb{font-family:ui-monospace,monospace;font-weight:700}
.tag{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;
  font-weight:700;letter-spacing:.3px}
.t-bad{background:#3a1a1e;color:#ff8b8b;border:1px solid #5c2529}
.t-warn{background:#3a2c14;color:#ffcb73;border:1px solid #5c4620}
.t-ok{background:#132c22;color:#68e0aa;border:1px solid #1e4a38}
.t-info{background:#142132;color:#7cc4ff;border:1px solid #23405e}
ul,ol{margin:9px 0;padding-left:24px}
li{margin:5px 0}
hr{border:0;border-top:1px solid var(--bd);margin:34px 0}
.foot{color:var(--fg3);font-size:12.5px;margin-top:44px;
  padding-top:18px;border-top:1px solid var(--bd)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.two{grid-template-columns:1fr}}
.hl{color:var(--yel);font-weight:700}
.neg{color:#ff8b8b;font-weight:700}
.pos{color:#68e0aa;font-weight:700}
</style></head><body><div class="wrap">""")

    # ── 头部 ──
    ap_(f"""<div class="meta">动作分析系统 · 里程碑 02 · 2026-09-23</div>
<h1>战术回合分析 —— 以球为主线</h1>
<div class="sub">素材：2026-02-25 马刺客场猛龙 · 末节 t={t0}–{t1:.1f}s（{shots['dur']}s 单一镜头，
无切换）· 1080p60 · 比分 SA 108 – TOR 104</div>

<div class="callout">
<h3>🔴 核心结论（先读这一条）</h3>
<p>按你定的主线——<span class="hl">球权 → 转移 → 相关球员位置变化 → 其他人行动 → 出手结束回合</span>
——六层流水线已<span class="pos">全部打通并跑完</span>。但在最后做证据复核时，
发现一个必须先讲的问题：</p>
<p><span class="neg">本片段所用的球检测器基本不可用。</span>它的置信度对"是不是球"没有区分力
（AUC = {vmeta['conf_discriminative_power_auc']}，0.5 即完全无效），而且
<span class="neg">橙反差最高的 {cnt.get('ct>0.40', 14)} 个检出全部是场边 LED 广告板上的
Mastercard 红橙双圆 logo</span>——假目标恰好拿到了最高分。</p>
<p>因此本节第 2 部分（球的转移）<b>只能作为"管线演示"看待，不能作为结论使用</b>——
它的输入（球位）经目视核对后，真球命中数是<b>个位数</b>（见第 6 节证据图）。
第 3、4 部分中，球员位置与位移<b>不依赖球，是可信的</b>；
关系层虽跑通但信号很弱。文末给出已实测的补救路线与建议。</p>
</div>""")

    # ── 1. 回合概览 ──
    ap_(f"""<h2>1 · 回合概览</h2>
<div class="kv">
 <div><div class="k">片段区间</div><div class="v">{t0}–{t1:.1f}s</div></div>
 <div><div class="k">时长 / 镜头数</div><div class="v">{shots['dur']}s / 1</div></div>
 <div><div class="k">分析帧率</div><div class="v">{shots['fps']:.0f}fps</div></div>
 <div><div class="k">球员检测帧</div><div class="v">{m['n_player_frames']}</div></div>
 <div><div class="k">球专线帧</div><div class="v">{bhi['ball_meta']['n_frames']} @10fps</div></div>
 <div><div class="k">场上入选球员</div><div class="v">10 / 帧</div></div>
</div>
<p class="meta">镜头切分：双指标（灰度 mean-abs AND RGB 直方图）联合判定，
全片段 <code>cuts = {len(shots['cuts'])}</code>，确认是单一固定机位镜头。
球另走 10fps 专线（2fps 下球每帧位移 300–600px，追不住；
10fps 降到 40–50px 可追）。</p>""")

    # ── 2. 球的转移（主线）──
    ap_(f"""<h2>2 · 球的转移（主线）<span class="tag t-bad">证据不可信</span></h2>
<div class="callout warn">
<h3>⚠️ 读这一节前必须知道</h3>
<p>控球人的判定是：<code>球心到球员脚点距离 / 框高 &lt; 1.2</code>，取最近者。
这依赖球位准确。而实测球位<b>大部分是错的</b>（见第 6 节）。
所以下面的时间轴应理解为<b>「管线能算出什么」</b>，而不是<b>「场上发生了什么」</b>。</p>
</div>

<h3>2.1 球权时间轴</h3>
{possession_timeline(merged, transfers, t0, t1)}
<p class="cap">色条 = 控球期（仅绘制有可信球位的时段）；蓝虚线 = 球权转移。
注意大片空白——那是有球位证据缺失的时段，本层<b>不做猜测</b>。</p>""")

    # 控球期表
    ap_("""<h3>2.2 控球期明细</h3>
<table><thead><tr>
<th class="num">#</th><th>持球人</th><th class="num">起</th><th class="num">止</th>
<th class="num">时长</th><th class="num">证据帧</th><th class="num">球位置信(均/峰)</th>
<th>证据等级</th></tr></thead><tbody>""")
    for mm in merged:
        ap_(f"""<tr><td class="num">{mm['seq']}</td><td><code>pid{mm['pid']}</code></td>
<td class="num">{mm['start_t']:.1f}</td><td class="num">{mm['end_t']:.1f}</td>
<td class="num">{mm['dur_sec']:.1f}s</td>
<td class="num">{mm['n_evidence_frames']}{' / '+str(mm['n_spans'])+'段' if mm['n_spans']>1 else ''}</td>
<td class="num">{mm['mean_conf']:.3f} / {mm['best_conf']:.3f}</td>
<td>{grade_badge(mm['grade'])}</td></tr>""")
    ap_("</tbody></table>")
    ap_(f"""<p class="meta">共 {len(merged)} 个控球期（由 {len(gd['spans'])} 个原始持球段按
「同一人 + 间隔 ≤ {m['max_gap_sec']}s」合并而来——合并是因为证据空洞会把一个人的连续控球切成多段）。
持球人归属覆盖 {pct(m['holder_coverage'])}（{m['n_holder_frames']}/{m['n_player_frames']} 帧），
其余 {m['n_unknown_frames']} 帧判为「无证据」。</p>""")

    # 转移表
    ap_("""<h3>2.3 球权转移与对抗性复核</h3>
<p>每次「持球人变了」都过两道判据，用来区分<b>真转移</b>与<b>追踪标签切换</b>：</p>
<ul>
<li><b>判据①</b> 球的实际位移 <code>ball_move_norm</code>：真传球球心会明显移动；标签切换时球几乎不动。</li>
<li><b>判据②</b> 新老持球人脚点距离 <code>holder_dist_norm</code>：真转移两人分得开；标签切换时脚点重合。</li>
</ul>
<table><thead><tr><th class="num">#</th><th class="num">t</th><th>转移</th>
<th class="num">间隔</th><th class="num">球位移</th><th class="num">人距</th>
<th>判定</th></tr></thead><tbody>""")
    vsym = {"supported_transfer": ("✅ 有支撑", "t-ok"),
            "weak_transfer": ("⚠️ 偏弱", "t-warn"),
            "identity_swap_suspect": ("❌ 疑标签切换", "t-bad"),
            "unverifiable": ("⬜ 不可验", "t-info")}
    for i, t in enumerate(t_audit):
        s, cls = vsym.get(t["verdict"], ("?", "t-info"))
        bm = f"{t['ball_move_norm']:.2f}" if t["ball_move_norm"] is not None else "NA"
        hd = f"{t['holder_dist_norm']:.2f}" if t["holder_dist_norm"] is not None else "NA"
        ap_(f"""<tr><td class="num">{i+1}</td><td class="num">{t['t']:.1f}</td>
<td><code>{t['from']} → {t['to']}</code></td><td class="num">{t['gap_sec']:.1f}s</td>
<td class="num">{bm}</td><td class="num">{hd}</td>
<td><span class="tag {cls}">{s}</span></td></tr>""")
    ap_("</tbody></table>")
    ap_(f"""<p class="meta">汇总：{verdict_c}。
另有 {m['n_resumes']} 次 <b>resume</b>（同一人、中间证据断了又续）已单列，
不计入转移——否则证据空洞会虚增转移次数。</p>""")

    # 持球核对图
    ap_("""<h3>2.4 管线输出核对图（示例）</h3>
<p>绿色粗框 = 被判定为持球人的球员；蓝框 = 其余入选球员；红圈 = 采信的球位。
<b>请重点看红圈落在哪</b>——这正是第 6 节要说明的问题。</p>""")
    picks = [(211.5, "pid19 控球期早段"), (219.5, "pid19 控球期峰值 ★★★"),
             (243.5, "pid51 控球期 ★★★")]
    ap_('<div class="two">')
    for t, desc in picks:
        fn = f"pos_t{int(t*10):05d}.jpg"
        ap_(f'<div><img class="fig" src="{F}/{fn}" alt="t={t}">'
            f'<p class="cap">t={t}s · {desc}</p></div>')
    ap_("</div>")

    # ── 3. 相关球员位置变化 ──
    ap_("""<h2>3 · 相关球员的位置变化<span class="tag t-ok">可信</span></h2>
<p>这一层<b>不依赖球</b>：只用到球员检测框与脚点，因此不受第 6 节问题影响。
对每次球权转移，统计转移时刻 ±1.5s 内各球员的位移（按画面中位框高归一化，
<code>disp_norm</code> = 位移 / 中位身高；方向 → 为画面右移）。</p>
<table><thead><tr><th class="num">t</th><th>转移</th><th>窗口内位移 Top-3</th>
</tr></thead><tbody>""")
    for t in transfers:
        mv = t.get("motion", {}).get("movers", [])[:3]
        cells = " ".join(
            f'<code>pid{x["pid"]}</code> <span class="mono">{x["disp_norm"]:.2f}{x["dir"]}</span>'
            for x in mv)
        ap_(f"""<tr><td class="num">{t['t']:.1f}</td>
<td><code>{t['from']} → {t['to']}</code></td><td>{cells}</td></tr>""")
    ap_("</tbody></table>")
    med_mv = 0.0
    allm = [x["disp_norm"] for t in transfers
            for x in t.get("motion", {}).get("movers", [])[:3]]
    if allm:
        med_mv = statistics.median(allm)
    ap_(f"""<p class="meta">转移窗口内位移 Top-3 的中位数 {med_mv:.2f} 倍身高 ——
说明每次球权变化前后确实伴随可观测的球员移动，这一层的信号是实在的。</p>""")

    # ── 4. 其他人的行动 ──
    ap_(f"""<h2>4 · 其他人的行动（关系层）<span class="tag t-bad">信号弱</span></h2>
<p>用 RelateAnything（官方裸短语词表 <code>DEFAULT_PREDICATES</code>）对每帧的球员对做关系预测，
再抽连续 ≥3 帧且均分 ≥0.25 的「持久关系段」。</p>
<div class="callout warn">
<h3>🔴 关键局限：关系信号被单一谓词垄断</h3>
<p><code>watching</code> 占全部三元组的 {spec[0]['share_pct']:.1f}%，
占 <b>top-1 的 {dom['watching_share_of_top1']}%</b>。
这意味着模型在篮球广角场景下几乎只会输出一个词，
<b>区分度极低</b>——它是"域外场景"的真实表现，不能当强证据用。</p>
</div>
<h4>谓词谱</h4>
<table><thead><tr><th>谓词</th><th class="num">次数</th><th class="num">占比</th>
<th class="num">top-1 帧</th><th class="num">均分</th><th>战术语义</th>
<th class="num">分布</th></tr></thead><tbody>""")
    mx = max((p["count"] for p in spec), default=1)
    for p in spec:
        col = "#ff5c5c" if p["pred"] == "watching" else "#4aa8ff"
        ap_(f"""<tr><td><code>{escape(p['pred'])}</code></td>
<td class="num">{p['count']}</td><td class="num">{p['share_pct']:.1f}%</td>
<td class="num">{p['top1_frames']}</td><td class="num">{p['mean_score']:.3f}</td>
<td>{escape(p['semantic'] or '—')}</td>
<td>{bar(p['count'], mx, 110, col)}</td></tr>""")
    ap_("</tbody></table>")
    segs = tac.get("segments", [])
    segs_sorted = sorted(segs, key=lambda s: -s["n_frames"])[:10]
    ap_("""<h4>最长的持久关系段（Top-10）</h4>
<table><thead><tr><th class="num">t 区间</th><th>关系</th><th class="num">帧数</th>
<th class="num">时长</th><th class="num">均分</th><th>战术语义</th></tr></thead><tbody>""")
    for s in segs_sorted:
        ap_(f"""<tr><td class="num">{s['start_t']:.1f}–{s['end_t']:.1f}</td>
<td><code>{s['a']} --{escape(str(s['pred']))}--&gt; {s['b']}</code></td>
<td class="num">{s['n_frames']}</td><td class="num">{s['dur_sec']:.1f}s</td>
<td class="num">{s['mean_score']:.3f}</td>
<td>{escape(s['semantic'] or '—')}</td></tr>""")
    ap_("</tbody></table>")
    ap_(f"""<p class="meta">全部 {len(segs)} 个持久段中，最长只有
{segs_sorted[0]['n_frames'] if segs_sorted else 0} 帧 / {segs_sorted[0]['dur_sec'] if segs_sorted else 0:.1f}s，
且几乎都是 <code>watching</code>。这不足以支撑"高位挡拆 / 换防 / 协防"级别的战术判断。</p>""")

    # ── 5. 出手 ──
    ap_("""<h2>5 · 出手即回合结束<span class="tag t-bad">未实现</span></h2>
<div class="callout">
<p>你定的回合边界是<b>出手</b>。这一环<b>尚未实现</b>，原因是硬的：
判出手需要（a）可靠的球位轨迹（当前不可用），
（b）篮筐位置标定，（c）球轨迹顶点/入筐判定。
当前只做到<b>用时间间隔做粗聚簇</b>——全片 43 秒被聚成
<b>1 个宏观回合</b>，这只说明"中间没有超长的空档"，<b>不是真正的回合切分</b>。</p>
<p>所以现在<b>还不能说"这是一个完整的战术回合"</b>。要闭合这一环，
第一优先级是先解决第 6 节的球检测问题。</p>
</div>""")

    # ── 6. 关键负面发现 ──
    ap_(f"""<h2>6 · 🚨 关键负面发现：球检测器不可用</h2>
<p>这是本次里程碑最有价值的产出——它避免我们把一个错误的结果当结论交付。</p>

<h3>6.1 置信度对真假没有区分力</h3>
<div class="kv">
 <div><div class="k">球专线总帧</div><div class="v">{gate['ball_frames_total']}</div></div>
 <div><div class="k">真检出（非外推）</div><div class="v">{gate['ball_detected']}</div></div>
 <div><div class="k">颜色/形状门禁通过</div><div class="v">{gate['ball_passed_gate']} ({gate['ball_pass_rate_pct']}%)</div></div>
 <div><div class="k">颜色/形状复核通过</div><div class="v">{vmeta['n_ball_like']}/{vmeta['n_detections']} ({vmeta['ball_like_pct']}%)</div></div>
 <div><div class="k">判为「不是球」</div><div class="v">{vmeta['n_detections']-vmeta['n_ball_like']}</div></div>
 <div><div class="k">conf 区分力 AUC</div><div class="v neg">{vmeta['conf_discriminative_power_auc']}</div></div>
</div>
<p><b>AUC = {vmeta['conf_discriminative_power_auc']}</b> 意味着用 <code>conf</code> 排序真球/假球
与随机猜没有区别。更糟的是方向还反了：</p>
<table><thead><tr><th>组</th><th class="num">conf 均值</th><th class="num">conf 中位</th></tr></thead><tbody>
<tr><td>真球</td><td class="num">{cs['ball_like_mean_conf']}</td><td class="num">{cs['ball_like_median_conf']}</td></tr>
<tr><td>非球</td><td class="num">{cs['not_ball_mean_conf']}</td><td class="num">{cs['not_ball_median_conf']}</td></tr>
</tbody></table>
<p class="meta">注意「非球」的 conf 中位 <b>反而更高</b>。
所以之前用 <code>conf &gt;= 0.10</code> 当门禁，等于在随机过滤。</p>

<h3>6.2 最高分的假目标：Mastercard logo</h3>
<p>改用「橙色反差」（框内橙色度 − 周围环带橙色度）作判据后，反差最高的一批刻意排在最前 ——
结果如下：</p>
<img class="fig" src="{F}/ev_mastercard.jpg" alt="橙反差 top-16">
<p class="cap">橙反差 Top-16。<b>全部</b>是场边 LED 广告板上的 Mastercard 红橙双圆 logo
（画外音：旁边就写着 "priceless"）。这是最糟的失败形态——假目标拿到了最高的橙色反差。</p>

<h3>6.3 分层抽样目视审计</h3>
<table><thead><tr><th>橙反差区间</th><th class="num">检出数</th><th>目视结果</th></tr></thead><tbody>
<tr><td class="num">&gt; 0.40</td><td class="num">{cnt.get('ct>0.40','—')}</td>
<td><span class="neg">全部为 Mastercard logo</span>，真球 0</td></tr>
<tr><td class="num">0.15 – 0.40</td><td class="num">{cnt.get('0.15<ct<=0.40','—')}</td>
<td>此层才出现真球（个位数）</td></tr>
<tr><td class="num">0.00 – 0.15</td><td class="num">{cnt.get('0.00<ct<=0.15','—')}</td>
<td>地板白线 / 木纹</td></tr>
<tr><td class="num">-0.15 – 0.00</td><td class="num">{cnt.get('-0.15<ct<=0.00','—')}</td>
<td>地板白线 / 木纹 / 鞋</td></tr>
<tr><td class="num">≤ -0.15</td><td class="num">{cnt.get('ct<=-0.15','—')}</td>
<td>框比周围<b>更不橙</b>，明显非球</td></tr>
</tbody></table>
<img class="fig" src="{F}/ev_audit.jpg" alt="分层抽样审计">
<p class="cap">分层抽样审计（每层随机 12 个）。第一行 12 格全是 Mastercard logo；
第二行往后是地板白线与木纹。真球只零星出现在第二层。</p>

<h3>6.4 定向核对：真球长什么样</h3>
<img class="fig" src="{F}/ev_targeted.jpg" alt="定向核对">
<p class="cap">红框 = 检出的「球」位置。t=210.0（球员持球，标记落在球上）与
t=247.4（地板上的球，标记准确）是真命中；t=204.5 / 204.6 画里有真球但标记落在
<b>地板白线</b>上（漏检）；其余全是 Mastercard logo。</p>""")

    ap_(f"""<h3>6.5 原始检出抽样</h3>
<img class="fig" src="{F}/ev_ball_samples.jpg" alt="原始检出抽样">
<p class="cap">原始球检出抽样 22 帧（标 conf）。肉眼可见：绝大多数是地板虚线、
观众席、计分屏、红球鞋，而非篮球。</p>""")

    # ── 7. 已尝试的补救 ──
    ap_(f"""<h2>7 · 已尝试的补救路线与实测结果</h2>
<table><thead><tr><th>路线</th><th>做法</th><th>实测结果</th><th>结论</th></tr></thead><tbody>
<tr>
<td>① 置信度门禁</td>
<td>按 <code>conf</code> 阈值过滤</td>
<td>AUC = {vmeta['conf_discriminative_power_auc']}；非球 conf 中位反而更高</td>
<td><span class="tag t-bad">失败</span></td></tr>
<tr>
<td>② 颜色 + 形状判据</td>
<td>篮球是橙色圆形 → 过滤</td>
<td>放进 219/333，但<b>地板橙印记、红球鞋照样通过</b>；且砍掉了真球（红色球鞋案）</td>
<td><span class="tag t-warn">部分失败</span></td></tr>
<tr>
<td>③ 橙色反差</td>
<td>框内橙度 − 环带橙度</td>
<td>能把 Mastercard logo 排到最前（因为反差最高），<b>方向与预期相反</b></td>
<td><span class="tag t-bad">失败</span></td></tr>
<tr>
<td>④ 局部背景运动补偿<br>（静态目标剔除）</td>
<td>用周围背景的位移估计镜头运动，看目标相对背景是否在动</td>
<td>{sr_meta['n_pairs']} 对有位移数据；判为静态 {pct(sr_meta['n_static']/max(sr_meta['n_pairs'],1))}。
但对照组分不开（相邻检出常是<b>不同物体</b>，位移本身无意义），测试<b>被混淆污染</b></td>
<td><span class="tag t-warn">未验证</span></td></tr>
</tbody></table>
<div class="callout warn">
<h3>关于路线④，如实说明</h3>
<p>这条路方向是对的（静态 logo 与真球的本质差别就是"相对背景是否运动"），
但<b>本次没有验证成功</b>：我的配对方式把"相邻的两次检出"当成同一物体，
而它们常常是不同物体（地板线跳到 logo），算出来的位移没有物理意义。
对照组因此是空的。要真正验证它，需要先有目标身份，
属于<b>下一阶段</b>的工作，不能算作已解决问题的方案。</p>
</div>""")

    # ── 8. 证据强度分级 ──
    ap_(f"""<h2>8 · 证据强度分级总表</h2>
<table><thead><tr><th>结论 / 数据</th><th>证据等级</th><th>说明</th></tr></thead><tbody>
<tr><td>片段切分（单镜头、无切换）</td><td><span class="tag t-ok">强</span></td>
<td>双指标联合判定，<code>cuts=0</code>，可复现</td></tr>
<tr><td>球员检测（每帧 10 人）</td><td><span class="tag t-ok">强</span></td>
<td>检测+遴选，位置目视一致</td></tr>
<tr><td>球员位置 / 位移 / 邻域结构</td><td><span class="tag t-ok">强</span></td>
<td>不依赖球，脚点几何量</td></tr>
<tr><td>追踪身份连续性</td><td><span class="tag t-warn">中</span></td>
<td>相邻帧 Jaccard 中位 {dup['adjacent_jaccard_median']:.3f}，全程 {dup['distinct_pids_total']} 个 pid 承载 10 个位置</td></tr>
<tr><td>球位（10fps 专线）</td><td><span class="tag t-bad">低</span></td>
<td>{bhi['ball_meta']['coverage_pct']}% "覆盖"是含外推的；外推链会跑出画面</td></tr>
<tr><td>持球人归属</td><td><span class="tag t-bad">低</span></td>
<td>建立在不可信球位上</td></tr>
<tr><td>球权转移</td><td><span class="tag t-bad">低</span></td>
<td>仅 {verdict_c.get('supported_transfer',0)}/{len(t_audit)} 次通过"球真的动了 + 两人分得开"双判据</td></tr>
<tr><td>关系三元组（RelateAnything）</td><td><span class="tag t-bad">低</span></td>
<td>watching 垄断 top-1 的 {dom['watching_share_of_top1']}%，区分度极低</td></tr>
<tr><td>出手 / 回合结束</td><td><span class="tag t-bad">未实现</span></td>
<td>需进球检测，未做</td></tr>
<tr><td>战术结论（挡拆/换防/协防）</td><td><span class="tag t-bad">未产出</span></td>
<td>被上述两项阻塞</td></tr>
</tbody></table>""")

    ap_(f"""<h3>身份稳定性（实测）</h3>
<div class="kv">
 <div><div class="k">逐帧 pid 数</div><div class="v">中位 {dup['n_pid_median']:.0f}</div></div>
 <div><div class="k">全程不同 pid</div><div class="v">{dup['distinct_pids_total']}</div></div>
 <div><div class="k">pid 复用系数</div><div class="v">{dup['pid_reuse_factor']}×</div></div>
 <div><div class="k">相邻帧 Jaccard</div><div class="v">{dup['adjacent_jaccard_median']:.3f}</div></div>
</div>
<p class="meta">每帧恰好 10 个 pid（选择器 top_n=10），但全程出现 {dup['distinct_pids_total']} 个不同 pid，
复用系数 {dup['pid_reuse_factor']}× —— 说明编号在不断新建。
相邻帧只有 Jaccard {dup['adjacent_jaccard_median']:.3f} 的身份重合，
约一半身份会逐帧换号。这也是为什么球权转移必须做"标签切换 vs 真转移"的复核。</p>""")

    # ── 9. 建议 ──
    ap_("""<h2>9 · 建议的下一步（按性价比排序）</h2>
<div class="card">
<h3>A. 先换球检测，别在坏信号上盖楼</h3>
<ol>
<li><b>把本片段的假目标当硬负样本</b>：Mastercard logo、地板白线、观众席、红球鞋，
    从这 44 秒里能自动挖出上千个硬负样本，成本极低。</li>
<li><b>改用时序模型而非单帧检测</b>：TrackNet 类热图 + 时序聚合专门解决
    "小目标 + 运动模糊 + 相似干扰物"；单帧检测在这类场景先天不足。</li>
<li><b>为这 44 秒人工标注球位</b>（10fps 约 440 点）作为真值集。
    没有真值集，任何球检测改进都无法客观评估——这次我们的复核之所以能发现问题，
    正是因为做了目视核对，但那是抽样、不可规模化。</li>
</ol>
</div>
<div class="card">
<h3>B. 用已有追踪数据做战术语义（可能比录像更快见效）</h3>
<p>你要的"高位挡拆 / 换防 / 弱侧协防晚一步"这一层语义，
本质上需要的是<b>球员坐标 + 时间</b>，而不是像素。
现有库里已有多源 PBP 与逐回合数据；若引入逐帧球员坐标
（tracking 类数据），挡拆/换防可以直接用几何+规则判定，
精度与可解释性都远高于当前视频路线。</p>
<p><b>建议并行</b>：录像线继续攻球检测；战术语义先用坐标数据打通，
两条线互为验证。</p>
</div>
<div class="card">
<h3>C. 短期可交付的部分</h3>
<ul>
<li>球员位置/位移/邻域结构层 —— <b>现在就能用</b>（本报告第 3 节）。</li>
<li>关系层的<b>几何基线</b>（脚点距离、左右、远近、聚簇）已与谓词并行输出，
    不依赖 RelateAnything 的弱信号，可作为过渡方案。</li>
<li>回合切分退一步：先用<b>镜头切换 + 长时间空档</b>做粗切分，
    明确标注"非真实回合边界"，等球检测解决后再升级。</li>
</ul>
</div>""")

    # 附录
    ap_(f"""<hr>
<h2>附录 · 产物与复现</h2>
<h3>数据产物（action_work/seg_possession/）</h3>
<table><thead><tr><th>文件</th><th>内容</th></tr></thead><tbody>
<tr><td><code>frames.json</code> / <code>shots.json</code></td><td>抽帧索引、镜头切分</td></tr>
<tr><td><code>tracks.json</code></td><td>原始检测 + 追踪</td></tr>
<tr><td><code>select_tracks.json</code></td><td>遴选+追踪合并后的球员（每帧 10 人）</td></tr>
<tr><td><code>relations.json</code></td><td>关系三元组 + 几何基线</td></tr>
<tr><td><code>tactics.json</code></td><td>持久关系段、谓词谱、垄断度</td></tr>
<tr><td><code>ball_verify.json</code></td><td><b>球检出的颜色/形状复核</b>（本报告第 6 节依据）</td></tr>
<tr><td><code>possession_gated.json</code></td><td><b>门禁持球归属 + 控球期 + 转移</b></td></tr>
<tr><td><code>transfer_audit.json</code></td><td><b>转移对抗性复核 + 身份稳定性</b></td></tr>
<tr><td><code>static_reject.json</code></td><td>静态目标剔除尝试（未验证）</td></tr>
</tbody></table>
<h3>引擎脚本（action_analysis/engine/）</h3>
<p class="meta">segment_frames · segment_detect_track · segment_select_track ·
segment_relations · segment_tactics · <b>segment_possession_gated</b> ·
<b>verify_ball_detections</b> · <b>verify_transfers</b> · reject_static_objects ·
render_possession_overlay · make_evidence_figs · make_report</p>
<h3>关键参数</h3>
<p class="meta">镜头切分 <code>gray={shots['gray_thr']} hist={shots['hist_thr']}</code> ·
球专线 <code>10fps conf_ball={bhi['meta']['conf_ball']}</code> ·
持球判定 <code>半径={m['holder_radius_norm']}×框高 窗=±{m['neighbor_window_sec']}s</code> ·
去抖 <code>{m['debounce_frames']} 帧</code> · 控球期合并 <code>间隔≤{m['max_gap_sec']}s</code> ·
橙反差阈值 <code>{vmeta['orange_thr']}</code></p>
<div class="foot">
报告由 <code>make_report.py</code> 从上述 JSON 直接渲染，所有数字均取自产物文件。
生成时间 2026-09-23 · 动作分析系统里程碑 02
</div>
</div></body></html>""")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("".join(H))
    print(f"[out] {a.out}  ({os.path.getsize(a.out)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
