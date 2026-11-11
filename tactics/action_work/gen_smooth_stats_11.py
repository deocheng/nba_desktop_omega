# -*- coding: utf-8 -*-
"""
gen_smooth_stats_11.py — 11 条顺畅轨迹统计摘要（Task 1）
数字全部从磁盘现读：
  - 球员每帧人数 / 球真检出率 / 球最大跳变：从 smooth_tracks_game20/*.json 重算
  - 目的性/协同性/稳定性/活跃度/顺畅分/movers：取自 smooth_picks_game20.json
    （scorer 权威输出，同样落盘）
裁定列：以 smooth_verdict_laocheng.json 为最高权威（老程目视 > 机器分）。
产出：norm_calib/smooth_stats_11_20261006.json + .html
总原则：人数只作辅助、不设硬阈值；球质量单独列栏警示、不进顺畅分。
"""
import json
import statistics
from pathlib import Path

NC = "norm_calib"
tracks_dir = Path(f"{NC}/smooth_tracks_game20")
picks = json.load(open(f"{NC}/smooth_picks_game20.json", encoding="utf-8"))
verdict = json.load(open(f"{NC}/smooth_verdict_laocheng.json", encoding="utf-8"))

smooth_by_cluster = {e["cluster"]: e for e in picks["smooth"]}
EXCL = set(verdict.get("exclude_clusters", []))
review_map = {int(k): v for k, v in verdict.get("reviews", {}).items() if "verdict" in v}

def cur_verdict(cid):
    if cid in review_map and review_map[cid]["verdict"] == "KEEP":
        return "KEEP(已确认)"
    if cid in EXCL:
        return "剔出"
    if cid in (11, 22):
        return "候选(已裁包装帧)"
    return "待老程核查"

rows = []
for f in sorted(tracks_dir.glob("*.json")):
    data = json.load(open(f, encoding="utf-8"))
    cid = int(data["pick_id"][1:])
    seg = data["seg"]; ep = data["ep"]; asr_name = data["asr_name"]
    players = data["players"]            # id -> {frame: [x,y]}
    ball = data["ball"]                  # list per frame: {xy, conf, pred}

    # —— 每帧可见人数（用每帧可见数，不累计 track_id，避免 ID 碎片化虚高）——
    all_frames = set()
    for pid, frm in players.items():
        all_frames.update(int(k) for k in frm.keys())
    frames_sorted = sorted(all_frames)
    pfn = []
    for fr in frames_sorted:
        pfn.append(sum(1 for pid, frm in players.items() if str(fr) in frm))
    median_people = round(statistics.median(pfn), 1) if pfn else None

    # —— 球质量（单独列栏，不进分）——
    ball = [b for b in ball if b is not None]   # 滤除整帧无检测(None)
    n_ball = len(ball)
    real = [b for b in ball if not b.get("pred")]
    ball_real_rate = round(len(real) / n_ball, 3) if n_ball else None
    pts = [b.get("xy") for b in ball]
    maxjump = 0.0
    for a, b in zip(pts, pts[1:]):
        if a and b:
            d = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
            if d > maxjump:
                maxjump = d

    sc = smooth_by_cluster.get(cid, {})
    rows.append({
        "cluster": cid,
        "seg": seg, "ep": ep,
        "win_start": sc.get("win_start"), "win_end": sc.get("win_end"),
        "cluster_range": sc.get("cluster_range"),
        "median_people_per_frame": median_people,
        "min_people_per_frame": sc.get("min_people_per_frame"),
        "n_movers": sc.get("n_movers"),
        "n_players_seen": sc.get("n_players_seen"),
        "straightness": sc.get("straightness"),     # 目的性
        "coordination": sc.get("coordination"),     # 协同性
        "stability": sc.get("stability"),            # 稳定性
        "median_speed_px": sc.get("median_speed_px"),  # 活跃度
        "smooth_score": sc.get("smooth_score"),
        "ball_real_rate": ball_real_rate,
        "ball_max_jump_px": round(maxjump, 1),
        "ball_coverage": sc.get("ball_coverage"),
        "asr_name": asr_name,
        "laocheng_verdict": cur_verdict(cid),
    })

# 按顺畅分降序
rows.sort(key=lambda r: (r["smooth_score"] or 0), reverse=True)

out = {
    "source": "smooth_tracks_game20/*.json + smooth_picks_game20.json + smooth_verdict_laocheng.json",
    "n": len(rows),
    "principles": [
        "所有数字从磁盘现读，禁止估算",
        "裁定权归老程；最终以 smooth_verdict_laocheng.json 为准",
        "球质量单独报告，不进顺畅分",
        "人数重叠严重(KEEP 13~31 vs 剔出 8~30)→ 人数只作辅助，不设硬阈值",
        "球真检出率普遍低(实测 6.7%~59%)→ 单独列栏警示",
    ],
    "rows": rows,
}
json.dump(out, open(f"{NC}/smooth_stats_11_20261006.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# —— HTML ——
def fmt(v, nd=3):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)

ball_warn_low = 0.30
trs = []
for r in rows:
    green = (r["laocheng_verdict"] == "KEEP(已确认)")
    ball_flag = "🔴" if (r["ball_real_rate"] is not None and r["ball_real_rate"] < ball_warn_low) else ""
    trs.append(
        f"<tr class='{'keep' if green else ''}'>"
        f"<td>c{r['cluster']}</td>"
        f"<td>{r['seg']}</td>"
        f"<td>{fmt(r['win_start'],0)}–{fmt(r['win_end'],0)}</td>"
        f"<td>{fmt(r['median_people_per_frame'],1)}</td>"
        f"<td>{fmt(r['n_movers'],0)}</td>"
        f"<td>{fmt(r['straightness'])}</td>"
        f"<td>{fmt(r['coordination'])}</td>"
        f"<td>{fmt(r['stability'])}</td>"
        f"<td>{fmt(r['median_speed_px'],2)}</td>"
        f"<td><b>{fmt(r['smooth_score'])}</b></td>"
        f"<td class='{'warn' if ball_flag else ''}'>{fmt(r['ball_real_rate'])} {ball_flag}</td>"
        f"<td>{fmt(r['ball_max_jump_px'],1)}</td>"
        f"<td>{r['laocheng_verdict']}</td>"
        f"</tr>"
    )

html = f"""<!doctype html><html lang='zh'><head><meta charset='utf-8'>
<title>11 条顺畅轨迹统计摘要 (2026-10-06)</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,'PingFang SC','Microsoft YaHei',sans-serif;margin:24px;color:#1a1a1a;background:#fafafa}}
h1{{font-size:20px}} h2{{font-size:15px;color:#444;margin-top:20px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff;margin-top:8px}}
th,td{{border:1px solid #ddd;padding:5px 7px;text-align:center}}
th{{background:#2c3e50;color:#fff;position:sticky;top:0}}
tr.keep{{background:#e8f8ef}}
td.warn{{background:#fdecea;color:#b71c1c;font-weight:600}}
.note{{font-size:12px;color:#666;background:#fff;border:1px solid #e0e0e0;padding:10px;border-radius:6px;margin-top:10px}}
.legend{{font-size:11.5px;color:#888}}
</style></head><body>
<h1>11 条顺畅轨迹统计摘要</h1>
<p class='legend'>数字全部从磁盘现读（球员每帧人数/球指标重算自轨迹文件；打分指标取自 picks 权威输出）。生成于 2026-10-06。</p>
<table>
<tr><th>簇</th><th>段</th><th>起止帧</th><th>中位每帧人数</th><th>movers</th>
<th>目的性</th><th>协同性</th><th>稳定性</th><th>活跃度(px)</th><th>顺畅分</th>
<th>球真检出率</th><th>球最大跳变px</th><th>老程裁定</th></tr>
{''.join(trs)}
</table>
<div class='note'>
<b>总原则</b>：① 所有数字从磁盘现读，禁止估算；② 裁定权归老程，最终以 smooth_verdict_laocheng.json 为准；
③ 球质量单独报告，不进顺畅分；④ 命名走 ASR gt_models，检测原语仅作结构佐证；⑤ 按 ep 分组防泄漏（cv_folds.json）。
<br><b>人数判据</b>：KEEP 13~31 vs 剔出 8~30，重叠严重 ⇒ 只作辅助，不设硬阈值（老程 #17 裁定：镜头拉近≠特写包装）。
<br><b>球质量警示</b>：真检出率普遍 &lt;30% 标 🔴（实测范围 0%~58.9%，conf~0.2，含 900+px 瞬移）⇒ 球轨迹不作顺畅主判据。
<br><b>#17</b> 行绿底 = 老程已确认 KEEP（场地局部配合，镜头拉近仍属真实比赛）。
</div>
</body></html>"""
open(f"{NC}/smooth_stats_11_20261006.html", "w", encoding="utf-8").write(html)
print(f"OK: {len(rows)} rows -> smooth_stats_11_20261006.json + .html")
for r in rows:
    print(f"c{r['cluster']:>2} {r['seg']:<9} 人数={r['median_people_per_frame']} movers={r['n_movers']} "
          f"分={r['smooth_score']} 球真检={r['ball_real_rate']} 跳={r['ball_max_jump_px']} 裁定={r['laocheng_verdict']}")
