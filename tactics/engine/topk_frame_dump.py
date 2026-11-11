#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.11 逐框编号裁定表：把某一帧的全部检测框**编号**列出 + 出带编号的大图。

背景：老程目视裁定用的是图上标的运动量数值(如"0.65 是观众")，需要能精确定位到框、
知道它在 Top-K 里是留(绿)还是丢(红)、以及它在画面哪个位置。

用法: topk_frame_dump.py --seg ep24_s1 --idx 70 [--k 13]
产物: track_judge/num/<seg>_f<idx>_num.png  + JSON（含每框编号/m/坐标/是否 TopK）
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
TH, FRAC = 12, 0.6


def gray(f):
    im = cv2.imread(str(f))
    return None if im is None else cv2.GaussianBlur(
        cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (5, 5), 0)


def motion(da, box, frac):
    H, W = da.shape
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    a1 = max(0, int(cx - w * frac / 2)); a2 = min(W, int(cx + w * frac / 2))
    b1 = max(0, int(cy - h * frac / 2)); b2 = min(H, int(cy + h * frac / 2))
    if a2 - a1 < 3 or b2 - b1 < 3:
        return 0.0
    return float((da[b1:b2, a1:a2] > TH).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", required=True)
    ap.add_argument("--idx", type=int, required=True)
    ap.add_argument("--k", type=int, default=13)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    d = SEGD / a.seg
    files = sorted((d / "frames").glob("f*.jpg"))
    tr = json.load(open(d / "tracks.json"))
    fr = next((f for f in tr["frames"] if f["idx"] == a.idx), None)
    if fr is None:
        print(f"{a.seg} 无 f{a.idx}"); return

    g, pg = gray(files[a.idx]), gray(files[a.idx - 1])
    da = cv2.absdiff(g, pg)
    items = [{"tid": int(p["id"]), "box": p["box"], "m": motion(da, p["box"], FRAC)}
             for p in fr.get("players", [])]
    items.sort(key=lambda x: -x["m"])
    for i, it in enumerate(items):
        it["no"] = i + 1
        it["topk"] = i < a.k
        x1, y1, x2, y2 = [int(v) for v in it["box"]]
        it["w"], it["h"] = x2 - x1, y2 - y1
        it["cx"], it["foot_y"] = (x1 + x2) / 2, y2

    img = cv2.imread(str(files[a.idx]))
    for it in items:
        x1, y1, x2, y2 = [int(v) for v in it["box"]]
        on = it["topk"]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 210, 0) if on else (0, 0, 225), 3 if on else 2)
        txt = f"#{it['no']} {it['m']:.2f}"
        cv2.putText(img, txt, (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 4)
        cv2.putText(img, txt, (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 200, 0) if on else (0, 0, 220), 2)
    cv2.putText(img, f"{a.seg} f{a.idx}  green=Top{a.k}  red=dropped  ALL={len(items)}",
                (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
    cv2.putText(img, f"{a.seg} f{a.idx}  green=Top{a.k}  red=dropped  ALL={len(items)}",
                (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 240, 255), 2)
    op = OUT / f"{a.seg}_f{a.idx}_num.png"
    cv2.imwrite(str(op), img)

    print(f"{a.seg} f{a.idx}  共 {len(items)} 检测  T=Top{a.k}(留)  D=丢弃(红)")
    print(f"{'#':>3}{'留/丢':>5}{'运动量':>7}{'tid':>6}{'框W':>6}{'框H':>6}{'中心x':>7}{'脚y':>7}")
    for it in items:
        flag = "T" if it["topk"] else "D"
        print(f"{it['no']:>3}{flag:>5}{it['m']:>7.2f}{it['tid']:>6}{it['w']:>6}{it['h']:>6}"
              f"{it['cx']:>7.0f}{it['foot_y']:>7.0f}")
    jp = OUT / f"{a.seg}_f{a.idx}.json"
    json.dump(items, open(jp, "w"), ensure_ascii=False, indent=1)
    print(f"\n-> {op}\n-> {jp}")


if __name__ == "__main__":
    main()
