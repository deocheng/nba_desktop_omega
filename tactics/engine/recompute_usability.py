#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recompute_usability.py — 从已生成的 <clip>_scores.json 重算任务级事件可用性（修复 int/str 键 bug）。

用法:
  python engine/recompute_usability.py --clips sas_hou sas_nop sas_det
  python engine/recompute_usability.py --all
产出: action_work/validate/<clip>_usability.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
from pathlib import Path

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
TH = 0.975
GAP_TOL = 3
SMOOTH_PX = 80.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", nargs="+", default=None)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    clips = a.clips or []
    if a.all or not clips:
        clips = [p.name[:-12] for p in sorted(AW.glob("validate/*_scores.json"))]

    for clip in clips:
        sp = AW / "validate" / f"{clip}_scores.json"
        if not sp.exists():
            print(f"[skip] {clip}: 无 {sp.name}")
            continue
        scores = json.loads(sp.read_text())
        inner = scores.get(clip, {})
        frames = sorted(inner.keys())
        present_int = {}
        for fn, cs in inner.items():
            hs = [c for c in cs if c["prob"] > TH]
            if not hs:
                continue
            best = max(hs, key=lambda c: c["prob"])
            num = int(fn[1:6])
            present_int[num] = ((best["bbox"][0]+best["bbox"][2])/2,
                                (best["bbox"][1]+best["bbox"][3])/2)
        nums = sorted(present_int.keys())
        cov = len(present_int)/len(frames) if frames else 0.0
        eps, cur, last = [], [], None
        for num in nums:
            if last is not None and num-last > GAP_TOL+1 and cur:
                eps.append(cur); cur = []
            cur.append(num); last = num
        if cur:
            eps.append(cur)
        ep_lens = [len(e) for e in eps]
        steps = []
        for e in eps:
            for x, y in zip(e, e[1:]):
                if x in present_int and y in present_int:
                    steps.append(math.hypot(present_int[y][0]-present_int[x][0],
                                            present_int[y][1]-present_int[x][1]))
        med = sorted(steps)[len(steps)//2] if steps else 0.0
        track = sum(1 for d in steps if d < SMOOTH_PX)/len(steps) if steps else 0.0
        usab = {"clip": clip, "th": TH, "n_frames": len(frames),
                "frame_coverage": round(cov, 4), "n_episodes": len(eps),
                "mean_episode_len": round(sum(ep_lens)/len(ep_lens), 2) if ep_lens else 0.0,
                "median_step_px": round(med, 1), "trackable_frac": round(track, 4),
                "n_claim_frames": len(present_int)}
        (AW / "validate" / f"{clip}_usability.json").write_text(
            json.dumps(usab, ensure_ascii=False, indent=1))
        print(f"[{clip}] 覆盖 {cov*100:.1f}%  片段 {len(eps)}  均长 {usab['mean_episode_len']}  "
              f"中位步长 {med:.0f}px  可跟踪 {track*100:.1f}%  → {clip}_usability.json")


if __name__ == "__main__":
    main()
