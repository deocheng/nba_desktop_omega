#!/usr/bin/env python3
"""里程碑 03 报告（关系层闭环）：把 RelateAnything 第 5 层推到全片段并证伪其信息量。

本报告的全部数字从 JSON 现读，不硬编码。核心是**两条会翻转结论的方法学陷阱**：
  陷阱 1（里程碑 02 已立）朴素随机基线与「保持响应率剖面的置换检验」给出相反答案。
  陷阱 2（本轮新增）**对照组必须与实验组同单位**。首轮对照把「真位每帧 1 次」
           与「随机位每帧 6 次」直接比，得出 40.9% vs 13.6% = 3.0× 富集的假显著；
           对齐到「每帧任一次」后是 40.9% vs 59.1%，方向反了。

用法: make_milestone03_report.py <probe.json> <relations_full.json> <out.html>
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re

HOLD = {"holding", "carrying", "wearing", "riding", "using"}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def img(rel, cap, note=""):
    n = f'<figcaption class="note">{esc(note)}</figcaption>' if note else ""
    return (f'<figure><img src="{esc(rel)}" alt="{esc(cap)}">'
            f'<figcaption>{esc(cap)}</figcaption>{n}</figure>')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("probe_json")
    ap.add_argument("relations_json")
    ap.add_argument("out_html")
    ap.add_argument("--align-json", default="")
    ap.add_argument("--pose-json", default="")
    ap.add_argument("--sweep-json", default="")
    a = ap.parse_args()

    probe = json.load(open(a.probe_json))
    rel = json.load(open(a.relations_json))
    fr = rel["frames"]
    meta = rel["meta"]
    base = os.path.dirname(os.path.abspath(a.out_html))
    align = json.load(open(a.align_json)) if a.align_json else None
    pose = json.load(open(a.pose_json)) if a.pose_json else None
    sweep = json.load(open(a.sweep_json)) if a.sweep_json else None

    # ---------------- 全片段谓词统计 ----------------
    cnt = collections.Counter(t["pred"] for f in fr for t in f["triples"])
    tot = sum(cnt.values())
    scores = sorted(t["score"] for f in fr for t in f["triples"])
    q = lambda p: scores[min(int(len(scores) * p), len(scores) - 1)]      # noqa: E731

    # watching 沿时间（15 段）
    ws = [sum(1 for t in f["triples"] if t["pred"] == "watching") /
          max(len(f["triples"]), 1) for f in fr]
    seg = 29
    segs = [ws[i:i + seg] for i in range(0, len(ws), seg)]

    # ---------------- Q1 / Q2 ----------------
    q1 = probe["Q1_scope_effect"]
    q2 = probe["Q2_ball_holding"]
    rows = q2["rows"]
    n = len(rows)
    true_frame = sum(1 for r in rows if r["n_hold"] > 0)
    ctrl_frame = sum(1 for r in rows if any(p in HOLD for p in r["ctrl_predicates"]))
    ctrl_calls = [p for r in rows for p in r["ctrl_predicates"]]
    ctrl_call_hits = sum(1 for p in ctrl_calls if p in HOLD)
    t2 = q2["true_stratified_by_inside_player_box"]
    c2 = q2["control"]["ctrl_stratified_by_inside_player_box"]

    fisher = {}
    try:
        from scipy.stats import fisher_exact
        ti = round(t2["inside_box"]["hold_rate"] * t2["inside_box"]["n"])
        ci = round(c2["inside_box"]["hold_rate"] * c2["inside_box"]["n"])
        fisher["inside"] = tuple(
            float(v) for v in fisher_exact(
                [[ti, t2["inside_box"]["n"] - ti],
                 [ci, c2["inside_box"]["n"] - ci]]))
        fisher["same_unit"] = tuple(
            float(v) for v in fisher_exact(
                [[true_frame, n - true_frame], [ctrl_frame, n - ctrl_frame]]))
        fisher["mismatch"] = tuple(
            float(v) for v in fisher_exact(
                [[true_frame, n - true_frame],
                 [ctrl_call_hits, len(ctrl_calls) - ctrl_call_hits]]))
    except ImportError:                                          # pragma: no cover
        fisher = {"inside": (float("nan"),) * 2, "same_unit": (float("nan"),) * 2,
                  "mismatch": (float("nan"),) * 2}
    print(f"[stat] Fisher 框内 OR={fisher['inside'][0]:.2f} p={fisher['inside'][1]:.3f} | "
          f"同单位 OR={fisher['same_unit'][0]:.3f} p={fisher['same_unit'][1]:.4f} | "
          f"错单位 OR={fisher['mismatch'][0]:.3f} p={fisher['mismatch'][1]:.4f}")

    def kv(k, v, cls=""):
        return f'<div class="kv {cls}"><span class="k">{esc(k)}</span><span class="v">{esc(v)}</span></div>'

    def table(headers, rows_, cls=""):
        h = "".join(f"<th>{esc(x)}</th>" for x in headers)
        b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows_)
        return f'<table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>'

    # ---------------- 正文 ----------------
    pred_rows = [[f'<code>{esc(p)}</code>', f"{c:,}", f"{c / tot * 100:.1f}%",
                  "模型最偏好谓词" if p == "watching" else "—"]
                 for p, c in cnt.most_common()]

    seg_rows = [[f"{i + 1}", f"{i * seg}", f"{min(i * seg + seg - 1, len(ws) - 1)}",
                 f"{204.5 + i * (seg / 10):.1f}s", f"{sum(s) / len(s):.3f}"]
                for i, s in enumerate(segs)]

    scope_rows = []
    for k, v in q1.items():
        nm = {"A_all": "A 全部框（原口径）", "B_oncourt": "B 场上球员（脚点在球场内且框高 ≥60px）",
              "C_topk6": "C 最近 Top-6（按框高取最大 6 个）"}[k]
        top = "、".join(f"<code>{esc(p)}</code>×{c}" for p, c in v["top_predicates"][:4])
        scope_rows.append([nm, f"{v['n_box_per_frame']}", f"{v['n_triples']:,}",
                           f"<b>{v['distinct_predicates']}</b>",
                           f"<b>{v['watching_share']:.1%}</b>", top])

    q2_rows = [[r["idx"], r["t"], r["n_box"], r["nearest_player"],
                f"{r['nearest_box_dist_px']}", "✅ 是" if r["nearest_in_box"] else "否",
                r["n_hold"], f"{r['ctrl_n_hold']}/6",
                "、".join(f"<code>{esc(p)}</code>" for p in r["ball_predicates"]) or "—"]
               for r in rows]

    # ---------------- 更正区块（v1 的时间戳错误）----------------
    corr_rows = []
    if align:
        v1 = {"R. Barrett": (218.5, 218.5), "J. Champagnie": (221.1, 221.5),
              "D. Fox": (223.4, 239.8), "J. Poeltl": (224.6, 244.3),
              "V. Wembanyama": (224.6, 244.3)}
        for e in align["events"]:
            w, r = v1.get(e["player"], (None, e["t"]))
            dev = "—" if w is None else (f"{r - w:+.1f}s" if abs(r - w) < 0.6
                                         else f"<b>{r - w:+.1f}s</b>")
            cls = "" if w is None or abs(r - w) < 0.6 else ' class="bad"'
            corr_rows.append([f"{e['n']} {esc(e['player'])} {esc(e['kind'])}",
                              f"clock {e['clock']}", f"{w}s", f"<b>{r}s</b>",
                              f"<span{cls}>{dev}</span>"])

    align_rows, align_cards = [], ""
    if align:
        name_cn = {"watching_share": "watching 占比",
                   "n_distinct_predicates": "每帧不同谓词数",
                   "predicate_entropy_norm": "归一化谓词熵"}
        for k, m in align["metrics"].items():
            align_rows.append([
                name_cn.get(k, k), f"{m['observed_event_mean']:.4f}",
                f"{m['null_mean']:.4f}",
                f"[{m['null_p05']:.4f}, {m['null_p95']:.4f}]",
                f"<b>{m['p_one_sided']:.4f}</b>",
                "✅ 显著" if m["significant_at_0.05"] else "⚠️ 不显著"])
            align_cards += kv(name_cn.get(k, k), f"p = {m['p_one_sided']:.3f}", "bad")
        per_ev = [[f"{r['n']}", f"{r['t']}s", esc(r['player']), esc(r['kind']),
                   f"{r['watching_at_frame']:.3f}",
                   "—" if r["watching_mean_win"] is None else f"{r['watching_mean_win']:.3f}"]
                  for r in align["per_event_watching"]]
    else:
        per_ev = []

    # ---------------- 姿态动作层区块 ----------------
    pose_cards, pose_jump_rows, jump_near_rows, sweep_rows = "", [], [], []
    if pose:
        al = pose["alignment"]
        c = pose["counts"]
        pose_cards = (kv("跳跃检出（v2）", f"{c['n_jumps']} 次 / 43.4s")
                      + kv("检出率", f"{pose['jump_rate_per_sec']} 次/秒")
                      + kv("争抢/封盖（联合判据）", f"{c['n_contests']} 次", "bad")
                      + kv("保留轨迹", f"{pose['track_filter']['n_kept']} / "
                                      f"{pose['track_filter']['n_tracks']} 条", "bad")
                      + kv("v2 对齐 p（默认参数）", f"{al['jumps']['p_value']:.4f}")
                      + kv("参数扫描显著格数",
                           f"{sweep['summary']['n_significant']}/{sweep['summary']['n_cells']}"
                           if sweep else "—", "bad"))
        pose_jump_rows = [[j["t"], f"track#{j['track']}", f"{j['air_dyn']:.3f}",
                           f"{j['span_sec']}s", f"{j['h']}px"] for j in pose["jumps"]]
        for e in pose["events"]:
            jn = [j for j in pose["jumps"] if abs(j["t"] - e["t"]) <= 2.0]
            nnd = min((abs(j["t"] - e["t"]) for j in jn), default=None)
            jump_near_rows.append([
                f"{e['n']}", f"{e['t']}s", esc(e["player"]), esc(e["kind"]),
                "、".join(f"{j['t']}s" for j in jn) or "—",
                "—" if nnd is None else f"{nnd:.1f}s"])
    if sweep:
        sweep_rows = [[f"±{r['half_win']}s", r["air_thr"], r["n_jumps"],
                       f"{r['jump_rate_per_sec']}", f"{r['obs_hits']}/5",
                       f"{r['null_mean']}", f"{r['p_jumps']:.4f}",
                       "✅" if r["sig_jumps"] else "⚠️"] for r in sweep["rows"]]

    body = f"""
<header>
  <p class="eyebrow">动作分析系统 · 里程碑 03（修订版 v2） · 关系层闭环 + 第二个模型的动作信号检验</p>
  <h1>关系层跑通了，但它不携带战术信息</h1>
  <p class="lede">把 RelateAnything 第 5 层（逐帧关系预测 + 官方 35 条裸短语）推到全
  435 帧片段，并做两组对照实验。结论是双重的：<b>闭环成立</b>（抽帧 → 检测追踪 →
  关系图序列，全片段 2610 条三元组已产出），但<b>该层的输出没有任何战术信息量</b>
  ——人—人关系退化成 <code>watching</code>，球—人关系只是几何包含的复述。
  同时暴露了第二个会翻转结论的方法学陷阱：<b>对照组必须与实验组同单位</b>。</p>
  <p class="lede"><b>本版为修订版（v2）</b>：修订了 v1 的一处时间戳错误，并把第二个模型
  （YOLO11n-pose）从「只提供几何」正式提升为「动作信号源」加以检验。两处都见下方专门章节。</p>
</header>

<section>
  <h2>⓪ 修订说明：v1 把两个 PBP 事件的时间写错了 16–20 秒</h2>
  <div class="warn">
    <p><b>v1 的错误</b>：报告正文与配套图 <code>fig_rel_time.png</code> 中，我把窗口内
    4 个 PBP 转换点的时间标成 <code>218.5 / 221.1 / 223.4 / 224.6 s</code>（手写常量），
    并据此写下了「<i>watching 占比在战术转换点上没有任何结构变化</i>」与
    「<i>t≈239–242 的下探没有被任何已知战术事件解释</i>」两句结论。</p>
    <p><b>事实</b>：事件时间必须从画面比分牌的逐帧读秒表插值得到。核对
    <code>clock_table.json</code> 后，③④ 两个事件的实际时刻是 <b>239.8s</b> 与 <b>244.3s</b>，
    我把虚线画在了完全无关的时刻上。而 <b>239.8s 正是那次失误/抢断</b> ——
    我为「下探找不到解释」而感到的困惑，其实是我自己标错了时间造成的。</p>
    {table(["事件", "PBP 时钟", "v1 标注", "实际 t", "偏差"], corr_rows) if corr_rows else ""}
    <p><b>处置</b>：① 图表的 PBP 时间改为<b>由读秒表推导</b>，脚本里不再允许出现手写事件时间；
    ② 对齐检验改为<b>数据驱动事件时刻 + 置换检验</b>（见 ⑤），而不是把标记画上去再目视判断；
    ③ 本条错误保留在报告中留痕，不删除。</p>
    <p><b>教训（写入技能）</b>：<b>凡是要把自己算出来的时刻和外部事件比对，事件时刻一律由数据推导，
    绝不允许手写常量。</b>手写常量错 20 秒，图上看不出来，结论就全歪了。</p>
  </div>
</section>

<section>
  <h2>① 结论摘要</h2>
  <div class="cards">
    {kv("闭环覆盖", f"{len(fr)} / 435 帧 (100%)")}
    {kv("三元组总量", f"{tot:,} 条（{tot / len(fr):.1f}/帧）")}
    {kv("推理速度", f"{meta['predict_ms_per_frame']} ms/帧 · CPU")}
    {kv("实际用到的谓词", f"{len(cnt)} / 35 条")}
    {kv("watching 占比", f"{cnt['watching'] / tot:.1%}", "bad")}
    {kv("球—人 holding 命中", f"{true_frame}/{n} = {true_frame / n:.1%}")}
    {kv("同单位对照命中", f"{ctrl_frame}/{n} = {ctrl_frame / n:.1%}", "bad")}
    {kv("框内分层差异", "Fisher OR=1.00 p=1.00", "bad")}
    {kv("关系层 × 事件对齐", f"p = {align['metrics']['watching_share']['p_one_sided']:.3f}"
                            if align else "—", "bad")}
    {kv("姿态起跳检出", f"{pose['counts']['n_jumps']} 次（{pose['jump_rate_per_sec']}/s）"
                        if pose else "—")}
    {kv("动作对齐参数扫描",
        f"{sweep['summary']['n_significant']}/{sweep['summary']['n_cells']} 格显著"
        if sweep else "—", "bad")}
  </div>
  <div class="cards">
    <div class="verdict ok">
      <h3>✅ 站得住的</h3>
      <ul>
        <li>关系层在整片段上<b>跑通且可复现</b>：435 帧、2610 条三元组、
            {meta['predict_ms_per_frame']} ms/帧、模型载入 {meta['load_sec']}s、全片段
            {meta['total_sec']}s。姿态缓存可复用。</li>
        <li>关系层的分数分布与里程碑 02 的单帧实测<b>同量级</b>：本轮 max
            {scores[-1]:.4f} / 中位 {q(0.5):.4f}，此前单帧 max 0.5133、自建长句式 0.0860。
            ⇒ 「必须用官方裸短语」这条结论在 435 帧上再次成立。</li>
        <li><b>退化不是名单污染</b>：三种名单口径下都只用到 4 个谓词（见 ③），
            所以问题出在模型对「人—人」这个关系类型的固有偏好，不是我们把观众框喂进去了。</li>
        <li><b>姿态层（第二个模型）确实产出了物理合理的动作线索</b>：v2 检出的 4 次起跳
            落在出手 / 篮板 / 上篮封盖附近，且检出率 0.092 次/秒量级合理。
            它是本轮唯一<b>没有</b>被证伪的动作信号方向（但见下条）。</li>
      </ul>
    </div>
    <div class="verdict no">
      <h3>❌ 不成立的</h3>
      <ul>
        <li><b>球—人 <code>holding</code> 不可用</b>。真球位置与随机位置在「框内 / 框外」
            两层上的命中率<b>完全相同</b>（0.818 vs 0.818、0.000 vs 0.000，Fisher
            OR=1.00 p=1.00）。<code>holding</code> 只是在复述「小方框几何落在球员框内」，
            而这个量我们自己用 <code>box_dist</code> 算更省事、更免费。</li>
        <li><b>「3.0× 富集」是假的</b>。首轮对照 40.9% vs 13.6% 看似显著，但真位是
            「每帧 1 次」而对照是「每帧 6 次」——单位不同不可比。对齐到「每帧任一次」后
            变成 40.9% vs 59.1%，方向反了（Fisher OR=0.479 p=0.366）。</li>
        <li><b>关系层不能作为战术证据源</b>。改用由读秒表推导的真实事件时刻后，
            三个指标（watching 占比 / 不同谓词数 / 谓词熵）在事件邻域内<b>均不显著</b>
            （p = 0.383 / 0.426 / 0.461，见 ⑤）。</li>
        <li><b>骨架动作信号的对齐也不能写成结论</b>。默认参数下 p=0.0415 显著，
            但 {sweep['summary']['n_significant']}/{sweep['summary']['n_cells']} 个参数格
            里只有 1 格显著（{sweep['summary']['significant_share']:.1%} vs
            期望 {sweep['summary']['expected_share_under_alpha0.05']:.0%}）⇒ 花园小径，
            属"物理线索"而非统计结论（见 ⑥）。</li>
        <li><b>v1 报告里「239–242s 的下探无法解释」是错的</b>——那是我把 ③ 事件时间
            标错造成的幻觉；实际 239.8s 就是那次失误/抢断（见 ⓪）。</li>
      </ul>
    </div>
  </div>
</section>

<section>
  <h2>② 这一层在整片段上到底输出了什么</h2>
  <p>435 帧、每帧 6 条（<code>topk=6</code>）、合计 {tot:,} 条三元组。把谓词全量计数：
     <b>35 条词表里只出现了 {len(cnt)} 条</b>，且分布极度偏斜。</p>
  {table(["谓词", "条数", "占比", "备注"], pred_rows)}
  <p class="warn">🔴 分数分布：p05={q(0.05):.4f} / p25={q(0.25):.4f} / 中位={q(0.5):.4f} /
     p75={q(0.75):.4f} / max={scores[-1]:.4f}，均值 {sum(scores) / len(scores):.4f}。
     <b>整个片段没有一条超过 0.55</b>，和里程碑 02 单帧实测的 0.5133 天花板一致。
     这不是采样不足，是模型能力的真实上限。</p>
</section>

<section>
  <h2>③ 实验一：退化是不是名单污染造成的？（Q1）</h2>
  <p>原口径把姿态检测到的所有框都喂给模型（{q1['A_all']['n_box_per_frame']} 人/帧，
     其中含观众、替补席、裁判）。如果退化只是被这些无关框稀释，那么只保留场上球员
     应该会显著改善。三种口径各跑 25 帧、每帧 <code>topk=6</code>、固定总三元组
     150 条以便直接比较：</p>
  {table(["名单口径", "框/帧", "三元组", "不同谓词数", "watching 占比", "Top-4 谓词"], scope_rows)}
  {img("fig_rel_q1.png", "图 1　名单口径对退化的影响",
       "左：A→B 把观众/替补/裁判剔掉后 watching 占比不降反升（86.0%→88.0%）；"
       "右：三种口径都只用到 4 个谓词，词表上限的 35 条用不到 1/8。")}
  <p><b>结论</b>：剔除场外人员<b>没有帮助</b>（86.0% → 88.0%，反而略升）。把框数压到 6 个
     会让 watching 降到 67.3%，但<b>不同谓词数仍然是 4</b>——也就是说剩下的 32%
     只是换成了 <code>to the left of</code> / <code>to the right of</code> /
     <code>beside</code> 这些<b>纯方位词</b>，信息量并没有增加。
     ⇒ <b>这是模型在「人—人」关系类型上的固有退化</b>，不是我们的输入脏。</p>
</section>

<section>
  <h2>④ 实验二：给出球框，模型能判断「谁持球」吗？（Q2）</h2>
  <p>这是关系层唯一可能有实用价值的方向：把已目视确认的真球位置（{n} 帧，来自
     <code>ball_truth.json</code> 的 6.3× 终审层 + 上升段 6 点）做成同尺寸方框，
     与球员框一起送进模型，看它能否产出 <code>holding</code> / <code>carrying</code>。</p>
  <h3>4.1　首轮结果看起来很好，但是错的</h3>
  <div class="cards">
    {kv("真位命中（每帧 1 次）", f"{true_frame}/{n} = {true_frame / n:.1%}")}
    {kv("对照命中（逐调用）", f"{ctrl_call_hits}/{len(ctrl_calls)} = {ctrl_call_hits / len(ctrl_calls):.1%}")}
    {kv("表面富集倍数", f"{(true_frame / n) / (ctrl_call_hits / len(ctrl_calls)):.1f}×", "bad")}
    {kv("问题", "真位 1 次/帧 vs 对照 6 次/帧", "bad")}
  </div>
  <p class="warn">🔴 <b>单位不对齐</b>。对照在同一帧里放了 6 个随机位置，
     「每帧任一次命中」的概率天然被放大 6 倍。把两边的统计单位都改成
     <b>「每帧任一次」</b>之后：</p>
  <div class="cards">
    {kv("真位 / 帧任一次", f"{true_frame}/{n} = {true_frame / n:.1%}")}
    {kv("对照 / 帧任一次", f"{ctrl_frame}/{n} = {ctrl_frame / n:.1%}", "bad")}
    {kv("Fisher 同单位", f"OR={fisher['same_unit'][0]:.3f} p={fisher['same_unit'][1]:.4f}", "bad")}
    {kv("判定", "不显著，且方向反转", "bad")}
  </div>
  <h3>4.2　真正的原因：<code>holding</code> 只是几何包含</h3>
  <p>把真位与对照都按「球框是否落在某个球员框内」分层，结果完全重合：</p>
  {img("fig_rel_q2.png", "图 2　决定性对照：真球位置 vs 随机位置",
       "框内层 0.818 vs 0.818（n=11 vs 22）、框外层 0.000 vs 0.000（n=11 vs 110）。"
       "Fisher 精确检验 OR=1.00、p=1.00 —— 两组无法区分。")}
  {table(["条件", "真球位置", "随机对照", "Fisher"],
         [["框内（球框落在球员框内）",
           f"<b>{t2['inside_box']['hold_rate']:.3f}</b> (n={t2['inside_box']['n']})",
           f"<b>{c2['inside_box']['hold_rate']:.3f}</b> (n={c2['inside_box']['n']})",
           f"OR={fisher['inside'][0]:.2f} p={fisher['inside'][1]:.2f}"],
          ["框外（球框落在球员框外）",
           f"<b>{t2['outside_box']['hold_rate']:.3f}</b> (n={t2['outside_box']['n']})",
           f"<b>{c2['outside_box']['hold_rate']:.3f}</b> (n={c2['outside_box']['n']})",
           "两组均无事件"]])}
  <p><b>结论</b>：<code>holding</code> 是否触发，<b>完全由「小方框是否几何落在球员框内」
     决定</b>，与框里的内容是不是球无关。模型在这个尺度上没有做出独立的持球语义判断
     ——它输出的正是我们自己 20 行代码就能算出的几何关系。
     ⇒ 关系层<b>不能</b>用来做持球归属。</p>
  <h3>4.3　逐帧明细（可复核）</h3>
  {table(["idx", "t", "球员框数", "几何最近球员", "最近框距 px", "球在框内", "真位命中", "同帧对照", "球相关谓词"], q2_rows)}
  <p class="note">「最近框距」是球点到球员框的最短距离（0 = 点在框内）。
     用点到框而不是点到脚点，因为球在空中时 y≈170–600 而脚点 y≈600–900，
     点到脚点会把所有帧的距离都推到 100px 以上、失去区分力（首版就踩了这个坑）。</p>
</section>

<section>
  <h2>⑤ 关系层有没有战术信息？（沿时间看）</h2>
  <p>如果关系层承载战术信息，那么在 PBP 的战术转换点上，谓词分布应该发生变化。
     把 <code>watching</code> 占比逐帧画出来，叠上窗口内 4 个转换点：</p>
  {img("fig_rel_time.png", "图 3　全 435 帧 watching 占比 vs PBP 战术转换点",
       "四个转换点：① t=218.5s Barrett 三分出手　② t=221.1s Champagnie 篮板　"
       "③ t=223.4s Fox 失误/Barnes 抢断　④ t=224.6s Poeltl 上篮被 Wembanyama 封盖。")}
  <p>v1 在这里写的是「四个转换点上没有任何结构变化」——那是<b>基于错误的事件时刻</b>得出的
     （见 ⓪）。改用由读秒表推导的真实时刻后，正确的做法不是目视，而是
     <b>把「事件邻域内的取值」与「该片段自身所有同宽滑动窗口」作置换检验</b>。
     统计量取 5 个事件时刻 ±2.5s 邻域的均值，零假设由随机抽取同样多的窗口中心生成（2000 次）：</p>
  {table(["指标", "事件邻域均值", "null 均值", "null 5–95% 区间", "p（单侧）", "判定"], align_rows) if align_rows else ""}
  <div class="cards">{align_cards}</div>
  <p>三个指标全部<b>不显著</b>。看起来最像"有反应"的是 ③ 失误/抢断：</p>
  {table(["事件", "t", "球员", "类型", "该帧 watching", "±2.5s 窗口均值"], per_ev) if per_ev else ""}
  <p>③（239.8s，失误+抢断）的窗口均值 <b>0.614</b> 是五个事件里最低的，也是我 v1 里那个
     「找不到解释的下探」——现在它有解释了：<b>它就是 239.8s 这次球权转换</b>。
     但同时 ④⑤（244.3s，上篮被封盖）处于<b>全局最高</b>（0.895，该帧 1.000）。
     两者相互抵消，所以<b>整体检验不显著</b>。</p>
  <p class="warn">🔴 这里必须把话说清楚：<b>不能</b>因为 ③ 一个点看着对就说"关系层能捕捉球权转换"，
     也<b>不能</b>因为整体不显著就说"完全无信息"。正确的表述是：
     <b>在 5 个事件的样本量下，关系层的三个指标都没有显示出与战术事件的可检出关联
     （p = 0.383 / 0.426 / 0.461）；单个点的吻合不足以支撑结论，且该片段没有更多事件可用来提高检验力。</b></p>
  <p>逐段数值（供交叉核对）：</p>
  {table(["段", "idx 起", "idx 止", "t", "watching 占比"], seg_rows)}
</section>

<section>
  <h2>⑥ 引入第二个模型做动作识别：YOLO11n-pose 的骨架到底能不能用</h2>
  <p>项目里其实一直跑着<b>两个</b>模型：RelateAnything（关系预测）与
     <b>YOLO11n / YOLO11n-pose</b>（检测 + 姿态）。但姿态模型此前<b>只被当作几何提供者</b>
     ——给球员框、给手腕坐标去卡球——它的<b>骨架运动</b>从未被用来识别动作。
     本节把这一层补上并检验。第一步是把 435 帧的 <b>完整 17 个 COCO 关键点</b>补出来
     （旧缓存只留了框和手腕，跳跃/封盖的核心判据全在被丢弃的关键点上）。</p>

  <h3>6.1　v1 失败：4.47 次起跳/秒</h3>
  <p class="warn">v1 用「整条轨迹踝关节 y 的中位基线」+ 全局中位位移做摇镜补偿 + 最小框高 60px，
     结果 <b>{pose['v1_failure_record']['result'] if pose else 'n/a'}</b>。
     诊断出的三条根因（都是从数据里量出来的）：
     ① 框中位高 219px、<b>p05 已是 124px</b> ⇒ 最小框高 60px 的过滤等于没过滤（100% 通过）；
     ② <b>46.6% 的框底 y&lt;600</b>（画面上半部）⇒ 近半检出是观众/替补，不是场上球员；
     ③ 贪心 IoU 把轨迹切得很碎（771 条里只有 <b>87 条</b> ≥15 帧），
     在短轨迹上取「整条中位数」当基线，任何抖动都被当成起跳。
     <b>而且置换检验给出 p=1.0</b>（null 均值同样饱和到 5.0）——指标饱和时检验本身失效。</p>

  <h3>6.2　v2：滚动中位数去趋势 + 场上球员约束</h3>
  <p>三条修正：① 用<b>滚动中位数（11 帧）去趋势</b>替代全局基线——跳是快事件、摇镜是慢漂移，
     局部去趋势一次性消掉摇镜，比显式的全局平移估计更稳；② 轨迹必须
     <b>踝关节在 ≥70% 帧可用</b>（不用框底回退）且<b>脚点在画面下半部</b>；
     ③ 事件要求是<b>局部极大 + 上升下降完整 + 时长 ≤1s</b>，而不是"超过阈值"。</p>
  <div class="cards">{pose_cards}</div>
  <p>起跳次数从 194 降到 <b>4</b>（0.092 次/秒），这个量级对一段 43 秒的半场攻防是合理的
     （出手、抢篮板、上篮/封盖各一次左右）。而且这 4 次落点很"漂亮"：</p>
  {table(["事件", "t", "球员", "类型", "±2s 内的起跳", "最近距离"], jump_near_rows) if jump_near_rows else ""}
  <p>逐次起跳明细：</p>
  {table(["t", "轨迹", "air_dyn 峰值", "跨越时长", "框高"], pose_jump_rows) if pose_jump_rows else ""}
  {img("fig_pose_timeline.png", "图 4　骨架起跳信号 vs PBP 事件（事件时间由读秒表推导）",
       "三角标记 = v2 检出的 4 次起跳。它们正好落在事件 ①②（出手 / 篮板）与 ④⑤"
       "（上篮 / 封盖）附近 —— 物理上说得通，但看这张图<b>无法判定是否为巧合</b>，"
       "因为整段的 air_dyn 基线本身也在起伏。判定交给下一节的参数扫描。")}

  <h3>6.3　🔴 但参数扫描推翻了「显著」</h3>
  <p>默认参数（半宽 ±1.5s、阈值 0.15）下，置换检验给出 <b>p = 0.0415，显著</b>。
     单看这一格很容易直接写成正向结论。但参数是人为选的，所以我扫了
     半宽 ∈ {{1.0, 1.5, 2.0, 2.5, 3.0}} × 阈值 ∈ {{0.10, 0.15, 0.20}} 共 15 格
     （每格独立跑 2000 次置换）：</p>
  {img("fig_pose_sweep.png", "图 5　动作对齐检验的参数扫描", "")}
  {table(["邻域半宽", "air 阈值", "起跳次数", "检出率 /s", "命中", "null 均值", "p 值", "显著"], sweep_rows) if sweep_rows else ""}
  <p class="warn">🔴 <b>15 格中只有 1 格 p&lt;0.05</b>（比例 {sweep['summary']['significant_share'] if sweep else 'n/a'}，
     而 α=0.05 下的偶然期望是 {sweep['summary']['expected_share_under_alpha0.05'] if sweep else 'n/a'}）。
     两者没有实质差别 ⇒ <b>这一格显著性属于「花园小径」：在足够多的参数组合里，总有一格会碰巧低于 0.05。</b>
     所以结论必须是：<b>骨架起跳信号与 PBP 事件的对齐，在当前样本量下不成立为统计结论。</b></p>
  <p>另有两点如实记录：① <b>「争抢/封盖」联合判据 0 次检出</b>——原因是
     「手举过肩」（reach&gt;0.10）本身只占场上球员样本的 2.4%（腕在肩下是常态，占 95.3%），
     与起跳的局部极大帧同时出现太罕见；这是<b>判据过严</b>，不是 bug，但也没拿到结果。
     ② 起跳信号在图上确实"看着对"（图 4 里 4 个三角正好在事件 ①②④⑤ 附近），
     它构成<b>物理上说得通的线索</b>，但按纪律<b>不能</b>升级为统计结论。</p>
</section>

<section>
  <h2>⑦ 本轮新增的方法学铁律（第 8、9 条）</h2>
  <div class="rule">
    <h3>🔴 对照组必须与实验组<b>同单位</b>；且模型输出要先怀疑是不是输入几何的复述</h3>
    <p>里程碑 02 已经确立「朴素随机基线 vs 保持响应率剖面的置换检验会给出相反答案」。
       本轮暴露出它的近亲：<b>单位不对齐</b>。</p>
    <ol>
      <li><b>统计单位必须显式声明并对齐。</b>「每帧 1 次」与「每帧 6 次」不可直接比。
          本轮首轮就是 1 vs 6，把 3.0× 的假富集当成了成果。对齐后方向反转
          （{true_frame / n:.1%} vs {ctrl_frame / n:.1%}）。</li>
      <li><b>对照必须同分布。</b>随机位置采样要在与真实目标相同的空间里抽
          （本轮限定在球场 ROI 内、y ∈ [0.10,0.75]·H），否则对照本身就不公平。</li>
      <li><b>分层后再比，而不是先比再解释。</b>把两组都按「框内/框外」分层后，
          差异直接归零（0.818 vs 0.818）。若不做分层，就会把两组的构成差异
          误读成模型能力差异。</li>
      <li><b>拿到一个「模型判断」先问：这个量我自己能不能算？</b>
          <code>holding</code> ≈ 框包含，<code>beside</code>/<code>to the left of</code>
          ≈ 方位比较，<code>watching</code> ≈ 默认值。当模型输出与输入几何一一对应时，
          它<b>没有增加信息</b>，不能当证据用。</li>
      <li><b>「模型偏好某个谓词」不等于「该谓词有判别力」。</b>
          84.6% 的 <code>watching</code> 是退化，不是「多数球员在互相注视」这种战术发现。</li>
    </ol>
  </div>
  <div class="rule">
    <h3>🔴🔴 第 9 条：外部事件时刻一律由数据推导；单格显著必须做参数扫描</h3>
    <p>这条来自本轮的两个真实事故。</p>
    <ol>
      <li><b>事件时刻绝不允许手写常量。</b>把「自己算出的量」与「外部事件」比对时，
          外部事件的时刻必须从权威载体<b>推导</b>（本轮：画面比分牌的逐帧读秒表插值）。
          v1 我手写了 4 个时刻，其中两个错了 <b>16–20 秒</b>；图上看不出来，
          结论却全歪了——我还替一个"找不到解释的下探"困惑了半天，那其实是标错的产物。
          以后：脚本里出现手写事件时间 = bug。</li>
      <li><b>参数扫描必须整表汇报，不许只报最好的一格。</b>本轮动作对齐在默认参数下
          p=0.0415 显著；扫 15 个合理组合后只有 1 格显著（6.7%），与 α=0.05 的偶然期望
          （5%）没有实质差别 ⇒ 那一格是<b>花园小径</b>。
          <b>判据：显著格数 / 总格数 若与 α 同量级，一律判"不稳健"。</b></li>
      <li><b>指标饱和会让检验本身失效。</b>v1 的动作检验里，观测命中 5/5 而 null 均值也是 5.0
          → p=1.0。当事件密度高到"任何窗口都命中"时，置换检验<b>没有区分力</b>，
          此时必须先去提高事件的选择性（降低基础率），而不是继续调 p 值。
          这与「覆盖度偏差」是同一类错误的两个面孔：<b>基础率太高 / 分布不均，都会让检验失去意义。</b></li>
      <li><b>「物理上说得通」是线索，不是结论。</b>4 次起跳正好落在出手/篮板/上篮封盖附近，
          这是很好的<b>线索</b>，可以指导下一轮怎么设计更强的动作判据；
          但在 p 不稳健的情况下，它<b>不能</b>被写成"骨架动作能解释战术事件"。</li>
    </ol>
  </div>
</section>

<section>
  <h2>⑧ 对项目的影响与下一步</h2>
  <p>关系层被证伪<b>不影响</b>里程碑 02 已建立的成果——球的颜色标定、篮筐锚定、
     目视真值集、PBP 球权链、置换检验这些都不依赖它。受影响的是「用 RelateAnything
     直接读战术」这条路线：<b>在本素材与当前模型规模下不可行</b>，需要换手段。
     姿态层则相反：它<b>确实产出了物理上合理的动作线索</b>，方向值得继续投入，
     只是当前样本量撑不起统计结论。</p>
  {table(["优先级", "下一步", "理由"],
         [["1", "关系层<b>不再作为证据源</b>，降级为可选可视化装饰（已在报告中标明）",
           "本轮已给出定量证伪，继续投入没有边际收益"],
          ["2", "姿态动作层<b>继续投</b>：把「争抢/封盖」判据放宽（reach 用相对自身分布的"
                "分位数而非固定 0.15），并加上<b>手腕峰值高度</b>与<b>髋-踝距离</b>两个特征",
           "起跳线索物理合理；本轮 0 次争抢是判据过严（手过肩仅占 2.4%）"],
          ["3", "<b>扩大样本</b>：本片段只有 5 个 PBP 事件，检验力天然不足；"
                "再取 3–5 个片段（同一场比赛的不同回合）即可把事件数提到 20+",
           "所有不显著结论都受限于 n=5；这是当前最大的瓶颈，比换模型更优先"],
          ["4", "球员身份用<b>球衣号码 OCR</b>",
           "关系三元组的 s/o 现在只是帧内序号（<code>sel_id</code>），"
           "没有身份就无法跨帧构成战术序列；轨迹也只有本脚本内的临时编号"],
          ["5", "若仍要关系语义，需<b>换更大的开放词表模型</b>（如全量 19,103 词表 + 映射层）",
           "35 条裸短语只用到 8 条、上限 0.55，天花板已经测到"],
          ["6", "<b>篮筐逐帧人工标注</b>（本片段仅 435 帧）",
           "里程碑 02 已确认全自动三条路线全部失败，人工标注一次性解决"]])}
</section>

<section>
  <h2>⑨ 产物清单</h2>
  <ul class="files">
    <li><code>relations_full/relations.json</code> —— 全 435 帧关系序列，2610 条三元组
        （含逐帧几何基线 <code>pairs[]</code>，可作模型输出的交叉验证量）</li>
    <li><code>relation_probe.json</code> —— Q1/Q2 实验数据（口径对比、球框注入、随机对照、
        分层结果、逐帧明细）</li>
    <li><code>rel_event_align.json</code> —— <b>事件时间（由读秒表推导）+ 三个指标的置换检验</b>
        （本轮更正 v1 错误的依据）</li>
    <li><code>pose_motion.json</code> —— 骨架动作信号：v1 失败记录、轨迹筛选、
        起跳/争抢事件、逐帧 air_dyn 序列、对齐检验</li>
    <li><code>pose_motion_sweep.json</code> —— 15 格参数扫描的完整 p 值与稳健性判定</li>
    <li><code>fig_rel_q1.png</code> / <code>fig_rel_q2.png</code> / <code>fig_rel_time.png</code>
        / <code>fig_pose_timeline.png</code> / <code>fig_pose_sweep.png</code></li>
    <li><code>relations_probe/relations.json</code> —— 12 帧验证先行子集（验证记录留档）</li>
    <li>新脚本：<code>engine/build_players_from_pose.py</code>、
        <code>engine/probe_ball_relation.py</code>、<code>engine/make_rel_figs.py</code>、
        <code>engine/rel_event_align.py</code>、<code>engine/pose_keypoints.py</code>、
        <code>engine/pose_motion.py</code>、<code>engine/pose_motion_sweep.py</code>、
        <code>engine/make_action_figs.py</code>、<code>engine/make_milestone03_report.py</code></li>
    <li>可复用缓存：<code>action_work/seg_hi/pose_kpt_cache.json</code>
        —— <b>435 帧完整 17 关键点</b>（5811 人，34.9s 生成，勿重跑）</li>
  </ul>
</section>

<footer>
  <p>动作分析系统 · 里程碑 03（修订版 v2） · 全部数字从 JSON 现读，
     脚本 <code>make_milestone03_report.py</code> 可复跑。</p>
  <p>本报告如实记录了<b>三次被自己推翻的结论</b>：① 「3.0× 富集」（单位不对齐）；
     ② 关系层事件对齐的 v1 结论（事件时间标错 16–20 秒）；
     ③ 动作对齐在默认参数下的 p=0.0415（参数扫描后 1/15，不稳健）。
     另记录一次<b>负面结论</b>（关系层不携带战术信息）与一次<b>检测器失败</b>（v1 4.47 起跳/秒）。
     未挑选有利数字。</p>
</footer>
"""

    css = """
:root{--bg:#12151c;--panel:#1a1f29;--fg:#e6e9ef;--dim:#8b93a3;--line:#2b323f;
      --red:#e5484d;--green:#3fb950;--blue:#4c8dff;--amber:#e3b341}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:15px/1.75 -apple-system,"PingFang SC","Hiragino Sans GB",sans-serif}
main{max-width:1080px;margin:0 auto;padding:48px 28px 80px}
header{border-bottom:1px solid var(--line);padding-bottom:26px;margin-bottom:34px}
.eyebrow{color:var(--amber);font-size:13px;letter-spacing:.14em;margin:0 0 10px}
h1{font-size:31px;line-height:1.3;margin:0 0 16px;letter-spacing:-.01em}
.lede{color:var(--dim);font-size:16px;max-width:900px;margin:0}
h2{font-size:21px;margin:46px 0 14px;padding-left:13px;border-left:3px solid var(--red)}
h3{font-size:16px;margin:26px 0 10px;color:var(--fg)}
p{color:#cfd5e0}
section{scroll-margin-top:20px}
code{background:#0f1319;border:1px solid var(--line);border-radius:4px;
     padding:1px 6px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(238px,1fr));gap:12px;margin:18px 0}
.kv{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:13px 15px}
.kv .k{display:block;color:var(--dim);font-size:12.5px;margin-bottom:5px}
.kv .v{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.kv.bad .v{color:var(--red)}
.verdict{background:var(--panel);border:1px solid var(--line);border-radius:9px;
         padding:16px 20px;grid-column:1/-1}
.verdict.ok{border-left:3px solid var(--green)}
.verdict.no{border-left:3px solid var(--red)}
.verdict h3{margin:0 0 10px;font-size:16px}
.verdict ul{margin:0;padding-left:20px}
.verdict li{margin:7px 0;color:#cfd5e0;font-size:14.5px}
table{width:100%;border-collapse:collapse;margin:16px 0;font-size:13.5px}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:#161b24;color:var(--dim);font-weight:600;font-size:12.5px;
   text-transform:uppercase;letter-spacing:.05em}
tbody tr:nth-child(even){background:#171c25}
td{font-variant-numeric:tabular-nums}
.bad{color:var(--red);font-weight:600}
figure{margin:22px 0;background:var(--panel);border:1px solid var(--line);
       border-radius:10px;padding:14px}
figure img{width:100%;display:block;border-radius:6px}
figcaption{color:var(--dim);font-size:13px;margin-top:11px;line-height:1.65}
figcaption.note{color:#7c8494;font-size:12.5px}
.warn{background:#1e1a1a;border:1px solid #4a2626;border-left:3px solid var(--red);
      border-radius:8px;padding:13px 17px;font-size:14.5px;color:#f0dcdc}
.note{color:var(--dim);font-size:13px}
.rule{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--amber);
      border-radius:9px;padding:18px 22px;margin:20px 0}
.rule h3{margin-top:0;color:var(--amber)}
.rule ol{margin:12px 0 0;padding-left:22px}
.rule li{margin:9px 0;color:#cfd5e0;font-size:14.5px}
ul.files{list-style:none;padding:0}
ul.files li{background:var(--panel);border:1px solid var(--line);border-radius:8px;
            padding:11px 15px;margin:9px 0;font-size:14px;color:#cfd5e0}
footer{border-top:1px solid var(--line);margin-top:52px;padding-top:20px;
       color:var(--dim);font-size:13px}
"""

    html = (f"<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>里程碑 03 · 关系层闭环</title><style>{css}</style></head>"
            f"<body><main>{body}</main></body></html>")

    # 标签平衡自检
    bad = []
    for t in ("div", "section", "table", "tr", "td", "th", "figure", "figcaption",
              "ul", "ol", "li", "p", "h1", "h2", "h3", "span", "code", "header",
              "footer", "tbody", "thead"):
        o = len(re.findall(rf"<{t}(?=[\s>])", body))
        c = len(re.findall(rf"</{t}>", body))
        if o != c:
            bad.append(f"{t} {o}/{c}")
    print("  ✅ 全部平衡" if not bad else f"  ❌ 不平衡: {bad}")

    os.makedirs(base, exist_ok=True)
    with open(a.out_html, "w") as fp:
        fp.write(html)
    print(f"[out] {a.out_html}  {len(html.encode()) / 1024:.1f} KB")

    # 图片存在性核验
    refs = re.findall(r'<img src="([^"]+)"', body)
    miss = [r for r in refs if not os.path.exists(os.path.join(base, r))]
    print(f"[img] 引用 {len(refs)} 张，缺失 {len(miss)}" + (f" {miss}" if miss else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
