#!/usr/bin/env python3
"""遴选策略对比：哪种排序能把「场上 10 人」从 30–47 个 person 检测里挑出来。

背景：转播画面里 YOLO 每帧检到 30–47 个 person，其中场上球员只有 10 个。
试过并排除的判据：
  ✗ 固定球场多边形（机位持续推拉摇移）
  ✗ 身高阈值（观众 92–285px vs 球员 115–215px，完全重叠）
  ✗ 朴素时间共现（相机位移达 2468px，共现被稀释到 42.5%）
  ✗ 相机补偿 + 时间共现（top 共现仅 37/87 帧，只剔掉 69/2699 个检测）

本脚本对同一帧渲染多种排序准则的 top-N 结果，目视对比哪种最接近「10 名球员」。

准则：
  A conf        —— 按检测置信度
  B area        —— 按框面积（球员比被遮挡的观众完整、更大）
  C conf*area   —— 组合
  D midh        —— 按「高度接近球员典型高度」打分
  E comb        —— conf + 尺寸合理性 + 位置（远离画面顶部的观众区）

用法： pro_select_criteria.py <tracks.json> <场景目录> <帧idx,帧idx,...> <outdir>
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw

STRATEGIES = ["conf", "area", "conf_area", "midh", "comb"]


def score(p: dict, kind: str, img_h: float = 1080.0) -> float:
    x1, y1, x2, y2 = p["box"]
    h = max(y2 - y1, 1.0)
    w = max(x2 - x1, 1.0)
    area = h * w
    conf = p["conf"]
    # 球员典型高度带（1080p 广角转播实测 115–215px）
    midh = 1.0 / (1.0 + abs(h - 165.0) / 90.0)
    # 画面顶部 18% 几乎必是看台
    top_pen = 0.25 if y2 < 0.18 * img_h else 1.0
    if kind == "conf":
        return conf
    if kind == "area":
        return area
    if kind == "conf_area":
        return conf * (area ** 0.5)
    if kind == "midh":
        return midh * conf
    return conf * midh * (area ** 0.25) * top_pen


def main() -> int:
    tracks = json.load(open(sys.argv[1]))
    srcdir = sys.argv[2]
    idxs = [int(x) for x in sys.argv[3].split(",")]
    outdir = sys.argv[4]
    os.makedirs(outdir, exist_ok=True)
    by_idx = {f["idx"]: f for f in tracks["frames"]}

    for kind in STRATEGIES:
        tiles = []
        for i in idxs:
            f = by_idx[i]
            p = os.path.join(srcdir, f"f{i+1:05d}.jpg")
            img = Image.open(p).convert("RGB")
            W, H = img.size
            ranked = sorted(f["players"], key=lambda z: -score(z, kind, H))
            sel = ranked[:10]
            dr = ImageDraw.Draw(img)
            for j, pl in enumerate(sel):
                x1, y1, x2, y2 = pl["box"]
                dr.rectangle([x1, y1, x2, y2], outline=(0, 255, 80), width=8)
                dr.text((x1 + 6, max(0, y1 - 30)), f"{j+1} c{pl['conf']:.2f} h{pl['h']:.0f}",
                        fill=(0, 255, 80), stroke_width=3, stroke_fill=(0, 0, 0))
            for pl in ranked[10:]:
                x1, y1, x2, y2 = pl["box"]
                dr.rectangle([x1, y1, x2, y2], outline=(120, 120, 120), width=2)
            dr.text((16, 16), f"[{kind}] f{i} t={f['t']}s  det={f['n_person_det']} "
                              f"-> top10", fill=(255, 255, 255),
                    stroke_width=3, stroke_fill=(0, 0, 0))
            tw = int(os.environ.get("TILE_W", "640"))
            tiles.append(img.resize((tw, tw * 9 // 16), Image.LANCZOS))
        # 横向拼
        if tiles:
            tw = tiles[0].width
            th = tiles[0].height
            sheet = Image.new("RGB", (tw * len(tiles), th), (20, 20, 20))
            for k, t in enumerate(tiles):
                sheet.paste(t, (tw * k, 0))
            outp = os.path.join(outdir, f"sel_{kind}.jpg")
            sheet.save(outp, quality=90)
            print(f"  -> {outp}  ({sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
