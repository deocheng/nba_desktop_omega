#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场区域掩膜 —— 「谁在场上」的原理性过滤器。

为什么必须有它
--------------
里程碑 03 已量化：YOLO11n-pose 每帧 ~13 个「人」里，**46.6% 的框底 y<600**——
是场边观众/替补，不是球员。这是两个下游失败的共同根因：
  ① Phase 1.5 队色探针退化：观众框把 2-means 的两个色心都拖成暗色
     ([103,91,88] / [56,37,42])，根本没分开 SAS 浅灰 vs TOR 黑；
  ② 球权分配到「最近的人」时可能分给观众。

本掩膜用**地板颜色 + 最大连通域**，逐帧计算，天然跟随镜头平移，
不依赖任何新权重、不需要逐帧人工标注。

判据：一个人物框「在场上」⇔ 其**底部中点**（脚点）落在球场掩膜内。

用法:
  court_mask.py <window> --probe            # 打印连通域统计
  court_mask.py <window> --render outdir    # 渲染掩膜叠加 + 人物框在/不在场着色
  court_mask.py <window> --save             # 落盘 court_mask.json（逐帧多边形近似=网格位图 RLE）
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

AW = Path(str(tactics_data_file("action_work")))

# 木地板：暖橙木色。OpenCV 色相 0–180 刻度（= 度数/2）
H_LO, H_HI = 8, 30          # ≈ 16°–60°
S_MIN, V_MIN = 0.28, 0.25
# 🔴 注意：篮球本身也是橙色、观众肤色也偏橙 —— 靠「最大连通域 + 形态学闭合」压掉，
#     不能靠颜色阈值单独解决。


def floor_color_mask(img, scale=0.25):
    h, w = img.shape[:2]
    small = cv2.resize(img, (int(w * scale), int(h * scale)),
                       interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] >= H_LO) & (hsv[:, :, 0] <= H_HI) &
         (hsv[:, :, 1] >= int(S_MIN * 255)) &
         (hsv[:, :, 2] >= int(V_MIN * 255))).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    return m, scale


def largest_cc(mask):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return None, None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    comp = (lab == i).astype(np.uint8) * 255
    return comp, stats[i]


def to_full(mask_small, shape, scale):
    h, w = shape[:2]
    return cv2.resize(mask_small, (w, h), interpolation=cv2.INTER_NEAREST)


def court_mask(img, scale=0.25, close_frac=0.02):
    """返回全分辨率球场掩膜（uint8 0/255）。"""
    m, sc = floor_color_mask(img, scale)
    comp, st = largest_cc(m)
    if comp is None:
        return np.zeros(img.shape[:2], np.uint8)
    k = int(max(img.shape[:2]) * close_frac) | 1
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, ker)
    comp = cv2.morphologyEx(comp, cv2.MORPH_OPEN, ker)
    comp, _ = largest_cc(comp)
    if comp is None:
        return np.zeros(img.shape[:2], np.uint8)
    return to_full(comp, img.shape, sc)


def foot_point(box):
    x1, y1, x2, y2 = box
    return int((x1 + x2) / 2), int(y2)


def on_court(mask, box):
    x, y = foot_point(box)
    h, w = mask.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return False
    return mask[y, x] > 0


def probe(win, frames=(0, 100, 200, 300, 400)):
    d = AW / win
    tracks = json.loads((AW / f"{win}_poss" / "ball_tracks.json").read_text())
    print(f"[{win}] 帧数 {len(tracks)}")
    for fi in frames:
        if fi >= len(tracks):
            continue
        img = cv2.imread(str(d / tracks[fi]["file"]))
        if img is None:
            continue
        cm = court_mask(img)
        area = float((cm > 0).mean())
        ps = tracks[fi].get("players", [])
        onn = sum(1 for p in ps if on_court(cm, p["bbox"]))
        ys = [int(p["bbox"][3]) for p in ps]
        print(f"  f{fi:05d} 掩膜占比 {area*100:5.1f}%  "
              f"人物 {len(ps):>2}  在场上 {onn:>2}  "
              f"框底 y 范围 {min(ys) if ys else 0}-{max(ys) if ys else 0}")


def render(win, outdir, frames=(0, 150, 300, 450)):
    d = AW / win
    tracks = json.loads((AW / f"{win}_poss" / "ball_tracks.json").read_text())
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for fi in frames:
        if fi >= len(tracks):
            continue
        fr = tracks[fi]
        img = cv2.imread(str(d / fr["file"]))
        if img is None:
            continue
        cm = court_mask(img)
        ov = img.copy()
        ov[cm > 0] = (ov[cm > 0] * 0.55 + np.array([30, 90, 30]) * 0.45).astype(np.uint8)
        onn = 0
        for p in fr.get("players", []):
            ok = on_court(cm, p["bbox"])
            onn += 1 if ok else 0
            x1, y1, x2, y2 = [int(v) for v in p["bbox"]]
            col = (60, 220, 60) if ok else (60, 60, 230)
            cv2.rectangle(ov, (x1, y1), (x2, y2), col, 3)
            cv2.putText(ov, str(p["track_id"]), (x1, max(18, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
        b = fr.get("ball")
        if b and "bbox" in b:
            bx1, by1, bx2, by2 = [int(v) for v in b["bbox"]]
            cv2.rectangle(ov, (bx1, by1), (bx2, by2), (0, 255, 255), 3)
        cv2.putText(ov, f"{win} f{fi:05d}  on-court {onn}/{len(fr.get('players', []))}",
                    (30, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
        p = out / f"court_{win}_f{fi:05d}.jpg"
        cv2.imwrite(str(p), ov)
        print("[图]", p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("window")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--render", default=None)
    ap.add_argument("--frames", nargs="+", type=int, default=None)
    a = ap.parse_args()
    if a.frames:
        fr = tuple(a.frames)
    else:
        fr = None
    if a.probe:
        probe(a.window, fr or (0, 100, 200, 300, 400))
    if a.render:
        render(a.window, a.render, fr or (0, 150, 300, 450))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
