#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.51 球的移动追踪 —— 球轨迹运动学基线(sas_det)。

背景: 识别层已收口(A4.42 球检测 + A4.49 teamID 100% QUALIFIED)。球员移动层已有
tactical_pressure(压力/空当)/tactical_events(速度/事件), 但**球轨迹本身**从未被量化:
此前所有工作都在「球检测精度」(能不能找到球), 没有「球怎么动」(飞行/持有/丢失)。

本脚本(纯计算, 不插值, 零新模型):
  逐帧球心(top1, th=0.30, diag<60, 与生产口径一致) → 逐帧速度 → 三分类:
    HOLD = 有检测 且 球速<250px/s 且 最近球员≤RAD(0.04×对角线)
    FLY  = 有检测 且 (球速≥250 或 最近球员>RAD)
    NONE = 无检测(头弃权; 🔴 不插值, 铁律)
  → episode(连续有检测段)/飞行段/持有段 分段与统计。

产出: action_work/validate/sas_det_ball_kinematics.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
CLIP = sys.argv[1] if len(sys.argv) > 1 else "sas_det"
OUT = AW / "validate" / f"{CLIP}_ball_kinematics.json"

TH = 0.30
DIAG_MAX = 60
N_FRAMES = 400
FPS = 10.0
RAD = 0.04 * math.hypot(1920, 1080)
HOLD_MAX = 250.0   # 与 t3b 口径2 一致(球在手中判据)
# 裁判剔除: 与 t3b canonical 同一裁定映射(不能把裁判当持球者)
ADJUDGED_REFEREES = {"sas_det": {31, 33, 38, 64}, "sas_lal": {7, 8, 38}}
EXCL = ADJUDGED_REFEREES.get(CLIP, set())

scores = json.loads((AW / "validate" / f"ball_cand_scores_dense_a442_{CLIP}_joint.json").read_text())
fr_scores = scores[CLIP] if CLIP in scores else scores
tr = json.loads((AW / f"{CLIP}_poss_tile_stab" / "ball_tracks.json").read_text())
states = json.loads((AW / "validate" / f"{CLIP}_frame_states.json").read_text())
live_of = {r["fid"]: r["live_state"] for r in states["rows"]}


def top1(cands):
    best = None
    for c in cands:
        diag = max(c["bbox"][2] - c["bbox"][0], c["bbox"][3] - c["bbox"][1])
        if c["prob"] >= TH and diag < DIAG_MAX:
            if best is None or c["prob"] > best["prob"]:
                best = c
    return best


# ---- 逐帧球心 + 最近球员(剔除裁判后) ----
bc = [None] * N_FRAMES      # 球心
nd = [None] * N_FRAMES      # 最近球员中心距
hold_tid = [None] * N_FRAMES
for i, fr in enumerate(tr[:N_FRAMES]):
    fk = i + 1
    t = top1(fr_scores.get(f"f{fk:05d}.jpg", []))
    if t is not None:
        b = t["bbox"]
        bc[i] = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
        best = (1e18, None)
        for p in fr.get("players", []):
            tid = p.get("track_id")
            pb = p.get("bbox")
            if tid is None or not pb or tid in EXCL:
                continue
            d = math.hypot((pb[0] + pb[2]) / 2 - bc[i][0], (pb[1] + pb[3]) / 2 - bc[i][1])
            if d < best[0]:
                best = (d, tid)
        if best[1] is not None:
            nd[i], hold_tid[i] = best[0], best[1]

# ---- 逐帧速度(仅相邻两帧都有检测; 不插值) ----
spd = [None] * N_FRAMES
for i in range(1, N_FRAMES):
    if bc[i] and bc[i - 1]:
        spd[i] = math.hypot(bc[i][0] - bc[i - 1][0], bc[i][1] - bc[i - 1][1]) * FPS

# ---- 三分类 ----
state = ["NONE"] * N_FRAMES
for i in range(N_FRAMES):
    if bc[i] is None:
        state[i] = "NONE"
        continue
    s = spd[i]
    fast = (s is not None and s >= HOLD_MAX)
    far = (nd[i] is None or nd[i] > RAD)
    state[i] = "FLY" if (fast or far) else "HOLD"


def runs(pred):
    """连续满足 pred 的段(0-based, 含首尾)。"""
    out, cur = [], None
    for i in range(N_FRAMES):
        if pred(i):
            if cur is None:
                cur = i
        else:
            if cur is not None:
                out.append({"start_fid": cur + 1, "end_fid": i, "n": i - cur})
                cur = None
    if cur is not None:
        out.append({"start_fid": cur + 1, "end_fid": N_FRAMES, "n": N_FRAMES - cur})
    return out


def flying_dist(seg):
    """飞行段首尾直线距离(px)。"""
    a, b = seg["start_fid"] - 1, seg["end_fid"] - 1
    if bc[a] is None or bc[b] is None:
        return None
    return math.hypot(bc[b][0] - bc[a][0], bc[b][1] - bc[a][1])


det_runs = runs(lambda i: state[i] != "NONE")
fly_runs = [dict(s, dist_px=round(flying_dist(s), 1)) for s in runs(lambda i: state[i] == "FLY")]
hold_runs = runs(lambda i: state[i] == "HOLD")
none_runs = runs(lambda i: state[i] == "NONE")
spd_vals = [s for i, s in enumerate(spd) if s is not None and state[i] == "FLY"]

n_det = sum(1 for s in state if s != "NONE")
n_hold = sum(1 for s in state if s == "HOLD")
n_fly = sum(1 for s in state if s == "FLY")

print(f"[{CLIP}] 球覆盖 {n_det}/{N_FRAMES} ({n_det/N_FRAMES*100:.1f}%)")
print(f"  分类: HOLD={n_hold} ({n_hold/n_det*100:.1f}% of检测) FLY={n_fly} ({n_fly/n_det*100:.1f}%) "
      f"NONE={N_FRAMES-n_det}")
print(f"  episode(连续有检测段)={len(det_runs)} 段, 中位长度 "
      f"{sorted(r['n'] for r in det_runs)[len(det_runs)//2] if det_runs else 0} 帧, "
      f"最长 {max((r['n'] for r in det_runs), default=0)} 帧")
print(f"  飞行段={len(fly_runs)} 段, 中位长度 "
      f"{sorted(r['n'] for r in fly_runs)[len(fly_runs)//2] if fly_runs else 0} 帧, "
      f"最长 {max((r['n'] for r in fly_runs), default=0)} 帧")
if fly_runs:
    ds = [r["dist_px"] for r in fly_runs if r["dist_px"] is not None]
    print(f"  飞行段首尾直线距离: 中位 {sorted(ds)[len(ds)//2]:.0f}px, 最大 {max(ds):.0f}px")
if spd_vals:
    print(f"  飞行帧球速: p25={sorted(spd_vals)[len(spd_vals)//4]:.0f} "
          f"p50={sorted(spd_vals)[len(spd_vals)//2]:.0f} p75={sorted(spd_vals)[3*len(spd_vals)//4]:.0f} px/s")
print(f"  持有段={len(hold_runs)} 段, 中位长度 "
      f"{sorted(r['n'] for r in hold_runs)[len(hold_runs)//2] if hold_runs else 0} 帧")
print(f"  无检测 gap={len(none_runs)} 段, 最长 {max((r['n'] for r in none_runs), default=0)} 帧 "
      f"(🔴 不插值, 只如实标记)")

json.dump({"meta": {"clip": CLIP, "th": TH, "diag_max": DIAG_MAX, "fps": FPS,
                    "hold_max_px_s": HOLD_MAX, "radius_px": round(RAD, 1),
                    "excluded_tids": sorted(EXCL), "no_interp": True},
           "counts": {"n_frames": N_FRAMES, "n_detected": n_det, "n_hold": n_hold,
                      "n_fly": n_fly, "n_none": N_FRAMES - n_det},
           "frame_state": state,
           "frame_speed_px_s": [None if s is None else round(s, 1) for s in spd],
           "frame_ball": [None if c is None else [round(c[0], 1), round(c[1], 1)] for c in bc],
           "frame_near_player_dist": [None if d is None else round(d, 1) for d in nd],
           "episodes": det_runs, "fly_segments": fly_runs, "hold_segments": hold_runs,
           "none_gaps": none_runs}, open(OUT, "w"), indent=1)
print(f"[out] {OUT}")
