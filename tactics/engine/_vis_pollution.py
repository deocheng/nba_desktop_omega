#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_vis_pollution.py — 污染过滤的目视验收图（保留=绿 / 剔除=红）。

验收口径（为什么必须有这一步）
------------------------------
过滤器只报"剔除 N 个"是自说自话；必须把**剔除物**与**保留物**同时摆出来看。
本脚本对指定 clip 的指定帧渲染全分辨率大图：
  绿框 = 保留（带 track_id 与 h）
  红框 = 剔除（带规则名）
  青框 = 持球者（A4 保护）
  橙框 = 球
用法
    python engine/_vis_pollution.py --clip w1 --frames 1,120,300,421
    python engine/_vis_pollution.py --clip sas_hou --frames 1,180,361
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
AW = ROOT / "action_work"
OUT = AW / "validate" / "pollution"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(AW / "validate" / "player_pollution.json"))
    ap.add_argument("--clip", required=True)
    ap.add_argument("--frames", default="1,120,300")
    ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args()
    d = json.loads(Path(a.src).read_text())[a.clip]
    want = {f"f{int(x):05d}.jpg" for x in a.frames.split(",")}
    for fn in sorted(want):
        rows = [r for r in d["rows"] if r["file"] == fn]
        if not rows:
            print(f"[skip] {fn} 无记录")
            continue
        img = cv2.imread(str(AW / a.clip / fn))
        if img is None:
            print(f"[skip] {fn} 图不存在")
            continue
        H, W = img.shape[:2]
        for r in rows:
            x1, y1, x2, y2 = [int(v) for v in r["bbox"]]
            if r["is_poss"]:
                col, t = (255, 255, 0), f"POSS t{r['track_id']} h={int(r['h'])}"
            elif r["keep"]:
                col, t = (0, 220, 0), f"t{r['track_id']} h={int(r['h'])}"
            else:
                col, t = (0, 0, 255), f"{r['reason']} h={int(r['h'])}"
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 3)
            cv2.putText(img, t, (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                        (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(img, t, (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                        col, 2, cv2.LINE_AA)
        nb = len(rows)
        nk = sum(r["keep"] for r in rows)
        cv2.putText(img, f"{a.clip} {fn}  {nb} -> {nk}   绿=保留 红=剔除 青=持球者",
                    (16, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.05, (0, 0, 0), 7, cv2.LINE_AA)
        cv2.putText(img, f"{a.clip} {fn}  {nb} -> {nk}   绿=保留 红=剔除 青=持球者",
                    (16, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.05, (255, 255, 255), 3, cv2.LINE_AA)
        if a.scale != 1.0:
            img = cv2.resize(img, (int(W * a.scale), int(H * a.scale)), interpolation=cv2.INTER_AREA)
        o = OUT / f"vis_{a.clip}_{Path(fn).stem}.jpg"
        cv2.imwrite(str(o), img, [cv2.IMWRITE_JPEG_QUALITY, 93])
        print(f"[out] {o}  {nb} -> {nk}")


if __name__ == "__main__":
    main()
