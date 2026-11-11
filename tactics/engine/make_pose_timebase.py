#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_pose_timebase.py — 为 sas_* 生成 tactical_movement 所需的最小 pose_motion.json（**仅时间基准**）。

诚实声明（务必保留）
--------------------
w1–w4 的 `pose_motion.json` 由真实姿态流水线产出，含 `max_air`/`n_tracks`/jumps/contests 等测量。
本脚本**不**为 sas_* 伪造这些测量值 —— 只生成 `series[*].t`（时间基准）与空 `events`，
因为 `tactical_movement.load_window()` 实际只消费这两项（见其源码：t0/t1/dt 与 evs）。

时间基准来源 = 已知抽取参数（**元数据，非测量**）：
    片段由源录像 `-ss 60 -t 40 fps=10` 抽取 ⇒ 400 帧覆盖 40s ⇒ dt = 0.1s，
    故第 i 帧（0-based）t = i × 0.1（相对片段起点的秒数）。
    ⚠️ 未做比赛时钟(clock)对齐 ⇒ t 是片段相对时间，不是比赛计时；events 留空。

用法
----
  python engine/make_pose_timebase.py --clip sas_hou
  python engine/make_pose_timebase.py --all
输出
----
  action_work/<clip>/pose_motion.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"

# 已知抽取参数（见 validate3 记录：-ss 60 -t 40 fps=10）
N_FRAMES = 400
FPS = 10.0
SRC_OFFSET_S = 60.0     # -ss 60：片段在源录像中的起始秒（仅记录，不参与相对 t）


def build(clip: str):
    n = N_FRAMES
    dt = 1.0 / FPS
    series = [{"t": round(i * dt, 3)} for i in range(n)]
    return {
        "_about": (
            "TIME-BASE ONLY STUB —— 仅含 series[*].t（相对片段起点的秒数），"
            "**不含**任何姿态测量（无 max_air / n_tracks / jumps / contests）。"
            f"t 由已知抽取参数 `-ss {SRC_OFFSET_S:g} -t 40 fps={FPS:g}` 推导：{n} 帧 / {n/FPS:g}s ⇒ dt={dt}s。"
            "未做比赛时钟对齐 ⇒ t 不是比赛计时；events 为空（未做 PBP 对齐）。"
            "生成脚本：engine/make_pose_timebase.py"
        ),
        "series": series,
        "params": {"n_frames": n, "fps": FPS, "dt": dt,
                   "src_offset_s": SRC_OFFSET_S, "clock_aligned": False},
        "events": [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    clips = (["sas_hou", "sas_nop", "sas_det"] if a.all
             else ([a.clip] if a.clip else []))
    if not clips:
        ap.error("需要 --clip 或 --all")
    for c in clips:
        d = build(c)
        out = AW / c / "pose_motion.json"
        out.write_text(json.dumps(d, indent=1, ensure_ascii=False))
        print(f"{c}: series={len(d['series'])}  t 0..{d['series'][-1]['t']}s  dt={d['params']['dt']}s "
              f"events={len(d['events'])} → {out}")


if __name__ == "__main__":
    main()
