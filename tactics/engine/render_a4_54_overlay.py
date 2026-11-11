#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.54 视觉自证 —— 把增强球轨迹(检测绿 + 遮挡吸附橙)与所选持球者框(蓝)叠加到
原帧, 渲染 3 个最长遮挡段的帧条, 供老程目视裁定吸附质量。

不写任何新数据, 纯读 <clip>_ball_track_occluded.json + 原帧 + 球员轨迹。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

import cv2

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
CLIP = sys.argv[1] if len(sys.argv) > 1 else "sas_det"
OUT_JSON = AW / "validate" / f"{CLIP}_ball_track_occluded.json"
TRACKS = AW / f"{CLIP}_poss_tile_stab" / "ball_tracks.json"
STATES = AW / "validate" / f"{CLIP}_frame_states.json"
FR = AW / CLIP

d = json.loads(OUT_JSON.read_text())
fr = d["frame"]
states = {r["fid"]: r for r in json.loads(STATES.read_text())["rows"]}
old = json.loads(TRACKS.read_text())
EXCL = set(d["meta"]["excluded_tids"])

# 取最长 3 段
gaps = sorted([g for g in d["gap_detail"] if g["len"] >= 5], key=lambda g: -g["len"])[:3]

for gi, g in enumerate(gaps):
    fa, fb = map(int, g["gap"].split("-"))
    lo, hi = max(1, fa - 2), min(400, fb + 2)
    strip = None
    for fk in range(lo, hi + 1):
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        if img is None:
            continue
        img = cv2.resize(img, (300, 169))
        sx, sy = 300 / 1920, 169 / 1080
        f = fr[fk - 1]
        # 球标记
        if f["ball"]:
            x, y = int(f["ball"][0] * sx), int(f["ball"][1] * sy)
            col = (0, 200, 0) if f["source"] == "detect" else (0, 165, 255)
            cv2.circle(img, (x, y), 7, col, 3)
        else:
            cv2.putText(img, "NONE", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
        # 持球者框
        if f["holder_tid"] is not None:
            pl = next((p for p in old[fk - 1].get("players", [])
                       if p.get("track_id") == f["holder_tid"] and p.get("bbox")), None)
            if pl:
                b = pl["bbox"]
                cv2.rectangle(img, (int(b[0] * sx), int(b[1] * sy)),
                              (int(b[2] * sx), int(b[3] * sy)), (255, 0, 0), 2)
        # PBP 文本
        pbp = states[fk].get("possession", "")
        cv2.putText(img, f"f{fk} {pbp}", (6, 162), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 255) if pbp == "SAS" else (0, 0, 255), 1)
        cv2.putText(img, f["source"][:4], (230, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 200, 0) if f["source"] == "detect" else (0, 165, 255), 1)
        strip = img if strip is None else cv2.hconcat([strip, img])
    if strip is not None:
        p = AW / "validate" / f"{CLIP}_a4_54_overlay_gap{gi+1}_{fa}-{fb}.png"
        cv2.imwrite(str(p), strip)
        print(f"[overlay] {p}  ({g['team']} start_dist={g['start_dist_px']} end_dist={g['end_dist_px']})")
print("[done]")
