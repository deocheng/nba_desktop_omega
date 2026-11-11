#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顺畅进攻目视复核页：把挑出的窗口逐条做成帧条(缩略图)，供老程直接看、裁定准不准。
自包含 HTML(图片 base64 内嵌)，浏览器直接打开。
- 导出的顺畅候选：每窗 6 帧
- 老程 DISREGARD 但机器高分的窗：每窗 3 帧（对照，验证指标局限）
- 静止剔出的窗：每窗 3 帧
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import base64
import io
import json
import os

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
BASE = f"{ROOT}/action_work"
NC = f"{BASE}/norm_calib"
SEG = f"{BASE}/tactic_notes_batch_full/segments"

ap = argparse.ArgumentParser()
ap.add_argument("--picks", default=f"{NC}/smooth_picks_game20.json")
ap.add_argument("--out", default=f"{NC}/smooth_review_game20.html")
a = ap.parse_args()

try:
    from PIL import Image
except ImportError:
    raise SystemExit("需要 Pillow: pip install pillow")

data = json.load(open(a.picks, encoding="utf-8"))
smooth = data["smooth"]
static = data.get("static", [])
excluded = data.get("excluded_by_laocheng", [])
SKIP = data.get("skip_start", 0)

def frames_map(seg):
    fj = json.load(open(f"{SEG}/{seg}/frames.json", encoding="utf-8"))
    return {r["idx"]: r["path"] for r in fj}

def thumb(seg, idx, width=260, q=62):
    m = FRAMES.get(seg)
    if not m:
        return None
    rel = m.get(idx)
    if not rel:
        return None
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return None
    try:
        im = Image.open(p).convert("RGB")
        w, h = im.size
        im = im.resize((width, int(h * width / w)), Image.LANCZOS)
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=q, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

def strip(seg, i0, i1, k=6):
    if i1 <= i0:
        idxs = [i0]
    else:
        idxs = [i0 + round(t * (i1 - i0) / (k - 1)) for t in range(k)]
    out = []
    for i in idxs:
        b = thumb(seg, i)
        if b:
            out.append((i, b))
    return out

FRAMES = {}
for r in smooth + static + excluded:
    if r["seg"] not in FRAMES:
        FRAMES[r["seg"]] = frames_map(r["seg"])

def card(r, nframes):
    s = strip(r["seg"], r["win_start"], r["win_end"], nframes)
    imgs = "".join(f"<figure><img src='data:image/jpeg;base64,{b}'><figcaption>f{i}</figcaption></figure>"
                   for i, b in s)
    hh = r.get("camera_scale_h"); mp = r.get("median_people_per_frame")
    cls = ("bad" if r.get("excluded_by_laocheng") else
           {"KEEP": "ok", "DISREGARD": "bad"}.get(r["laocheng_verdict"], "warn"))
    return f"""<div class="card {cls}">
<div class="hd">#{r['cluster']} · {r['seg']} · 窗 {r['win_start']}–{r['win_end']}
 <span class="pill">{r['laocheng_verdict']}</span> <span class="pill2">{r['verdict']}</span></div>
<div class="mt">顺畅分 <b>{r['smooth_score']:.3f}</b> · 目的性 {r['straightness']:.2f} · 协同 {r['coordination']:.2f}
 · 稳定 {r['stability']:.2f} · 跑动者 {r['n_movers']} · 球真检 {r['ball_real_rate']:.0%}
 · 镜头h {('—' if hh is None else f'{hh:.0f}')} · 人数/帧 {('—' if mp is None else f'{mp:.0f}')} · ASR名 {r['asr_name'] or '—'}</div>
<div class="strip">{imgs}</div>
<div class="rs">{r['verdict_reason']}</div></div>"""

# 分组
exported = [r for r in smooth if r["laocheng_verdict"] != "DISREGARD"]
disregarded = [r for r in smooth if r["laocheng_verdict"] == "DISREGARD"]

h1 = "".join(card(r, 6) for r in exported)
h2 = "".join(card(r, 3) for r in excluded)
h3 = "".join(card(r, 3) for r in static)

html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>顺畅进攻目视复核</title><style>
body{{font-family:system-ui,"PingFang SC",sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:18px}}
h1{{font-size:18px}}h2{{font-size:14px;color:#9aa3b2;margin:18px 0 8px}}
.card{{background:#171a21;border:1px solid #2a2f3a;border-radius:8px;padding:10px;margin:10px 0}}
.card.ok{{border-left:4px solid #5fbf7f}}
.card.bad{{border-left:4px solid #e06b6b}}
.card.warn{{border-left:4px solid #e0a23b}}
.hd{{font-size:13px;font-weight:600;margin-bottom:4px}}
.mt{{font-size:11.5px;color:#cdd6e4;margin-bottom:6px}}
.strip{{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px}}
.strip figure{{margin:0;flex:0 0 auto}}
.strip img{{width:260px;border-radius:4px;display:block;background:#000}}
.strip figcaption{{font-size:10px;color:#7a8290;text-align:center;margin-top:2px}}
.pill{{font-size:10px;padding:1px 6px;border-radius:9px;background:#263041;color:#9aa3b2}}
.pill2{{font-size:10px;padding:1px 6px;border-radius:9px;background:#1f3328;color:#7fd1a0}}
.rs{{font-size:11px;color:#e0a23b;margin-top:4px}}
.note{{font-size:12px;color:#9aa3b2;line-height:1.7;background:#151821;padding:10px;border-radius:6px;margin:8px 0}}
</style></head><body>
<h1>顺畅进攻 · 目视复核 v2（窗口帧条，左→右为时间顺序）</h1>
<div class="note">
<b>本轮已按老程 2026-10-05 复核修正</b>：滑窗起点统一跳过开场 {SKIP} 帧（修 #11 替补席镜头、#22 过渡特效吃进窗口的问题）；
老程裁定剔出的 7 条即使机器分高也不进语料。<br>
绿色左边框=老程 KEEP；紫色划线=老程裁定剔出；黄色=未裁定。
每窗抽帧显示，看是否为真实流畅进攻。指标局限：顺畅分只量球员协同移动，
<b>区分不了半场进攻 vs 场外/放大/特写/讲解/庆祝</b>，「镜头h」(球员框高中位)可作机位参考：h 大≈特写/放大。
</div>
<h2>① 顺畅候选（共 {len(exported)} 条 · 每窗 6 帧）</h2>
{h1}
<h2>② 老程裁定剔出（共 {len(excluded)} 条 · 每窗 3 帧 · 机器分仅供参考）</h2>
{h2}
<h2>③ 静止/剔出（共 {len(static)} 条 · 跑动者&lt;3）</h2>
{h3}
</body></html>"""
p = a.out
open(p, "w", encoding="utf-8").write(html)
print(f"[产物] {p}  ({os.path.getsize(p)/1024/1024:.2f} MB)")
print(f"  ①顺畅候选(导出) {len(exported)} 条×6帧 · ②老程裁定剔出 {len(excluded)} 条×3帧 · ③静止 {len(static)} 条×3帧")
