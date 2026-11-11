#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 步全量：用 axis-aware detect_primitives(接 orient_anchors.json, pan=80) 在 13 簇真实像素轨道上
检测原语 → 窗口级战术匹配(tactic_models.json) → 候选清单(老程裁定)。
诚实标注：当前检测层只产 SCREEN/HANDOFF/CUT 三类；CUT 同源桥接为 DRIVE 以解锁 PnR 等主力战术；
ROLL/PASS/POP 等原语未实装 → 依赖它们的模型暂不匹配(在报告里点明)。
输出：norm_calib/a_step_candidates.json + 文本摘要 + p0 同款风格的 HTML 报告 a_step_report.html。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import importlib.util
import json
import os
import re
import sys

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(tactics_data_file("engine")))
from tactic_match import _prim_name, detect_primitives, match_windowed

R0 = str(tactics_data_file("action_work/run_p0_broadcast_native.py"))
spec = importlib.util.spec_from_file_location("r0", R0)
r0 = importlib.util.module_from_spec(spec); spec.loader.exec_module(r0)

BASE = str(tactics_data_file("action_work"))
anch = json.load(open(f"{BASE}/norm_calib/orient_anchors.json", encoding="utf-8"))
ANCH = anch["anchors"]; PAN = anch["pan_deg"]
MODELS = json.load(open(f"{BASE}/tactic_models.json", encoding="utf-8"))["models"]

def name_of(m):
    for n in m["names"]:
        if any('\u4e00' <= c <= '\u9fff' for c in n):
            return n
    return m["names"][0]

results = {}
for cid_s, a in ANCH.items():
    cid = int(cid_s)
    seg, s, e = a["seg"], a["start"], a["end"]
    bw = tuple(a["basket_ward"])
    frames = r0.load_window(seg, s, e)
    if len(frames) < 5:
        results[cid_s] = {"skip": True, "reason": "帧不足"}
        continue
    dm, md = r0.cluster_stats(frames)
    ev = detect_primitives(frames, disp_med=dm, med_diag=md, orient=bw)
    # CUT -> DRIVE 同源桥接(朝筐加速即突破)
    ev2 = list(ev)
    for e0 in ev:
        if e0["type"] == "CUT":
            ev2.append({**e0, "type": "DRIVE", "note": (e0.get("note", "") + " [CUT同源→DRIVE]")})
    ev = ev2
    ev_counts = {}
    for e0 in ev:
        pn = _prim_name(e0); ev_counts[pn] = ev_counts.get(pn, 0) + 1
    cands = match_windowed(ev, MODELS, win=60, step=30, min_cov=0.4,
                           min_events=1, top_per_win=3, min_evidence=2, signature_evaluated=False)
    best = {}
    for c in cands:
        mid = c["model"]; cov = c["coverage"]
        if mid not in best or cov > best[mid][0]:
            mdl = next(m for m in MODELS if m["id"] == mid)
            # 信任分级：该候选是否依赖 CUT/DRIVE（DRIVE 当前 100% 由 CUT→DRIVE 桥接生成，
            # CUT 在广播半场「朝筐=画面左移」下过触发——见报告顶部红旗）→ 标记为 ⚠ 不可信；
            # 仅依赖 SCREEN(CROSS/DOWN)/HANDOFF（交互型、相对稳健）的标记为 ✅ 较可信。
            uses_noisy = any(pr in ("CUT", "DRIVE") for _, pr in c["detail"])
            best[mid] = (cov, c["t0"], c["t1"], c["detail"], c["unverified"], name_of(mdl), uses_noisy)
    n_cut = ev_counts.get("CUT", 0)
    cut_noise = (n_cut / len(frames)) > 0.20   # CUT/帧 > 0.2 → 过触发告警
    results[cid_s] = {
        "seg": seg, "start": s, "end": e, "visible_far_corner": a["visible_far_corner"],
        "basket_ward": a["basket_ward"], "n_frames": len(frames),
        "events": ev_counts, "cut_noise": cut_noise,
        "candidates": [{"model": mid, "name": nm, "coverage": round(cov, 3),
                        "t0": t0, "t1": t1, "detail": dl, "unverified": uv, "trust": ("含CUT⚠" if ud else "SCREEN/HANDOFF✅")}
                       for mid, (cov, t0, t1, dl, uv, nm, ud) in
                       sorted(best.items(), key=lambda x: -x[1][0])],
    }

json.dump({"pan_deg": PAN, "results": results},
          open(f"{BASE}/norm_calib/a_step_candidates.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# 文本摘要
print(f"pan={PAN}  13 簇匹配完成（诚实分级：DRIVE 来自 CUT 桥接，PnR 族标⚠）\n")
for cid_s, r in results.items():
    if r.get("skip"):
        continue
    noise = "  [CUT过触发⚠]" if r.get("cut_noise") else ""
    print(f"#{cid_s} {r['seg']}#{r['start']}-{r['end']} ({r['n_frames']}帧) [{r['visible_far_corner']}]{noise} "
          f"原语={r['events']}")
    for c in r["candidates"][:4]:
        flag = " [seq未验⤵]" if c["unverified"] else ""
        print(f"    → cov={c['coverage']:.2f} [{c['trust']}] {c['name']}  {c['detail']}{flag}")  # trust 文本已含⚠/✅
    print()

# HTML 报告
def ev_row(ev_counts):
    return " ".join(f"{k}×{v}" for k, v in sorted(ev_counts.items()))
rows = ""
for cid_s, r in results.items():
    if r.get("skip"):
        continue
    noise = "<span style='color:#e0a23b'>⚠ CUT 过触发</span>" if r.get("cut_noise") else ""
    cands = "".join(
        f"<li>cov={c['coverage']:.2f} <span class='{('w' if '⚠' in c['trust'] else 'ok')}'>[{c['trust']}]</span> "
        f"<b>{c['name']}</b> {('[seq未验]' if c['unverified'] else '')}"
        f"<br><span style='color:#7a8290;font-size:11px'>{c['detail']}</span></li>"
        for c in r["candidates"][:5])
    rows += (f"<div class='box'><div class='h'>#{cid_s} {r['seg']}#{r['start']}-{r['end']} "
             f"({r['n_frames']}帧) · {r['visible_far_corner']} · bw={r['basket_ward']} {noise}</div>"
             f"<div class='ev'>原语：{ev_row(r['events'])}</div>"
             f"<ol class='cands'>{cands}</ol></div>")
html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A 步全量候选战术清单 (pan={PAN})</title>
<style>body{{font-family:system-ui,"PingFang SC",sans-serif;margin:0;background:#0f1115;color:#e6e6e6;padding:20px}}
h1{{font-size:18px}}h2{{font-size:13px;color:#9aa3b2}}
.box{{background:#171a21;border:1px solid #2a2f3a;border-radius:8px;padding:12px;margin:10px 0}}
.h{{font-size:13px;font-weight:600;margin-bottom:6px}}.ev{{font-size:12px;color:#cdd6e4;margin-bottom:6px}}
.cands li{{font-size:12px;margin:4px 0;color:#e6e6e6}}
.ok{{color:#5fbf7f;font-size:11px}}.w{{color:#e0a23b;font-size:11px}}
.note{{font-size:12px;color:#9aa3b2;line-height:1.7;margin:8px 0}}
.k{{color:#e06b6b}}</style></head><body>
<h1>A 步全量候选战术清单 · pan={PAN} · axis-aware（诚实分级版）</h1>
<div class="note"><b>红线：战术名以 ASR 为准，本页只报结构原语与候选，cov = 类型覆盖（签名未验）。</b>
<br>🔴 <span class="k">CUT 在广播半场「朝筐=画面左移」下严重过触发</span>（实测 #8 共 40 个 CUT、净位移 40–532px、涉及 33 个 track ID≈实际 28 人，ID 不稳定把同一人拆多条）；
DRIVE 当前 100% 由 CUT→DRIVE 桥接生成。故凡依赖 CUT/DRIVE 的候选（反向挡拆/一五挡拆/库追挡拆/切入）一律标 <span class="w">[含CUT⚠]</span>，<b>不可信</b>，仅供老程用 ASR 真值反查。
<br>✅ 仅依赖 SCREEN(DOWN/CROSS)/HANDOFF 的候选标 <span class="ok">[SCREEN/HANDOFF✅]</span>，相对可信（下掩护/横掩护/手递手交互型原语较稳健）。
<br>🔴 ROLL/PASS/POP/POST_UP 等原语未实装 → 依赖它们的模型暂不匹配。
<br>[seq未验] = 该模型判别量涉时序依赖，当前只看原语集合未验次序。</div>
{rows}
</body></html>"""
open(f"{BASE}/norm_calib/a_step_report.html", "w", encoding="utf-8").write(html)
print("[report] a_step_report.html + a_step_candidates.json 写入")
