#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检测原语 × ASR战术名 交叉核对：量化当前检测层对这批战术的判别力边界。
纪律：标签只信 ASR；本脚本**不重新命名**，只回答「检测器检出的原语与该战术名期望的原语对不对得上」。
对每个簇把 ASR 名→模型期望原语，与实测原语比对，并诚实区分：
  (A) 期望原语【已实装】且【检出】 → 命中
  (B) 期望原语【已实装】但【未检出】 → 已实装漏检
  (C) 期望原语【未实装】(检测器产不出)  → 结构性缺口(非本层能力,需补实装)
输出：norm_calib/prim_vs_asr_check.json + 浏览器报告 + 摘要。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os
from collections import defaultdict

from common.nba_paths import tactics_data_file

BASE = str(tactics_data_file("action_work"))
NC = f"{BASE}/norm_calib"

# 检测器当前真实能产出的原语（detect_primitives 的输出域 + CUT→DRIVE 桥接）
IMPLEMENTED = {"SCREEN", "SCREEN.DOWN", "SCREEN.CROSS", "HANDOFF", "CUT", "DRIVE"}

tm = json.load(open(f"{BASE}/tactic_models.json", encoding="utf-8"))
def cn(s):
    for n in s:
        if any('\u4e00' <= c <= '\u9fff' for c in n): return n
    return s[0]
id2m = {m["id"]: m for m in tm["models"]}
alias = tm.get("alias_index", {})

# 读取已命名语料（含 split / 原语）
named = json.load(open(f"{NC}/a_step_named.json", encoding="utf-8"))["clusters"]
split_info = {}
for s in (json.loads(l) for l in open(f"{NC}/tactical_corpus_split.jsonl", encoding="utf-8") if l.strip()):
    split_info[s["cluster_id"]] = s["split"]

def expected_primitives(model_id):
    """ASR模型id→期望原语集合(经alias解析)。"""
    m = id2m.get(model_id)
    if m is None:
        tgt = alias.get(model_id)
        m = id2m.get(tgt) if tgt else None
    if m is None:
        return None, None
    return set(m.get("primitives", [])), m.get("key_primitive")

rows = []
agg = {"hit": 0, "miss_impl": 0, "gap": 0}
for cid_s in sorted(named, key=lambda x: int(x)):
    nc = named[cid_s]
    det = set(nc.get("detected_primitives", {}).keys())
    cid = int(cid_s)
    for g in nc["asr_tactic_names"]:
        exp, keyp = expected_primitives(g["model"])
        if exp is None:
            rows.append({"cluster": cid, "seg": nc["seg"], "tactic": g["name"],
                         "status": "模型库外", "expected": None, "detected": sorted(det)})
            continue
        impl_exp = exp & IMPLEMENTED      # 期望中已实装的
        gap_exp = exp - IMPLEMENTED       # 期望中未实装的(结构性缺口)
        hit = sorted(impl_exp & det)      # 已实装且检出
        miss = sorted(impl_exp - det)     # 已实装但漏检
        rows.append({"cluster": cid, "seg": nc["seg"], "tactic": g["name"],
                     "model": g["model"], "split": split_info.get(cid),
                     "key_primitive": keyp, "expected_all": sorted(exp),
                     "expected_implemented": sorted(impl_exp), "expected_gap": sorted(gap_exp),
                     "hit": hit, "miss_impl": miss, "detected": sorted(det),
                     "status": ("全未实装" if not impl_exp else ("全命中" if not miss else "部分命中"))})
        agg["hit"] += len(hit); agg["miss_impl"] += len(miss); agg["gap"] += len(gap_exp)

json.dump({"implemented_primitives": sorted(IMPLEMENTED), "agg": agg, "rows": rows},
          open(f"{NC}/prim_vs_asr_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- 摘要 ----
print("检测原语 × ASR战术名 交叉核对（标签只信ASR；本表不重命名，只量判别力）\n")
print(f"检测器可产出原语: {sorted(IMPLEMENTED)}")
print(f"累计: 已实装命中={agg['hit']}  已实装漏检={agg['miss_impl']}  未实装缺口={agg['gap']}\n")
print(f"{'簇':<4}{'战术名(ASR)':<22}{'期望(已实装)':<26}{'命中':<16}{'漏检':<14}{'未实装缺口'}")
for r in rows:
    if r["status"] == "模型库外":
        print(f"#{r['cluster']:<3}{r['tactic']:<22}{'(模型库外)':<26}{'-':<16}{'-':<14}-")
        continue
    print(f"#{r['cluster']:<3}{r['tactic']:<22}{'+'.join(r['expected_implemented']) or '—':<26}"
          f"{'+'.join(r['hit']) or '—':<16}{'+'.join(r['miss_impl']) or '—':<14}{'+'.join(r['expected_gap']) or '—'}")

# ---- HTML ----
hrows = ""
for r in rows:
    if r["status"] == "模型库外":
        hrows += f"<tr><td>#{r['cluster']}</td><td>{r['seg']}</td><td>{r['tactic']}</td><td colspan=4 class=k>模型库外，期望原语未知</td></tr>"
        continue
    chip = lambda items, cls: "".join(f"<span class='{cls}'>{x}</span> " for x in items) or "—"
    hrows += (f"<tr><td>#{r['cluster']}</td><td>{r['seg']}</td><td>{r['tactic']}</td>"
              f"<td>{chip(r['hit'],'ok')}</td><td>{chip(r['miss_impl'],'w')}</td><td>{chip(r['expected_gap'],'k')}</td></tr>")
html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>检测原语×ASR交叉核对</title><style>
body{{font-family:system-ui,"PingFang SC",sans-serif;background:#0f1115;color:#e6e6e6;padding:20px;margin:0}}
h1{{font-size:18px}}table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px}}
th,td{{border:1px solid #2a2f3a;padding:6px 8px;text-align:left}}
th{{background:#1a1e26;color:#9aa3b2}}
.ok{{color:#5fbf7f}}.w{{color:#e0a23b}}.k{{color:#e06b6b}}
.note{{font-size:12px;color:#9aa3b2;line-height:1.7;background:#151821;padding:10px;border-radius:6px;margin:8px 0}}
</style></head><body>
<h1>检测原语 × ASR战术名 交叉核对（判别力边界）</h1>
<div class=note>
<b>口径</b>：战术名只信 ASR（不改名）；本表量化「检测器检出原语 vs 该战术名期望原语」的差距。<br>
<b>检测器可产出原语</b>（当前唯一能生成的）：<span class=ok>{' '.join(sorted(IMPLEMENTED))}</span><br>
<span class=ok>命中</span>=期望且已实装且检出｜<span class=w>漏检</span>=期望且已实装但没检出｜
<span class=k>未实装缺口</span>=该战术需要的原语检测器<b>根本产不出</b>（如 ROLL/SCREEN.WEDGE/EXCHANGE/GHOST/EXIT…），
属<b>结构性能力缺口</b>，非本批数据问题。<br>
<b>结论预告</b>：多数战术的期望原语含大量未实装项 ⇒ 检测层当前<b>无法判别这批战术</b>，
命名必须走 ASR（与老程裁定一致）；检测层仅对 SCREEN/HANDOFF 提供结构佐证。
</div>
<table><tr><th>簇</th><th>段</th><th>战术名(ASR)</th><th>命中</th><th>漏检(已实装)</th><th>未实装缺口</th></tr>
{hrows}</table>
<div class=note>累计：已实装命中={agg['hit']}｜已实装漏检={agg['miss_impl']}｜未实装缺口={agg['gap']}</div>
</body></html>"""
open(f"{NC}/prim_vs_asr_report.html", "w", encoding="utf-8").write(html)
print("\n[report] prim_vs_asr_report.html + prim_vs_asr_check.json 写入")
