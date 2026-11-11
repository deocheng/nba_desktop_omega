#!/usr/bin/env python3
"""A5.9 老程的目标定义：**每帧只保留 K=13 个目标**（两队各5 + 主裁判1 + 场边助理裁判2）。

选法：按「框内运动量」**降序取前 K**（不用阈值 —— 阈值法已证会误杀/漏判，见 A5.8④）。
理由：场上 11 人 + 场边 2 助理裁判是**全场唯一持续移动的人**，观众/场外工作人员静止。

产物：
  1. 统计：每帧运动量的分布、Top-13 与其余的分离度、Top-13 的框尺寸/位置特征
  2. 可视化：抽若干帧，画「全部检测(灰) + Top13(绿) + 被丢弃(红)」三色图，供目视自证
"""
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
TH = 12
FRAC = 0.6          # 取框中心 60% 区域(避开框边缘/背景)
POOL_FRAC = 0.12    # 参与统计的框内缩比例


def gray(f):
    im = cv2.imread(str(f))
    return cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (5, 5), 0)


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
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--k", type=int, default=13)
    ap.add_argument("--vis", type=int, default=6, help="可视化帧数")
    a = ap.parse_args()

    d = SEGD / a.seg
    tr = json.load(open(d / "tracks.json"))
    files = sorted((d / "frames").glob("f*.jpg"))
    OUT.mkdir(parents=True, exist_ok=True)

    stats = []
    picks = []
    prev = None
    for fr in tr["frames"]:
        idx = fr["idx"]
        if idx == 0 or idx >= len(files):
            continue
        g = gray(files[idx])
        pg = gray(files[idx - 1]) if (prev is None or prev[0] != idx - 1) else prev[1]
        if pg is None:
            continue
        da = cv2.absdiff(g, pg)
        items = []
        for p in fr.get("players", []):
            m = motion(da, p["box"], FRAC)
            b = p["box"]
            items.append({"m": m, "box": b, "h": b[3] - b[1],
                          "foot_y": b[3], "cx": (b[0] + b[2]) / 2})
        items.sort(key=lambda x: -x["m"])
        sel = items[:a.k]
        rest = items[a.k:]
        stats.append({"idx": idx, "n": len(items),
                      "topk_min_m": sel[-1]["m"] if sel else 0,
                      "rest_max_m": rest[0]["m"] if rest else 0,
                      "n_kept": len(sel)})
        picks.append((idx, items, sel))
        prev = (idx, g)

    ns = [s["n"] for s in stats]
    print(f"{a.seg}: 帧数 {len(stats)}  每帧检测 中位 {np.median(ns):.0f} "
          f"(min {min(ns)}, max {max(ns)})")
    gap = np.array([s["topk_min_m"] - s["rest_max_m"] for s in stats])
    print(f"Top{a.k} 与其余的运动量间隔: 中位 {np.median(gap):+.3f}  "
          f"p25 {np.percentile(gap,25):+.3f}  p75 {np.percentile(gap,75):+.3f}  "
          f"间隔>0 的帧占比 {np.mean(gap > 0):.2%}")
    kept_h = [it["h"] for _, _, sel in picks for it in sel]
    rest_h = [it["h"] for _, items, sel in picks for it in items[len(sel):]]
    print(f"Top{a.k} 框高 中位 {np.median(kept_h):.0f}px | 被丢弃 框高 中位 {np.median(rest_h):.0f}px")
    print(f"Top{a.k} 脚点y 中位 {np.median([it['foot_y'] for _,_,sel in picks for it in sel]):.0f} | "
          f"被丢弃 脚点y 中位 {np.median([it['foot_y'] for _,items,sel in picks for it in items[len(sel):]]):.0f}")

    # 可视化
    step = max(1, len(picks) // a.vis)
    for vi in range(0, min(a.vis * step, len(picks)), step):
        idx, items, sel = picks[vi]
        img = cv2.imread(str(files[idx]))
        sel_boxes = {tuple(np.round(it["box"], 3)) for it in sel}
        for it in items:
            x1, y1, x2, y2 = [int(v) for v in it["box"]]
            key = tuple(np.round(it["box"], 3))
            if key in sel_boxes:
                col, w = (0, 200, 0), 3
            else:
                col, w = (0, 0, 220), 1
            cv2.rectangle(img, (x1, y1), (x2, y2), col, w)
            if key in sel_boxes:
                cv2.putText(img, f"{it['m']:.2f}", (x1, max(14, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 0), 1)
        cv2.putText(img, f"{a.seg} f{idx}  ALL={len(items)}  Top{a.k}(green)  "
                         f"dropped(red)={len(items)-len(sel)}",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
        cv2.putText(img, f"{a.seg} f{idx}  ALL={len(items)}  Top{a.k}(green)  "
                         f"dropped(red)={len(items)-len(sel)}",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 240, 255), 2)
        p = OUT / f"{a.seg}_top{a.k}_f{idx}.png"
        cv2.imwrite(str(p), img)
        print("  ->", p)
    json.dump(stats, open(OUT / f"{a.seg}_top{a.k}_stats.json", "w"), indent=1)


if __name__ == "__main__":
    main()
