#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按老程『目测裁定吧』授权，把 routing_manifest 的三路路由落为最终处置清单。

注意：本模型不可读图，故「目测」= 用 right_white + replay_later + 段尾位置作结构代理推断。
裁定规则（老程 2026-10-04 授权）：
  DISREGARD_BOARD  = 分屏(纸板) 7簇/1081帧        板帧完全不考虑
  DISREGARD_GRAY   = 疑似/混合 7簇/339帧          right_white 0.10-0.19 判包装层/小板覆盖
  DISREGARD_CLOSEUP= GAME 内特写窗(无场地线)       已知 ep13_s1#5-50(c17)
  A_STEP           = GAME 剩余干净回放窗           A步标定 + 学习对象（点选后再最终过滤）
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
rm = json.load(open(f"{BASE}/routing_manifest.json", encoding="utf-8"))

# 已知特写窗（B 报告 §6.1 登记；无场地线，标定无意义）
CLOSEUP = {17: "ep13_s1#5-50"}

buckets = defaultdict(lambda: {"clusters": [], "frames": 0, "members": []})

SRC = {
    "DISREGARD_BOARD": "DISREGARD_BOARD",
    "DISREGARD_GRAY": "GRAY_VISUAL_SIGNOFF",
    "A_STEP": "GAME_HALFCOURT_CANDIDATE",
}
for disp, src in SRC.items():
    for m in rm["routes"][src]["members"]:
        c = m["cluster"]
        d = "DISREGARD_CLOSEUP" if c in CLOSEUP else disp
        buckets[d]["clusters"].append(c)
        buckets[d]["frames"] += m["frames"]
        for w in m["members"]:
            buckets[d]["members"].append({
                "seg": w["seg"], "start": w["start"], "end": w["end"],
                "note": "known_closeup" if c in CLOSEUP else "",
            })

out = {
    "decided_by": "老程『目测裁定吧』授权(2026-10-04)；AI 因模型不可读图，用 right_white+replay_later+段尾位置作结构代理推断",
    "rules": {
        "DISREGARD_BOARD": "分屏(纸板) 7簇/1081帧：板帧完全不考虑",
        "DISREGARD_GRAY": "疑似/混合 7簇/339帧：right_white 0.10-0.19 介于比赛与分屏间，判包装层/小板覆盖，非干净半场",
        "DISREGARD_CLOSEUP": "GAME 内特写窗(无场地线)：ep13_s1#5-50(c17)",
        "A_STEP": "GAME 剩余干净回放窗：A步标定+学习对象（点选后再最终过滤）",
    },
    "flag_review_disregard": [
        "ep13_s1#80-216", "ep16_s0#121-219", "ep17_s1#147-219", "ep10_s0#205-219"
    ],
    "buckets": {k: {"clusters": v["clusters"], "frames": v["frames"],
                    "members": v["members"]} for k, v in buckets.items()},
    "summary": {
        "total_frames": rm["total_frames"],
        "disregard_frames": buckets["DISREGARD_BOARD"]["frames"]
        + buckets["DISREGARD_GRAY"]["frames"] + buckets["DISREGARD_CLOSEUP"]["frames"],
        "a_step_frames": buckets["A_STEP"]["frames"],
    },
}
json.dump(out, open(f"{BASE}/routing_decided.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

print("total_frames =", rm["total_frames"])
for k, v in buckets.items():
    print(f"  {k:18} clusters={len(v['clusters']):>2} frames={v['frames']:>4}")
print("  => A_STEP 语料 =", buckets["A_STEP"]["frames"], "帧；剔除 =",
      out["summary"]["disregard_frames"], "帧")
print("written ->", f"{BASE}/routing_decided.json")
