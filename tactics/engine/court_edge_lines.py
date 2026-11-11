#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.13d 边线取证：把画面里的**真实长直线**检出来，指认「被观众挡住的那条边线」。

背景：v1/v2 虚拟边线全段净收益 ≈ 0（救回 159 vs 新增误杀 138，救回的多是画面底边观众）。
      怀疑方向错：我拟合的是「地板可见下沿」（近水平），而球场**底线**在斜视角下是**陡斜**的。

做法：Canny + 概率 Hough 检长直线 → 只保留**两侧颜色分属"地板色/非地板色"**的线
      （球场边界两侧必然是一地板一非地板）→ 叠图 + 标注角度/长度。
用法: court_edge_lines.py --seg ep24_s1 --idx 70 [--minlen 140]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))

WOOD_LO, WOOD_HI = (10, 45, 140), (38, 255, 255)


def wood_ratio(img, x, y, r=9):
    H, W = img.shape[:2]
    x0, x1 = max(0, x - r), min(W, x + r)
    y0, y1 = max(0, y - r), min(H, y + r)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, WOOD_LO, WOOD_HI)
    return float((m > 0).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--minlen", type=int, default=140)
    ap.add_argument("--topn", type=int, default=14)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 多尺度 Hough（地板划线的对比度低，用两档 Canny）
    lines = []
    for lo, hi in [(40, 120), (80, 200)]:
        e = cv2.Canny(gray, lo, hi)
        e = cv2.dilate(e, np.ones((3, 3), np.uint8), 1)
        ls = cv2.HoughLinesP(e, 1, np.pi / 360, threshold=70,
                             minLineLength=a.minlen, maxLineGap=40)
        if ls is not None:
            lines += [tuple(int(v) for v in np.asarray(l).reshape(-1)) for l in ls]

    # 去重 + 只留「两侧一地板一非地板」的线
    kept = []
    for (x1, y1, x2, y2) in lines:
        L = float(np.hypot(x2 - x1, y2 - y1))
        if L < a.minlen:
            continue
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        dx, dy = x2 - x1, y2 - y1
        n = np.hypot(dx, dy)
        px, py = -dy / n, dx / n          # 法向量
        o = 16
        p1 = (int(mx + px * o), int(my + py * o))
        p2 = (int(mx - px * o), int(my - py * o))
        if not (0 <= p1[0] < W and 0 <= p1[1] < H and 0 <= p2[0] < W and 0 <= p2[1] < H):
            continue
        r1 = wood_ratio(img, *p1)
        r2 = wood_ratio(img, *p2)
        if (r1 >= 0.35 and r2 <= 0.15) or (r2 >= 0.35 and r1 <= 0.15):
            ang = abs(np.degrees(np.arctan2(dy, dx)))
            if ang > 90:
                ang = 180 - ang
            kept.append({"p": (x1, y1, x2, y2), "L": L, "ang": ang,
                         "wood": (round(r1, 2), round(r2, 2))})
    # 去重（同一条线多次检出）：按 (角度桶, 中点) 粗聚类
    kept.sort(key=lambda k: -k["L"])
    uniq = []
    for k in kept:
        x1, y1, x2, y2 = k["p"]
        mk = ((x1 + x2) // 60, (y1 + y2) // 60, int(k["ang"] // 8))
        if any(u["mk"] == mk for u in uniq):
            continue
        k["mk"] = mk
        uniq.append(k)
        if len(uniq) >= a.topn:
            break

    vis = img.copy()
    for i, k in enumerate(uniq):
        x1, y1, x2, y2 = k["p"]
        cv2.line(vis, (x1, y1), (x2, y2), (0, 230, 255), 3)
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        tag = f"{i}:{k['ang']:.0f}deg L{k['L']:.0f}"
        cv2.putText(vis, tag, (mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(vis, tag, (mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 230, 255), 2)

    op = OUT / f"{a.seg}_f{a.idx}_edgelines.png"
    cv2.imwrite(str(op), vis)
    print(f"=== {a.seg} f{a.idx} 边线取证 ===")
    for i, k in enumerate(uniq):
        print(f"  #{i:>2} 角度{k['ang']:>5.1f}° 长{k['L']:>6.0f}px  "
              f"端点 {k['p']}  两侧木地板率 {k['wood']}")
    print(f"-> {op}")


if __name__ == "__main__":
    main()
