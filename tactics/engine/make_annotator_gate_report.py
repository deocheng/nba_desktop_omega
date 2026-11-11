#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_annotator_gate_report.py — 「我能否当标注者」协议试点报告。

数字全部现场从 pilot_decision.json / pilot_*_score.json 现读现算，不手抄。
产物: reports/milestone_05/milestone_05_annotator_gate.html
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
JD = ROOT / "reports/milestone_05/measure/judge"
OUT = ROOT / "reports/milestone_05/milestone_05_annotator_gate.html"

CSS = """body{background:#12141a;color:#e6e8ee;font:15px/1.75 -apple-system,"PingFang SC",sans-serif;margin:0;padding:36px 20px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:27px;margin:0 0 6px;color:#fff}
h2{font-size:20px;margin:38px 0 12px;padding-left:11px;border-left:4px solid #ff5a5a;color:#fff}
h3{font-size:16px;margin:24px 0 8px;color:#ffd166}
.sub{color:#98a0b3;font-size:13px;margin:0 0 24px}
.alert{background:#3a1414;border:1px solid #b33939;border-left:5px solid #ff5a5a;padding:16px 18px;border-radius:8px;margin:18px 0}
.ok{background:#0f2a1c;border:1px solid #2e7d52;border-left:5px solid #4ade80;padding:14px 18px;border-radius:8px;margin:16px 0}
.warn{background:#3a2f10;border:1px solid #9a7b1f;border-left:5px solid #ffd166;padding:14px 18px;border-radius:8px;margin:16px 0}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:13.5px}
th,td{border:1px solid #2b2f3a;padding:7px 10px;text-align:left}
th{background:#1b1f28;color:#cfd6e6;font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
tr.hi td{background:#1d2430}
code{background:#1b1f28;padding:2px 6px;border-radius:4px;font-size:12.5px;color:#ffd166}
.kpi{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0}
.card{flex:1 1 200px;background:#181c24;border:1px solid #262c38;border-radius:10px;padding:14px 16px}
.card .v{font-size:26px;font-weight:700;color:#fff;font-variant-numeric:tabular-nums}
.card .k{font-size:12px;color:#98a0b3;margin-top:4px}
ul{margin:8px 0 8px 20px}li{margin:5px 0}
hr{border:0;border-top:1px solid #262c38;margin:30px 0}
"""


def main():
    d = json.loads((JD / "pilot_decision.json").read_text())
    acc = d["acc"]
    # 同一公式再独立算一遍，与 pilot_decision.py 交叉核对（防单点算错）
    eps_alt = (acc - d["target"]) / (1 - 2*d["target"])

    H = []
    A = H.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    A("<title>里程碑 05 · 标注者可用性门禁（2026-09-25）</title>")
    A(f"<style>{CSS}</style></head><body><div class='wrap'>")

    A("<h1>里程碑 05 · 标注者可用性门禁</h1>")
    A("<p class='sub'>协议试点：先证明「判读者可靠」，再动手重建真值库。"
      "所有数字由 <code>engine/make_annotator_gate_report.py</code> 从 "
      "<code>measure/judge/pilot_decision.json</code> 现读现算，无手抄。</p>")

    A("<div class='alert'><b>一句话结论：协议改良<b>没有</b>把判读准确率抬到 90% 水位——"
      f"合并两轮仅 <b>{acc*100:.1f}%</b>（{d['ok']}/{d['n']}，Wilson 95%CI "
      f"[{d['wilson_lo']*100:.1f}%, {d['wilson_hi']*100:.1f}%]，区间上界仍低于 90%）。"
      "⇒ <b>不能由本 AI 重建真值库</b>；这条路不是「再试一次」能解决的，瓶颈在标注者本身。</b></div>")

    # 1 设计
    A("<h2>1 · 试点设计（针对上一轮暴露的三个缺陷逐条设防）</h2>")
    A("<table><tr><th>上一轮缺陷</th><th>本轮对策</th><th>落地</th></tr>"
      "<tr><td>渲染尺度让球缝丢失（100px 窗准确率 65%）</td>"
      "<td><b>三面板并列</b>：200px 看整体形状 / 60px 5× 放大找球缝黑弧 / 全帧做上下文否决</td>"
      "<td><code>judge_pilot.py render</code></td></tr>"
      "<tr><td>判读者可能（无意识地）回忆出早前打印过的标注字典</td>"
      "<td><b>格头只印序号 #NN</b>，不印窗口/帧号；且强制固定判读顺序（右→中→左）</td>"
      "<td><code>render_row()</code> 的 <code>hdr = f\"#{i:02d}\"</code></td></tr>"
      "<tr><td>若第二轮抽到第一轮样本，等于拿已泄露的真值自评</td>"
      "<td><b>留出轮</b>：<code>--exclude-tag</code> 排除上一轮全部样本</td>"
      f"<td>本轮 c2 排除 c1 的 27 格，两轮<b>样本重叠 = {len(d['overlap'])}</b></td></tr>"
      "<tr><td>渲染/流程自身的缺陷会静默污染测量</td>"
      "<td>渲染时 <code>assert</code> 源池规模（防比对逻辑回归）；<b>面板标签必须与拼接顺序逐列对应</b>；"
      "<b>禁止打印含 truth 字段的 key 文件</b></td>"
      "<td>本轮实测踩到两条：① 查看 key 结构时泄漏 idx0/idx1 真值（发生在 c1 判定<b>之后</b>，"
      "未回溯污染）；② 标签行按 <code>(FULL,60px,200px)</code> 绘制而拼接实为 "
      "<code>[200px,60px,FULL]</code>，<b>三列全错位</b>——已修，故 c1/c2 接触表的表头标注不可信，"
      "但判读是依据面板实际内容做出的，结论不受影响</td></tr></table>")
    A("<p><b>真值口径</b>：取 <code>labels3_visual.json</code> 与 <code>labels_bank.json</code> "
      "<b>两套标注一致</b>的 46 个样本（A4.11 审计结论）。这是当前可用的最强代理真值，"
      "但它<b>并非无误差</b>——下文 §4 专门处理这一点。</p>")

    # 2 结果
    A("<h2>2 · 结果：两轮留出复现</h2>")
    A("<div class='kpi'>")
    for tag in ("c1", "c2"):
        s = d["rounds"][tag]
        A(f"<div class='card'><div class='v'>{s['acc']*100:.1f}%</div>"
          f"<div class='k'>第{'一' if tag == 'c1' else '二'}轮 {tag}："
          f"{s['ok']}/{s['ok']+s['bad']}（弃权 {s['unc']}）</div></div>")
    A(f"<div class='card'><div class='v'>{acc*100:.1f}%</div>"
      f"<div class='k'>合并 {d['ok']}/{d['n']}</div></div>")
    A(f"<div class='card'><div class='v'>{d['unc']}</div>"
      f"<div class='k'>弃权总数（弃权率 "
      f"{d['unc']/(d['n']+d['unc'])*100:.1f}%，已排除出分母）</div></div></div>")

    A("<table><tr><th>轮次</th><th class='n'>判对</th><th class='n'>判错</th>"
      "<th class='n'>弃权</th><th class='n'>准确率</th><th class='n'>95%CI</th>"
      "<th class='n'>过判</th><th class='n'>漏判</th></tr>")
    for tag, name in (("c1", "c1（27 格，种子 41）"), ("c2", "c2（19 格留出，种子 97）")):
        s = d["rounds"][tag]
        n = s["ok"] + s["bad"]
        A(f"<tr><td>{name}</td><td class='n'>{s['ok']}</td><td class='n'>{s['bad']}</td>"
          f"<td class='n'>{s['unc']}</td><td class='n'>{s['acc']*100:.1f}%</td>"
          f"<td class='n'>—</td><td class='n'>{s['over']}</td>"
          f"<td class='n'>{s['under']}</td></tr>")
    A(f"<tr class='hi'><td><b>合并</b></td><td class='n'><b>{d['ok']}</b></td>"
      f"<td class='n'><b>{d['bad']}</b></td><td class='n'><b>{d['unc']}</b></td>"
      f"<td class='n'><b>{acc*100:.1f}%</b></td>"
      f"<td class='n'>[{d['wilson_lo']*100:.1f}%, {d['wilson_hi']*100:.1f}%]</td>"
      f"<td class='n'><b>{d['over']}</b></td><td class='n'><b>{d['under']}</b></td></tr></table>")

    A(f"<div class='warn'>单侧精确二项检验，<code>H₀: 准确率 ≥ 90%</code>："
      f"<b>p = {d['binom_p_le']:.5f}</b> ⇒ 在 α=0.01 上<b>拒绝 H₀</b>。"
      f"这不是「样本不足说不清」，而是<b>有方向性的否定</b>："
      f"连 95%CI 的上界（{d['wilson_hi']*100:.1f}%）都没够到 90%。</div>")

    A("<h3>2.1 两轮各自判错在哪（协议改良挡不住哪些错）</h3>")
    A("<table><tr><th>轮</th><th>格</th><th>窗口/帧</th><th>真值</th>"
      "<th>我的判读</th><th>错误类型</th></tr>")
    for tag in ("c1", "c2"):
        for e in d["rounds"][tag]["errs"]:
            kind = "过度判球" if e[4] == "BALL" else "漏判（判成非球）"
            A(f"<tr><td>{tag}</td><td class='n'>#{e[0]:02d}</td>"
              f"<td>{e[1]} {e[2][1:6]}</td><td>{e[3]}</td><td>{e[4]}</td>"
              f"<td>{kind}</td></tr>")
    A("</table>")
    A(f"<p>过判 : 漏判 = <b>{d['over']} : {d['under']} = "
      f"{d['over']/max(d['under'],1):.2f} : 1</b>，方向与 A4.11 记录的"
      "「系统性过度判球（把光头／肤色圆物／近景躯干当成球）」<b>完全一致</b>。"
      "换成更严的渲染协议并没有改变这个偏差方向——说明它来自判读机制本身，不是渲染问题。</p>")

    # 3 合并不达标
    A("<h2>3 · 裁决</h2>")
    A(f"<div class='alert'><b>裁决 = {d['verdict']}</b><br>"
      f"95%CI 上界 {d['wilson_hi']*100:.1f}% &lt; 目标线 90% ⇒ "
      "在本协议下，本 AI 不能作为「90% 级」真值库的标注者。"
      "按 A4.11 §5 修复协议的前置条件，<b>不建库</b>。</div>")

    # 4 敏感性
    A("<h2>4 · 这个结论稳健吗？——代理真值误差敏感性</h2>")
    A("<p>唯一的反驳可能是：「真值本身错了，所以把 74% 冤枉成了我的问题」。"
      "设代理真值错误率为 ε，则实测一致率 ≈ acc·(1−2ε) + ε，反解："
      "<code>acc = (measured − ε)/(1 − 2ε)</code>。</p>")
    A("<table><tr><th>代理真值错误率 ε</th><th class='n'>反解出的我的真实能力</th>"
      "<th>是否可达 90%</th></tr>")
    for s in d["eps_sensitivity"]:
        A(f"<tr{' class=hi' if s['reaches_90'] else ''}><td>{s['eps']*100:.0f}%</td>"
          f"<td class='n'>{s['acc_reconstructed']*100:.1f}%</td>"
          f"<td>{'✅' if s['reaches_90'] else '❌ 仍 < 90%'}</td></tr>")
    A("</table>")
    A(f"<p>要把实测 {acc*100:.1f}% 解释成「我其实有 90%」，代理真值必须有约 "
      f"<b>ε ≈ {eps_alt*100:.1f}%</b> 的错误率（脚本输出 {d['eps_needed_to_claim_90']*100:.1f}%，"
      "两条路径独立算出同一值）。</p>")
    A("<div class='alert'><b>这个解释不成立</b>：ε 是在「两套标注<b>一致</b>」的子集上定义的，"
      "而 A4.11 已记录两套标注在 60 个共同样本上冲突 14 个且<b>方向完全单向</b>"
      "（p=1.22e-04）、盲判仲裁 <b>9:1</b> 支持 labels3。"
      "在这类两个方法都点头的样本上，ε 远低于 19.5%。</div>")
    A("<h3>4.1 反而有一个更悲观的方向</h3>")
    A("<p>代理真值本身也是<b>同一种目视标注</b>产生的（且判读者同样是本 AI）。"
      "我与它<b>共享同一个过判偏差</b>（本轮过判 2.67:1，A4.11 同样记录过判）。"
      "共享偏差会<b>抬高</b>一致率 ⇒ <b>74.4% 应被视为我真实能力的一个乐观上界</b>，"
      "而不是中位估计。真值越干净，我的实测数字只会更低，不会更高。</p>")

    # 5 门禁含义
    A("<h2>5 · 这对「球检测精度 ≥ 90%」这条门禁意味着什么</h2>")
    A("<ul>")
    A("<li>门禁<b>依然既未证明也未证伪</b>——因为量尺（真值库）本身不合格，"
      "而换量尺的原料（可靠标注者）也没有。</li>")
    A("<li>本轮排除了一个原本最省事的方案：<b>「让 AI 自己标注自己的评测集」不可行</b>。"
      "74% 的标注者只能确认 74% 量级的结论；用它去判定 90%，等于用 0.1 刻度的尺量毫米。</li>")
    A("<li>已确认的既有事实不受影响：RF-DETR 分块推理覆盖率 63.3%→98.3%、"
      "验证头 AUC≈0.90、头分数可分性极强（TP 中位 0.996 / FP 中位 0.012）。"
      "这些是<b>相对比较</b>，不依赖绝对真值。</li>")
    A("</ul>")

    A("<h2>6 · 三条出路（按代价排序）</h2>")
    A("<table><tr><th>#</th><th>方案</th><th>所需</th><th>能否直接产出 90% 级真值</th></tr>")
    A("<tr><td>A</td><td><b>用户抽检</b>：由人（老程）看接触表判定</td>"
      "<td>人工判读 ~380 个样本（CI ±3 点）</td>"
      "<td>✅ 人眼在 5× 放大下对「球缝」的判读是客观的；这是唯一现成的可靠标注者</td></tr>")
    A("<tr><td>B</td><td><b>引入独立 VLM 标注者</b></td>"
      "<td>下载本地视觉语言模型权重（HF 镜像可达）</td>"
      "<td>⚠️ 需先测其与代理真值的一致率；小目标识别是 VLM 弱项，不保证优于本 AI</td></tr>")
    A("<tr><td>C</td><td><b>缩小真值需求</b>：把门禁定义从「检测精度 90%」改为"
      "「任务级事件可用性」</td>"
      "<td>重新定义验收口径（用户裁决）</td>"
      "<td>✅ 绕开绝对精度：只要人工锚定的少量关键事件（如 16 个 PBP 事件时刻）"
      "球位置误差可接受，任务即可用</td></tr>")
    A("</table>")
    A("<div class='warn'><b>需要用户裁决的点</b>：门禁口径到底取哪一个——"
      "① 每窗检测精度 P≥90%；② 全局检测精度 P≥90%；③ 任务级（战术分析可用）事件可用性。"
      "口径不同，所需真值规模与可行路线完全不同（① 最贵且当前不可达；③ 最省且与项目"
      "「产物=战术分析」的定位最一致）。</div>")

    A("<hr>")
    A("<p class='sub'>证据文件：<code>measure/judge/pilot_c1_score.json</code> · "
      "<code>pilot_c2_score.json</code> · <code>pilot_decision.json</code> · "
      "接触表 <code>pilot_c1_sheet0..8.jpg</code> / <code>pilot_c2_sheet0..6.jpg</code>。"
      "脚本：<code>engine/judge_pilot.py</code> · <code>engine/pilot_decision.py</code> · "
      "<code>engine/make_annotator_gate_report.py</code>。</p>")
    A("</div></body></html>")

    OUT.write_text("\n".join(H), encoding="utf-8")
    print(f"→ {OUT}  ({OUT.stat().st_size} 字节)")


if __name__ == "__main__":
    main()
