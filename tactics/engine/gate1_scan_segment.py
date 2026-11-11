#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.13b 全段门1 扫描：找「被门1 误判到场外的真球员」= 虚拟边线真正的用武之地。

老程：「画面的下一方，球场的一条边线，被观众挡住了，你应该加一条虚拟边线」
      + 「首先，场内的，场外的这能直接过滤很多干扰」

问题：f70 单帧加虚拟边线**救回 0 个框** —— 可能只是这帧本来就没问题。
      要证明这条线到底有没有用，得**全段扫**：逐帧跑门1，看有没有帧
      「场外框里有 大框 + 高运动 的球员特征」= 被误杀。

做法：复用 `_detcache_<seg>_1280.json`（逐帧检测），逐帧 court_mask，
      对每个框取脚点判在场/场外；再按相邻帧差算**框内运动量**。
用法: gate1_scan_segment.py --seg ep24_s1 [--k 13]
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

TH = 25.0  # 框内灰度差阈值


def frame_motion(prev_g, cur_g, box, frac=0.7):
    """框内(收缩 frac)灰度差 > TH 的像素占比。"""
    x1, y1, x2, y2 = box
    W = cur_g.shape[1]
    H = cur_g.shape[0]
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    w, h = x2 - x1, y2 - y1
    a1 = max(0, int(cx - w * frac / 2)); a2 = min(W, int(cx + w * frac / 2))
    b1 = max(0, int(cy - h * frac / 2)); b2 = min(H, int(cy + h * frac / 2))
    if a2 <= a1 or b2 <= b1:
        return 0.0
    d = cv2.absdiff(prev_g[b1:b2, a1:a2], cur_g[b1:b2, a1:a2])
    return float((d > TH).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--k", type=int, default=13, help="期望的场上人数（11 场上 + 2 场边）")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    d = SEGD / a.seg
    frames = sorted((d / "frames").glob("f*.jpg"))
    cache = json.load(open(ROOT / "action_work" / f"_detcache_{a.seg}_1280.json"))
    print(f"=== 门1 全段扫描 {a.seg}（{len(frames)} 帧）===")

    rows = []
    prev_g = None
    n_mask_fail = 0
    for i, fp in enumerate(frames):
        img = cv2.imread(str(fp))
        H, W = img.shape[:2]
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        r = court_mask(img)
        if r is None or r[0] is None:
            n_mask_fail += 1
            m = None
        else:
            m = r[0]
        dets = [bb for (cls, cf, bb) in cache[i] if cf >= a.conf]
        n_in = 0
        outs = []
        for bb in dets:
            x1, y1, x2, y2 = [float(v) for v in bb]
            h = y2 - y1
            mv = frame_motion(prev_g, g, bb) if prev_g is not None else 0.0
            fx, fy = _foot(bb)
            onc = bool(m is not None and 0 <= fx < W and 0 <= fy < H and m[fy, fx] > 0)
            if onc:
                n_in += 1
            else:
                outs.append({"box": [round(v, 1) for v in bb], "h": round(h, 1),
                             "foot_y": _foot(bb)[1], "m": round(mv, 3)})
        rows.append({"idx": i, "n_det": len(dets), "n_in": n_in, "n_out": len(outs),
                     "mask": m is not None, "outs": outs})
        prev_g = g

    bad_mask = [r for r in rows if not r["mask"]]
    print(f"court_mask 失败帧: {len(bad_mask)}/{len(rows)}")
    nin = [r["n_in"] for r in rows]
    print(f"门1 保留数 n_in: 中位 {int(np.median(nin))} 最小 {min(nin)} 最大 {max(nin)}")
    lows = sorted(rows, key=lambda r: r["n_in"])[:12]
    print("\n-- 门1 保留数最低的 12 帧（潜在漏杀）--")
    print(f"{'帧':>5}{'检测':>6}{'留':>5}{'丢':>5}  最大丢框高")
    for r in lows:
        hm = max([o["h"] for o in r["outs"]], default=0)
        print(f"{r['idx']:>5}{r['n_det']:>6}{r['n_in']:>5}{r['n_out']:>5}  {hm:.0f}px")

    # 找「球员特征」的场外框：大框 + 高运动
    print("\n-- 场外框里的『球员特征』候选（框高>=110px 且 运动量>=0.15）--")
    cand = []
    for r in rows:
        if not r["mask"]:
            continue
        for o in r["outs"]:
            if o["h"] >= 110 and o["m"] >= 0.15:
                cand.append({"idx": r["idx"], **o})
    cand.sort(key=lambda x: -(x["h"] * x["m"]))
    print(f"共 {len(cand)} 个")
    for c in cand[:20]:
        print(f"  帧{c['idx']:>3}  高{c['h']:>6.0f}px  运动{c['m']:.3f}  脚y{c['foot_y']:>4}  box{c['box']}")

    op = OUT / f"gate1_scan_{a.seg}.json"
    json.dump(rows, open(op, "w"), ensure_ascii=False)
    print(f"\n-> {op}")


if __name__ == "__main__":
    main()
