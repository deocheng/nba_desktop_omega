#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机端到端验证 fusion_judge：对 3 个已剪锚点 clip 现算 sb_frac + 调 Qwen + 裁定。
sb_frac 以整段为代理（管线真实调用会传 refine 的 close 段时间窗）。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(tactics_data_file("bonsai")))
import fusion_judge as fj

NBACUP = str(tactics_data_file("clips/tactics_notes_pick/nbacup"))
CLIPS = [
    ("cand1244", f"{NBACUP}/cand_1244.5-1269.0.mp4", "EXCLUDE(吹停转场)"),
    ("cand932",  f"{NBACUP}/cand_932.5-949.0.mp4",   "KEEP(一次进攻)"),
    ("possA_full", f"{NBACUP}/possA_full_444.5-458.0.mp4", "KEEP(最完整标杆)"),
]


def dur_of(p):
    import cv2
    cap = cv2.VideoCapture(p)
    d = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return d


for name, path, expect in CLIPS:
    d = dur_of(path)
    # 整段代理：close_span=(0, d)
    c = {"far": [0, 0, 300], "mid": [0, 0], "close": [0, d, 700],
         "dur": round(d, 1), "act_rise": 0, "shape_ok": True,
         "sb_frac": None, "clip": [0, d]}
    r = fj.judge_candidate(c, path, fj.QWEN_URL, use_qwen=True,
                          close_span=(0, d))
    print(f"\n=== {name} (时长{d:.1f}s, 期望 {expect}) ===")
    print(f"  sb_frac   = {r['sb_frac']}")
    print(f"  qwen_live = {r.get('qwen_live')}")
    print(f"  verdict   = {r['verdict']}  (conf={r['conf']})")
    print(f"  reason    = {r['reason']}")
