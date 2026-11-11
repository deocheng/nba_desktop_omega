#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.9e 跨段 Top-K 目视裁定图：6 段 × 2 帧，每帧画「Top13(绿) vs 丢弃(红)」。

只算 2 帧/段（读 frames[idx] 与 frames[idx-1] 求帧差），快。
拼成一张大 contact sheet，供老程一眼裁定「Top13 挑的是不是场上那 13 个人」。

用法: topk_crossseg_contact.py --segs a,b,c [--k 13]
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
OUT = ROOT / "action_work" / "track_judge" / "topk"
TH, FRAC, CW = 12, 0.6, 620


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


def draw_seg(seg, k, picks_frac=(0.35, 0.72)):
    d = SEGD / seg
    tp = d / "tracks.json"
    files = sorted((d / "frames").glob("f*.jpg"))
    if not tp.exists() or not files:
        return None
    tr = json.load(open(tp))
    byidx = {fr["idx"]: fr for fr in tr["frames"]}
    outs = []
    for pf in picks_frac:
        idx = int(len(files) * pf)
        if idx < 1 or idx not in byidx:
            continue
        g, pg = gray(files[idx]), gray(files[idx - 1])
        if g is None or pg is None:
            continue
        da = cv2.absdiff(g, pg)
        items = [{"m": motion(da, p["box"], FRAC), "box": p["box"]}
                 for p in byidx[idx].get("players", [])]
        if not items:
            continue
        items.sort(key=lambda x: -x["m"])
        sel = {tuple(np.round(i["box"], 3)) for i in items[:k]}
        img = cv2.imread(str(files[idx]))
        for it in items:
            x1, y1, x2, y2 = [int(v) for v in it["box"]]
            on = tuple(np.round(it["box"], 3)) in sel
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 0) if on else (0, 0, 220), 3 if on else 1)
            if on:
                cv2.putText(img, f"{it['m']:.2f}", (x1, max(14, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 0), 1)
        cv2.putText(img, f"{seg} f{idx}  ALL={len(items)}  green=Top{k}  red=dropped",
                    (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
        cv2.putText(img, f"{seg} f{idx}  ALL={len(items)}  green=Top{k}  red=dropped",
                    (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (60, 240, 255), 2)
        h = int(CW * img.shape[0] / img.shape[1])
        small = cv2.resize(img, (CW, h), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(OUT / f"cross_{seg}_f{idx}.png"), img)
        outs.append(small)
    return outs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segs", default="ep24_s1,ep1_s0,ep10_s0,ep12_s0,ep5_s1,ep19_s0")
    ap.add_argument("--k", type=int, default=13)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    rows = []
    for seg in a.segs.split(","):
        seg = seg.strip()
        r = draw_seg(seg, a.k)
        if not r:
            print(f"{seg}: 跳过")
            continue
        if len(r) == 1:
            r = r + [np.full_like(r[0], 30)]
        lab = np.full((r[0].shape[0], 6, 3), 255, np.uint8)
        rows.append(np.hstack([r[0], lab, r[1]]))
        print(f"{seg}: 已出图")
    if not rows:
        return
    w = min(x.shape[1] for x in rows)
    rows = [x[:, :w] for x in rows]
    sep = np.full((8, w, 3), 255, np.uint8)
    sheet = rows[0]
    for x in rows[1:]:
        sheet = np.vstack([sheet, sep, x])
    op = OUT / "crossseg_topk_contact.png"
    cv2.imwrite(str(op), sheet)
    print("->", op)


if __name__ == "__main__":
    main()
