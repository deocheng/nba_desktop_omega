#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场地线点选工具（半场梯形 4 角点）—— 老程本地点选用，AI 不代点。

用途
----
P0 标定需要每个机位 4 个**梯形角点**（对应 `HalfCourt.from_points(src_points)` 的 4 点）。
该工具用 cv2 窗口 + 鼠标，让你对一张代表帧点出这 4 个点，自动存 JSON。
AI 流程随后用 `HalfCourt.load_calibration(<json>)` 接入（只用未扩展点，守 C4）。

点选顺序（务必按此顺序，否则梯形顶点错位）
----------------------------------------
  1. f_l  远左角（画面远端左边线交点）
  2. f_r  远右角（画面远端右边线交点）
  3. n_r  近右角（画面近端右边线交点）
  4. n_l  近左角（画面近端左边线交点）
（对应 half_court_spatial_engine.from_lines 里 src=[f_l,f_r,n_r,n_l]）

操作
----
  左键          点下一个角点
  右键          撤销上一个角点
  s / Enter     保存并退出
  q / Esc       放弃退出（不写文件）
  空格          放大镜（在终端看当前坐标，辅助）

产物 JSON 结构
--------------
  {"seg","start","end","img_width","img_height",
   "src_points":[[x0,y0],[x1,y1],[x2,y2],[x3,y3]],   # 4 角点，顺序如上
   "note":"未扩展真值；接 HalfCourt.from_points"}

用法
----
  PYTHONPATH="" python3 action_work/pick_court_lines.py <代表帧.jpg> <out.json> [--seg ep10_s0 --start 37 --end 204]
"""
from __future__ import annotations

import argparse
import json
import sys

import cv2
import numpy as np

ORDER = ["f_l(远左)", "f_r(远右)", "n_r(近右)", "n_l(近左)"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frame")
    ap.add_argument("out")
    ap.add_argument("--seg", default="")
    ap.add_argument("--start", type=int, default=-1)
    ap.add_argument("--end", type=int, default=-1)
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    a = ap.parse_args()

    img = cv2.imread(a.frame)
    if img is None:
        print("无法读取", a.frame); sys.exit(1)
    H, W = img.shape[:2]
    scale = min(1.0, 1100 / W, 760 / H)
    disp = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    pts = []  # 原始坐标（未缩放）

    def draw():
        d = disp.copy()
        for i, (x, y) in enumerate(pts):
            px, py = int(x * scale), int(y * scale)
            cv2.circle(d, (px, py), 6, (0, 200, 255), -1)
            cv2.putText(d, f"{i}:{ORDER[i][:3]}", (px + 8, py - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        if len(pts) == 4:
            poly = np.array([[int(p[0] * scale), int(p[1] * scale)] for p in
                             [pts[0], pts[1], pts[3], pts[2]]], np.int32)
            cv2.polylines(d, [poly], True, (0, 220, 120), 2)
        cv2.putText(d, f"点选顺序: {ORDER[len(pts)] if len(pts) < 4 else '完成→按s保存'}",
                    (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.imshow("pick_court_lines", d)

    def on_click(ev, x, y, flags, param):
        nonlocal pts
        if ev == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x / scale, y / scale))
            draw()
        elif ev == cv2.EVENT_RBUTTONDOWN and pts:
            pts.pop()
            draw()

    cv2.namedWindow("pick_court_lines", cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback("pick_court_lines", on_click)
    draw()
    print("左键点 4 角点(f_l,f_r,n_r,n_l)；右键撤销；s/Enter 保存；q/Esc 放弃")
    while True:
        k = cv2.waitKey(0) & 0xFF
        if k in (ord('s'), 13) and len(pts) == 4:
            out = {"seg": a.seg, "start": a.start, "end": a.end,
                   "img_width": W, "img_height": H,
                   "src_points": [[round(p[0], 1), round(p[1], 1)] for p in pts],
                   "note": "未扩展真值；接 HalfCourt.from_points 守 C4"}
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            print("已保存", a.out)
            break
        elif k in (ord('q'), 27):
            print("放弃，未保存"); break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
