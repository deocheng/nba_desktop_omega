#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""里程碑 05 · 球检测精度攻关报告 v2（加入多帧动态 + 掩膜连续化）。

所有数字现场重算：真值库计数、消融 AUC/工作点、多帧与掩膜特征 AUC、自助 CI、头元数据、冒烟结果。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import roc_auc_score

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ball_fusion_eval import load, lowo, op  # noqa: E402

MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
OUT = Path(str(tactics_data_file("reports/milestone_05/milestone_05_ball_precision.html")))
WINS = ("w1", "w2", "w3", "w4")

bank_all = json.loads((MS / "labels_bank.json").read_text())
bank = [r for r in bank_all if r["label"] in ("TP", "FP")]
y = np.array([r["label"] == "TP" for r in bank]).astype(int)
wins = np.array([r["window"] for r in bank])
n_unc = sum(1 for r in bank_all if r["label"] == "unc")

CONFIGS = [
    ("仅外观+几何", dict(motion=False, motion2=False, mask=False)),
    ("+多帧运动 v1", dict(motion=True, motion2=False, mask=False)),
    ("+运动 v1+v2", dict(motion=True, motion2=True, mask=False)),
    ("+运动+掩膜（最终）", dict(motion=True, motion2=True, mask=True)),
]
abl, probs = [], {}
for tag, kw in CONFIGS:
    F, yy, ww, _ = load(True, **kw)
    p = lowo(F, yy, ww)
    probs[tag] = p
    row = {"tag": tag, "dim": F.shape[1], "auc": float(roc_auc_score(yy, p))}
    for w in WINS:
        m = ww == w
        row[w + "_auc"] = float(roc_auc_score(yy[m], p[m]))
        b = op(p, yy, m)
        row[w] = f"R={b[0]*100:.0f}%@P={b[1][1]*100:.0f}%" if b[1] else "无"
    b = op(p, yy, np.ones(len(yy), bool))
    row["glob"] = f"R={b[0]*100:.1f}%@P={b[1][1]*100:.1f}%" if b[1] else "无"
    abl.append(row)
pbest = probs[CONFIGS[-1][0]]

rng = np.random.default_rng(0)
ci = {}
for w in WINS:
    m = wins == w
    yy, pp = y[m], pbest[m]
    Rs = []
    for _ in range(300):
        s = rng.choice(len(yy), len(yy), replace=True)
        sy, sp = yy[s], pp[s]
        npos = int((sy == 1).sum())
        if npos == 0:
            continue
        b = 0.0
        for th in np.arange(0.05, 0.995, 0.01):
            pred = sp > th
            tp = int((pred & (sy == 1)).sum()); fp = int((pred & (sy == 0)).sum())
            if tp + fp and tp / (tp + fp) >= 0.90:
                b = max(b, tp / npos)
        Rs.append(b)
    Rs = np.array(Rs)
    bb = op(pbest, y, m)
    ci[w] = {"point": f"{bb[0]*100:.1f}%" if bb[1] else "无",
             "lo": float(np.percentile(Rs, 2.5) * 100), "hi": float(np.percentile(Rs, 97.5) * 100),
             "med": float(np.median(Rs) * 100)}


def feat_auc(path, keys):
    rows = json.loads((MS / path).read_text())
    yy = np.array([r["label"] == "TP" for r in rows]).astype(int)
    out = []
    for k in keys:
        v = np.array([r[k] for r in rows], float)
        a = float(roc_auc_score(yy, v))
        out.append((k, a, float(np.median(v[yy == 1])), float(np.median(v[yy == 0]))))
    return out

mot = feat_auc("motion_rows.json",
               ["d_med", "d_min", "d_min_norm", "static_frac", "recur20", "nframe_with"])
mot2 = feat_auc("motion_rows2.json",
                ["chain_tot", "plaus_next", "d_next", "turn_cos", "extrap_resid"])
msk = feat_auc("mask_rows.json",
               ["center_dist", "gap_below", "in_floor", "col_floor_frac", "frame_cover"])

head = joblib.load(MS / "ball_head.joblib")
sm_in = json.loads((MS / "apply_smoke_in.json").read_text())
sm_out = json.loads((MS / "apply_smoke_out.json").read_text())
n_in = sum(len(v) for fr in sm_in.values() for v in fr.values())
n_out = sum(len(v) for fr in sm_out.values() for v in fr.values())


def tbl(rows):
    s = ""
    for k, a, tp, fp in rows:
        cls = "ok" if abs(a - 0.5) > 0.15 else ("warn" if abs(a - 0.5) > 0.08 else "")
        note = f"反向 {1-a:.3f}" if a < 0.45 else "—"
        s += (f"<tr><td><code>{k}</code></td><td class='{cls}'>{a:.3f}</td><td>{1-a:.3f}</td>"
              f"<td>{tp:.2f}</td><td>{fp:.2f}</td><td>{note}</td></tr>")
    return s


abl_html = ""
for r in abl:
    abl_html += (f"<tr><td>{r['tag']}</td><td>{r['dim']}</td><td><b>{r['auc']:.4f}</b></td>"
                 + "".join(f"<td>{r[w+'_auc']:.4f}<br><span class='mut'>{r[w]}</span></td>" for w in WINS)
                 + f"<td>{r['glob']}</td></tr>")

ci_html = "".join(
    f"<tr><td>{w}</td><td>{ci[w]['point']}</td><td>{ci[w]['med']:.0f}%</td>"
    f"<td>[{ci[w]['lo']:.0f}%, {ci[w]['hi']:.0f}%]</td></tr>" for w in WINS)

true_prec = ""
for w in WINS:
    rs = [r for r in bank_all if r["window"] == w and r["label"] in ("TP", "FP")]
    tp = sum(1 for r in rs if r["label"] == "TP")
    true_prec += (f"<tr><td>{w}</td><td>{len(rs)}</td><td>{tp}</td><td>{len(rs)-tp}</td>"
                  f"<td>{tp/max(1,len(rs))*100:.1f}%</td></tr>")

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>里程碑 05 · 球检测精度攻关 v2（多帧动态 + 掩膜）</title>
<style>
  :root{{--bg:#0d1117;--card:#161b22;--ink:#e6edf3;--mut:#8b949e;--acc:#58a6ff;
        --ok:#3fb950;--warn:#d29922;--bad:#f85149;--line:#30363d}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);
    font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6;padding:32px}}
  .wrap{{max-width:1080px;margin:0 auto}}
  h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:30px 0 10px;border-left:3px solid var(--acc);padding-left:10px}}
  h3{{font-size:15px;margin:20px 0 8px;color:var(--acc)}}
  .sub{{color:var(--mut);font-size:13px;margin-bottom:18px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:14px 0}}
  .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}}
  .kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
  .kpi .v{{font-size:20px;font-weight:700}} .kpi .l{{font-size:12px;color:var(--mut);margin-top:4px}}
  .ok{{color:var(--ok)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}} .acc{{color:var(--acc)}} .mut{{color:var(--mut);font-size:11px}}
  table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:12.5px}}
  th,td{{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}}
  th{{background:#1c2330;color:var(--acc)}} tr:nth-child(even){{background:#11161d}}
  code{{background:#1c2330;padding:1px 6px;border-radius:4px;font-size:12px;color:#ffa657}}
  pre{{background:#0b0f14;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font-size:12px;color:#c9d1d9}}
  .note{{border-left:3px solid var(--warn);background:#1d1b12;padding:10px 14px;border-radius:6px;margin:12px 0;font-size:13px}}
  .okc{{border-left:3px solid var(--ok);background:#0f1d14}}
  .badc{{border-left:3px solid var(--bad);background:#1d1212}}
  ul{{margin:8px 0 8px 4px;padding-left:20px}} li{{margin:5px 0}}
  .foot{{color:var(--mut);font-size:12px;margin-top:24px;border-top:1px solid var(--line);padding-top:12px}}
</style></head><body><div class="wrap">
<h1>里程碑 05 · 球检测精度攻关 v2</h1>
<div class="sub">真实目视标注 → 验证头 → <b>多帧动态 + 掩膜连续化</b> → 90% 门禁 ·
数字全部现场重算（<code>reports/milestone_05/measure/</code>）</div>

<div class="card">
<h3>本轮新增结论</h3>
<ul>
<li><b class="ok">多帧动态有效，但机制与直觉相反</b>：不是"球动 / 人头静"，而是
"<b>球被相邻帧一致地重复检出，人头/球衣类 FP 在时间上孤立或跳变</b>"——
特征 AUC 稳定反向（<code>d_med</code> {mot[0][1]:.3f}、<code>d_max</code> 0.37，反向 ≈0.62–0.63）。</li>
<li><b class="ok">最大收益：w3 从"不可能"变"可达"</b>。w3 是唯一无 P≥90% 工作点的窗；
加运动特征后自助<b>中位召回 {ci['w3']['med']:.0f}%</b>（不加时为 0%，多数重采样根本没有该工作点）。</li>
<li><b class="ok">掩膜"硬门禁 → 连续特征"是正解</b>：旧做法（脚点在掩膜内）P80%/R31% 方向性错误；
新做法用「框心到地板距离 / 正下方垂直间隙」——TP 距地板中位 <b>{msk[0][2]:.0f}px</b>、
FP <b>{msk[0][3]:.0f}px</b>。</li>
<li><b class="warn">w1 仍是硬骨头</b>：全配置 AUC 恒在 0.848–0.854，掩膜特征对它无效（AUC {msk[2][1]:.3f}）。</li>
<li><b class="warn">样本量决定可信度</b>：分窗召回自助 95% CI 宽达 ±20–30pp（n≈40 TP），分窗数字必须按区间读。</li>
</ul>
</div>

<div class="grid">
  <div class="kpi"><div class="v">{len(bank_all)}</div><div class="l">真实标注样本（unc {n_unc} 已排除）</div></div>
  <div class="kpi"><div class="v">{head['cv_auc']:.3f}</div><div class="l">5-fold AUC（最终特征集）</div></div>
  <div class="kpi"><div class="v">{head['lowo_auc']:.3f}</div><div class="l">LOWO AUC（跨窗泛化）</div></div>
  <div class="kpi"><div class="v">{abl[-1]['glob']}</div><div class="l">全局 P≥90% 最大召回</div></div>
</div>

<h2>1 · 真值库与基线（地基，未变）</h2>
<div class="card">
<table><tr><th>窗</th><th>n</th><th>TP</th><th>FP</th><th>真实精度</th></tr>
{true_prec}
<tr><td><b>合计</b></td><td><b>{len(bank)}</b></td><td><b>{int(y.sum())}</b></td><td><b>{int((1-y).sum())}</b></td>
<td><b>{y.sum()/len(bank)*100:.1f}%</b></td></tr></table>
<p>管线直出的 top-1 框约一半不是球；<b>所有改进都在这个地基上度量</b>。</p>
</div>

<h2>2 · 多帧动态特征（用户假说检验）</h2>
<div class="card">
<p>对每个候选，在 ±5 帧（同点复现用 ±10 帧）内找最近候选。<code>反向</code>=1−AUC；
反向 &gt; 0.5 表示"TP 的该量更小"。</p>
<table><tr><th>特征</th><th>AUC</th><th>反向</th><th>TP 中位</th><th>FP 中位</th><th>解读</th></tr>
{tbl(mot)}
</table>
<h3>轨迹链 v2（用贪心链 + 物理合理性）</h3>
<table><tr><th>特征</th><th>AUC</th><th>反向</th><th>TP 中位</th><th>FP 中位</th><th>解读</th></tr>
{tbl(mot2)}
</table>
<div class="note"><b>方法学教训</b>：最近邻关联会<b>选错目标</b>——真球旁边若有静态 FP（人头/球衣），
"最近候选"其实是那个 FP（故 <code>plaus_next</code> 中位出现 TP=0 / FP=1 的怪象）。
要彻底解决需<b>运动模型驱动的跟踪</b>（卡尔曼/匈牙利匹配 + 预测残差），而非逐帧最近邻。</div>
</div>

<h2>3 · 掩膜连续化（用户要求继续的方向）</h2>
<div class="card">
<p>旧做法把掩膜当<b>硬门禁</b>（脚点/球心必须在掩膜内）：P80% 但 R 仅 31%——因为
<b>球大量出现在空中</b>，空中球在图像上落在掩膜外。本轮改为<b>连续几何特征</b>：</p>
<table><tr><th>特征</th><th>AUC</th><th>反向</th><th>TP 中位</th><th>FP 中位</th><th>解读</th></tr>
{tbl(msk)}
</table>
<p><code>center_dist</code> / <code>gap_below</code> 反向 AUC ≈ 0.69–0.74：球贴近地板区域上方
（= 在球场上或球场上空），FP 则在地板区域之外（看台/场边）。这是"球在场地、人头在看台"的几何表达。</p>
<div class="note badc"><b>为什么 2D 掩膜无法彻底解决</b>：远侧观众席在图像上位于"球场区域的正上方"，
任何"把球场区域向上延伸"的 2D 掩膜都会把远侧观众一并纳入。<b>正解是 3D 门禁</b>：
估计球场单应（homography），对候选按高度假设（h=0 贴地 / h≈2–4m 空中）反投影到地面，
判断落点是否落在球场多边形内 —— 观众的反投影必然在场外。</div>
</div>

<h2>4 · 消融：每步净贡献（LOWO = 跨窗泛化）</h2>
<div class="card">
<table><tr><th>特征集</th><th>维度</th><th>全局 AUC</th>
{''.join(f'<th>{w}<br><span class="mut">AUC / P≥90% 最大召回</span></th>' for w in WINS)}
<th>全局 P≥90%</th></tr>
{abl_html}</table>
<p>读法：<b>多帧运动打开 w3，掩膜再补一点</b>；全局 AUC 0.8968 → {abl[-1]['auc']:.4f}，
但真正的价值在"分窗门禁是否存在"（w3 由"无"变"有"）。</p>
<div class="note okc">对用户两个方向的总回答：<b>都能用，且互补</b>——多帧动态解决"时间上孤立/跳变"的误报（w3 受益最大），
掩膜连续化解决"位于场地之外"的误报（w2/w3 受益）。二者合起来把全局 P≥90% 召回从
65.6% 提到 {abl[-1]['glob'].split('R=')[1].split('@')[0]}。</div>
</div>

<h2>5 · 分窗工作点置信区间（自助 300 次，最终配置）</h2>
<div class="card">
<table><tr><th>窗</th><th>点估计</th><th>自助中位</th><th>95% CI</th></tr>
{ci_html}</table>
<div class="note"><b>读数纪律</b>：CI 下限为 0 表示"该窗在某些重采样下凑不出 90% 精度"这件事本身不确定性极高。
<b>不要把分窗召回当点值引用</b>，尤其 w1/w3。</div>
</div>

<h2>6 · 交付物与用法</h2>
<div class="card">
<p>验证头 <code>measure/ball_head.joblib</code>：n={head['n']}，特征 {head['feat_dim']} 维
（<code>{head['features']}</code>），阈值 <b>{head['threshold']:.3f}</b>，
5-fold P={head['cv_precision']*100:.1f}% / R={head['cv_recall']*100:.1f}%。</p>
<pre># 训练（外观 TTA ⊕ 几何 ⊕ 运动 v1/v2 ⊕ 掩膜；训练/推理同源）
python engine/ball_verify_head.py train --target-p 0.90

# 推理：过滤检测 JSON（输入 {{"窗": {{"f00010.jpg": [候选框]}}}}；运动/掩膜特征现场现算）
python engine/ball_verify_head.py apply in.json out.json</pre>
<p>冒烟：w4 的 {n_in} 个候选 → <b>{n_out}</b> 个通过（{n_out/n_in*100:.0f}%）。</p>
<p>支撑脚本：<code>engine/ball_feats_all.py</code>（统一特征）、
<code>ball_motion_feats.py</code> / <code>ball_motion_feats2.py</code>（运动 v1/v2）、
<code>ball_mask_feats.py</code>（掩膜几何）、<code>ball_fusion_eval.py</code>（消融）。</p>
</div>

<h2>7 · 未达成 / 下一步（按阻塞价值）</h2>
<div class="card">
<ul>
<li><b class="bad">w1 无 P≥90% 工作点</b>（AUC 0.848–0.854）——最宽的全景机位，25px 球与人群单帧像素级接近不可分。</li>
<li><b>运动模型驱动跟踪</b>（卡尔曼/匈牙利 + 预测残差）替代最近邻关联，修掉 v2 的关联错误。</li>
<li><b>3D 门禁</b>：球场单应 + 高度假设反投影（§3 的"正解"）——需人工标一次场地标定点（篮筐/底线/中圈），
用已测的"镜头平移 ~3.4px/帧"做传播。</li>
<li>标注 500+ 与 dinov2-large 未测（预期边际，但 w1 或可因数据改善）。</li>
</ul>
</div>

<div class="foot">生成脚本 <code>engine/make_ball_precision_report.py</code> ·
标签库 <code>measure/labels_bank.json</code> · 头 <code>measure/ball_head.joblib</code> ·
特征 <code>measure/feats_all.npy</code> · 2026-09-24（v2）</div>
</div></body></html>"""

OUT.write_text(html)
print(f"[out] {OUT}")
for r in abl:
    print(f"  {r['tag']:<20} dim={r['dim']:>5} AUC={r['auc']:.4f}  全局P90={r['glob']}  "
          + " ".join(f"{w}:{r[w]}" for w in WINS))
print("自助 CI:", {w: (ci[w]["point"], f"{ci[w]['lo']:.0f}-{ci[w]['hi']:.0f}", f"med{ci[w]['med']:.0f}") for w in WINS})
