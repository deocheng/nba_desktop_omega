#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sas_det 新旧 head 门禁对比（只读）：同一候选云、同一 track_ball 跟踪、同一 trackable 门禁，
唯一变量 = 打分头（旧 v2 head[废bank训练] vs 新 sas head[AI自标训练]）。

⚠️ 新头标签为 AI 自标（≤74% 可靠性）→ 结果仅探索，不作结论。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
import track_ball as tb  # noqa: E402

MIN_TRK = 3
THS = (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8)

ap = argparse.ArgumentParser()
ap.add_argument("--old", default=str(AW / "validate" / "sas_det_scores.json"))
ap.add_argument("--new", default=str(AW / "validate" / "ball_cand_scores_sas.json"))
ap.add_argument("--new-name", default="NEW sas-head(AI-self)")
args = ap.parse_args()


def gate(scores, n):
    rows = []
    for th in THS:
        tracks = tb.track_clip(scores, th, birth=th, gap=8)
        m = tb.track_metrics(tracks, n, MIN_TRK)
        cov = m["frame_coverage"] * 100
        trk = m["trackable_frac"]
        ok = trk is not None and trk >= 0.80
        rows.append((th, cov, trk, ok, m["n_tracks"]))
    return rows


for name, path in (("OLD v2-head(void bank)", Path(args.old)),
                   (args.new_name, Path(args.new))):
    d = json.loads(Path(path).read_text())
    fr = d["sas_det"] if "sas_det" in d else d
    n = len(fr)
    print(f"\n=== {name}  (n_frames={n}) ===")
    best = None
    for th, cov, trk, ok, nt in gate(fr, n):
        mark = "PASS" if ok else "FAIL"
        print(f" th={th:.2f}: cov={cov:5.1f}% track={trk if trk is not None else float('nan'):.3f} "
              f"{mark} n_trk={nt}")
        if ok and (best is None or cov > best[1]):
            best = (th, cov, trk)
    if best:
        print(f" → 最佳可用工作点: th={best[0]:.2f} cov={best[1]:.1f}% track={best[2]:.3f} PASS")
    else:
        print(" → 无任何 th 通过 trackable≥0.80 门禁")
