#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tactical_events.py — 战术事件层（A4.23 · pass / drive / pick_and_roll）。

把 A4.22 的新指标（球速/方向）+ 占有权稳定段接进离散战术事件判定，并叠加
A4.21 的 N-of-M 时序稳定层到「换手/传球计数」（Task C）。

输入
----
  action_work/{clip}_poss_tile/ball_tracks.json   逐帧 ball + players(track_id,bbox)
  action_work/{clip}_poss_tile/possession_segments.json   hysteresis 占有权 RLE 段

事件定义（均带时序稳定，避免 A4.22 报告点出的「换手计数未稳定不得当传球数」）
----------------------------------------------------------------------------------
  PASS  ：占有权段 A→B 的过渡，且过渡窗口内有球飞行(球速>FAST)；
          时序稳定 = A、B 两段均 ≥ PASS_N 帧（N-of-M 确认新持球者确实接住）。
  DRIVE ：占有权段内，持球者框心速度 > DRIVE_PX_S 连续 ≥ DRIVE_MIN_M 帧，且球在手中(球速<HOLD_MAX)。
  PNR   ：DRIVE 发生的同时，存在一个近静止队友(屏幕人)贴近某防守人(另一球员)，
          且位于持球者移动路径前方 —— ⚠️ 探索性：无 team ID，screen/defender 为运动学启发式，不得当结论。

方法纪律（继承项目铁律）
------------------------
  - 球速/方向只在 plaus [80,1500]px/s 内判定飞行（复用 A4.22 闸门）。
  - 持球者移动速度仅计「球在手中」帧（排除飞行段误归，同 A4.22）。
  - 帧率 10fps；输出数字全从 JSON 现读。
  - 无 team ID ⇒ 不区分攻防两侧；PnR 仅作探索性标注。

用法
----
  python engine/tactical_events.py --clip w1
  python engine/tactical_events.py --all-clips
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import importlib.util
import json
import math
import statistics as st
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
OUT = AW / "validate" / "tactical_events"
FPS = 10.0

FAST_PX_S = 300.0        # 传球飞行阈值（球速>此 ⇒ 球在飞）
HOLD_MAX_PS = 250.0      # 球在手中阈值（球速<此 ⇒ 持球）
PLAUS_LO, PLAUS_HI = 80.0, 1500.0   # A4.22 物理合理区间
HOLDER_RADIUS = 150.0
HYST = 3                  # 沿用 ball_possession 默认迟滞
PASS_N = 5                # Task C：新持球者段须 ≥5 帧确认（N-of-M）
DRIVE_PX_S = 130.0       # 持球者驱动速度阈值 ≈ 观察分布 p75（w1 132 / w3 127）
DRIVE_MIN_M = 3          # 连续 ≥3 帧
STATIONARY = 100.0       # 屏幕人近静止阈值
D_SCREEN = 120.0         # 屏幕人-防守人贴近距离(px)
D_HANDLER_SCREEN = 200.0 # 屏幕人须贴近持球者驱动路径


def _import(name, path):
    spec = importlib.util.spec_from_file_location(name, str(ROOT / "engine" / path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


bem = _import("bem", "ball_event_metrics.py")


def ctr(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def load_clip(clip):
    c = clip.replace("baseline_", "")
    p = AW / f"{c}_poss_tile" / "ball_tracks.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    out = []
    for fr in data:
        ball = fr.get("ball")
        bc = ctr(ball["bbox"]) if isinstance(ball, dict) and ball.get("bbox") else None
        players = [{"tid": pl.get("track_id"), "c": ctr(pl["bbox"]),
                    "bbox": pl["bbox"]} for pl in fr.get("players", []) if pl.get("bbox")]
        out.append({"frame": fr.get("frame"), "ball": bc,
                    "interp": bool(ball.get("interp", False)) if isinstance(ball, dict) else False,
                    "players": players})
    return out


def load_segments(clip):
    c = clip.replace("baseline_", "")
    p = AW / f"{c}_poss_tile" / "possession_segments.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def per_tid_speed(frames):
    """逐球员框心速度(px/s)，med5 滚动中位平滑（复用 tactical_movement 思路）。"""
    n = len(frames)
    traj = {}
    for i, fr in enumerate(frames):
        for p in fr["players"]:
            traj.setdefault(p["tid"], []).append((i, p["c"]))
    tid_spd = {tid: [None] * n for tid in traj}
    for tid, pts in traj.items():
        raw = [None] * len(pts)
        for k in range(1, len(pts)):
            gi0, c0 = pts[k - 1]
            gi1, c1 = pts[k]
            if gi1 == gi0 + 1:
                d = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
                raw[k] = d * FPS
        # med5
        sm = []
        for k in range(len(raw)):
            seg = [v for v in raw[max(0, k - 2):k + 3] if v is not None]
            sm.append(st.median(seg) if seg else None)
        for k, (gi, _) in enumerate(pts):
            tid_spd[tid][gi] = sm[k]
    return tid_spd


def tid_at_frame(segments, n):
    arr = [None] * n
    for s in segments:
        for gi in range(s["start"], s["end"] + 1):
            if 0 <= gi < n:
                arr[gi] = s["track_id"]
    return arr


def smooth_holder(taf, W=9, M=5):
    """N-of-M 时序稳定层（Task C）：滑动窗 W 帧内，某 tid 出现 ≥M 帧才确认为持球者，
    否则置 None。这会把宽景里每 ~2 帧抖动的「最近球员」压成稳定的占有权段，
    换手计数从此建立在稳定段上，而非逐帧抖动。"""
    n = len(taf)
    out = [None] * n
    for gi in range(n):
        lo, hi = max(0, gi - W // 2), min(n, gi + W // 2 + 1)
        cnt = {}
        for g in range(lo, hi):
            t = taf[g]
            if t is not None:
                cnt[t] = cnt.get(t, 0) + 1
        best, bc = None, 0
        for t, c in cnt.items():
            if c > bc:
                bc, best = c, t
        out[gi] = best if bc >= M else None
    return out


def smoothed_segments(sh):
    segs = []
    cur = None
    for gi, t in enumerate(sh):
        if t is None:
            if cur is not None:
                segs.append({"track_id": cur[0], "start": cur[1], "end": gi - 1, "n": gi - cur[1]})
                cur = None
        else:
            if cur is None or cur[0] != t:
                if cur is not None:
                    segs.append({"track_id": cur[0], "start": cur[1], "end": gi - 1, "n": gi - cur[1]})
                cur = (t, gi)
    if cur is not None:
        segs.append({"track_id": cur[0], "start": cur[1], "end": len(sh) - 1, "n": len(sh) - cur[1]})
    return segs


def detect(frames, segments):
    n = len(frames)
    ball_segs = bem.ball_speed_dir(frames, FPS)
    ball_spd = {s["f1"]: s["speed_ps"] for s in ball_segs}
    tid_spd = per_tid_speed(frames)
    taf = tid_at_frame(segments, n)

    # Task C：N-of-M 平滑占有权（崩溃逐帧抖动）
    sh = smooth_holder(taf, W=9, M=5)
    sm_segs = smoothed_segments(sh)

    # 持球者速度（稳定占有权段内即视为「球在手中」——hysteresis 已保证，
    # 不再额外用 ball_spd 门禁，避免 A4.22 跳变 artifacts 打断连续驱动段）
    holder_spd_held = [None] * n
    for gi in range(n):
        tid = sh[gi]
        if tid is None:
            continue
        sp = tid_spd.get(tid, [None] * n)[gi]
        if sp is not None:
            holder_spd_held[gi] = sp

    events = []
    # ---- PASS（稳定占有权段 A→B 过渡 + 球飞行证据）----
    raw_pass = 0
    for i in range(len(segments) - 1):
        if segments[i]["track_id"] != segments[i + 1]["track_id"]:
            raw_pass += 1

    def pass_flight(gi_star):
        # 过渡帧附近球确实在飞（速度>FAST）或球明显位移(>100px 跨过渡)
        if ball_spd.get(gi_star, 0) > FAST_PX_S or ball_spd.get(gi_star + 1, 0) > FAST_PX_S:
            return True
        pts = [ball_spd.get(g, None) for g in (gi_star - 2, gi_star - 1, gi_star, gi_star + 1, gi_star + 2)]
        if any(p is not None and p > PLAUS_LO for p in pts):
            return True
        return False

    confirmed_pass = 0
    for i in range(len(sm_segs) - 1):
        a, b = sm_segs[i], sm_segs[i + 1]
        if a["track_id"] == b["track_id"]:
            continue
        # 过渡帧 ≈ b.start
        gi_star = b["start"]
        if pass_flight(gi_star):
            confirmed_pass += 1
            events.append({"type": "PASS", "from": a["track_id"], "to": b["track_id"],
                           "at": gi_star, "from_n": a["n"], "to_n": b["n"]})

    # ---- DRIVE（稳定持球者连续高速 + 球在手中）----
    drive_runs = []
    run = []
    for gi in range(n):
        sp = holder_spd_held[gi]
        if sp is not None and sp > DRIVE_PX_S:
            run.append(gi)
        else:
            if len(run) >= DRIVE_MIN_M:
                drive_runs.append(run)
            run = []
    if len(run) >= DRIVE_MIN_M:
        drive_runs.append(run)

    pnr = 0
    for r in drive_runs:
        tid = sh[r[0]]
        if tid is None:
            continue
        dirs = []
        for k in range(1, len(r)):
            gi0, gi1 = r[k - 1], r[k]
            p0 = next((p["c"] for p in frames[gi0]["players"] if p["tid"] == tid), None)
            p1 = next((p["c"] for p in frames[gi1]["players"] if p["tid"] == tid), None)
            if p0 and p1:
                dirs.append(math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0])))
        med_dir = round(st.median(dirs), 1) if dirs else None
        peak = max((tid_spd[tid][gi] for gi in r if tid_spd[tid][gi] is not None), default=None)
        screen = None
        hc = next((p["c"] for p in frames[r[len(r) // 2]]["players"] if p["tid"] == tid), None)
        for gi in r:
            others = [p for p in frames[gi]["players"] if p["tid"] != tid]
            for p in others:
                if (tid_spd.get(p["tid"], [None] * n)[gi] or 1e9) > STATIONARY:
                    continue  # 屏幕人须近静止
                if hc is not None and math.hypot(p["c"][0] - hc[0], p["c"][1] - hc[1]) > D_HANDLER_SCREEN:
                    continue  # 屏幕人须贴近持球者驱动路径
                for q in others:
                    if q["tid"] == p["tid"]:
                        continue
                    if math.hypot(p["c"][0] - q["c"][0], p["c"][1] - q["c"][1]) <= D_SCREEN:
                        screen = (p["tid"], q["tid"])
                        break
                if screen:
                    break
            if screen:
                break
        ev = {"type": "DRIVE", "tid": tid, "start": r[0], "end": r[-1],
              "n": len(r), "med_dir_deg": med_dir, "peak_spd": round(peak, 1) if peak else None}
        if screen:
            ev["screen_setter"] = screen[0]
            ev["screen_defender"] = screen[1]
            ev["type"] = "PnR"
            pnr += 1
        events.append(ev)

    return {
        "clip": None, "fps": FPS, "n_frames": n,
        "n_raw_segments": len(segments),
        "n_smoothed_segments": len(sm_segs),
        "raw_holder_changes": raw_pass,
        "confirmed_passes": confirmed_pass,
        "n_drive": sum(1 for e in events if e["type"] == "DRIVE"),
        "n_drive_total": sum(1 for e in events if e["type"] in ("DRIVE", "PnR")),
        "n_pnr_exploratory": pnr,
        "events": events,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all-clips", action="store_true")
    a = ap.parse_args()
    clips = []
    if a.all_clips:
        clips = ["sas_hou", "sas_nop", "sas_det", "baseline_w1", "baseline_w2",
                 "baseline_w3", "baseline_w4"]
    elif a.clip:
        clips = [a.clip if a.clip.startswith("baseline_") else f"baseline_{a.clip}"]
    else:
        ap.error("需要 --clip 或 --all-clips")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for clip in clips:
        frames = load_clip(clip)
        segs = load_segments(clip)
        if frames is None or segs is None:
            print(f"[skip] {clip}: 缺 poss_tile ball_tracks/possession_segments")
            continue
        res = detect(frames, segs)
        res["clip"] = clip
        (OUT / f"{clip}_tactical_events.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1))
        rows.append(res)
        print(f"{clip:12s} raw_seg={res['n_raw_segments']:3d} sm_seg={res['n_smoothed_segments']:3d}  "
              f"raw_chg={res['raw_holder_changes']:3d} passes={res['confirmed_passes']:3d}  "
              f"drives={res['n_drive']:3d} pnr_exp={res['n_pnr_exploratory']}")
    if rows:
        (OUT / "tactical_events_rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"\n→ {len(rows)} 域战术事件已落盘 {OUT}")


if __name__ == "__main__":
    main()
