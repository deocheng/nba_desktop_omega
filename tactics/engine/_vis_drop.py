#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_vis_drop.py — 把「FP 过滤判死的球点 / 保留的球点」渲染成裁剪拼图，供目视核对。

纪律：本片段无可信真值，过滤不能只靠距离阈值下结论。
每张拼图每格 = 一个球点的 3 档视野：
    wide(±180px) | mid(±60px) | zoom(±24px)
中心用青色十字标出算法认定的球心。

产出
----
  action_work/validate/<clip>_drop_sheet.jpg  被 DROP 的轨迹点
  action_work/validate/<clip>_keep_sheet.jpg  被 KEEP 的轨迹点（对照）

用法
----
  python engine/_vis_drop.py --all [--per-track 6]
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
AW = ROOT / "action_work"

CELL = 160          # 每档视野渲染边长
LABEL_H = 26        # 每格顶部标签条高度


def crop3(img, cx, cy):
    outs = []
    for h in (180, 60, 24):
        x1, y1 = max(0, int(cx - h)), max(0, int(cy - h))
        x2, y2 = min(img.shape[1], int(cx + h)), min(img.shape[0], int(cy + h))
        c = img[y1:y2, x1:x2].copy()
        if c.size == 0:
            c = np.zeros((2 * h, 2 * h, 3), np.uint8)
        mx, my = int(cx - x1), int(cy - y1)
        cv2.drawMarker(c, (mx, my), (0, 255, 255), cv2.MARKER_CROSS, 16, 2)
        c = cv2.resize(c, (CELL, CELL), interpolation=cv2.INTER_AREA)
        outs.append(c)
    return np.hstack(outs)


def sheet(clip, which, per_track=6, cols=2):
    meta_p = AW / "validate" / f"{clip}_fp_filter.json"
    if not meta_p.exists():
        print(f"[跳过] 无 {meta_p.name}（先跑 ball_fp_filter.py）")
        return
    meta = json.loads(meta_p.read_text())
    rows = [r for r in meta["rows"] if ((not r["keep"]) if which == "drop" else r["keep"])]
    fdir = AW / clip

    cells = []
    for r in rows:
        for k, (fi, c) in enumerate(zip(r["frames"][:per_track], r["centers"][:per_track])):
            fn = f"f{int(fi):05d}.jpg"
            img = cv2.imread(str(fdir / fn))
            if img is None:
                continue
            tile = crop3(img, c[0], c[1])
            bar = np.full((LABEL_H, tile.shape[1], 3), 28, np.uint8)
            txt = (f"t{r['track']} f{int(fi):03d} p{r['probs'][k]:.2f} "
                   f"d~{r['d_mean']:.0f} y{c[1]:.0f}")
            cv2.putText(bar, txt, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (200, 230, 255), 1, cv2.LINE_AA)
            cells.append(np.vstack([bar, tile]))

    if not cells:
        print(f"[空] {clip} {which}")
        return
    W = CELL * 3
    H = CELL + LABEL_H
    rows_n = (len(cells) + cols - 1) // cols
    canvas = np.full((rows_n * H, cols * W, 3), 12, np.uint8)
    for i, c in enumerate(cells):
        r, cc = divmod(i, cols)
        canvas[r * H:(r + 1) * H, cc * W:(cc + 1) * W] = c
    out = AW / "validate" / f"{clip}_{which}_sheet.jpg"
    cv2.imwrite(str(out), canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"[{clip}] {which}: {len(cells)} 格 → {out.name}  {canvas.shape[1]}x{canvas.shape[0]}")


def zoom(clip, which, tracks, half=90, px=360):
    """把指定轨迹的**代表点**大幅放大渲染（用于复核「疑似残留 FP」等个案）。"""
    meta = json.loads((AW / "validate" / f"{clip}_fp_filter.json").read_text())
    row = {r["track"]: r for r in meta["rows"]}
    fdir = AW / clip
    tiles = []
    for ti in tracks:
        r = row.get(ti)
        if r is None or bool(r["keep"]) != (which == "keep"):
            continue
        k = len(r["frames"]) // 2                      # 取中位点作代表
        fi, c = r["frames"][k], r["centers"][k]
        img = cv2.imread(str(fdir / f"f{int(fi):05d}.jpg"))
        if img is None:
            continue
        x1, y1 = max(0, int(c[0] - half)), max(0, int(c[1] - half))
        x2, y2 = min(img.shape[1], int(c[0] + half)), min(img.shape[0], int(c[1] + half))
        cr = img[y1:y2, x1:x2].copy()
        cv2.drawMarker(cr, (int(c[0] - x1), int(c[1] - y1)), (0, 255, 255),
                       cv2.MARKER_CROSS, 18, 2)
        cr = cv2.resize(cr, (px, px), interpolation=cv2.INTER_CUBIC)
        bar = np.full((30, px, 3), 25, np.uint8)
        cv2.putText(bar, f"t{ti} f{int(fi):03d} p{r['probs'][k]:.2f} "
                         f"d{r['d_mean']:.0f} ({c[0]:.0f},{c[1]:.0f})",
                    (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (210, 235, 255), 1, cv2.LINE_AA)
        tiles.append(np.vstack([bar, cr]))
    if not tiles:
        print(f"[空] {clip} zoom {which} {tracks}")
        return
    out = AW / "validate" / f"{clip}_{which}_zoom.jpg"
    cv2.imwrite(str(out), np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[{clip}] zoom-{which}: {len(tiles)} 格 → {out.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--which", default="both", choices=["drop", "keep", "both"])
    ap.add_argument("--per-track", type=int, default=6)
    ap.add_argument("--cols", type=int, default=2)
    ap.add_argument("--zoom", default=None,
                    help="放大模式：逗号分隔轨迹号（如 1,3,15,16），配合 --which keep/drop")
    a = ap.parse_args()
    clips = (["sas_hou", "sas_nop", "sas_det"] if a.all
             else ([a.clip] if a.clip else []))
    if a.zoom:
        ts = [int(x) for x in a.zoom.split(",") if x.strip()]
        for c in clips:
            zoom(c, a.which if a.which != "both" else "keep", ts)
        return
    whs = (["drop", "keep"] if a.which == "both" else [a.which])
    for c in clips:
        for w in whs:
            sheet(c, w, a.per_track, a.cols)


if __name__ == "__main__":
    main()
