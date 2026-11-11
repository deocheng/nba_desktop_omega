#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.12b 三种选池方案在同一帧上的硬对比（对照老程裁定）。

方案 A = Top-K(框内运动量)          ← 我之前的做法
方案 B = 门1 场内/场外(几何)         ← 老程指出的正确第一步
方案 C = 门1 ∪ 球锚点(距球最近 N 个) ← 老程说的"发界外球不动 ⇒ 球成了根据"

同时在图上**标出球的位置**，让老程裁定「谁才是持球人」（我上轮目视说 #22 持球，
但球心距 #22 216px，距 #5 只有 37px ⇒ 我的预读与球的位置不符，属待裁定）。

用法: gate_pipeline_compare.py --seg ep24_s1 --idx 70
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

# 老程明确裁定
SPECT = {3, 8, 9, 13}          # 观众（必须排除）
PLAYER = {22}                  # 被红框丢掉的场上球员（必须保留）
# 其余 Top13 内非观众者 ⇒ 按人数自洽反推为场上球员（待老程复核）
DERIVED_PLAYER = {1, 2, 4, 5, 6, 7, 10, 11, 12}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--k", type=int, default=13)
    ap.add_argument("--balln", type=int, default=3)
    a = ap.parse_args()

    seg_d = SEGD / a.seg
    items = json.load(open(OUT / f"{a.seg}_f{a.idx}.json"))
    files = sorted((seg_d / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    r = court_mask(img)
    m = r[0] if r and r[0] is not None else None
    if m is None:
        print("该帧 court_mask 不可用"); return

    def oncourt(b):
        fx, fy = _foot(b)
        return m[fy, fx] > 0 if 0 <= fx < m.shape[1] and 0 <= fy < m.shape[0] else False

    for it in items:
        it["oncourt"] = oncourt(it["box"])
        it["cy"] = it["foot_y"] - it["h"] / 2

    # 球
    bt_p = seg_d / "ball_tracks.json"
    ball = None
    if bt_p.exists():
        bt = json.load(open(bt_p))
        e = [x for x in bt if x.get("frame") == a.idx]
        if e and e[0].get("ball"):
            ball = e[0]["ball"]["bbox"]
    bx = by = None
    if ball:
        bx, by = (ball[0] + ball[2]) / 2, (ball[1] + ball[3]) / 2
        for it in items:
            it["dball"] = float(np.hypot(it["cx"] - bx, it["cy"] - by))

    selA = {i["no"] for i in items if i["topk"]}
    selB = {i["no"] for i in items if i["oncourt"]}
    selC = set(selB)
    if bx is not None:
        selC |= {i["no"] for i in sorted(items, key=lambda x: x["dball"])[:a.balln]}

    def score(name, sel):
        fp = sorted(sel & SPECT)
        miss_spec = sorted(SPECT - sel)
        miss_pl = sorted((PLAYER | DERIVED_PLAYER) - sel)
        print(f"\n方案 {name}：保留 {len(sel)} 个")
        print(f"  混进观众      : {fp if fp else '无'}")
        print(f"  漏掉观众(好)  : {miss_spec if miss_spec else '无'}  ({len(miss_spec)}/{len(SPECT)})")
        print(f"  漏掉球员(坏)  : {miss_pl if miss_pl else '无'}  ({len(miss_pl)}/{len(PLAYER | DERIVED_PLAYER)})")

    print(f"=== {a.seg} f{a.idx} ===")
    print(f"老程裁定：观众={sorted(SPECT)}  被红框丢掉的球员={sorted(PLAYER)}")
    print(f"         （其余 Top13 内非观众者按人数自洽反推为场上球员={sorted(DERIVED_PLAYER)}，待复核）")
    if bx is not None:
        print(f"球心 ({bx:.0f},{by:.0f})；距球最近 5 个框："
              + ", ".join(f"#{i['no']}({i['dball']:.0f}px)" for i in sorted(items, key=lambda x: x["dball"])[:5]))
    score("A Top-K(运动量)", selA)
    score("B 门1 场内/场外", selB)
    score(f"C 门1 ∪ 球锚点(最近{a.balln})", selC)

    # 图：绿=场内保留，红=场外丢弃，黄框=球
    vis = img.copy()
    ov = vis.copy()
    ov[m > 0] = (0.45 * ov[m > 0] + 0.55 * np.array([30, 190, 40])).astype(np.uint8)
    vis = cv2.addWeighted(ov, 0.5, vis, 0.5, 0)
    for it in items:
        x1, y1, x2, y2 = [int(v) for v in it["box"]]
        on = it["oncourt"]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 220, 0) if on else (0, 0, 225), 3 if on else 2)
        tag = "#%d %s%.2f" % (it["no"], "" if it["topk"] else "[丢]", it["m"])
        if it["no"] in SPECT:
            tag += " 观众?"
        cv2.putText(vis, tag, (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 4)
        cv2.putText(vis, tag, (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0) if on else (0, 0, 220), 2)
    if ball:
        x1, y1, x2, y2 = [int(v) for v in ball]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 230, 255), 3)
        cv2.putText(vis, "BALL", (x1, max(16, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                    (0, 0, 0), 5)
        cv2.putText(vis, "BALL", (x1, max(16, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                    (0, 230, 255), 2)
    cv2.putText(vis, f"{a.seg} f{a.idx}  green=场内保留  red=场外丢弃  BALL=球",
                (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
    cv2.putText(vis, f"{a.seg} f{a.idx}  green=场内保留  red=场外丢弃  BALL=球",
                (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 240, 255), 2)
    op = OUT / f"{a.seg}_f{a.idx}_gatecmp.png"
    cv2.imwrite(str(op), vis)
    print(f"\n-> {op}")


if __name__ == "__main__":
    main()
