#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯数据定位叙事边界 —— 不依赖目视（可证伪）。
① 切镜检测：帧差 > 中位 + 8×MAD（沿用项目已验证口径）
② 比分条状态聚类：对 ROI(y=600~660) 做降采样向量 + 层次聚类，
   每个簇 = 一个比分/时钟状态段；簇切换 = 回合边界候选。
③ 运动活跃度曲线：帧间差分均值，找"死球/暂停"低谷。
输出 JSON + 文本，供 ffmpeg 切片段。
"""
import json
import os
import sys

import cv2
import numpy as np

# 比分条 ROI（上一轮从磁盘实读定位，1280x720 广播）
SB_Y0, SB_Y1, SB_X0, SB_X1 = 600, 660, 0, 1280


def frame_diff_series(path, max_frames=None, scale=0.25):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    prev = None
    diffs = []
    sbs = []
    i = 0
    while True:
        if max_frames and i >= max_frames:
            break
        ok, fr = cap.read()
        if not ok:
            break
        small = cv2.resize(fr, None, fx=scale, fy=scale)
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev is not None:
            diffs.append(float(np.mean(cv2.absdiff(g, prev))))
        prev = g
        sb = fr[SB_Y0:SB_Y1, SB_X0:SB_X1]
        sbs.append(cv2.resize(sb, (40, 8)).astype(np.float32).ravel())
        i += 1
    cap.release()
    return fps, np.array(diffs), np.array(sbs)


def shot_cuts(diffs, k=8.0):
    med = float(np.median(diffs))
    mad = float(np.median(np.abs(diffs - med)))
    thr = med + k * mad
    idx = [int(i) for i in np.where(diffs > thr)[0]]
    # 合并相邻（同一切点的连续高差帧）
    merged = []
    for i in idx:
        if merged and i - merged[-1][-1] <= 2:
            merged[-1].append(i)
        else:
            merged.append([i])
    return thr, [m[0] for m in merged]


def sb_state_runs(sbs, thresh=6.0):
    """比分条向量聚类：贪心分段，帧间 L2 > thresh 视为状态切换"""
    runs, cur = [], [0]
    for i in range(1, len(sbs)):
        d = float(np.linalg.norm(sbs[i] - sbs[i - 1]))
        if d > thresh:
            runs.append((cur[0], cur[-1] + 1))
            cur = [i]
        else:
            cur.append(i)
    runs.append((cur[0], cur[-1] + 1))
    # 合并过短的段（<5帧）：比分条每秒都在动，短段是噪声
    merged = []
    for a, b in runs:
        if merged and b - a < 5:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


if __name__ == "__main__":
    path = sys.argv[1]
    t_start = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else None
    out = sys.argv[4] if len(sys.argv) > 4 else "/tmp/locate.json"

    tmp = "/tmp/_locate_probe.mp4"
    cmd = f'ffmpeg -hide_banner -loglevel error -y -ss {t_start} -i "{path}" '
    if dur:
        cmd += f"-t {dur} "
    cmd += f"-an -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p {tmp}"
    os.system(cmd)

    fps, diffs, sbs = frame_diff_series(tmp)
    n = len(sbs)
    print(f"probe: fps={fps} frames={n} dur={n/fps:.2f}s  (源 t={t_start:.1f} 起)")

    thr, cuts = shot_cuts(diffs)
    print(f"\n=== ① 切镜 (阈值 diff>{thr:.2f}) ===")
    for c in cuts:
        print(f"  帧{c:<5} 片内t={c/fps:.2f}s  源t={t_start + c/fps:.2f}s")

    runs = sb_state_runs(sbs)
    print(f"\n=== ② 比分条状态段 ({len(runs)} 段) ===")
    for a, b in runs:
        if b - a >= 5:
            print(f"  帧{a}-{b:<5} 片内{a/fps:.1f}~{b/fps:.1f}s  源{t_start+a/fps:.1f}~{t_start+b/fps:.1f}s"
                  f"  长{(b-a)/fps:.1f}s")

    print("\n=== ③ 运动活跃度(每0.5s) ===")
    step = max(1, int(fps * 0.5))
    line = []
    for i in range(0, len(diffs), step):
        seg = diffs[i:i + step]
        if len(seg):
            line.append(f"{t_start + i/fps:.0f}s:{np.mean(seg):.1f}")
    print("  " + "  ".join(line))

    json.dump({"fps": fps, "n_frames": n, "t_start": t_start,
               "cut_threshold": thr, "shot_cuts_frame": cuts,
               "shot_cuts_src_t": [round(t_start + c / fps, 2) for c in cuts],
               "sb_runs_frame": runs,
               "sb_runs_src_t": [[round(t_start + a / fps, 2), round(t_start + b / fps, 2)]
                                 for a, b in runs]},
              open(out, "w"), ensure_ascii=False, indent=1)
    print("\nwrote", out)
