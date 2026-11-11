# -*- coding: utf-8 -*-
"""
gen_gray_review.py — 灰区 7 簇 (GRAY_VISUAL_SIGNOFF, 339 帧) 目视复核页（Task 3 扩池准备）
总原则：灰区必须先经老程逐簇目视，裁定后才并入挑选池（板帧 7 簇整类剔除）。
用法：
  # 生成复核页（老程翻看，逐簇判 KEEP / 剔）
  python gen_gray_review.py
  # 老程裁定后，把通过的簇写出为 pure_game_windows_gray.json（供 pick --pool game20_gray 用）
  python gen_gray_review.py --build-from my_gray_verdicts.json
    my_gray_verdicts.json = {"7":"KEEP","10":"EXCLUDE","14":"KEEP","20":"KEEP",...}
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
RM = f"{NC}/routing_manifest.json"

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=f"{NC}/gray_review.html")
ap.add_argument("--build-from", help="老程裁定 json: {cluster: KEEP|EXCLUDE}，写出 pure_game_windows_gray.json")
a = ap.parse_args()

try:
    from PIL import Image
except ImportError:
    raise SystemExit("需要 Pillow: pip install pillow")

rm = json.load(open(RM, encoding="utf-8"))
gray = rm["routes"]["GRAY_VISUAL_SIGNOFF"]

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
for cl in gray["members"]:
    for m in cl["members"]:
        if m["seg"] not in FRAMES:
            FRAMES[m["seg"]] = frames_map(m["seg"])

# ---- 模式A：写 pure_game_windows_gray.json ----
if a.build_from:
    verdicts = {int(k): v.upper() for k, v in json.load(open(a.build_from, encoding="utf-8")).items()}
    keep = [int(c) for c in verdicts if verdicts[c] == "KEEP"]
    gray_by_c = {c["cluster"]: c for c in gray["members"]}
    out = {"built_from": "routing_manifest.json GRAY_VISUAL_SIGNOFF + 老程裁定",
           "pure_game": []}
    for c in keep:
        src = gray_by_c[c]
        members = [{"seg": m["seg"], "start": m["start"], "end": m["end"]} for m in src["members"]]
        out["pure_game"].append({"cluster": c, "members": members})
    json.dump(out, open(f"{NC}/pure_game_windows_gray.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[写入] pure_game_windows_gray.json  (KEEP 簇 {len(keep)} 个: {sorted(keep)})")
    print("  随后可跑: python pick_smooth_offense_ext.py --pool merged --skip-start 8 --out-suffix _v2")
    raise SystemExit(0)

# ---- 模式B：生成复核页 ----
cards = []
for cl in gray["members"]:
    cid = cl["cluster"]
    for m in cl["members"]:
        seg, s0, s1 = m["seg"], m["start"], m["end"]
        s = strip(seg, s0, s1, 6)
        imgs = "".join(f"<figure><img src='data:image/jpeg;base64,{b}'><figcaption>f{i}</figcaption></figure>"
                       for i, b in s)
        cards.append(f"""<div class="card">
<div class="hd">#灰{cid} · {seg} · 窗 {s0}–{s1} <span class="pill2">待老程裁定</span></div>
<div class="mt">疑似/混合（right_white={cl.get('right_white')}）· 帧数 {cl.get('frames')}</div>
<div class="strip">{imgs}</div>
<div class="rs">请老程判：KEEP（真实半场进攻，并入池） / 剔（特写·讲解·包装·庆祝·场外）</div></div>""")

html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>灰区 7 簇 目视复核</title><style>
body{{font-family:system-ui,"PingFang SC",sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:18px}}
h1{{font-size:18px}} .note{{font-size:12px;color:#9aa3b2;line-height:1.7;background:#151821;padding:10px;border-radius:6px;margin:8px 0}}
.card{{background:#171a21;border:1px solid #2a2f3a;border-left:4px solid #e0a23b;border-radius:8px;padding:10px;margin:10px 0}}
.hd{{font-size:13px;font-weight:600;margin-bottom:4px}}
.mt{{font-size:11.5px;color:#cdd6e4;margin-bottom:6px}}
.strip{{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px}}
.strip figure{{margin:0;flex:0 0 auto}}
.strip img{{width:260px;border-radius:4px;display:block;background:#000}}
.strip figcaption{{font-size:10px;color:#7a8290;text-align:center;margin-top:2px}}
.pill2{{font-size:10px;padding:1px 6px;border-radius:9px;background:#3a2f12;color:#e0a23b}}
.rs{{font-size:11px;color:#e0a23b;margin-top:4px}}
</style></head><body>
<h1>灰区 7 簇 (GRAY_VISUAL_SIGNOFF, 339 帧) · 目视复核</h1>
<div class="note">
这 7 簇是自动判据落灰区、尚未经老程目视的窗口。规则同主线：<b>板帧 7 簇(1081帧) 整类剔除</b>（分屏包装）；
这里只复核灰区。每张卡一窗，左→右为时间顺序。<b>判 KEEP 的簇告诉我，我写 pure_game_windows_gray.json 并跑 pick --pool merged</b>；
判剔的簇直接丢弃。<br>强制 --skip-start=8 + 人数中位辅助 + 老程最终门禁（灰区可能含更多包装/过渡）。
</div>
{''.join(cards)}
</body></html>"""
open(a.out, "w", encoding="utf-8").write(html)
print(f"[产物] {a.out}  ({os.path.getsize(a.out)/1024/1024:.2f} MB)  · 灰区 {gray['n_clusters']} 簇 / {gray['frames']} 帧")
