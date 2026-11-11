#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
screen_specificity_vis.py — 把最严掩护判据(V5)的命中逐条摊开 + 视觉自证（A4.61）
=================================================================================
用法: python engine/screen_specificity_vis.py --segs ep24_s1,ep5_s0,ep16_s0
输出: 每个段 /tmp/sx_<seg>.png (命中帧拼图, 画掩护者=红框/通行者=绿框 + 位移标注)
      + stdout 逐条 (tids, 帧区间, 掩护者/通行者位移, 距离剖面min)
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

import cv2

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
from screen_specificity_probe import D_SCREEN_FRAC, _runs_for_pair, classify, features, load_seg  # noqa: E402


def analyze_seg(seg_dir: Path):
    raw = json.load(open(seg_dir / "ball_tracks.json", encoding="utf-8"))
    files = [fr.get("file") for fr in raw]
    frames, med_diag, med_disp = load_seg(seg_dir)
    d_screen = D_SCREEN_FRAC * med_diag
    tids = sorted({t for f in frames for t in f["players"]})
    hits = []
    for ia, a in enumerate(tids):
        for b in tids[ia + 1:]:
            for (i0, i1) in _runs_for_pair(frames, a, b, d_screen, 3):
                f = features(frames, a, b, i0, i1)
                if not f:
                    continue
                offx = []
                for i in range(i0, i1 + 1):
                    pa, pb = frames[i]["players"].get(a), frames[i]["players"].get(b)
                    if pa and pb:
                        offx.append(pb[0] - pa[0])
                f["_side_flip"] = (len(offx) >= 3 and offx[0] * offx[-1] < 0)
                cl = classify(f, med_diag, med_disp, d_screen)
                f["cl"] = cl
                if cl["V5"]:
                    hits.append(f)
    return frames, files, med_diag, med_disp, hits


def render(seg_dir, frames, files, hits, out_png, top=6):
    imgs = []
    picks = hits[:top]
    for f in picks:
        mid = (f["i0"] + f["i1"]) // 2
        fn = files[mid] if mid < len(files) else None
        if not fn:
            continue
        img = cv2.imread(str(seg_dir / "frames" / Path(fn).name))
        if img is None:
            img = cv2.imread(str(fn))
        if img is None:
            continue
        for tid, col in ((f["scr"], (0, 0, 255)), (f["trav"], (0, 200, 0))):
            bb = frames[mid]["bbox"].get(tid)
            if bb:
                cv2.rectangle(img, (int(bb[0]), int(bb[1])), (int(bb[2]), int(bb[3])), col, 3)
        lab = f'V5 scr={f["scr"]}(d{f["scr_disp"]:.0f}) trav={f["trav"]}(d{f["trav_disp"]:.0f}) f{f["i0"]}-{f["i1"]}'
        cv2.putText(img, lab, (15, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        h, w = img.shape[:2]
        img = cv2.resize(img, (w // 3, h // 3))
        imgs.append(img)
    if not imgs:
        return False
    while len(imgs) < 6:
        imgs.append(imgs[-1] * 0)
    sheet = cv2.vconcat([cv2.hconcat(imgs[:3]), cv2.hconcat(imgs[3:6])])
    cv2.imwrite(str(out_png), sheet)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(AW / "tactic_notes_batch_pilot_cf" / "segments"))
    ap.add_argument("--segs", required=True)
    a = ap.parse_args()
    base = Path(a.base)
    for s in [x.strip() for x in a.segs.split(",") if x.strip()]:
        sd = base / s
        if not (sd / "ball_tracks.json").exists():
            print(f"[skip] {sd} 无 ball_tracks.json")
            continue
        frames, files, med_diag, med_disp, hits = analyze_seg(sd)
        print(f"\n=== {s}  med_diag={med_diag:.0f} med_disp={med_disp:.2f}  V5命中={len(hits)} ===")
        for f in hits:
            print(f"  scr={f['scr']:>3} trav={f['trav']:>3} f{f['i0']}-{f['i1']}({f['dur']}帧) "
                  f"scr_disp={f['scr_disp']:.0f} trav_disp={f['trav_disp']:.0f} trav_net={tuple(round(v) for v in f['trav_net'])} "
                  f"dmin={f['dmin']:.0f} d0={f['d_first']:.0f} d1={f['d_last']:.0f} side_flip={f['_side_flip']}")
        if hits:
            png = Path("/tmp") / f"sx_{s}.png"
            ok = render(sd, frames, files, hits, png)
            print(f"  [自证图] {png if ok else '渲染失败'}")


if __name__ == "__main__":
    main()
