#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.13f 虚拟边线「判定翻转」诊断：把门1→v3 翻转的框逐条摊开，判断收紧对不对。

背景：v3(hough) 全段「救回 46 / 新增误杀 252」——但「误杀」这个词有歧义：
      **如果被收紧的框本来就是观众，那就是对的**。必须看位置分布才能定性。

做法：逐帧跑 门1(m) 与 v3(m2)，收集所有脚点判定发生翻转的框，记录：
      方向（tighten: 场内→场外 / loosen: 场外→场内）、脚点 (fx,fy)、框高、框宽。
      再按「观众 vs 球员」的可测量特征分档（脚点 y、框高、x 范围）。
用法: vbaseline_flip_diag.py --seg ep24_s1 [--fit hough]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
from court_filter import _foot, court_mask  # noqa: E402
from court_virtual_baseline2 import virtual_court  # noqa: E402


def q(v, p):
    return float(np.percentile(v, p)) if len(v) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--fit", default="hough")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    frames = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    cache = json.load(open(ROOT / "action_work" / f"_detcache_{a.seg}_1280.json"))
    print(f"=== 判定翻转诊断 {a.seg} fit={a.fit}（{len(frames)} 帧）===")

    flips = []
    pts_base, pts_v3 = [], []
    lines = []
    nfail = 0
    for i, fp in enumerate(frames):
        img = cv2.imread(str(fp))
        H, W = img.shape[:2]
        r = court_mask(img)
        if r is None or r[0] is None:
            nfail += 1
            continue
        m = r[0]
        m2, info = virtual_court(m, verbose=False, fit=a.fit, img=img)
        if not info.get("ok"):
            nfail += 1
            continue
        A, B = info["line"]
        lines.append((A, B))
        for (cls, cf, bb) in cache[i]:
            if cf < a.conf:
                continue
            fx, fy = _foot(bb)
            if not (0 <= fx < W and 0 <= fy < H):
                continue
            x1, y1, x2, y2 = [float(v) for v in bb]
            o1, o2 = m[fy, fx] > 0, m2[fy, fx] > 0
            pts_base.append((fx, fy))
            pts_v3.append((fx, fy, o2))
            if o1 == o2:
                continue
            flips.append({"idx": i, "dir": "tighten" if o1 else "loosen",
                          "foot": (int(fx), int(fy)), "h": round(y2 - y1, 1),
                          "w": round(x2 - x1, 1), "line_y": int(A * fx + B)})

    print(f"可用帧 {len(lines)}，失败 {nfail}")
    ti = [f for f in flips if f["dir"] == "tighten"]
    lo = [f for f in flips if f["dir"] == "loosen"]
    print(f"\n收紧（场内→场外）{len(ti)} 个   放松（场外→场内）{len(lo)} 个")

    def report(tag, arr):
        if not arr:
            print(f"  {tag}: 无")
            return
        ys = [f["foot"][1] for f in arr]
        hs = [f["h"] for f in arr]
        xs = [f["foot"][0] for f in arr]
        dy = [f["foot"][1] - f["line_y"] for f in arr]
        print(f"  {tag}: 脚点y p10/50/90 = {q(ys,.1):.0f}/{q(ys,.5):.0f}/{q(ys,.9):.0f} | "
              f"框高 p10/50/90 = {q(hs,.1):.0f}/{q(hs,.5):.0f}/{q(hs,.9):.0f} | "
              f"距虚拟边线(>0=线下方) p10/50/90 = {q(dy,.1):.0f}/{q(dy,.5):.0f}/{q(dy,.9):.0f}")
        near = sum(1 for d in dy if d <= 40)
        print(f"        其中 {near}/{len(arr)} ({100*near/len(arr):.0f}%) 在虚拟边线下方 ≤40px 内（=边界附近，最易错判）")
    report("收紧", ti)
    report("放松", lo)

    # 出散点图：脚点空间
    W, H = 1280, 720
    canvas = np.full((H, W, 3), 245, np.uint8)
    for (fx, fy, on) in pts_v3:
        cv2.circle(canvas, (int(fx), int(fy)), 1, (170, 170, 170), -1)
    for f in ti:
        cv2.circle(canvas, f["foot"], 4, (0, 0, 230), -1)
    for f in lo:
        cv2.circle(canvas, f["foot"], 4, (0, 170, 0), -1)
    if lines:
        A = float(np.median([l[0] for l in lines]))
        B = float(np.median([l[1] for l in lines]))
        cv2.line(canvas, (0, int(B)), (W - 1, int(A * (W - 1) + B)), (255, 0, 200), 2)
    cv2.putText(canvas, f"red=tighten({len(ti)}) green=loosen({len(lo)}) grey=unchanged",
                (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (30, 30, 30), 2)
    op = OUT / f"flipdiag_{a.seg}.png"
    cv2.imwrite(str(op), canvas)
    json.dump(flips, open(OUT / f"flips_{a.seg}.json", "w"), ensure_ascii=False)
    print(f"\n-> {op}")
    print(f"-> {OUT / f'flips_{a.seg}.json'}")


if __name__ == "__main__":
    main()
