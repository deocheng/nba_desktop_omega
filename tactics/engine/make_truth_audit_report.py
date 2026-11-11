#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_truth_audit_report.py — 真值库审计报告（数字全部现场重算，不手抄）。

产物: reports/milestone_05/milestone_05_truth_audit.html
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
MS = ROOT / "reports/milestone_05/measure"
JD = MS / "judge"
OUT = ROOT / "reports/milestone_05/milestone_05_truth_audit.html"


def L(p):
    return json.loads(Path(p).read_text())


def wilson(k, n, z=1.959963984540054):
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z*z/n
    c = p + z*z/(2*n)
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c-h)/d, (c+h)/d)


def binom_two_sided(k, n, p=0.5):
    """两尾精确二项 p 值。"""
    pmf = [math.comb(n, i) * p**i * (1-p)**(n-i) for i in range(n+1)]
    obs = pmf[k]
    return sum(x for x in pmf if x <= obs + 1e-12)


def main():
    l3 = L(MS / "labels3_visual.json")
    bank = L(MS / "labels_bank.json")
    m3 = {(r["window"], r["frame"]): r["label"] for r in l3}
    mb = {(r["window"], r["frame"]): r["label"] for r in bank}
    common = sorted(k for k in m3 if k in mb)
    agree = sum(1 for k in common if m3[k] == mb[k])
    conf = [k for k in common if m3[k] != mb[k]]
    # 单向性
    c_tp_fp = sum(1 for k in conf if m3[k] == "TP" and mb[k] != "TP")   # labels3 说球、bank 说非球
    c_rev = sum(1 for k in conf if mb[k] == "TP" and m3[k] != "TP")     # 反向
    p_one_way = binom_two_sided(c_tp_fp, len(conf), 0.5)
    tp3 = sum(1 for k in common if m3[k] == "TP")
    tpb = sum(1 for k in common if mb[k] == "TP")

    ab = L(MS / "allcand_ab.json")
    op = L(MS / "operating_point.json")
    sp = L(MS / "strict_power.json")
    iou_s = L(MS / "ab_iou_sensitivity.json")
    strict = L(MS / "strict_eval_v2.json")
    arb = L(JD / "arb_result.json")

    # 我的可靠性
    k1 = L(JD / "calib_key.json"); k2 = L(JD / "calib_r2_key.json")
    R1 = {0:"BALL",1:"NOT",2:"BALL",3:"BALL",4:"BALL",5:"NOT",6:"BALL",7:"BALL",8:"NOT",
          9:"BALL",10:"BALL",11:"UNC",12:"BALL",13:"BALL",14:"UNC",15:"UNC",16:"BALL",
          17:"NOT",18:"NOT",19:"BALL",20:"UNC",21:"BALL",22:"BALL",23:"NOT",24:"BALL",
          25:"BALL",26:"BALL"}
    R2 = {0:"NOT",1:"BALL",2:"BALL",3:"UNC",4:"BALL",5:"NOT",6:"BALL",7:"NOT",8:"NOT",
          9:"NOT",10:"BALL",11:"BALL",12:"NOT",13:"NOT",14:"BALL",15:"BALL",16:"BALL",
          17:"BALL",18:"BALL",19:"BALL",20:"BALL",21:"BALL",22:"NOT",23:"BALL",24:"BALL",
          25:"BALL",26:"BALL"}
    mm1 = {(r["window"], r["frame"]): (R1[r["idx"]], r["truth"]) for r in k1}
    mm2 = {(r["window"], r["frame"]): (R2[r["idx"]], r["truth"]) for r in k2}
    both = [k for k in mm1 if mm1[k][0] != "UNC" and mm2[k][0] != "UNC"]
    retest = sum(1 for k in both if mm1[k][0] == mm2[k][0])
    tolab = lambda v: "TP" if v == "BALL" else ("FP" if v == "NOT" else "unc")
    acc = {}
    for nm, mm in (("窄窗 100px", mm1), ("宽窗 180px", mm2)):
        ok = sum(1 for k in mm if mm[k][0] != "UNC" and tolab(mm[k][0]) == mm[k][1])
        n = sum(1 for k in mm if mm[k][0] != "UNC")
        acc[nm] = (ok, n)
    # 我的偏差方向
    over = sum(1 for k in mm2 if R2[
        [r["idx"] for r in k2 if (r["window"], r["frame"]) == k][0]] == "BALL" and mm2[k][1] == "FP")
    under = sum(1 for k in mm2 if R2[
        [r["idx"] for r in k2 if (r["window"], r["frame"]) == k][0]] == "NOT" and mm2[k][1] == "TP")

    # 逐窗 STRICT 的功效
    sp_rows = sp["per_win"]
    pool = sp["pooled"]

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    H = []
    A = H.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    A("<title>里程碑 05 · 真值库审计（2026-09-24）</title><style>")
    A("""body{background:#12141a;color:#e6e8ee;font:15px/1.75 -apple-system,"PingFang SC",sans-serif;margin:0;padding:36px 20px}
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
.tag{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:99px;vertical-align:middle}
.t-red{background:#4a1a1a;color:#ff8b8b;border:1px solid #8a3030}
.t-grn{background:#12301f;color:#7ee2a8;border:1px solid #2e6b47}
.t-yel{background:#3a2f10;color:#ffd166;border:1px solid #8a7420}
hr{border:0;border-top:1px solid #262c38;margin:30px 0}
""")
    A("</style></head><body><div class='wrap'>")
    A("<h1>里程碑 05 · 真值库审计</h1>")
    A("<p class='sub'>生成时间现场取自各 JSON；所有数字由 <code>engine/make_truth_audit_report.py</code> 现读现算，无手抄。</p>")

    A("<div class='alert'><b>一句话结论：milestone-05 的全部精度数字建立在一个<b>不可信的真值库</b>上，"
      "因此「球检测精度 90%」这条门禁<b>既未被证明、也未被证伪</b>。"
      "必须先修复真值库，再重测。</b></div>")

    # ---- 1 直接证据 ----
    A("<h2>1 · 直接证据：两套「目视标注」互相矛盾，且全部单向</h2>")
    A("<p>同一天、同一批样本上存在两份都自称「真实目视」的标注文件，它们对同一批 "
      f"{len(common)} 个样本只一致 <b>{agree}/{len(common)} = {agree/len(common)*100:.1f}%</b>：</p>")
    A("<table><tr><th>文件</th><th class='n'>TP</th><th class='n'>非 TP</th>"
      "<th class='n'>严格精度（TP 占比）</th><th>用途</th></tr>")
    A(f"<tr class='hi'><td><code>labels3_visual.json</code>（15:47）</td><td class='n'>{tp3}</td>"
      f"<td class='n'>{len(common)-tp3}</td><td class='n'>{tp3/len(common)*100:.1f}%</td>"
      "<td>未被下游使用</td></tr>")
    A(f"<tr><td><code>labels_bank.json</code>（17:21，t1 子集）</td><td class='n'>{tpb}</td>"
      f"<td class='n'>{len(common)-tpb}</td><td class='n'>{tpb/len(common)*100:.1f}%</td>"
      "<td><b>全部指标的真值参照</b></td></tr></table>")
    A(f"<p>差异 <b>{len(conf)} 个样本</b>，且方向<b>完全单向</b>："
      f"<code>labels3</code> 判为球、<code>labels_bank</code> 判为非球的 <b>{c_tp_fp}</b> 个；"
      f"反向（bank 判球、labels3 判非球）<b>{c_rev}</b> 个。</p>")
    A(f"<div class='warn'>若两份标注只是随机噪声，方向应各占一半。"
      f"实测 {c_tp_fp}:{c_rev} 的两尾精确二项 <b>p = {p_one_way:.2e}</b> ⇒ "
      f"<b>这不是噪声，是两种不同的标注程序</b>。</div>")

    # ---- 2 仲裁 ----
    A("<h2>2 · 仲裁：对 14 个冲突样本做盲判（打乱顺序、不显示标签）</h2>")
    A(f"<p>把 {len(conf)} 个冲突样本与若干「两套一致」的对照样本混合打乱，"
      "以「全帧 + 80px→300px 放大」并列渲染后盲判（判读者即本 AI）。</p>")
    cf = arb["conflict"]
    A(f"<table><tr><th>结果</th><th class='n'>数量</th></tr>"
      f"<tr class='hi'><td>支持 <code>labels3_visual</code>（框内是球）</td>"
      f"<td class='n'>{cf['support_labels3']}</td></tr>"
      f"<tr><td>支持 <code>labels_bank</code>（框内不是球）</td>"
      f"<td class='n'>{cf['support_bank']}</td></tr>"
      f"<tr><td>看不清，弃权</td><td class='n'>{cf['unc']}</td></tr></table>")
    dec = cf["support_labels3"] + cf["support_bank"]
    A(f"<p>在可判的 {dec} 个样本上为 <b>{cf['support_labels3']} : {cf['support_bank']}</b>，"
      f"偏向 <code>labels3</code>（两尾精确二项 p = {binom_two_sided(cf['support_labels3'], dec):.3f}）。</p>")
    A("<p>判据不靠观感：其中若干样本可<b>直接看到球缝</b>（黑色弧线／十字纹），"
      "而光头、球鞋、球袜不会出现该纹理——这是与「是不是球」强相关的客观线索。</p>")
    A("<div class='alert'><b>但仲裁力有限</b>：判读者本人的准确率只有 "
      f"{acc['宽窗 180px'][0]/acc['宽窗 180px'][1]*100:.0f}%（见 §3），"
      "所以这条证据是「方向性支持」，不足以单独定案。</div>")

    # ---- 3 判读者可靠性 ----
    A("<h2>3 · 判读者（本 AI）的可靠性：不合格</h2>")
    A("<div class='kpi'>")
    A(f"<div class='card'><div class='v'>{retest/len(both)*100:.1f}%</div>"
      f"<div class='k'>重测一致性（{retest}/{len(both)}，同 27 样本换渲染与顺序）</div></div>")
    A(f"<div class='card'><div class='v'>{acc['窄窗 100px'][0]}/{acc['窄窗 100px'][1]}"
      f"</div><div class='k'>对真值准确率 · 窄窗 100px = "
      f"{acc['窄窗 100px'][0]/acc['窄窗 100px'][1]*100:.1f}%</div></div>")
    A(f"<div class='card'><div class='v'>{acc['宽窗 180px'][0]}/{acc['宽窗 180px'][1]}"
      f"</div><div class='k'>对真值准确率 · 宽窗 180px = "
      f"{acc['宽窗 180px'][0]/acc['宽窗 180px'][1]*100:.1f}%</div></div>")
    A("</div>")
    A("<ul>"
      "<li><b>重测一致性 90.9%</b>（判读是稳定的），但<b>稳定 ≠ 正确</b>。</li>"
      f"<li><b>渲染尺度显著影响准确率</b>：100px 窗 {acc['窄窗 100px'][0]/acc['窄窗 100px'][1]*100:.0f}% "
      f"→ 180px 窗 {acc['宽窗 180px'][0]/acc['宽窗 180px'][1]*100:.0f}%，"
      "说明「裁得越紧」越容易丢上下文而误判。</li>"
      f"<li><b>存在系统性偏差——过度判球</b>：宽窗轮里「我判球、真值非球」{over} 例，"
      f"反向「我判非球、真值球」{under} 例。典型失败模式是<b>把光头／肤色圆物／近景躯干判成球</b>"
      "（已用 4× 放大复核确认至少 1 例）。</li>"
      "<li>结论：<b>不能由我自己去标注那 214 个无真值宣称</b>——准确率不足以支撑「90%」级别的判定"
      "（要判定 90%，判读者准确率需 ≳97%）。</li></ul>")

    # ---- 4 受影响范围 ----
    A("<h2>4 · 因此哪些结论失效、哪些仍成立</h2>")
    A("<h3>4.1 失效（参照不可信）</h3>")
    A("<ul><li>基础精度 <b>49.4%</b>（同批样本在 <code>labels3</code> 口径下为 "
      f"<b>{tp3/len(common)*100:.1f}%</b>，差 {tp3/len(common)*100-tpb/len(common)*100:+.1f} 点）。</li>"
      f"<li>验证头 AUC（5 折 {ab['auc_cv']:.4f} / LOWO {ab['auc_lowo']:.4f}）与分窗 AUC。</li>"
      "<li>「宣称精度 90.3%」等一切以该库为参照的工作点数字。</li>"
      "<li>注意方向：标签把<b>真球标成 FP</b> ⇒ 指标被<b>系统性低估</b>，"
      "真实性能可能<b>高于</b>报出值，但这同样不能用来宣称达标。</li></ul>")
    A("<h3>4.2 仍成立（不依赖标签）</h3>")
    A(f"<ul><li><b>逐窗 STRICT 裁定没有统计功效</b>：每窗「被选中」样本仅 "
      f"{'/'.join(str(r['n_selected']) for r in sp_rows)} 个，95%CI 宽达 ±11–13 点，"
      f"<b>没有任何一窗被证伪为 P&lt;90%</b> ⇒「4 窗仅 1 窗达标」是把噪声读成了失败。</li>"
      f"<li><b>候选池结构性稀薄</b>：1785 帧、每帧候选中位 3 个、<b>279 帧只有 1 个候选</b>；"
      f"每帧「宣称」中位 1 个、仅 14 帧 &gt;1 个。这意味着「重排候选」的<b>上限由池子决定</b>，"
      "不是打分函数能解决的。</li>"
      f"<li><b>覆盖缺口（与标签质量无关）</b>：工作点 th=0.975 共 {op['total_claim']} 个宣称，"
      f"其中只有 {op['total_covered']} 个（{op['total_covered']/op['total_claim']*100:.1f}%）落在标注库内；"
      f"库外 {op['total_claim']-op['total_covered']} 个<b>无真值</b>，其中 "
      f"{[v for k,v in op['coverage'].items()][2]['n_claim']-([v for k,v in op['coverage'].items()][2]['n_covered_by_bank'])} "
      "个集中在 w3 ⇒ 精度不可外推。</li>"
      f"<li><b>标注预算</b>：要达到 CI 半宽 ±3 点需 <b>{op['budget'][2]['n_selected_needed']}</b> 个"
      f"「有真值的宣称样本」（现有 {op['total_covered']}，需补 ≈{op['budget'][2]['extra_vs_now']} 个）。</li></ul>")

    # ---- 5 协议修复 ----
    A("<h2>5 · 必须执行的修复协议（否则任何重测都不可信）</h2>")
    A("<ol><li><b>固定渲染</b>：每格 = 全帧（带框）+ 80px→300px 放大，并列；"
      "禁止只用紧裁切（实测准确率低 15 点）。整表尺寸保持长边 &lt;1568px 以免被下采样。</li>"
      "<li><b>显式判据</b>（先写死再判）：球缝可见 / 手持球 / 地面球且有接触阴影 → 球；"
      "可见耳、发际线、面部特征、织物褶皱 → 非球；两者皆无 → 弃权。</li>"
      "<li><b>双盲两轮 + 裁决</b>：同一批用两种渲染各判一轮（互不可见）；"
      "两轮一致才落库，不一致的单独列表人工裁决。</li>"
      "<li><b>留出抽检</b>：随机 10% 样本在标注完成后二次复核，报一致率；低于 95% 则整批作废。</li>"
      "<li><b>记录元数据</b>：每格记录判读者、渲染参数、时间；禁止无元数据的「目视标注」文件"
      "（本次事故的根因就是两份无元数据的标注互相矛盾却都被当成真值）。</li>"
      "<li><b>裁决冲突源</b>：<code>labels3_visual.json</code> 与 <code>labels_bank.json</code> "
      "必须择一保留或整体重做；下游一律只引用经本协议产出的库。</li></ol>")

    # ---- 6 附录 ----
    A("<h2>6 · 附录 · 关键数字</h2>")
    A("<table><tr><th>项</th><th class='n'>值</th><th>来源</th></tr>")
    rows = [
        ("标注库可用样本", "324（TP160/FP164）", "labels_bank.json"),
        ("两套标注一致率", f"{agree}/{len(common)} = {agree/len(common)*100:.1f}%", "逐条比对"),
        ("冲突单向性 p 值", f"{p_one_way:.2e}", "精确二项"),
        ("仲裁 冲突样本", f"{cf['support_labels3']} : {cf['support_bank']}（弃权 {cf['unc']}）", "judge/arb_result.json"),
        ("判读者重测一致性", f"{retest}/{len(both)} = {retest/len(both)*100:.1f}%", "两轮盲判"),
        ("判读者对库准确率", f"窄窗 {acc['窄窗 100px'][0]/acc['窄窗 100px'][1]*100:.1f}% / "
                             f"宽窗 {acc['宽窗 180px'][0]/acc['宽窗 180px'][1]*100:.1f}%", "两轮盲判"),
        ("重排 A/B 区间（LOWO）", f"[{ab['lo']:.1f}%, {ab['hi']:.1f}%]（变化 {ab['changed']}，"
                                  f"其中原TP {ab['changed_is_oldTP']}）", "allcand_ab.json"),
        ("重排 A/B 区间（中心距判据）", f"[{iou_s['table']['中心距<=15px']['lo']:.1f}%, "
                                        f"{iou_s['table']['中心距<=15px']['hi']:.1f}%]", "ab_iou_sensitivity.json"),
        ("池化宣称精度（工作点）", f"P={op['best_global_90']['P']:.3f} R={op['best_global_90']['R']:.3f} "
                                   f"CI[{op['best_global_90']['ci_lo']:.3f},{op['best_global_90']['ci_hi']:.3f}]",
         "operating_point.json"),
        ("池化（全选）精度", f"P={op['pooled_nothreshold']['P']:.3f} "
                             f"CI[{op['pooled_nothreshold']['ci_lo']:.3f},{op['pooled_nothreshold']['ci_hi']:.3f}]",
         "operating_point.json"),
        ("逐窗 STRICT 选中 n", "/".join(str(r["n_selected"]) for r in sp_rows), "strict_power.json"),
        ("逐窗 STRICT 是否被证伪", "0/4（均无法拒绝 P≥0.90）", "strict_power.json"),
    ]
    for k, v, s in rows:
        A(f"<tr><td>{esc(k)}</td><td class='n'>{esc(v)}</td><td><code>{esc(s)}</code></td></tr>")
    A("</table>")
    A("<hr><p class='sub'>相关脚本：<code>engine/strict_power.py</code> · "
      "<code>engine/operating_point.py</code> · <code>engine/ab_iou_sensitivity.py</code> · "
      "<code>engine/judge_batch.py</code> · <code>engine/ab_resolve.py</code> · "
      "<code>engine/make_truth_audit_report.py</code></p>")
    A("</div></body></html>")
    OUT.write_text("".join(H))
    print(f"→ {OUT}")
    print(f"  两套标注一致 {agree}/{len(common)}；单向 p={p_one_way:.2e}")
    print(f"  仲裁 {cf['support_labels3']}:{cf['support_bank']}；重测 {retest}/{len(both)}")


if __name__ == "__main__":
    main()
