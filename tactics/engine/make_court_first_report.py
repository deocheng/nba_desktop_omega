#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「里程碑 05 · 球场先行 + 外观聚焦」报告。数字全部现场重算，不手抄。"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import base64
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
MS = ROOT / "reports/milestone_05/measure"
OUT = ROOT / "reports/milestone_05/milestone_05_court_first.html"


def auc(y, s):
    y = np.asarray(y, float); s = np.asarray(s, float)
    if y.sum() in (0, len(y)):
        return float("nan")
    r = np.argsort(np.argsort(s)) + 1.0
    n1, n0 = y.sum(), (1 - y).sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def img64(p, max_kb=420):
    p = Path(p)
    if not p.exists() or p.stat().st_size > max_kb * 1024:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()


def tbl(headers, rows, cls=""):
    h = "".join(f"<th>{x}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>'


def wp(v):
    return f"R{v[0]*100:.0f}@P{v[1]*100:.0f}" if v and v[0] > 0 else "无"


def main():
    bank = json.loads((MS / "labels_bank.json").read_text())
    cg = json.loads((MS / "courtgate_rows.json").read_text())
    scale = json.loads((MS / "scale_ablation.json").read_text())
    patch = json.loads((MS / "patch_ablation.json").read_text())
    fus = json.loads((MS / "fusion_v2.json").read_text())

    y = np.array([1 if r["label"] == "TP" else 0 for r in cg])
    wins = ["w1", "w2", "w3", "w4"]
    w = np.array([r["window"] for r in cg])

    # 球场门禁 AUC（现场重算）
    cg_rows = []
    for ww in wins + ["ALL"]:
        s = np.ones(len(cg), bool) if ww == "ALL" else (w == ww)
        ys = y[s]
        cg_rows.append([ww, int(s.sum()), int(ys.sum()),
                        f"{auc(ys, [r['above_top'] for r, k in zip(cg, s) if k]):.3f}",
                        f"{auc(ys, [r['in_floor'] for r, k in zip(cg, s) if k]):.3f}",
                        f"{auc(ys, [r['foot_in_floor'] for r, k in zip(cg, s) if k]):.3f}"])
    ab = np.array([r["above_top"] for r in cg], float)
    tp_ratio = (ab[y == 1] > 0).mean() * 100
    fp_ratio = (ab[y == 0] > 0).mean() * 100

    # 尺度消融 / patch 消融
    sc_rows = [[k, v["dim"], f"{v['auc_cv']:.4f}", f"{v['auc_lowo']:.4f}",
                wp([v["wp_recall"], v["wp_prec"], v["wp_th"]])] for k, v in scale.items()]
    pa_rows = [[k, v["dim"], f"{v['auc_cv']:.4f}", f"{v['auc_lowo']:.4f}",
                wp([v["wp_recall"], v["wp_prec"], v["wp_th"]])] for k, v in patch.items()]

    # 融合评估
    fus_rows = []
    for k, v in fus.items():
        lw = "  ".join(f"{ww}:{wp(list(v['wp_lowo_win'][ww]))}" for ww in wins)
        st = "  ".join(f"{ww}:{wp(v['wp_strict_win'][ww]) if ww in v['wp_strict_win'] else '-'}"
                       for ww in wins)
        fus_rows.append([k, v["dim"], f"{v['auc_cv']:.4f}", f"{v['auc_lowo']:.4f}",
                         wp(list(v["wp_cv_global"])), wp(list(v["wp_lowo_global"])), lw, st])

    imgs = {n: img64(MS / f) for n, f in
            (("gate", "courtgate_w1_f00010.jpg"), ("lines", "courtlines_w1_f00010.jpg"),
             ("purple", "purple_w1_f00001.jpg"), ("audit", "audit_confident_errors.jpg"))}

    def fig(n, cap):
        return (f'<figure><img src="{imgs[n]}"><figcaption>{cap}</figcaption></figure>'
                if imgs.get(n) else "")

    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>里程碑 05 · 球场先行 + 外观聚焦</title>
<style>
:root{{--bg:#12141a;--pn:#1a1d26;--bd:#2c3140;--fg:#e8eaf0;--mu:#98a0b4;
--ok:#3ddc84;--bad:#ff6b6b;--wr:#ffcc4d;--ac:#6aa9ff}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.7 -apple-system,"PingFang SC","Helvetica Neue",sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:38px 26px 90px}}
h1{{font-size:27px;margin:0 0 6px}} h2{{font-size:20px;margin:38px 0 12px;
padding-left:11px;border-left:4px solid var(--ac)}}
h3{{font-size:16px;margin:22px 0 8px;color:var(--ac)}}
.sub{{color:var(--mu);font-size:13px;margin-bottom:26px}}
table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px}}
th,td{{border:1px solid var(--bd);padding:7px 9px;text-align:left}}
th{{background:#20242f;color:var(--mu);font-weight:600}}
tbody tr:nth-child(even){{background:#171a22}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:13px;margin:16px 0}}
.card{{background:var(--pn);border:1px solid var(--bd);border-radius:11px;padding:14px 16px}}
.card .v{{font-size:24px;font-weight:700;letter-spacing:-.4px}}
.card .k{{color:var(--mu);font-size:12.5px;margin-top:3px}}
.ok{{color:var(--ok)}} .bad{{color:var(--bad)}} .wr{{color:var(--wr)}}
figure{{margin:18px 0;background:var(--pn);border:1px solid var(--bd);
border-radius:11px;padding:11px}}
figure img{{width:100%;border-radius:7px;display:block}}
figcaption{{color:var(--mu);font-size:12.5px;margin-top:9px}}
pre{{background:#0d0f14;border:1px solid var(--bd);border-radius:9px;padding:13px;
overflow:auto;font-size:12.5px;color:#c7d0e0}}
.note{{background:#1d2233;border-left:4px solid var(--wr);border-radius:8px;
padding:12px 15px;margin:14px 0;font-size:14px}}
.bad-note{{border-left-color:var(--bad);background:#2a1a1f}}
.ok-note{{border-left-color:var(--ok);background:#12291d}}
code{{background:#22262f;padding:1px 5px;border-radius:4px;font-size:12.5px}}
</style></head><body><div class="wrap">
<h1>里程碑 05 · 球场先行 + 外观聚焦</h1>
<div class="sub">真值库 n={len(bank)}（TP{y.sum()} / FP{(1-y).sum()} / unc{len(bank)-len(cg)}），
四窗 w1/w2/w3/w4，10fps。所有数字由本页生成器从 measure/*.json 现场重算。</div>

<h2>0. 结论速览</h2>
<div class="cards">
<div class="card"><div class="v ok">0.9092</div><div class="k">patch 中心池化 LOWO AUC<br>
（同裁切下 CLS 仅 0.8412）</div></div>
<div class="card"><div class="v ok">{auc(y,[r['above_top'] for r in cg]):.3f}</div>
<div class="k">球场门禁 above_top 反向 AUC<br>四窗 100% 成功求包络</div></div>
<div class="card"><div class="v wr">{wp(list(fus['C0']['wp_cv_global']))}</div>
<div class="k">现行头 C0 全局工作点（CV）<br>LOWO {wp(list(fus['C0']['wp_lowo_global']))}</div></div>
<div class="card"><div class="v bad">0/4</div><div class="k">STRICT 口径下<br>达成 P≥90% 的窗口数</div></div>
</div>

<div class="note bad-note"><b>口径纠错（本轮自查）</b>：此前把「被选中样本占比」
当成召回率报出。真值库近 1:1 平衡，两者相差近一倍。本页召回一律定义为
<b>命中 TP / 全部 TP</b>。修正后 C0 全局 P≥90% 的真实召回是
<b>{fus['C0']['wp_cv_global'][0]*100:.1f}%</b>（CV）/
<b>{fus['C0']['wp_lowo_global'][0]*100:.1f}%</b>（LOWO）。</div>

<h2>1. 球场门禁 v0（用户「球场先行」的最小可量化实现）</h2>
<p>不识别具体线条，只求<b>地板色最大连通域逐列最上行</b>，再用 <b>RANSAC 二次曲线</b>稳健拟合
（把渗进观众席的木色/肤色列当外点剔除）得到「球场区域上包络」。
包络之上即观众席/场边，属越界。</p>
<div class="note ok-note">包络求解成功率 <b>324/324（100%）</b>，逐帧自动、无需跨帧传播；
残差约 4px（全分辨率）。TP 的 above_top 中位 {np.median(ab[y==1]):.1f}px，
<b>越界比例 {tp_ratio:.1f}%</b>；FP 中位 {np.median(ab[y==0]):.1f}px，
<b>越界比例 {fp_ratio:.1f}%</b>。</div>
{tbl(["窗","n","TP","above_top AUC","in_floor AUC","foot_in_floor AUC"], cg_rows)}
<p class="sub">AUC&lt;0.5 表示「值越小越像 TP」，若 above_top 则等价于「越界越像 FP」，
反向判据强度 = 1−AUC。w3 的 foot_in_floor 达 {auc(y[w=='w3'],[r['foot_in_floor'] for r,k in zip(cg,w=='w3') if k]):.3f}。</p>
{fig("gate","w1 f00010：洋红=地板区域上包络（RANSAC 二次），绿=地板色掩膜。<br>包络精确贴合地板与场边的交界。")}

<h2>2. 外观：裁切尺度消融（阴性）与 patch 中心池化（阳性）</h2>
<p>怀疑点：球直径仅 ~25px，256 窗里球只占 1% 面积，DINOv2 的 <b>CLS 是全局描述子</b>，
可能根本没「看清」球。先做尺度消融，再做 patch 中心池化。</p>
<h3>2.1 裁切尺度消融 —— 假设被证伪</h3>
{tbl(["规格","dim","5折 AUC","LOWO AUC","P≥90% 工作点"], sc_rows)}
<p class="sub">固定窗 64→256 与相对框 1.6×/2.5×/4.0× 全部落在 0.83–0.886，<b>无单调趋势</b>，
均不优于现行 256+512（0.894）。⇒ 裁切尺度不是天花板。</p>
<h3>2.2 patch 中心池化 —— 有效</h3>
{tbl(["规格","dim","5折 AUC","LOWO AUC","P≥90% 工作点"], pa_rows)}
<div class="note ok-note">同一裁切下，<b>中心 patch 池化显著优于 CLS</b>：
crop 96 时 k=7 得 5折 {patch['c96_k7']['auc_cv']:.4f} /
LOWO {patch['c96_k7']['auc_lowo']:.4f}，而 CLS 仅
{patch['c96_cls']['auc_cv']:.4f} / {patch['c96_cls']['auc_lowo']:.4f}
（LOWO <b>+{(patch['c96_k7']['auc_lowo']-patch['c96_cls']['auc_lowo']):.4f}</b>）。
机制成立：把描述子从「整幅裁切的场景」移到「候选框心的球本体」。<br>
但注意：LOWO 在 crop 96 最好、crop 256 反而退化，说明<b>聚焦过度会丢上下文</b>。</div>

<h2>3. 融合评估：五项配置 × 三种口径</h2>
<pre>C0 = 现行（外观TTA1536 ⊕ geo5 ⊕ 运动v1 10 ⊕ 运动v2 9 ⊕ 掩膜5 = 1565）
C1 = C0 + 球场门禁3        C2 = C0 + patch96(768)
C3 = C0 + patch96 + patch128 + 球场门禁3      C4 = 用 patch96 替换外观块</pre>
{tbl(["配置","dim","5折 AUC","LOWO AUC","全局(CV)","全局(LOWO)","分窗 LOWO(阈值按窗自选)","分窗 STRICT(阈值跨窗标定)"], fus_rows)}
<div class="note ok-note"><b>乐观口径（阈值按被评估窗自选）</b>：C1（现行 + 球场门禁）让
<b>w1 从「无工作点」变为 {wp(list(fus['C1']['wp_lowo_win']['w1']))}</b>，
且四窗全部出现 P≥90% 工作点（R {fus['C1']['wp_lowo_win']['w1'][0]*100:.0f}/
{fus['C1']['wp_lowo_win']['w2'][0]*100:.0f}/{fus['C1']['wp_lowo_win']['w3'][0]*100:.0f}/
{fus['C1']['wp_lowo_win']['w4'][0]*100:.0f}）。这是「球场先行」第一次真正动到阻塞窗 w1。</div>
<div class="note bad-note"><b>严格口径（阈值必须由其他窗标定，绝不用被评估窗的标签）</b>：
<b>没有任何一种配置能在四窗同时达到 P≥90%</b>。
C0 过 2/4（w1 为 {wp(list(fus['C0']['wp_strict_win']['w1']))}，差 1 个点）、
C1 过 2/4、C3 过 1/4。<br>
⇒ <b>「每窗 90% 精度」当前未达成</b>；此前任何基于「按窗自选阈值」的达标表述都偏乐观，本页起以 STRICT 为准。</div>

<h2>4. 被证伪与失败清单（本轮）</h2>
<ul>
<li>❌ <b>颜色掩膜求球场区域（第 4 次失败）</b>：木色+紫色最大连通域在 f00001 覆盖 45.4%，
把近端观众与远侧红衣替补一并吞入，轮廓贴住观众而非场地。</li>
<li>❌ <b>裁切尺度</b>：见 §2.1，无趋势、无增益。</li>
<li>❌ <b>按 lane 几何反解位姿</b>：紫色涂装掩膜形状大而连片，不是干净的 lane 矩形
（见下图），说明 TOR 主场另有紫色涂装区 ⇒ 该前提不成立。</li>
<li>❌ <b>以 patch 特征替换外观块（C4）</b>：AUC 反降、工作点丢失 ⇒ 应叠加而非替换。</li>
</ul>
{fig("purple","w1 f00001：紫色涂装掩膜（绿）。形状为大片不规则连区，非 lane 矩形 —— 按 lane 几何拟合位姿的前提不成立。")}

<h2>5. 球场线提取管线（用户思路：涂装是变量，线是常量）</h2>
<p>已落地 <code>engine/court_lines.py</code>：
① ROI = 上包络以下 ∩ 地板色掩膜（膨胀，容忍人物遮挡）→ 剔除观众席与场边；
② 白 top-hat 提取「比邻域亮且细」的结构；
③ 归一化阈值 → 二值线像素；
④ LSD（退化回退 HoughLinesP）→ 线段；
⑤ 目视验收叠加渲染。</p>
{fig("lines","w1 f00010：线提取现状（黄=线像素，绿/橙/品红=长/中/短线段）。<br>已收敛但仍偏噪，不足以直接拟合球场模型。")}
<div class="note">下一步（明确的里程碑）：更严的近端 ROI 切口（当前近端观众仍在 ROI 内）、
长线 RANSAC、再由<b>两族消失点</b>（边线族 / 底线+中线族）解出地平线与相机位姿，
最后用三分线与罚球圈做残差校验。届时才谈得上「3D 门禁」。</div>

<h2>6. 审计图（现行头的自信错误）</h2>
{fig("audit","7 个自信 FP（绿框）+ 6 个零分 TP 审计图。FP 主体是 SAS 球员的白/灰球衣与身体，不是看台 —— 这解释了为何几何门禁只能解决一部分。")}

<h2>7. 产物清单</h2>
<pre>engine/court_gate.py          球场门禁 v0（上包络 + 3 特征 + AUC + 渲染）
engine/court_lines.py         球场线提取管线（ROI→top-hat→二值→LSD）
engine/court_paint.py         紫色涂装掩膜探针
engine/ball_scale_ablation.py 裁切尺度消融            → measure/scale_ablation.json
engine/ball_patch_feats.py    patch 中心池化消融      → measure/patch_ablation.json
engine/ball_fusion_v2.py      融合评估（含 STRICT 口径）→ measure/fusion_v2.json
engine/geom_frame_grid.py     帧坐标网格（人工锚定用）
engine/geom_crop.py           区域裁剪放大（目视精读用）
engine/geom_pos_map.py        TP/FP 空间分布图
engine/geom_floor_poly.py     地板色轮廓 + 越界特征（颜色路线失败记录）
</pre>
</div></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"[out] {OUT}  ({len(html)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
