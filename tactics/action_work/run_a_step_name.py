#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 步命名对齐：13 簇 → 所属 ep → ASR/人声讲解真值战术名(权威) + 检测原语(佐证)。
老程裁定（2026-10-04）：「战术名按对应原视频定」——gt_models 字段即每期讲解的战术名真值。
模型匹配只作结构佐证，不参与命名。cut 语义：三分线外向内快速移动=内切，反向=外弹(pop)，
属时序运动(静态画面识别不了)→ 本脚本只统计检测到的原语，不改其命名。
输出：norm_calib/a_step_named.json + a_step_named_report.html(浏览器预览)。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os

from common.nba_paths import tactics_data_file

BASE = str(tactics_data_file("action_work"))

# 1) 模型库：id→中文名；alias_index 用于兜底
tm = json.load(open(f"{BASE}/tactic_models.json", encoding="utf-8"))
def cn_name(s):
    for n in s:
        if any('\u4e00' <= c <= '\u9fff' for c in n):
            return n
    return s[0]
id2name = {m["id"]: cn_name(m["names"]) for m in tm["models"]}
alias2id = tm.get("alias_index", {})

def name_of(mid):
    if mid in id2name:
        return id2name[mid], True
    tgt = alias2id.get(mid)
    if tgt and tgt in id2name:
        return id2name[tgt], True   # 经 alias 命中
    return mid, False               # 模型库里无对应(诚实标注)

# 2) ASR 真值：ep → {gt_models, video}
rows = json.load(open(f"{BASE}/tactic_notes_batch_full/batch_results.json", encoding="utf-8"))["rows"]
ep2gt = {r["ep"]: {"gt_models": r.get("gt_models") or [], "video": r.get("video", "")} for r in rows}

# 3) 13 簇锚 + 检测结果
anch = json.load(open(f"{BASE}/norm_calib/orient_anchors.json", encoding="utf-8"))["anchors"]
PAN = json.load(open(f"{BASE}/norm_calib/orient_anchors.json", encoding="utf-8"))["pan_deg"]
cand = json.load(open(f"{BASE}/norm_calib/a_step_candidates.json", encoding="utf-8"))["results"]

out = {"pan_deg": PAN, "clusters": {}}
for cid_s, a in anch.items():
    seg = a["seg"]; ep = seg.split("_")[0]
    gt = ep2gt.get(ep, {"gt_models": [], "video": ""})
    gt_names = []
    for mid in gt["gt_models"]:
        nm, ok = name_of(mid)
        gt_names.append({"model": mid, "name": nm, "in_library": ok})
    c = cand.get(cid_s, {})
    out["clusters"][cid_s] = {
        "seg": seg, "ep": ep, "video": gt["video"],
        "asr_tactic_names": gt_names,
        "detected_primitives": c.get("events", {}),
        "cut_noise": c.get("cut_noise", False),
        "model_candidates_reference": c.get("candidates", [])[:3],
    }

json.dump(out, open(f"{BASE}/norm_calib/a_step_named.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# ---- 文本摘要 ----
print(f"pan={PAN}  13 簇 ASR 战术名对齐（命名=ASR权威，检测原语仅佐证）\n")
for cid_s in sorted(out["clusters"], key=lambda x: int(x)):
    r = out["clusters"][cid_s]
    names = "、".join(f"{g['name']}{'' if g['in_library'] else '(库外)'}" for g in r["asr_tactic_names"]) or "<<无真值>>"
    noise = "  [CUT过触发⚠]" if r["cut_noise"] else ""
    print(f"#{cid_s} {r['seg']} [{r['ep']}]  战术名(ASR)={names}{noise}")
    print(f"      原语佐证={r['detected_primitives']}")

# ---- HTML ----
rows_html = ""
for cid_s in sorted(out["clusters"], key=lambda x: int(x)):
    r = out["clusters"][cid_s]
    names = "、".join(f"<b>{g['name']}</b>{'' if g['in_library'] else '<span class=k>(模型库无此条)</span>'}"
                      for g in r["asr_tactic_names"]) or "<span class=k>&lt;&lt;无 ASR 真值&gt;&gt;</span>"
    prims = " ".join(f"{k}×{v}" for k, v in sorted(r["detected_primitives"].items())) or "<span class=k>无</span>"
    noise = "<span class='w'>⚠ CUT过触发</span> " if r["cut_noise"] else ""
    ref = "；".join(f"{c['name']}({c['trust']})" for c in r["model_candidates_reference"]) or "—"
    rows_html += (f"<div class=box><div class=h>#{cid_s} {r['seg']} · {r['ep']} · {r['video'][:28]}…</div>"
                  f"<div class=name>🅿️ 战术名(ASR真值) = {names}</div>"
                  f"<div class=ev>{noise}检测原语(佐证) = {prims}</div>"
                  f"<div class=ref>模型结构候选(仅参考) = {ref}</div></div>")

html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A 步 ASR 战术名对齐 (13簇)</title>
<style>body{{font-family:system-ui,"PingFang SC",sans-serif;margin:0;background:#0f1115;color:#e6e6e6;padding:20px}}
h1{{font-size:18px}}
.box{{background:#171a21;border:1px solid #2a2f3a;border-radius:8px;padding:12px;margin:10px 0}}
.h{{font-size:13px;font-weight:600;margin-bottom:6px}}
.name{{font-size:14px;color:#7fd1a0;margin-bottom:5px}}
.ev{{font-size:12px;color:#cdd6e4;margin-bottom:3px}}
.ref{{font-size:11px;color:#7a8290}}
.note{{font-size:12px;color:#9aa3b2;line-height:1.7;margin:8px 0;background:#151821;padding:10px;border-radius:6px}}
.k{{color:#e06b6b}}.w{{color:#e0a23b}}</style></head><body>
<h1>A 步 · 13 簇 ASR 战术名对齐（pan={PAN}）</h1>
<div class=note><b>命名口径（老程裁定）</b>：战术名 = 对应原视频的人声讲解真值(gt_models)，<b>不由模型猜</b>；
检测原语仅作结构佐证。cut 语义=三分线外向内快速移动(内切)，反向=外弹(pop)，属时序运动、静态画面不可辨。
<br>「模型结构候选」列仅为上一轮 axis-aware 结构匹配结果（含信任级），<b>不参与命名</b>：凡依赖 CUT/DRIVE 的
结构候选受广播半场 CUT 过触发影响，仅供交叉参考。</div>
{rows_html}
</body></html>"""
open(f"{BASE}/norm_calib/a_step_named_report.html", "w", encoding="utf-8").write(html)
print("\n[report] a_step_named_report.html + a_step_named.json 写入")
