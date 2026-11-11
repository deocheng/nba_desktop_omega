#!/usr/bin/env python3
"""第 1 层：抽帧 + 镜头切换检测（分段定位）。

为什么自己做切换检测而不用 ffmpeg 的 `select='gt(scene,...)'`：
实测该滤镜在 `-ss` 输入定位后输出的 `pts_time` 仍是**原片时间轴**，与 seek 点对不上，
容易把切换点算错位置。自己抽帧再算差分，时间轴完全可控。

输出：
  <outdir>/f*.jpg                 抽到的帧
  <outdir>/shots.json             每个镜头 [{start_frame, end_frame, start_t, end_t, n}]
  <outdir>/frames.json            逐帧 {idx, t, path}
  stdout                          镜头清单 + 最长连续镜头建议

用法：
  segment_frames.py <video> <outdir> --start 150 --dur 100 --fps 2 \
                    [--min-shot-sec 12] [--keep-longest]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

FFMPEG = "/opt/homebrew/bin/ffmpeg"


def extract(video: str, outdir: str, start: float, dur: float, fps: float,
            width: int = 0) -> list[dict]:
    """抽帧。

    width=0 表示保持原分辨率 —— **对小目标检测很重要**：
    球在 1080p 下只有约 17px 高，缩到 960 宽（半分辨率）后只剩 ~8px，YOLO 基本检不到。
    """
    os.makedirs(outdir, exist_ok=True)
    for f in os.listdir(outdir):
        if f.startswith("f") and f.endswith(".jpg"):
            os.remove(os.path.join(outdir, f))
    vf = f"fps={fps}" + (f",scale={width}:-2" if width else "")
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-ss", f"{start}", "-t", f"{dur}", "-i", video,
        "-vf", vf, "-q:v", "3", "-y", os.path.join(outdir, "f%05d.jpg"),
    ]
    subprocess.run(cmd, check=True)
    files = sorted(f for f in os.listdir(outdir) if f.startswith("f") and f.endswith(".jpg"))
    return [{"idx": i, "t": round(start + i / fps, 3),
             "path": os.path.join(outdir, f)} for i, f in enumerate(files)]


def frame_sig(path: str, size: int = 128) -> tuple[np.ndarray, np.ndarray]:
    """帧签名 = (降采样灰度, RGB 直方图)。

    单用灰度 mean-abs 不够：本片实测真切换的灰度差只有 0.19–0.22，
    与快攻/摇镜造成的 0.15–0.18 混在一起，没有安全余量。
    加 RGB 直方图（对内容突变敏感、对相机移动不敏感）做**联合判定**才分得开。
    """
    im = Image.open(path).convert("RGB").resize((size, size * 9 // 16), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32)
    gray = a.mean(axis=2).reshape(-1) / 255.0
    hist = np.concatenate([
        np.histogram(a[:, :, c], bins=32, range=(0, 255), density=True)[0]
        for c in range(3)
    ])
    return gray, hist


def detect_shots(frames: list[dict], gray_thr: float = 0.16,
                 hist_thr: float = 0.015) -> tuple[list[int], list[dict]]:
    """返回 (切换点帧下标, 逐帧差分明细)。

    判定：灰度差 AND 直方图差**同时**越线才算切换。
    """
    sigs = [frame_sig(f["path"]) for f in frames]
    cuts, rows = [], []
    for i in range(1, len(sigs)):
        dg = float(np.abs(sigs[i][0] - sigs[i - 1][0]).mean())
        dh = float(np.abs(sigs[i][1] - sigs[i - 1][1]).sum() / 6.0)
        is_cut = dg > gray_thr and dh > hist_thr
        if is_cut:
            cuts.append(i)
        rows.append({"frame": i, "t": frames[i]["t"],
                     "gray_d": round(dg, 4), "hist_d": round(dh, 4),
                     "cut": is_cut})
    return cuts, rows


def group_shots(frames: list[dict], cuts: list[int]) -> list[dict]:
    bounds = [0] + cuts + [len(frames)]
    shots = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b <= a:
            continue
        shots.append({
            "start_frame": a, "end_frame": b - 1, "n": b - a,
            "start_t": frames[a]["t"], "end_t": frames[b - 1]["t"],
            "dur_sec": round(frames[b - 1]["t"] - frames[a]["t"] + 1.0, 2),
        })
    return shots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("outdir")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--width", type=int, default=0,
                    help="抽帧缩放宽度；0=保持原分辨率（推荐，保小目标）")
    ap.add_argument("--min-shot-sec", type=float, default=12.0)
    ap.add_argument("--gray-thr", type=float, default=0.16)
    ap.add_argument("--hist-thr", type=float, default=0.015)
    ap.add_argument("--keep-longest", action="store_true",
                    help="只保留最长的连续镜头（删除其余帧）")
    a = ap.parse_args()

    frames = extract(a.video, a.outdir, a.start, a.dur, a.fps, a.width)
    w = ""
    try:
        w = f" 尺寸={Image.open(frames[0]['path']).size}"
    except Exception:
        pass
    print(f"[extract] {len(frames)} 帧 @ {a.fps}fps  ({a.start}s..{a.start+a.dur}s){w}")
    cuts, rows = detect_shots(frames, a.gray_thr, a.hist_thr)
    print(f"[cuts] 检出 {len(cuts)} 个切换点 -> 帧下标 {cuts[:40]}")
    for i in cuts[:20]:
        r = rows[i - 1]
        print(f"   t={r['t']:>7.2f}s  gray_d={r['gray_d']:.4f} hist_d={r['hist_d']:.4f}")
    shots = group_shots(frames, cuts)
    shots.sort(key=lambda s: -s["n"])
    print(f"[shots] {len(shots)} 个镜头（按长度降序）")
    for s in shots[:12]:
        mark = " ✅" if s["dur_sec"] >= a.min_shot_sec else ""
        print(f"   帧 {s['start_frame']:>4}-{s['end_frame']:>4}  "
              f"t={s['start_t']:>7.2f}-{s['end_t']:>7.2f}  "
              f"{s['n']:>3} 帧 / {s['dur_sec']:>5.2f}s{mark}")

    with open(os.path.join(a.outdir, "shots.json"), "w") as f:
        json.dump({"fps": a.fps, "start": a.start, "dur": a.dur,
                   "gray_thr": a.gray_thr, "hist_thr": a.hist_thr,
                   "cuts": cuts, "shots": shots, "diffs": rows},
                  f, ensure_ascii=False, indent=2)

    longest = max(shots, key=lambda s: s["n"]) if shots else None
    if longest:
        print(f"\n[recommend] 最长连续镜头：帧 {longest['start_frame']}-{longest['end_frame']} "
              f"(t={longest['start_t']}-{longest['end_t']}, {longest['dur_sec']}s)")
        if a.keep_longest:
            keep = set(range(longest["start_frame"], longest["end_frame"] + 1))
            n = 0
            for f in frames:
                if f["idx"] not in keep:
                    os.remove(f["path"])
                    n += 1
            frames = [f for f in frames if f["idx"] in keep]
            print(f"[keep-longest] 已删 {n} 帧，保留 {len(frames)} 帧")

    with open(os.path.join(a.outdir, "frames.json"), "w") as f:
        json.dump(frames, f, ensure_ascii=False, indent=2)
    print(f"[out] {a.outdir}/frames.json  shots.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
