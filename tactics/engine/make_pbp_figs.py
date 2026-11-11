#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PBP 交叉校验的可视化：① 球位三方案对照图 ② PBP 事件时间轴 SVG。

为什么单独做这张对照图：
用户 2026-09-23 指出「pos_t02195.jpg 红圈标的是地板，球在 30 号球员手里」。
事后用 PBP 反查证实 —— t=219.5 对应第 4 节剩 68.0s，正是
「R. Barrett 三分不中(69.0s) → J. Champagnie 抢到篮板(66.0s)」的中间，
Champagnie 冲抢长篮板的瞬间。三个球位摆在同一帧上，对错一目了然。
"""
import argparse
import json
import os

import cv2
import numpy as np

DARK = (26, 26, 34)


def fig_ball_compare(frame_path: str, out: str,
                     old_pt=(1016.0, 669.0), hybrid_pt=(1219.0, 341.0),
                     refined_pt=(1238.0, 351.0), truth=(1236.0, 349.0),
                     hoop=(1246, 235, 48, 25)):
    bgr = cv2.imread(frame_path)
    vis = bgr.copy()
    h, w = vis.shape[:2]

    # 注意力/球场带（用 court_mask 更严谨；这里轻量化只画关键元素）
    def marker(pt, color, label, off=(16, -14), thick=3, mk=cv2.MARKER_CROSS):
        x, y = int(pt[0]), int(pt[1])
        cv2.drawMarker(vis, (x, y), color, mk, 30, thick)
        cv2.putText(vis, label, (x + off[0], y + off[1]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, color, 2)

    if hoop:
        x, y, bw, bh = hoop
        cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 165, 255), 2)
        cv2.putText(vis, "HOOP (red rim)", (x - 6, max(20, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

    marker(old_pt, (60, 60, 255), "OLD pipeline (1016,669)  334px OFF", off=(-360, 8))
    cv2.circle(vis, (int(old_pt[0]), int(old_pt[1])), 26, (60, 60, 255), 2)
    marker(hybrid_pt, (0, 215, 255), "HYBRID color+attn+wrist  19px", off=(-330, -16))
    marker(refined_pt, (0, 255, 0), "REFINED (S>=100,V>=70)   2.9px", off=(10, 34),
           mk=cv2.MARKER_TILTED_CROSS)
    marker(truth, (255, 255, 255), "GROUND TRUTH (1236,349)", off=(18, -22),
           mk=cv2.MARKER_STAR)

    bar = np.full((96, w, 3), 22, np.uint8)
    cv2.putText(bar, "202602250TOR | Q4 68.0s | SAS 108 - TOR 104 | "
                     "PBP: Barrett 3PT miss @69.0 -> Champagnie REBOUND @66.0",
                (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (240, 240, 240), 2)
    cv2.putText(bar, "ball was MID-AIR off a missed 3PT, Champagnie corralling it at the rim"
                     "  (NOT a layup)",
                (16, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 200, 255), 2)
    cv2.imwrite(out, np.vstack([vis, bar]), [cv2.IMWRITE_JPEG_QUALITY, 90])

    # 局部放大三联
    x0, y0, x1, y1 = 1080, 250, 1450, 760
    crop = bgr[y0:y1, x0:x1]
    cv2.imwrite(out.replace(".jpg", "_zoom.jpg"),
                cv2.resize(crop, None, fx=1.9, fy=1.9, interpolation=cv2.INTER_NEAREST),
                [cv2.IMWRITE_JPEG_QUALITY, 92])


def svg_timeline(pbp_json: str, out: str) -> str:
    """PBP 事件 + 我们帧位 + 转移链，一张横向时间轴 SVG。"""
    d = json.load(open(pbp_json, encoding="utf-8"))
    frames = d["frames"]
    ev = d["events"]
    W, H = 1320, 430
    L, R = 66, 1288
    y_axis = 250
    c0 = frames[0]["clock_sec"]      # 83.0
    c1 = frames[-1]["clock_sec"]     # 40.7

    def X(clk):
        return L + (c0 - clk) / (c0 - c1) * (R - L)

    s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="ui-sans-serif,-apple-system,Helvetica,Arial" >']
    s.append(f'<rect x="0" y="0" width="{W}" height="{H}" rx="12" fill="#1b1b22"/>')
    s.append(f'<text x="{L}" y="34" fill="#eaeaea" font-size="17" font-weight="700">'
             f'PBP 真值 vs 视觉识别 · 202602250TOR · 第4节 83.0s→40.7s</text>')
    s.append(f'<text x="{L}" y="56" fill="#9aa0aa" font-size="12">'
             f'上：PBP 事件（灰=投篮 橙=篮板 红=失误 蓝=被盖）　中：我们的 6 次转移 '
             f'（绿=命中 紫=未命中）　下：87 帧位置</text>')

    # 时间轴
    s.append(f'<line x1="{L}" y1="{y_axis}" x2="{R}" y2="{y_axis}" '
             f'stroke="#4a4a55" stroke-width="2"/>')
    for clk in range(82, 40, -2):
        x = X(clk)
        s.append(f'<line x1="{x:.1f}" y1="{y_axis}" x2="{x:.1f}" y2="{y_axis+6}" '
                 f'stroke="#5a5a66" stroke-width="1"/>')
        if clk % 10 == 0 or clk in (83,):
            s.append(f'<text x="{x:.1f}" y="{y_axis+22}" fill="#8b909a" font-size="10" '
                     f'text-anchor="middle">{clk}s</text>')

    COL = {"Made": "#6fd08c", "Missed": "#c9c9d1"}
    for e in ev:
        if e["clock_sec"] is None or not (c1 - 0.5 <= e["clock_sec"] <= c0 + 0.5):
            continue
        et = e["event_type"] or ""
        m = e["main"] or ""
        if e["is_scoring"]:
            col = COL.get(e["result"], "#c9c9d1")
            x = X(e["clock_sec"])
            s.append(f'<circle cx="{x:.1f}" cy="{y_axis}" r="5" fill="{col}"/>')
            s.append(f'<line x1="{x:.1f}" y1="{y_axis-6}" x2="{x:.1f}" y2="{y_axis-40}" '
                     f'stroke="{col}" stroke-width="1.4"/>')
            s.append(f'<text x="{x:.1f}" y="{y_axis-46}" fill="{col}" font-size="10" '
                     f'text-anchor="middle">{e["player"]} {e["result"]}</text>')
            s.append(f'<text x="{x:.1f}" y="{y_axis-58}" fill="#7d838d" font-size="9.5" '
                     f'text-anchor="middle">{et}{" " + str(e["dist"]) + "ft" if e["dist"] else ""}</text>')
        elif "Rebound" in m:
            x = X(e["clock_sec"])
            s.append(f'<circle cx="{x:.1f}" cy="{y_axis}" r="5" fill="#ffa63d"/>')
            s.append(f'<line x1="{x:.1f}" y1="{y_axis-6}" x2="{x:.1f}" y2="{y_axis-40}" '
                     f'stroke="#ffa63d" stroke-width="1.6"/>')
            s.append(f'<text x="{x:.1f}" y="{y_axis-46}" fill="#ffa63d" font-size="10" '
                     f'text-anchor="middle">REB {e["player"]}</text>')
        elif "Turnover" in m or "Steal" in m:
            x = X(e["clock_sec"])
            s.append(f'<circle cx="{x:.1f}" cy="{y_axis}" r="5" fill="#ff6b6b"/>')
            s.append(f'<text x="{x:.1f}" y="{y_axis-46}" fill="#ff6b6b" font-size="10" '
                     f'text-anchor="middle">{e["player"]} {"TO" if "Turnover" in m else "STL"}</text>')
        elif "Block" in m:
            x = X(e["clock_sec"])
            s.append(f'<circle cx="{x:.1f}" cy="{y_axis}" r="5" fill="#6bb6ff"/>')
            s.append(f'<text x="{x:.1f}" y="{y_axis-46}" fill="#6bb6ff" font-size="10" '
                     f'text-anchor="middle">BLK {e["player"]}</text>')

    # 我们 87 帧
    for fr in frames:
        if fr["frame"] % 6:
            continue
        x = X(fr["clock_sec"])
        s.append(f'<line x1="{x:.1f}" y1="{y_axis+30}" x2="{x:.1f}" y2="{y_axis+44}" '
                 f'stroke="#55555f" stroke-width="1"/>')
    s.append(f'<text x="{L}" y="{y_axis+62}" fill="#8b909a" font-size="10">'
             f'▲ 每 6 帧一个刻度（共 87 帧，2fps）</text>')

    # 转移链
    y_tr = y_axis + 92
    s.append(f'<text x="{L}" y="{y_tr-10}" fill="#c9c9d1" font-size="11">'
             f'我们的 6 次球权转移（PBP ±1s 判定）</text>')
    v = d.get("verdicts", [])
    tr = [(221.0, 67.0, True), (226.5, 61.0, False), (230.0, 57.5, False),
          (235.5, 52.0, False), (236.5, 51.0, False), (242.5, 45.7, False)]
    for t, clk, ok in tr:
        x = X(clk)
        col = "#6fd08c" if ok else "#a97ce0"
        s.append(f'<line x1="{x:.1f}" y1="{y_tr}" x2="{x:.1f}" y2="{y_tr-22}" '
                 f'stroke="{col}" stroke-width="2.6"/>')
        s.append(f'<circle cx="{x:.1f}" cy="{y_tr-22}" r="4.5" fill="{col}"/>')
        s.append(f'<text x="{x:.1f}" y="{y_tr+14}" fill="{col}" font-size="9.5" '
                 f'text-anchor="middle">{t:.1f}s</text>')
        if ok:
            s.append(f'<text x="{x:.1f}" y="{y_tr-32}" fill="#6fd08c" font-size="10" '
                     f'text-anchor="middle">✓ 1.0s</text>')
    s.append(f'<line x1="{L}" y1="{y_tr}" x2="{R}" y2="{y_tr}" stroke="#3a3a44" stroke-width="1.5"/>')

    s.append(f'<text x="{L}" y="{H-26}" fill="#ffb26b" font-size="12.5" font-weight="600">'
             f'命中 1/6 = 17%　随机期望 28%　→ 转移链不优于随机，尚不可用</text>')
    s.append(f'<text x="{L}" y="{H-8}" fill="#9aa0aa" font-size="11">'
             f'唯一命中的那次（t=221.0 / 时钟 67.0s）落在「Barrett 三分不中 69.0 → '
             f'Champagnie 篮板 66.0」之间</text>')
    s.append('</svg>')
    svg = "\n".join(s)
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True)
    ap.add_argument("--pbp-json", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    fig_ball_compare(a.frame, os.path.join(a.outdir, "cmp_ball_t2195.jpg"))
    svg_timeline(a.pbp_json, os.path.join(a.outdir, "pbp_timeline.svg"))
    print("[out]", a.outdir)


if __name__ == "__main__":
    main()
