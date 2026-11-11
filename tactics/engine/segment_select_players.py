#!/usr/bin/env python3
"""第 4 层：场上球员遴选（从每帧 30–47 个 person 里选出场上 10 人）。

═══════════════════════════════════════════════════════════════════════
已实测排除的判据（都栽在「转播机位持续推拉摇移」上）
═══════════════════════════════════════════════════════════════════════
  ✗ 固定球场多边形
      44 秒内相机累计平移达 **2468px**（x 方向），任何固定多边形都会甩出画外。
  ✗ 身高阈值
      实测观众框高 92–285px、球员 115–215px，两者完全重叠，切不开。
  ✗ 朴素时间共现（网格化统计「该格子出现于多少帧」）
      相机摇移让观众在图像坐标里跟着动 -> 最"静止"的格子也只命中 27.6% 的帧。
  ✗ 相机补偿 + 时间共现
      补偿后提升到 42.5%，仍不足以分离；只剔掉了 69/2699 个检测。
  ✗ 躯干颜色聚类（想用 SA=白 / TOR=黑 / 裁判=灰 分离裁判）
      转播自动白平衡 + 阴影使躯干均值亮度全部落在 30–130 区间，
      白球衣也被压暗，无干净间隙。

═══════════════════════════════════════════════════════════════════════
采用方案：检测质量打分 + top-N（实测有效）
═══════════════════════════════════════════════════════════════════════
  分数 = conf × 尺寸合理性(高度接近球员典型带) × area^0.25 × 顶部看台惩罚

  为什么有效：场上球员是**完整、未被遮挡、光照充分**的目标 -> YOLO 置信度高。
  观众被栏杆/前排遮挡只露上半身、替补席密集重叠 -> 置信度普遍偏低。

  ⚠️ 已知残留问题（如实记录，未修复）：
      每帧通常会有 **1–2 名裁判**被一起选中（裁判同样在场上、全身可见、置信度高）。
      本层不做裁判剔除，下游以 `is_ref_candidate` 标记并保留。
      正确做法是球衣颜色聚类，但见上方排除理由。
═══════════════════════════════════════════════════════════════════════

输出 `players.json`：每帧场上球员（按分数排序，带 rank）+ 遴选统计。

用法：
  segment_select_players.py <tracks.json> <outdir> [--top-n 10]
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

PLAYER_H_MID = 165.0     # 1080p 广角转播下球员典型框高
PLAYER_H_TOL = 90.0


def score(p: dict, img_h: float = 1080.0) -> float:
    x1, y1, x2, y2 = p["box"]
    h = max(y2 - y1, 1.0)
    w = max(x2 - x1, 1.0)
    area = h * w
    midh = 1.0 / (1.0 + abs(h - PLAYER_H_MID) / PLAYER_H_TOL)
    top_pen = 0.25 if y2 < 0.18 * img_h else 1.0
    return p["conf"] * midh * (area ** 0.25) * top_pen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tracks_json")
    ap.add_argument("outdir")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--img-h", type=float, default=1080.0)
    a = ap.parse_args()

    d = json.load(open(a.tracks_json))
    frames = d["frames"]
    n = len(frames)

    kept = []
    for f in frames:
        ranked = sorted(f["players"], key=lambda z: -score(z, a.img_h))
        sel = ranked[:a.top_n]
        out = []
        for r, p in enumerate(sel, 1):
            x1, y1, x2, y2 = p["box"]
            out.append({"rank": r, "sel_id": f"p{r}",
                        "track_id": p["id"], "box": p["box"],
                        "foot": [round((x1 + x2) / 2, 1), round(y2, 1)],
                        "h": p["h"], "conf": p["conf"],
                        "score": round(score(p, a.img_h), 3)})
        kept.append({"idx": f["idx"], "t": f["t"],
                     "n_det": f["n_person_det"], "players": out,
                     "ball": f.get("ball"), "ball_handler": f.get("ball_handler"),
                     "handler_dist": f.get("handler_dist")})

    counts = [len(x["players"]) for x in kept]
    raw = [x["n_det"] for x in kept]
    hs = [p["h"] for x in kept for p in x["players"]]
    hist: dict[int, int] = defaultdict(int)
    for c in counts:
        hist[c] += 1

    meta = {"n_frames": n, "top_n": a.top_n,
            "raw_person_total": sum(raw), "selected_total": sum(counts),
            "raw_per_frame": {"min": min(raw), "median": sorted(raw)[n // 2], "max": max(raw)},
            "selected_per_frame_hist": dict(sorted(hist.items())),
            "selected_h": {"min": min(hs), "median": sorted(hs)[len(hs) // 2], "max": max(hs)},
            "known_issue": "每帧含约 1–2 名裁判（未剔除）"}
    os.makedirs(a.outdir, exist_ok=True)
    with open(os.path.join(a.outdir, "players.json"), "w") as f:
        json.dump({"meta": meta, "frames": kept}, f, ensure_ascii=False, indent=1)

    print(f"[select] {n} 帧 | top-{a.top_n} 打分遴选")
    print(f"[funnel] 原始 person {meta['raw_person_total']} "
          f"({meta['raw_per_frame']['median']}/帧) -> "
          f"选中 {meta['selected_total']} ({sum(counts)/n:.1f}/帧)")
    print(f"[选中框高] {meta['selected_h']['min']:.0f} / "
          f"{meta['selected_h']['median']:.0f} / {meta['selected_h']['max']:.0f} px")
    print(f"[⚠️ 已知] {meta['known_issue']}")
    print(f"[out] {os.path.join(a.outdir, 'players.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
