#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coverage evaluation for the 347-sample joint head (manual347).

Compares the new head's sas_lal / sas_det coverage against the A4.33 joint baseline.

Honesty rules (avoid leakage inflation):
  - training sas_lal frames = (human bank frames) U (manual-injected frames)
  - "honest unlabeled" = 400 frames minus training frames  -> pure generalization
  - also report A4.33-compatible "320 unlabeled" = 400 - human bank frames
    (this set CONTAINS the 80 manual frames, so its lift is partly in-sample)
  - separately report how many of the 80 manual-injected frames are now covered
    (in-sample evidence the補标 taught the head).
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import sys

from common.nba_paths import tactics_data_file

ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="manual347",
                help="scores prefix tag, e.g. manual347 / final351")
ap.add_argument("--drop", default="f00012.jpg,f00022.jpg,f00221.jpg,f00222.jpg,f00300.jpg,f00364.jpg",
                help="comma-separated manual frames NOT used as TPs in this training")
A = ap.parse_args()
TAG = A.tag
DROPPED = set(x for x in A.drop.split(",") if x)
print(f"[eval] tag={TAG}  dropped_manual_frames={sorted(DROPPED)}")

VAL = "action_work/validate"
AW = str(tactics_data_file("action_work"))

def load(p): return json.load(open(p))

human_bank = load(os.path.join(VAL, "sas_lal_label_bank_human.json"))["labels"]
human_frames = {L["frame"] for L in human_bank}

manual_bank = load(os.path.join(VAL, "sas_lal_label_bank_manual.json"))["labels"]
manual_frames_all = {L["frame"] for L in manual_bank if L.get("source") == "manual"}
manual_kept = manual_frames_all - DROPPED   # frames used as manual TPs

all_frames = [f"f{j:05d}.jpg" for j in range(1, 401)]

def coverage(scores_clip, frames, th):
    """fraction of `frames` whose max candidate prob > th."""
    cov = 0
    for fr in frames:
        row = scores_clip.get(fr, [])
        if not row:
            continue
        mp = max(c["prob"] for c in row)
        if mp > th:
            cov += 1
    return cov, len(frames)

# load new scores
new_lal = load(os.path.join(VAL, f"ball_cand_scores_{TAG}_sas_lal_joint.json"))["sas_lal"]
new_det = load(os.path.join(VAL, f"ball_cand_scores_{TAG}_sas_det_joint.json"))["sas_det"]

# frame sets
honest_unlabeled = [f for f in all_frames if f not in human_frames and f not in manual_kept]
unlabeled320 = [f for f in all_frames if f not in human_frames]
manual_frames_list = [f for f in all_frames if f in manual_kept]

print("=" * 60)
print("FRAME SET SIZES")
print(f"  human bank frames      : {len(human_frames)}")
print(f"  manual kept (TP) frames: {len(manual_kept)}")
print(f"  overlap (manual&human) : {len(manual_kept & human_frames)}")
print(f"  honest unlabeled (400 - both): {len(honest_unlabeled)}")
print(f"  A4.33 320 unlabeled (400 - human): {len(unlabeled320)}")
print(f"  manual-injected frames  : {len(manual_frames_list)}")
print("=" * 60)

print("\nsas_lal COVERAGE (new head)")
for th in (0.3, 0.8):
    c, n = coverage(new_lal, honest_unlabeled, th)
    c320, n320 = coverage(new_lal, unlabeled320, th)
    cm, nm = coverage(new_lal, manual_frames_list, th)
    print(f"  @th={th}:")
    print(f"    honest unlabeled {c}/{n} = {100*c/n:.1f}%  (pure generalization)")
    print(f"    A4.33 320-set   {c320}/{n320} = {100*c320/n320:.1f}%")
    print(f"    manual-injected {cm}/{nm} = {100*cm/nm:.1f}%  (in-sample: 补标是否学会)")

print("\nsas_det COVERAGE (zero-regression check)")
for th in (0.3, 0.8):
    c, n = coverage(new_det, list(new_det.keys()), th)
    print(f"  @th={th}: {c}/{n} = {100*c/n:.1f}%")

print("\nBASELINE (A4.33 joint head, for reference):")
print("  sas_lal 320 unlabeled @0.3 = 53.8% (+16.6pp vs 37.2%)")
print("  sas_det zero-regression @0.3 = 53.0->51.7 ; @0.8 = 42.2->45.2")

# also report sas_det coverage on its OWN unlabeled (400 - sas_det human bank) for symmetry
det_human = load(os.path.join(VAL, "sas_det_label_bank_human.json"))["labels"]
det_human_frames = {L["frame"] for L in det_human}
det_unlabeled = [f for f in new_det.keys() if f not in det_human_frames]
for th in (0.3, 0.8):
    c, n = coverage(new_det, det_unlabeled, th)
    print(f"  sas_det honest unlabeled @th={th}: {c}/{n} = {100*c/n:.1f}%")
