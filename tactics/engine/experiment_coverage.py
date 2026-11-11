#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读实验：sas_* 覆盖提优的诊断。
思路：sas_det 门禁用 th=0.8 是因为低 th 时 trackable_frac<0.80（大量 implausible jump）。
但 A4.22 已证明逐帧球信号里 40-53% 是 jump；故「低 th 提召回 + jump-gate 删跳变」可能
在不破坏 trackable 门禁的前提下把覆盖从 6.25% 提到接近真实球覆盖率(~10-15%)。
本脚本只读 scores.json + track_ball，不落盘，纯诊断。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import importlib.util
import json
import math
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
spec = importlib.util.spec_from_file_location("tb", str(ROOT / "engine" / "track_ball.py"))
tb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tb)

MAX_STEP = 150.0   # A4.22 plaus 上界 px/帧
MIN_TRK = 3


def split_jump(tracks):
    out = []
    for t in tracks:
        cur = {"frames": [t["frames"][0]], "centers": [t["centers"][0]], "probs": [t["probs"][0]]}
        for k in range(1, len(t["frames"])):
            d = math.hypot(t["centers"][k][0] - t["centers"][k - 1][0],
                           t["centers"][k][1] - t["centers"][k - 1][1])
            if d > MAX_STEP:
                if len(cur["frames"]) >= MIN_TRK:
                    out.append(cur)
                cur = {"frames": [t["frames"][k]], "centers": [t["centers"][k]], "probs": [t["probs"][k]]}
            else:
                cur["frames"].append(t["frames"][k])
                cur["centers"].append(t["centers"][k])
                cur["probs"].append(t["probs"][k])
        if len(cur["frames"]) >= MIN_TRK:
            out.append(cur)
    return out


for clip in ("sas_det", "sas_nop", "sas_hou"):
    fr = json.loads((AW / "validate" / f"{clip}_scores.json").read_text())[clip]
    n = len(fr)
    print(f"\n=== {clip} (n_frames={n}) ===")
    for th in (0.3, 0.4, 0.5, 0.6, 0.8):
        tracks = tb.track_clip(fr, th, birth=th, gap=8)
        m0 = tb.track_metrics(tracks, n, MIN_TRK)
        kept = split_jump(tracks)
        m1 = tb.track_metrics(kept, n, MIN_TRK)
        ok0 = (m0["trackable_frac"] is not None and m0["trackable_frac"] >= 0.80)
        ok1 = (m1["trackable_frac"] is not None and m1["trackable_frac"] >= 0.80)
        print(f" th={th}: raw cov={m0['frame_coverage']*100:5.1f}% track={m0['trackable_frac']} "
              f"{'PASS' if ok0 else 'FAIL'} n_trk={m0['n_tracks']}  | +jumpgate cov={m1['frame_coverage']*100:5.1f}% "
              f"track={m1['trackable_frac']} {'PASS' if ok1 else 'FAIL'} n_trk={m1['n_tracks']}")
