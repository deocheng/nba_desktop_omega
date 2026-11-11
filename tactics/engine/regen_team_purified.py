#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regen_team_purified.py —— 用 A4.62 候选池净化版 compute_team_of 重算所有 pilot 段的
ball_tracks_team.json(team=None 掉出配对池的 tid 被标记)。一次性重算脚本, 不重跑追踪。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
import assign_team as at
import court_filter as cf
import tactic_notes_totracks as tt


def regen(seg_dir: Path, use_cf: bool):
    tracks = seg_dir / "tracks_cf.json" if (use_cf and (seg_dir / "tracks_cf.json").exists()) \
        else seg_dir / "tracks.json"
    if not tracks.exists():
        print(f"  [跳过] {seg_dir.name}: 无 {tracks.name}")
        return
    if use_cf and not (seg_dir / "tracks_cf.json").exists():
        # 先跑球场掩膜剔观众(与 run_segment 一致)
        cf.filter_tracks_json(tracks, seg_dir / "frames",
                              seg_dir / "tracks_cf.json", 0.5)
        tracks = seg_dir / "tracks_cf.json"
    team_of, info = at.compute_team_of(seg_dir, tracks_name=tracks.name)
    out = seg_dir / "ball_tracks_team.json"
    tt.convert(tracks, seg_dir / "frames", out, team_of=team_of)
    # 落盘净化统计 + 队色心(供视觉自证/证据表, 不重跑追踪)
    (seg_dir / "team_assign_purified.json").write_text(
        json.dumps({"info": info}, ensure_ascii=False, indent=1), encoding="utf-8")
    p = info["purify"]
    print(f"  {seg_dir.name:12s} tracks={tracks.name} 净化 {p['n_purified']}/{p['n_tids_total']} "
          f"(med_diag={p['med_diag']}) 队色={info['center_names']} "
          f"→ {out.name}")


def main():
    # pilot_cf 段(已有 tracks_cf.json)
    base1 = AW / "tactic_notes_batch_pilot_cf" / "segments"
    # batch 段(只有 tracks.json, 需先 court_filter)
    base2 = AW / "tactic_notes_batch" / "segments"
    print(f"[regen] pilot_cf @ {base1}")
    for sd in sorted(base1.glob("ep*_s*")):
        regen(sd, use_cf=True)
    print(f"[regen] batch @ {base2}")
    for sd in sorted(base2.glob("ep*_s*")):
        regen(sd, use_cf=True)


if __name__ == "__main__":
    main()
