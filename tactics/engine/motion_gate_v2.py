#!/usr/bin/env python3
"""A5.8f 老程「移动距离」判据的最终形态：**按帧判 + 基线门**。

判据（逐帧、逐检测框）：
  1. 算全帧帧差占比 base；若 base > BASE_MAX ⇒ 该帧画面整体剧变(切镜/快切) ⇒ **判据弃用**（不判，不删）
  2. 否则算框内差值 diff = 框内占比 − base；diff > DIFF_MIN ⇒ **该框在动 ⇒ 保留进跟踪**
  3. 其余（静止框：观众/替补席/教练）⇒ **不进跟踪**

检验：
  - 老程裁定的 ep24_s1 8 条（按「老程标注的具体帧」逐帧验，不再按整条中位数）
  - ep1_s0#116 老程精确分组（126=球员 / 141-194=观众A / 207,220=邻座B）
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
TH = 12
SHRINK = 0.12
BASE_MAX = 9.99      # 关闭弃用门
RATIO_MIN = 3.0      # 框内/全帧基线 的比值门

# 老程标注的具体帧 → 期望(动=场上有价值 / 静=无价值)
LABELED = {
    ("ep24_s1", 269, "tracks.json"): {116: "动", 118: "动", 119: "动", 121: "动",
                                       122: "动", 128: "动"},   # 球员, f116 转场存疑
    ("ep24_s1", 309, "tracks.json"): {148: "静", 149: "静", 150: "静", 152: "静",
                                       153: "静", 154: "静"},   # 教练
    ("ep24_s1", 21, "tracks.json"): {5: "静", 10: "静", 16: "静", 21: "静", 26: "静"},
    ("ep24_s1", 246, "tracks.json"): {104: "静", 113: "静", 122: "静", 132: "静",
                                       141: "静", 150: "静"},
    ("ep24_s1", 336, "tracks.json"): {160: "静", 165: "静", 167: "静", 171: "静",
                                       173: "静", 177: "静"},
    ("ep24_s1", 190, "tracks.json"): {103: "静", 111: "静", 135: "动"},
    ("ep24_s1", 88, "tracks_b.json"): {52: "静", 55: "静", 58: "静", 61: "静",
                                        64: "动", 68: "静"},
    ("ep24_s1", 116, "tracks_b.json"): {99: "静", 112: "静", 123: "静", 161: "静",
                                         181: "静", 193: "静"},
    ("ep1_s0", 116, "tracks.json"): {126: "动", 141: "静", 154: "静", 167: "静",
                                      181: "静", 194: "静", 207: "静", 220: "静"},
}


def load_gray(files, i):
    img = cv2.imread(str(files[i]))
    if img is None:
        return None
    return cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)


def main():
    tp = fp = tn = fn = skip = 0
    print(f"{'seg#tid':<20}{'帧':>5}{'框内':>8}{'基线':>8}{'差值':>8}  {'期望':<5}{'判':<6}{'':<4}")
    for (seg, tid, src), want in LABELED.items():
        d = SEGD / seg
        tr = json.load(open(d / src))
        files = sorted((d / "frames").glob("f*.jpg"))
        for fr in tr["frames"]:
            idx = fr["idx"]
            if idx not in want or idx == 0 or idx >= len(files):
                continue
            hits = [p for p in fr.get("players", []) if p["id"] == tid]
            if not hits:
                continue
            g, pg = load_gray(files, idx), load_gray(files, idx - 1)
            if g is None or pg is None:
                continue
            da = cv2.absdiff(g, pg)
            base = float((da > TH).mean())
            for p in hits:
                x1, y1, x2, y2 = [int(v) for v in p["box"]]
                dx = int((x2 - x1) * SHRINK); dy = int((y2 - y1) * SHRINK)
                x1, y1 = max(0, x1 + dx), max(0, y1 + dy)
                x2, y2 = min(g.shape[1], x2 - dx), min(g.shape[0], y2 - dy)
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                r = float((da[y1:y2, x1:x2] > TH).mean())
                diff = r - base
                exp = want[idx]
                ratio = r / base if base > 1e-6 else (99.0 if r > 0.02 else 1.0)
                if False:
                    verdict, mark = "弃用", "skip"
                    skip += 1
                else:
                    pred = "动" if ratio > RATIO_MIN else "静"
                    verdict = pred
                    if exp == "动" and pred == "动":
                        tp += 1; mark = "TP"
                    elif exp == "静" and pred == "静":
                        tn += 1; mark = "TN"
                    elif exp == "动" and pred == "静":
                        fn += 1; mark = "FN❌"
                    else:
                        fp += 1; mark = "FP❌"
                print(f"{seg}#{tid:<8}{idx:>5}{r:>8.3f}{base:>8.3f}{ratio:>8.2f}  "
                      f"{exp:<5}{verdict:<6}{mark}")
    n = tp + tn + fn + fp
    print(f"\n可判帧 {n}（弃用 {skip}）+  命中 {tp+tn}/{n} = {(tp+tn)/n:.1%}")
    print(f"  TP(判动且该动)={tp}  TN(判静且该静)={tn}  FP(误判动)={fp}  FN(误判静)={fn}")
    if tp + fp:
        print(f"  判「动」的精确率 {tp}/{tp+fp} = {tp/(tp+fp):.1%}")
    if tp + fn:
        print(f"  场上目标的召回 {tp}/{tp+fn} = {tp/(tp+fn):.1%}")


if __name__ == "__main__":
    main()
