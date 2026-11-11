#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.12c-2 号码线索的**正确用法**：不逐帧判，而是像 assign_team.py 那样**per-track 多数票**。

理由（对照已有成功经验）：assign_team.py 用「逐帧躯干中位色 + per-track 多数票」做到
ID 碎片免疫；号码同理 —— 单帧号码区只有 40–80px，OCR 必然差，但一条轨迹几十帧里
总有几帧号码清晰 ⇒ 投票聚合。

用法: jersey_track_vote.py --seg ep24_s1 [--tids 147,145,142,130,151,10,6] [--per 25]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import collections
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
TESS = "/opt/homebrew/bin/tesseract"

LABEL = {147: "观众#3", 145: "观众#8", 142: "观众#9", 130: "观众#13",
         151: "球员#5", 10: "球员#6", 6: "球员#7", 7: "★球员#22(被丢)",
         155: "球员#2", 153: "球员#10"}


def ocr(grey, psm):
    best = ""
    for inv in (False, True):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            p = f.name
        cv2.imwrite(p, cv2.bitwise_not(grey) if inv else grey)
        try:
            r = subprocess.run([TESS, p, "stdout", "--psm", str(psm), "-l", "eng",
                                "-c", "tessedit_char_whitelist=0123456789"],
                               capture_output=True, text=True, timeout=15)
            t = "".join(c for c in r.stdout if c.isdigit())
            if len(t) > len(best):
                best = t
        except Exception:
            pass
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--tids", default="147,145,142,130,151,10,6,7,155,153")
    ap.add_argument("--per", type=int, default=25)
    a = ap.parse_args()

    d = SEGD / a.seg
    files = sorted((d / "frames").glob("f*.jpg"))
    tr = json.load(open(d / "tracks.json"))
    # tid -> [(frame_idx, box)]
    seq = collections.defaultdict(list)
    for fr in tr["frames"]:
        for p in fr.get("players", []):
            seq[int(p["id"])].append((fr["idx"], p["box"]))
    cache = {}

    def load(i):
        if i not in cache:
            cache[i] = cv2.imread(str(files[i]))
        return cache[i]

    print(f"=== {a.seg}  号码 per-track 多数票 ===")
    print(f"{'tid':>6}{'标签':>14}{'帧数':>6}{'采样':>6}{'出号帧':>7}{'票王':>8}")
    for ts in a.tids.split(","):
        tid = int(ts)
        rows = seq.get(tid, [])
        if not rows:
            print(f"{tid:>6}{'—':>14}{0:>6}")
            continue
        step = max(1, len(rows) // a.per)
        picks = rows[::step][:a.per]
        votes = collections.Counter()
        n_hit = 0
        for idx, box in picks:
            im = load(idx)
            if im is None:
                continue
            x1, y1, x2, y2 = [int(v) for v in box]
            w, h = x2 - x1, y2 - y1
            # 号码区放宽到上半身，并随框变小而放大更多
            a1 = max(0, int(x1 + 0.15 * w)); a2 = min(im.shape[1], int(x1 + 0.85 * w))
            b1 = max(0, int(y1 + 0.12 * h)); b2 = min(im.shape[0], int(y1 + 0.60 * h))
            roi = im[b1:b2, a1:a2]
            if roi.size == 0:
                continue
            g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            mag = max(3.0, 320.0 / max(1, roi.shape[0]))
            big = cv2.resize(g, None, fx=mag, fy=mag, interpolation=cv2.INTER_CUBIC)
            eq = cv2.createCLAHE(clipLimit=2.6, tileGridSize=(8, 8)).apply(big)
            t = ""
            for psm in (7, 8, 10):
                got = ocr(eq, psm)
                if len(got) > len(t):
                    t = got
            if t:
                n_hit += 1
                votes[t] += 1
        top = votes.most_common(1)[0] if votes else ("—", 0)
        print(f"{tid:>6}{LABEL.get(tid, ''):>14}{len(rows):>6}{len(picks):>6}"
              f"{n_hit:>7}{top[0]:>8}({top[1]})")


if __name__ == "__main__":
    main()
