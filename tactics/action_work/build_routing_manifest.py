#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按老程 2026-10-04 方向修正重路由：板帧完全不考虑，完整回放在同段后出现。

输入（磁盘既存，非新造）：
  norm_calib/pure_game_windows.json  —— 三分类窗口（auto_split / auto_mixed / pure_game）
  norm_calib/window_layout.json      —— 每窗口 right_white + kind

输出：
  norm_calib/routing_manifest.json

路由（老程拍板：板帧完全不考虑，因完整回放后会现身）：
  DISREGARD_BOARD          = 分屏(纸板)  → 完全剔除（不进 A 步、不进训练；完整回放在同段后出现）
  GAME_HALFCOURT_CANDIDATE = 比赛     → A 步标定 + 训练素材来源（完整回放多落在此）；须目视剔特写窗
  GRAY_VISUAL_SIGNOFF     = 疑似/混合 → 目视裁定

安全网 replay_later_check：
  对每个板帧窗口，检查同段是否存在「在其之后(start>=end)」的非板窗口（比赛/混合），
  作为「完整回放已捕获」的证据；若无 → flag 待老程目视确认（防静默丢 footage）。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from collections import defaultdict

from common.nba_paths import tactics_data_file

BASE = str(tactics_data_file("action_work/norm_calib"))
pw = json.load(open(f"{BASE}/pure_game_windows.json", encoding="utf-8"))
wl = json.load(open(f"{BASE}/window_layout.json", encoding="utf-8"))
wl_by_c = {e["cluster"]: e for e in wl}

# 扁平化所有窗口，带分类
all_windows = []
for cat, kind in [("auto_split", "分屏(纸板)"), ("auto_mixed", "疑似/混合"), ("pure_game", "比赛")]:
    for it in pw[cat]:
        for m in it["members"]:
            all_windows.append({"seg": m["seg"], "start": m["start"], "end": m["end"],
                                "cat": cat, "kind": kind, "cluster": it["cluster"]})
by_seg = defaultdict(list)
for w in all_windows:
    by_seg[w["seg"]].append(w)


def replay_later_check(seg: str, end: int):
    return [w for w in by_seg.get(seg, []) if w["cat"] != "auto_split" and w["start"] >= end]


ROUTE_MAP = {
    "DISREGARD_BOARD": ("auto_split", "分屏(纸板)"),
    "GAME_HALFCOURT_CANDIDATE": ("pure_game", "比赛"),
    "GRAY_VISUAL_SIGNOFF": ("auto_mixed", "疑似/混合"),
}
DESC = {
    "DISREGARD_BOARD": "分屏战术板帧：老程拍板完全不考虑（完整回放会在同段后出现）；不进 A 步、不进训练",
    "GAME_HALFCOURT_CANDIDATE": "纯比赛窗：A 步标定 + 训练素材来源（完整回放多落在此）；须老程目视剔特写(无场地线)窗",
    "GRAY_VISUAL_SIGNOFF": "疑似/混合：自动判据落灰区，须老程目视裁定",
}
KNOWN_CLOSEUP = {"ep13_s1#5-50": "cluster17 球员近景无场地线（B 报告 §6.1 登记）"}

manifest = {
    "built_from": ["pure_game_windows.json", "window_layout.json"],
    "total_frames": pw["total_frames"],
    "routes": {},
}
for route, (cat, kind) in ROUTE_MAP.items():
    items = pw[cat]
    clusters = [it["cluster"] for it in items]
    frames = sum(it["frames"] for it in items)
    members = []
    for it in items:
        c = it["cluster"]
        wlinfo = wl_by_c.get(c, {})
        mems = []
        for m in it["members"]:
            later = replay_later_check(m["seg"], m["end"])
            mems.append({
                **m,
                "replay_later": [
                    {"seg": w["seg"], "start": w["start"], "end": w["end"], "kind": w["kind"]}
                    for w in later
                ],
            })
        members.append({
            "cluster": c, "frames": it["frames"],
            "right_white": wlinfo.get("right_white"), "kind": wlinfo.get("kind"),
            "members": mems,
        })
    manifest["routes"][route] = {
        "desc": DESC[route], "clusters": clusters,
        "n_clusters": len(clusters), "frames": frames,
        "frac_of_total": round(frames / pw["total_frames"], 4), "members": members,
    }

manifest["routes"]["GAME_HALFCOURT_CANDIDATE"]["known_closeup_windows"] = KNOWN_CLOSEUP
manifest["decisions_pending"] = [
    "A 步：老程用 pick_court_lines.py 点选 Top-9 机位(乙口径,72点) → 接 P0 单应(守 C4)",
    "GRAY 7 簇/339 帧目视裁定",
    "DISREGARD_BOARD 中 replay_later 为空的板窗：确认完整回放是否确在同段（防静默丢 footage）",
]

out = f"{BASE}/routing_manifest.json"
json.dump(manifest, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("total_frames =", pw["total_frames"])
for route, info in manifest["routes"].items():
    print(f"\n[{route}] clusters={info['n_clusters']} frames={info['frames']} frac={info['frac_of_total']}")
    for m in info["members"]:
        print(f"  c{m['cluster']:>2} rw={m['right_white']:.3f} {m['kind']:>8} frames={m['frames']:>3} members={len(m['members'])}")
# replay_later 安全网汇总
print("\n--- replay_later 安全网（板帧窗是否有同段后续非板窗）---")
flagged = []
for m in manifest["routes"]["DISREGARD_BOARD"]["members"]:
    for w in m["members"]:
        seg_win = f"{w['seg']}#{w['start']}-{w['end']}"
        if w["replay_later"]:
            print(f"  OK   {seg_win}: 后续非板窗 {len(w['replay_later'])} 个")
        else:
            print(f"  FLAG {seg_win}: 同段无后续非板窗！")
            flagged.append(seg_win)
print("\nFLAGGED:", flagged if flagged else "无")
print("written ->", out)
