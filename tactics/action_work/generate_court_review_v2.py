#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""点选页 v2：支持部分真实点 + 虚拟点（老程 2026-10-04 几何分类）。
读 routing_final.json(A_STEP_FINAL) + 老程几何分类 GEO，生成 court_review.html。
- 每簇按 GEO 预设可用角点（real/virtual/none）；real 需老程点图放置，virtual 标记即可（坐标后处理按矩形推导）。
- #3 无场地 → 灰掉，仅战术语料，不参与点选。
- 6 个未分类簇默认全 4 角可用（待老程板上更正）。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import base64
import json
import os
import re

from common.nba_paths import tactics_data_file

BASE = str(tactics_data_file("action_work/norm_calib"))
SEG = str(tactics_data_file("action_work/tactic_notes_batch_full/segments"))

# 老程几何分类（2026-10-04）：real=画面真实可见角点；virtual=几何可推导(画虚拟)；none=不在画面
GEO = {
    3:  {"no_court": True},
    5:  {"real": ["f_l"], "virtual": ["n_l"]},
    8:  {"real": ["f_l"], "virtual": ["n_l"]},
    11: {"real": ["f_l"], "virtual": ["n_l"]},
    15: {"real": ["f_r"]},
    18: {"real": ["f_r"]},
    22: {"real": ["f_r"]},
    29: {"real": ["f_r"], "virtual": ["n_r"]},
    # 老程 2026-10-04 全量标注：#6/#13/#19 远左(f_l)，#9/#12/#16 远右(f_r)
    6:  {"real": ["f_l"], "virtual": ["n_l"]},
    13: {"real": ["f_l"], "virtual": ["n_l"]},
    19: {"real": ["f_l"], "virtual": ["n_l"]},
    9:  {"real": ["f_r"], "virtual": ["n_r"]},
    12: {"real": ["f_r"], "virtual": ["n_r"]},
    16: {"real": ["f_r"], "virtual": ["n_r"]},
}
ALLC = ["f_l", "f_r", "n_l", "n_r"]

rf = json.load(open(f"{BASE}/routing_final.json", encoding="utf-8"))
ast = rf["buckets"]["A_STEP_FINAL"]["detail"]  # list of "ep..#s-e(N帧):reason"

def frame_path(seg, idx):
    return f"{SEG}/{seg}/frames/f{idx+1:05d}.jpg"

def pick_rep(seg, start, end):
    mid = start + (end - start) // 2
    for d in (0, 1, -1, 2, -2, 3, -3):
        if os.path.exists(frame_path(seg, mid + d)):
            return frame_path(seg, mid + d)
    return frame_path(seg, mid)

clusters = []
for d in ast:
    m = re.match(r"(ep\d+_s\d+)#(\d+)-(\d+)\((\d+)帧\)", d)
    seg, s, e, fr = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    c = int(seg.split("_s")[0][2:])  # not used; cluster from detail order
    # cluster id = index in A_STEP_FINAL list order? use numeric from seg? We stored cluster in routing_final? no.
    # recover cluster id via manifest mapping not available; use GEO keys by matching seg/start/end
    cid = None
    for k, v in GEO.items():
        pass
    # cluster id is encoded implicitly; reconstruct from A_STEP_FINAL['clusters'] order
    clusters.append({"seg": seg, "start": s, "end": e, "frames": fr, "detail": d})

# attach cluster id from routing_final A_STEP_FINAL['clusters'] by position
ids = rf["buckets"]["A_STEP_FINAL"]["clusters"]
assert len(ids) == len(clusters), (len(ids), len(clusters))
for cl, cid in zip(clusters, ids):
    cl["cluster"] = cid
    g = GEO.get(cid, {"real": ALLC})
    cl["geo"] = g
    rep = pick_rep(cl["seg"], cl["start"], cl["end"])
    with open(rep, "rb") as f:
        cl["img"] = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")

payload = {"clusters": clusters, "total_frames": rf["total_frames"],
           "all_corners": ALLC}
html = open(str(tactics_data_file("action_work/court_review_template_v2.html")),
            encoding="utf-8").read()
html = html.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
open(f"{BASE}/court_review.html", "w", encoding="utf-8").write(html)
print("clusters:", len(clusters), "bytes:", len(html))
print("no_court:", [c["cluster"] for c in clusters if c["geo"].get("no_court")])
