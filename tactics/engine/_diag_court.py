#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：对某 clip 的若干候选帧各跑一次 court_fit 配准，报告 fit/n_vis/n_line，挑最佳。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file(""))); AW = ROOT/"action_work"
sys.path.insert(0, str(ROOT/"engine"))
import court_render as cr


def best_for(clip, fidxs):
    best = None
    for fi in fidxs:
        img = cr.frame_img(clip, fi)
        if not img.exists():
            print(f"  {clip} f{fi:05d} 缺帧"); continue
        p, det = cr.register_frame(img, seed=None, verbose=False)
        ok = det.get("ok", p is not None)
        fit = det.get("fit")
        print(f"  {clip} f{fi:05d}: fit={fit} n_vis={det.get('n_vis')} n_line={det.get('n_line')} ok={ok}")
        if p is not None and (best is None or (fit is not None and fit < best[2])):
            best = (fi, p, fit)
    if best:
        print(f"  >> 最佳 {clip}: f{best[0]:05d} fit={best[2]}")
        out = AW/"validate"/f"_{clip}_bestcam.json"
        out.write_text(json.dumps({"clip":clip,"frame":best[0],"p":[float(v) for v in best[1]],
                                    "fit":best[2]}, ensure_ascii=False, indent=1))
        print(f"  >> 存 {out}")
    else:
        print(f"  >> {clip}: 全部帧配准失败")

if __name__ == "__main__":
    clip = sys.argv[1]
    fidxs = [int(x) for x in sys.argv[2:]]
    best_for(clip, fidxs)
