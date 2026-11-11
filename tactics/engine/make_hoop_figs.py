#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""篮圈窗口锚定跟踪的目视核实图。

⚠️ 存在的理由：本项目已吃过一次"平滑轨迹其实是假目标"的亏
（t=247.1–247.6 那条 25px/帧、尺寸稳定、到手腕单调收敛的 6 帧"完美"轨迹，
逐帧目视后全是木地板白色虚线纹理，真因是镜头平移）。
所以**平滑性不能当证据**——任何跟踪轨迹都必须出目视核对图。

产出：
  hoop_strip.jpg       —— 窗口内分层抽帧：整帧 + 放大 + 跟踪框
  hoop_velocity.jpg    —— 逐帧 dx 速度剖面（与 strip 对照，看"减速→平台→加速"是否真实）
"""
from __future__ import annotations

import argparse
import json
import os

import cv2
import numpy as np


def load_rows(p):
    return json.load(open(p, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True, help="hoop_track.json")
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--samples", default="214.0,215.0,216.0,217.0,218.0,219.0,219.5,220.0,220.5,221.0,221.5")
    ap.add_argument("--zoom", type=int, default=210)
    ap.add_argument("--panel-w", type=int, default=430)
    a = ap.parse_args()

    rows = load_rows(a.track)
    inw = [r for r in rows if r["hoop_box"]]
    tmap = {round(r["t"], 1): r for r in inw}

    want = [float(v) for v in a.samples.split(",")]
    picks = []
    for w in want:
        best = min(inw, key=lambda r: abs(r["t"] - w))
        if best not in picks:
            picks.append(best)

    panels = []
    for r in picks:
        p = os.path.join(a.frames_dir, f"f{r['frame']:05d}.jpg")
        if not os.path.exists(p):
            continue
        img = cv2.imread(p)
        H, W = img.shape[:2]
        x, y, w, h = r["hoop_box"]

        # 左：整帧 + 框
        full = img.copy()
        cv2.rectangle(full, (x, y), (x + w, y + h), (0, 0, 255), 3)
        cv2.rectangle(full, (x - 40, y - 30), (x + w + 40, y + h + 40), (0, 255, 255), 2)
        cx, cy = x + w // 2, y + h // 2
        cv2.drawMarker(full, (cx, cy), (255, 0, 255), cv2.MARKER_CROSS, 26, 3)
        sc = a.panel_w / W
        full = cv2.resize(full, (a.panel_w, int(H * sc)))
        bar = np.zeros((30, a.panel_w, 3), np.uint8)
        txt = f"t={r['t']:.1f}s  box=({x},{y},{w},{h})"
        cv2.putText(bar, txt, (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
        full = np.vstack([bar, full])

        # 右：放大
        z = a.zoom
        x0 = max(0, min(W - z, cx - z // 2))
        y0 = max(0, min(H - z, cy - z // 2))
        crop = img[y0:y0 + z, x0:x0 + z].copy()
        cv2.rectangle(crop, (x - x0, y - y0), (x + w - x0, y + h - y0), (0, 0, 255), 2)
        crop = cv2.resize(crop, (a.panel_w, a.panel_w), interpolation=cv2.INTER_NEAREST)
        bar2 = np.zeros((30, a.panel_w, 3), np.uint8)
        cv2.putText(bar2, f"zoom {z}px  ncc={r['ncc'] if r['ncc'] else '-'}  {r['mode']}",
                    (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 255, 180), 1, cv2.LINE_AA)
        crop = np.vstack([bar2, crop])

        # 左右高度对齐（整帧因缩放高度不一，需补齐）
        hh = max(full.shape[0], crop.shape[0])
        ww = a.panel_w
        if full.shape[0] < hh:
            full = np.vstack([full, np.zeros((hh - full.shape[0], ww, 3), np.uint8)])
        if crop.shape[0] < hh:
            crop = np.vstack([crop, np.zeros((hh - crop.shape[0], ww, 3), np.uint8)])

        panels.append(np.hstack([full, crop]))

    if panels:
        strip = np.vstack(panels)
        os.makedirs(a.outdir, exist_ok=True)
        q = os.path.join(a.outdir, "hoop_strip.jpg")
        cv2.imwrite(q, strip, [cv2.IMWRITE_JPEG_QUALITY, 88])
        print(f"[out] {q}  尺寸 {strip.shape[1]}x{strip.shape[0]}  面板 {len(panels)}")

    # 速度剖面
    ph, pw = 300, 1180
    canvas = np.full((ph, pw, 3), 24, np.uint8)
    xs = [r["t"] for r in inw]
    dxs = [0]
    for k in range(1, len(inw)):
        dxs.append(inw[k]["hoop_box"][0] - inw[k - 1]["hoop_box"][0])
    t0, t1 = min(xs), max(xs)
    if t1 > t0:
        pts = []
        for t, d in zip(xs, dxs):
            px = 70 + (t - t0) / (t1 - t0) * (pw - 100)
            py = ph / 2 - d * 6.0
            pts.append((int(px), int(max(16, min(ph - 16, py)))))
        cv2.line(canvas, (70, ph // 2), (pw - 30, ph // 2), (90, 90, 90), 1)
        for k in range(1, len(pts)):
            cv2.line(canvas, pts[k - 1], pts[k], (0, 220, 255), 2)
        for t in range(int(t0), int(t1) + 1):
            px = int(70 + (t - t0) / (t1 - t0) * (pw - 100))
            cv2.line(canvas, (px, ph // 2 - 4), (px, ph // 2 + 4), (120, 120, 120), 1)
            cv2.putText(canvas, str(t), (px - 10, ph // 2 + 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.42, (150, 150, 150), 1, cv2.LINE_AA)
        cv2.putText(canvas, "dx per frame (px)  scaled x6", (70, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, "expect: decelerate -> plateau -> accelerate  (real camera pan)",
                    (70, ph - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 180), 1, cv2.LINE_AA)
        q2 = os.path.join(a.outdir, "hoop_velocity.jpg")
        cv2.imwrite(q2, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"[out] {q2}")
        print(f"  dx 统计: min={min(dxs)} max={max(dxs)} "
              f"平台帧(dx=0)={sum(1 for d in dxs if d == 0)}")


if __name__ == "__main__":
    main()
