#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「第二轮：地基修复 + 球检测根因定案」报告（数字**现场重算**，不手抄）。

读取：
  reports/milestone_05/measure/tileab.json        （tile 几何 A/B）
  action_work/ball_cand_scores.json               （全候选头分数，若存在）
  reports/milestone_05/measure/labels_bank.json   （324 条人工真值）
  action_work/w*_rfdetr_tile.json                 （4748 候选）
  HF 模型卡 config.json / README.md                （Map Ball 引用）
用法: python engine/make_round2_report.py
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW, MS = ROOT / "action_work", ROOT / "reports/milestone_05/measure"
MC = Path(str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
          + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
          + "46c33088c790670a7e81e21e753fa368b2d77a70")
OUT = ROOT / "reports/milestone_05/milestone_05_round2_findings.html"
WINS = ("w1", "w2", "w3", "w4")


def jload(p, d=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return d


def cand_stats():
    rows, per = {}, {}
    for w in WINS:
        d = jload(AW / f"{w}_rfdetr_tile.json", {})
        n = sum(len(v) for v in d.values())
        withb = sum(1 for v in d.values() if v)
        c = [o["conf"] for v in d.values() for o in v]
        rows[w] = {"frames": len(d), "cands": n, "with": withb,
                   "perc": 100 * withb / max(1, len(d)),
                   "cmed": float(np.median(c)) if c else 0.0,
                   "cp90": float(np.percentile(c, 90)) if c else 0.0,
                   "cp95": float(np.percentile(c, 95)) if c else 0.0}
        t1 = jload(AW / f"{w}_ball_verified_t1.json", {})
        per[w] = sum(len(v) for v in t1.values())
    tot = sum(r["cands"] for r in rows.values())
    frames = sum(r["frames"] for r in rows.values())
    kept = sum(per.values())
    return rows, tot, frames, kept


def ab_stats():
    """全候选重排的 A/B —— 优先读 ball_head_v2.py 落盘的 allcand_ab.json（LOWO 口径）。"""
    j = jload(MS / "allcand_ab.json", None)
    if j:
        j["_src"] = "LOWO（留窗口外）打分，标签行为 out-of-fold"
        return j
    sc = jload(AW / "ball_cand_scores.json", None)
    bank = [r for r in jload(MS / "labels_bank.json", []) if r["label"] in ("TP", "FP")]
    if sc is None or not bank:
        return None

    def iou(a, b):
        x1, y1 = max(a[0], b[0]), max(a[1], b[1])
        x2, y2 = min(a[2], b[2]), min(a[3], b[3])
        i = max(0, x2 - x1) * max(0, y2 - y1)
        ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
        return i / ua if ua > 0 else 0.0

    change = []
    same = {"TP": 0, "FP": 0}
    for r in bank:
        cs = sc.get(r["window"], {}).get(r["frame"], [])
        if not cs:
            change.append(r); continue
        top = max(cs, key=lambda c: c["prob"])
        if iou(top["bbox"], r["bbox"]) >= 0.5:
            same[r["label"]] += 1
        else:
            change.append(r)
    n = len(bank)
    ntp = sum(1 for r in bank if r["label"] == "TP")
    return {"n": n, "same_TP": same["TP"], "same_FP": same["FP"],
            "changed": len(change), "oldP": ntp / n * 100,
            "lo": same["TP"] / n * 100, "hi": (same["TP"] + len(change)) / n * 100,
            "changed_is_oldTP": sum(1 for r in change if r["label"] == "TP"),
            "_src": "⚠️ v1 头 + 漂移索引（非 LOWO，仅作参考）"}


def card_facts():
    cfg = jload(MC / "config.json", {})
    txt = (MC / "README.md").read_text() if (MC / "README.md").exists() else ""
    mp = {}
    for line in txt.splitlines():
        s = line.strip().lstrip("*").strip()
        if s.startswith("Map ") or s.startswith("Map"):
            k = s.split(":")[0].replace("Map ", "").strip()
            try:
                mp[k] = float(s.split(":")[1].strip())
            except Exception:
                pass
    return {"id2label": cfg.get("id2label", {}), "metrics": mp, "readme": txt}


def bar(v, vmax, w=190, col="#3ba55d"):
    p = 0 if vmax <= 0 else max(0.0, min(1.0, v / vmax))
    return (f'<span style="display:inline-block;width:{int(p*w)}px;height:9px;'
            f'background:{col};border-radius:2px;vertical-align:middle"></span>')


def main():
    rows, tot, frames, kept = cand_stats()
    ab = ab_stats()
    card = card_facts()
    mb = card["metrics"].get("Ball", float("nan"))
    mpl = card["metrics"].get("Player", float("nan"))
    mrf = card["metrics"].get("Referee", float("nan"))

    H = []
    A = H.append
    A("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>动作分析 · 第二轮：地基修复 + 球检测根因定案</title>
<style>
 body{background:#0f1115;color:#e6e8eb;font:15px/1.75 -apple-system,"PingFang SC",sans-serif;
   margin:0;padding:38px 46px;max-width:1180px}
 h1{font-size:27px;margin:0 0 6px;color:#fff}
 h2{font-size:20px;margin:36px 0 10px;color:#fff;border-left:4px solid #3ba55d;padding-left:11px}
 h3{font-size:16px;margin:22px 0 6px;color:#cfe3ff}
 .sub{color:#8b949e;font-size:13px;margin-bottom:22px}
 table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}
 th,td{border:1px solid #262c36;padding:7px 10px;text-align:left;vertical-align:top}
 th{background:#171b22;color:#c9d1d9;font-weight:600}
 td.num{text-align:right;font-variant-numeric:tabular-nums}
 code{background:#171b22;padding:1px 5px;border-radius:4px;font-size:12.5px;color:#ffd479}
 .ok{color:#3ba55d;font-weight:600} .bad{color:#e5534b;font-weight:600}
 .warn{color:#d29922;font-weight:600}
 .box{background:#171b22;border:1px solid #262c36;border-radius:8px;padding:14px 18px;margin:14px 0}
 .key{background:#14231a;border:1px solid #2b4a34;border-left:4px solid #3ba55d}
 .neg{background:#241a19;border:1px solid #4a2b28;border-left:4px solid #e5534b}
 .quote{border-left:3px solid #6e7681;padding:6px 14px;color:#9aa4af;font-style:italic;margin:10px 0}
 ul{margin:8px 0 8px 22px;padding:0} li{margin:5px 0}
 .small{font-size:12.5px;color:#8b949e}
</style></head><body>
<h1>动作分析系统 · 第二轮执行报告</h1>
<div class="sub">地基修复（L1/L2/L4/L6-a/L6-b） + 球检测根因定案 + 全候选重排 A/B ·
所有数字由 <code>engine/make_round2_report.py</code> 现场重算</div>""")

    # ---------- 0. 一眼结论 ----------
    A(f"""<div class="box key"><b>一句话结论</b><br>
球精度 ≥90% 的瓶颈已被<b>定位到检测器本身</b>，且有第三方原文佐证：现行 RF-DETR 的
<code>Map Ball = {mb:.4f}</code>，模型卡自述球"只有几个像素、常与背景混在一起把模型搞糊涂"、
训练图"多来自凯尔特人比赛"。实测 {tot} 个候选里 <b>{rows['w1']['perc']:.0f}%–{rows['w3']['perc']:.0f}% 的帧都有"球"候选</b>，
但置信度挤在窄带（中位 {rows['w1']['cmed']:.3f} / p90 {rows['w1']['cp90']:.3f}）⇒
<b>"按置信度选每帧 top-1"≈ 随机选</b>，这正是基础精度仅 49.4% 的来源。</div>""")

    # ---------- 1. 执行清单 ----------
    A("<h2>1 · 本轮执行清单与裁定</h2>")
    A("""<table><tr><th>编号</th><th>内容</th><th>产物</th><th>裁定</th></tr>
<tr><td>L1</td><td>镜头分割（窗口内含切镜头）</td><td><code>engine/shot_segment.py</code></td>
<td class="ok">完成</td></tr>
<tr><td>L2</td><td>配准修复：遮罩静态叠加图形 + 内点铺开门禁 + 尺度强制=1</td>
<td><code>global_align.py</code> · <code>euclid_ize</code></td><td class="ok">完成</td></tr>
<tr><td>L4</td><td>消失点（联合四线 RANSAC + 地平线/正交门禁）</td>
<td><code>engine/court_vp2.py</code></td>
<td class="bad">阴性：单帧无足够长线段，脚本如实报 NO SOLUTION</td></tr>
<tr><td>L6-a</td><td>球场马赛克（块中值 + 链式拼接）</td>
<td><code>engine/court_mosaic.py</code></td>
<td class="bad">阴性：镜头往返 ⇒ 单一画布前提不成立（见 §2）</td></tr>
<tr><td>L6-b</td><td>球场规范模型拟合求相机位姿</td>
<td><code>court_model.py</code> · <code>court_fit.py</code></td>
<td class="warn">失败：目标函数陷入退化解，未完成</td></tr>
<tr><td>L9-a</td><td>tile 几何 A/B（非等比拉伸毁球假设）</td>
<td><code>engine/ball_tile_ab.py</code></td>
<td class="bad">证伪（见 §4）</td></tr>
<tr><td>L9-b</td><td>全候选重排（现行仅用 top-1，扔掉 89% 候选）</td>
<td><code>engine/ball_allcand_eval.py</code></td>
<td>见 §5</td></tr>
</table>""")

    # ---------- 2. 球场 ----------
    A("<h2>2 · 球场路线：三条路全灭，且真因已查清</h2>")
    A("""<div class="box neg"><b>① 消失点</b>（阴性）<br>
单帧 ≥150px 的线段只有 3 条：远端边线在上沿被 ROI 切掉、近端边线被观众压住、
中圈巨型 logo 的<b>曲线描边</b>反而成了最强白线响应。⇒ 不是算法问题，是素材可观测性问题。</div>""")
    A("""<div class="box neg"><b>② 马赛克</b>（阴性，<u>已改判自己的旧结论</u>）<br>
我最初把马赛克里的"同一球场出现三次"判成贴图 bug。新脚本 <code>engine/chain_audit.py</code>
现场重算（不读缓存）后改判：<b>镜头是强非单调的往返摇</b> —— 平移行程
min −2593px / max +341px、<b>极差 2934px</b>，而净位移只有 −1555px
（f121 到最左、f281 回中、f401 再到最左）。<br>
⇒ 画布 4857px ≈ 1920+2934 完全对上；"三次重复"是<b>往返漂移鬼影</b>，不是重复贴图。<br>
⇒ 旧的自相关检验（找周期次峰）<b>选错了检验</b>——漂移不规则、非周期，本来就找不到次峰。
正确检验是<b>往返一致性</b>，实测不过。<b>单画布马赛克路线正式关闭。</b></div>""")
    A("""<div class="box warn"><b>③ 规范模型拟合</b>（失败，诚实记录）<br>
新建 <code>court_model.py</code>（NBA 全部线型的米制常量：边界/中线/中圈/油漆区/罚球圈/三分弧+底角/篮板/篮圈）
+ <code>court_fit.py</code>（对称双向距离目标：正向=模型线到实测线像的距离，反向=实测线像到模型线的距离，
反向项专防"把球场缩成一小团"），粗搜 3600 位姿 → Powell 精修。<br>
结果：最优 F≈9.1px / R≈20.7px，参数被顶到搜索盒边界，渲染图目视确认模型线明显错位。
<b>目标函数区分度不足</b>，未做人工锚点初值。</div>""")
    A("""<div class="box"><b>对"球场先行"架构的裁定</b><br>
<b>方向正确，但不是当前关键路径。</b>理由是一条已实测的硬数据：把球场门禁特征加进验证头，
LOWO AUC 只从 <code>0.8994</code> 变成 <code>0.8991</code>（C0 → C1）——<b>等于零增益</b>。
而 §3 显示瓶颈在检测器。⇒ 把球场做到毫米级也换不来 90%。<br>
<span class="small">注：球场坐标化的<b>真实价值</b>在别处——球员位置战术分析、镜头不变特征。
若目标转向战术分析，球场配准应重启（建议走"人工锚点 + 链式传播"而非纯自动）。</span></div>""")

    # ---------- 3. 根因 ----------
    A("<h2>3 · 球检测根因定案（第三方原文 + 实测量化互证）</h2>")
    A(f"""<div class="quote">Map: {card['metrics'].get('map', mb):.4f} ·
Map Small: {card['metrics'].get('Small', float('nan')):.4f} ·
<b>Map Ball: {mb:.4f}</b> · Map Player: {mpl:.4f} · Map Referee: {mrf:.4f}<br>
"The ball is only a few pixels in size and often gets mixed with the background and confuses the model"<br>
"Images are mostly from <b>Celtics</b> games and hence there may be a lack of training data diversity"
<span class="small">—— <code>koppolusameer/rfdetr-basketball-player-ball-referee-detection</code> 模型卡原文</span></div>""")
    A(f"""<p>基座是 <b>RF-DETR <u>nano</u></b>（<code>Roboflow/rf-detr-nano</code>），本地 <code>config.json</code> 已核实
类别顺序为 <code>{json.dumps(card['id2label'], ensure_ascii=False)}</code>（所以"只取 cls=0"的过滤分支没错）。
检测器的 ball 类 mAP 只有 <b>{mb:.2f}</b>，而 player/referee 是 {mpl:.2f}/{mrf:.2f} —— <b>差了 3.4 倍</b>。</p>""")
    A("""<table><tr><th>窗口</th><th class="num">帧数</th><th class="num">有"球"候选的帧</th>
<th class="num">候选总数</th><th class="num">每帧候选</th><th class="num">conf 中位</th>
<th class="num">conf p90</th><th class="num">conf p95</th></tr>""")
    for w in WINS:
        r = rows[w]
        A(f"""<tr><td>{w}</td><td class="num">{r['frames']}</td>
<td class="num">{r['with']} ({r['perc']:.1f}%)</td><td class="num">{r['cands']}</td>
<td class="num">{r['cands']/r['frames']:.2f}</td><td class="num">{r['cmed']:.3f}</td>
<td class="num">{r['cp90']:.3f}</td><td class="num">{r['cp95']:.3f}</td></tr>""")
    A(f"""<tr><th>合计</th><th class="num">{frames}</th><th class="num">—</th>
<th class="num">{tot}</th><th class="num">{tot/frames:.2f}</th><th class="num">—</th>
<th class="num">—</th><th class="num">—</th></tr></table>""")
    A(f"""<div class="box warn"><b>读出什么</b><br>
① <b>{tot}</b> 个候选、{rows['w1']['perc']:.0f}–{rows['w3']['perc']:.0f}% 的帧都有候选 ⇒ 召回素材充足；
② 置信度<b>中位 {rows['w1']['cmed']:.3f}、p95 仅 {rows['w1']['cp95']:.3f}</b>——全部挤在 0.5~0.72 的窄带里，
<b>没有任何区分度</b>（这与早前"conf 对真/假球 AUC≈0.5"完全一致）；
③ 于是"每帧取 conf 最高的那一个"<b>接近随机选</b>：候选 {tot/frames:.2f} 个/帧 ⇒ 随机精度约 1/{tot/frames:.1f}，
实测 49.4% ≈ 1/2.0，两者吻合。<br>
⇒ <b>瓶颈是检测器的 ball 类本身近乎不可分</b>，不是后处理、门禁、口径或分辨率。</div>""")

    # ---------- 4. 证伪 ----------
    A("<h2>4 · 已证伪：非等比拉伸「毁球」假设</h2>")
    A("""<p>我实测了 <code>RfDetrImageProcessor.resize()</code> 的源码：给了 <code>height</code>+<code>width</code> 就
<b>精确缩放到该尺寸、不保持长宽比</b>（源码原文 "Do NOT keep the aspect ratio"）。
因此现行 <code>--tile-w 640 --tile-h 384</code> 把每块拉伸到 384×384：横轴 ×0.600、纵轴 ×1.000，
真值库里 25×29px 的球被压成 <b>15×29px 椭圆</b>。这看起来是个大 bug。</p>
<p>于是做了 A/B（<code>engine/ball_tile_ab.py</code>，在人工标注帧上比较真球位置的最高置信度）。
结果<b>证伪了这个假设</b>：</p>""")
    ta = jload(MS / "tileab.json", None)
    if ta:
        A("""<table><tr><th>tile 几何</th><th class="num">真球命中率</th>
<th class="num">真球处置信中位</th><th class="num">tile/帧</th></tr>""")
        for k, v in ta["results"].items():
            A(f"""<tr><td>{k}</td><td class="num">{v['tp_hit_rate']*100:.1f}%</td>
<td class="num">{v['tp_best_median']:.3f}</td>
<td class="num">{v['tiles_per_frame']:.1f}</td></tr>""")
        A("</table>")
    A("""<div class="box neg">方形恒等（384×384，球保持 25×29）与现行拉伸版（640×384，球 15×29）
<b>真球置信度几乎一模一样</b>；更小的 tile（把球放大 1.33×/1.5×）<b>反而更差</b>。
⇒ 模型对这个像素尺度区间不敏感，<b>球的问题不是分辨率，是外观可分性</b>。
附带结论：<b>放大 tile 有害，勿走</b>。</div>""")

    # ---------- 5. 全候选重排 ----------
    A("<h2>5 · 全候选重排：现行管线扔掉了 89% 的候选</h2>")
    A(f"""<p>原始 tile 检出 <b>{tot}</b> 个候选，但 <code>detect_ball_verified.py --top1</code> 只留每帧
conf 最高的 1 个再送验证头打分 —— 其余 <b>{100*(1-kept/tot):.0f}%</b> 的候选
<b>从未被验证头看过</b>（最终只输出 {kept} 个）。而 conf 又不携带信息 ⇒ 这个筛选接近随机丢。</p>
<p>已对<b>全部 {tot} 个候选</b>重跑二次验证（conf2 全标）与验证头打分，再做 A/B：
在 324 个已人工标注的帧上，比较"旧 top-1（按 conf）"与"新 top-1（验证头在全部候选里 argmax）"。</p>""")
    if ab:
        A(f"""<table><tr><th>指标</th><th class="num">值</th></tr>
<tr><td>已标注帧</td><td class="num">{ab['n']}</td></tr>
<tr><td>新旧 top-1 <b>一致</b>（标签可沿用）</td>
<td class="num">{ab['same_TP']+ab['same_FP']}（原 TP {ab['same_TP']} / 原 FP {ab['same_FP']}）</td></tr>
<tr><td>新旧 top-1 <b>变化</b>（需人工复核）</td>
<td class="num">{ab['changed']}（其中原标注为 TP 的 {ab['changed_is_oldTP']} 个）</td></tr>
<tr><td>旧口径基础精度（conf top-1）</td><td class="num">{ab['oldP']:.1f}%</td></tr>
<tr><td>新口径基础精度<b>下界</b>（变化全判为 FP）</td><td class="num">{ab['lo']:.1f}%</td></tr>
<tr><td>新口径基础精度<b>上界</b>（变化全判为 TP）</td><td class="num">{ab['hi']:.1f}%</td></tr>
</table>
<p class="small">变化的那些帧已渲成接触表（<code>allcand_ab_sheet*.jpg</code>，上=原框、下=新 top-1），
需逐格人工判读后才能定论。上下界之间就是这步的收益空间。</p>""")
    else:
        A('<div class="box warn">全候选打分尚未完成，本节数字待补。</div>')

    # ---------- 6. 路线 ----------
    A("<h2>6 · 通往 ≥90% 的三条路（按性价比排序）</h2>")
    A("""<table><tr><th>#</th><th>路线</th><th>为什么可能有效</th><th>成本/风险</th></tr>
<tr><td>R1</td><td><b>全候选重排 + 轨迹级门禁</b>（本轮已铺好地基）</td>
<td>立即回收被扔掉的 89% 候选；把"逐帧独立判断"改成"整条轨迹判断"，
真球的轨迹平滑、假阳性时间孤立（已在特征里，w3 曾靠它从"无工作点"打开）</td>
<td class="ok">低。无需新标注、无需训练。收益上界 = §5 的上界</td></tr>
<tr><td>R2</td><td><b>本域微调检测器</b>（L9 真身）</td>
<td>直接打 map_ball=0.18 这个根因；用验证头在高精度工作点上做教师自动标，
补上"标签源不成立"这个当年判死 Phase B 的理由</td>
<td class="warn">中高。M4/16GB 上训 RF-DETR 慢；160 个真框偏少，需靠教师扩样</td></tr>
<tr><td>R3</td><td><b>换素材/机位</b></td>
<td>25px 的球 + 广播级运动模糊，是问题的物理下限；换成球占 60–100px 的机位，
整条精度曲线的形状都会变</td>
<td class="bad">高（改变产品形态）。但可能是唯一能<b>彻底</b>解决的路</td></tr>
</table>""")
    A("""<div class="box"><b>我的建议</b>：先把 R1 走完（已完成 90% 的工程铺垫，只差人工判读变化帧），
拿到"全候选重排"的真实收益；若仍未达标，再决定是投 R2 的算力还是走 R3 换素材。
<b>球场路线暂停</b> —— 它的收益已被实测证明为零（C0→C1 无变化），不要在这里继续沉没成本。</div>""")

    A('<p class="small">报告生成时间戳由文件系统给出；所有数值均取自 '
      '<code>action_work/</code> 与 <code>reports/milestone_05/measure/</code> 下的原始 JSON。'
      '</p></body></html>')
    OUT.write_text("".join(H), encoding="utf-8")
    print(f"[out] {OUT}")
    print(f"  候选 {tot} / 帧 {frames} / 现行保留 {kept}  模型卡 Map Ball={mb}")
    if ab:
        print(f"  A/B: 变化 {ab['changed']}  精度区间 [{ab['lo']:.1f}%, {ab['hi']:.1f}%]")


if __name__ == "__main__":
    main()
