#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从磁盘实读：定位可切「完整配合」的候选（老程授权在战术笔记原片里剪）。
只信落盘数据：smooth_picks(merged_role) 的 KEEP + routing_manifest 的路由。
输出：候选清单 = ep/seg/帧区间/ASR战术名/指标，供回原片切片段。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import glob
import json
import os

from common.nba_paths import data_file, tactics_data_file

BASE = str(tactics_data_file("action_work"))
NC = f"{BASE}/norm_calib"
SRC = str(data_file("NBA战术笔记"))

picks = json.load(open(f"{NC}/smooth_picks_merged_role.json"))
man = json.load(open(f"{NC}/routing_manifest.json"))
asr = json.load(open(f"{NC}/a_step_named.json")) if os.path.exists(f"{NC}/a_step_named.json") else {}

# 簇 -> 路由归类
cl2route = {}
for rk, rv in man["routes"].items():
    for c in rv["clusters"]:
        cl2route[c] = rk

rows = picks["smooth"] + picks["static"] + picks["excluded_by_laocheng"]
print(f"落盘窗 {len(rows)} / 声明 {picks['n_windows']}\n")

keep = [r for r in rows if r.get("laocheng_verdict") == "KEEP"]
print(f"老程 KEEP = {len(keep)} 个\n")

hdr = (f"{'clus':<5}{'ep':<7}{'seg':<10}{'win':<12}{'路由':<26}"
       f"{'n_mv':<6}{'spd':<7}{'people':<8}{'scale_h':<9}{'ball':<7}ASR")
print(hdr)
print("-" * len(hdr))
for r in sorted(keep, key=lambda x: x["cluster"]):
    route = cl2route.get(r["cluster"], "未分类")
    name = r.get("asr_name") or ""
    print(f"{r['cluster']:<5}{r.get('ep',''):<7}{r['seg']:<10}"
          f"{str(r['win_start'])+'-'+str(r['win_end']):<12}{route:<26}"
          f"{r['n_movers']:<6}{r['median_speed_px']:<7}"
          f"{str(r['median_people_per_frame']):<8}{str(r.get('camera_scale_h')):<9}"
          f"{str(r.get('ball_real_rate')):<7}{name}")

# 找原始视频文件名
print("\n=== 原始视频定位（按 ep 号）===")
eps = sorted({r.get("ep", "") for r in keep if r.get("ep")}, key=lambda e: int(e[2:]))
vids = sorted(glob.glob(os.path.join(SRC, "*.mp4")))
for e in eps:
    n = e[2:]
    hit = [os.path.basename(v) for v in vids if f"Ep{n}：" in v or f"EP{n}：" in v or f"第{n}期" in v]
    print(f"  {e}  →  {hit[0][:60] if hit else '❌ 未匹配'}")

json.dump([{k: r.get(k) for k in ("cluster", "ep", "seg", "win_start", "win_end",
                                 "asr_name", "n_movers", "median_speed_px",
                                 "median_people_per_frame", "camera_scale_h",
                                 "ball_real_rate", "laocheng_verdict")}
           for r in sorted(keep, key=lambda x: x["cluster"])],
          open(f"{NC}/clip_candidates.json", "w"), ensure_ascii=False, indent=1)
print("\nwrote", f"{NC}/clip_candidates.json")
