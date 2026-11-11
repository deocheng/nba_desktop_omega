#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜头窗口 → 机位簇（只读侦察）

为什么做
--------
P0（坐标系不一致）要修，必须老程**目视点选场地线**。
已知标定粒度是「每段」（14 次）或「每镜头窗口」（47 次）。
但转播会在**固定机位**之间来回切 —— 若能把窗口归并到「机位簇」，
点选次数可能从 47 降到个位数。

做法（全部只读、只依赖 cv2/numpy）
----------------------------------
 1. 段内 MAD 尖峰 → 切镜候选（复用 engine/shot_cut_detect.py 的 cuts/mad_series）
 2. 直方图相关交叉验证，剔除「字幕条出现/消失」假切（复用 engine/shot_segment.py 口径 HCUT=0.55）
 3. 按真切镜切窗；每窗抽 <=BG_N 帧取**逐像素中位背景帧**（把运动球员当前景消掉）
 4. 背景帧两两 pearson 相关 → 距离矩阵 → 平均链接层次聚类 → 机位簇

产物: action_work/norm_calib/shot_clusters_clean14.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
ENGINE = ROOT / "engine"
AW = ROOT / "action_work"
SEGBASE = AW / "tactic_notes_batch_full" / "segments"
sys.path.insert(0, str(ENGINE))

import shot_cut_detect as scd  # noqa: E402  (复用 MAD 尖峰检切)

BW, BH = 320, 180      # 背景帧工作分辨率
SW, SH = 160, 90       # MAD 判定分辨率（与 shot_cut_detect 一致）
BG_N = 24              # 每窗取中位背景所用的帧数上限
HCUT = 0.55            # 直方图相关间距中点（shot_segment 实测 [0.479,0.639]）


def load_seg(seg):
    """读一段所有帧 → (小图序列 160x90, 背景用图序列 320x180)"""
    d = SEGBASE / seg / "frames"
    fs = sorted(d.glob("*.jpg")) or sorted(d.glob("*.png"))
    smalls, bgs = [], []
    for p in fs:
        im = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        bgs.append(cv2.resize(im, (BW, BH), interpolation=cv2.INTER_AREA))
        smalls.append(cv2.resize(im, (SW, SH), interpolation=cv2.INTER_AREA))
    return np.stack(smalls), np.stack(bgs), len(fs)


def hist_of(g160):
    h = cv2.calcHist([g160], [0], None, [64], [0, 256]).ravel()
    s = h.sum()
    return h / s if s > 0 else h


def pearson(a, b):
    a = a.astype(np.float32).ravel()
    b = b.astype(np.float32).ravel()
    a -= a.mean()
    b -= b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def build_windows(seg):
    smalls, bgs, nf = load_seg(seg)
    if nf == 0:
        return seg, [], []
    # --- 1. MAD 尖峰候选 ---
    mad = [float(np.abs(smalls[i].astype(np.float32) - smalls[i - 1].astype(np.float32)).mean())
           for i in range(1, len(smalls))]
    idxs = list(range(1, len(smalls)))
    cand = scd.cuts(mad, idxs)
    # --- 2. 直方图相关交叉验证 ---
    verified = []
    for f, ratio in cand:
        if f < 1 or f >= len(smalls):
            continue
        ha, hb = hist_of(smalls[f - 1]), hist_of(smalls[f])
        hc = float(np.corrcoef(ha, hb)[0, 1])
        if hc < HCUT:
            kind = "real"
        elif hc < 0.90:
            kind = "suspect"
        else:
            kind = "false"      # 字幕条/叠加层变化，非切镜
        verified.append({"frame": f, "ratio": round(ratio, 2), "hcorr": round(hc, 4),
                         "kind": kind})
    real = [v["frame"] for v in verified if v["kind"] == "real"]
    # --- 3. 切窗 + 中位背景帧 ---
    bounds = [0] + real + [nf]
    wins = []
    for k in range(len(bounds) - 1):
        s, e = bounds[k], bounds[k + 1]
        if e - s < 5:                # 太短的窗口无标定价值
            continue
        idx = np.linspace(s, min(e, nf) - 1, min(BG_N, e - s)).astype(int)
        bg = np.median(bgs[idx], axis=0).astype(np.uint8)
        wins.append({"seg": seg, "start": int(s), "end": int(e - 1), "len": int(e - s),
                     "bg": bg})
    return seg, wins, verified


def avg_link(labels, D, thr):
    """平均链接层次聚类。D: 方阵距离；thr: 合并阈值"""
    clusters = [[i] for i in range(len(labels))]

    def cd(a, b):
        return float(np.mean([D[i][j] for i in a for j in b]))

    while True:
        best, bi, bj = None, -1, -1
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = cd(clusters[i], clusters[j])
                if best is None or d < best:
                    best, bi, bj = d, i, j
        if best is None or best > thr:
            break
        clusters[bi] = clusters[bi] + clusters[bj]
        clusters.pop(bj)
    order = sorted(range(len(clusters)), key=lambda i: -len(clusters[i]))
    return [clusters[i] for i in order]


def main():
    segs = ["ep10_s0", "ep11_s0", "ep12_s0", "ep12_s1", "ep13_s1", "ep15_s0",
            "ep16_s0", "ep16_s1", "ep17_s0", "ep17_s1", "ep18_s0", "ep18_s1",
            "ep19_s0", "ep20_s0"]

    allw, verdict = [], {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for seg, wins, ver in ex.map(build_windows, segs):
            verdict[seg] = ver
            allw.extend(wins)
            n_real = sum(1 for v in ver if v["kind"] == "real")
            n_sus = sum(1 for v in ver if v["kind"] == "suspect")
            n_fal = sum(1 for v in ver if v["kind"] == "false")
            print(f"{seg:<10} 候选 {len(ver):>2}  真 {n_real} 疑 {n_sus} 假 {n_fal}  "
                  f"→ 窗 {len(wins)}")

    n = len(allw)
    print(f"\n总窗口 {n}")

    S = np.zeros((n, n), dtype=np.float32)
    M = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            c = pearson(allw[i]["bg"], allw[j]["bg"])
            d = float(np.abs(allw[i]["bg"].astype(np.float32) -
                             allw[j]["bg"].astype(np.float32)).mean())
            S[i][j] = S[j][i] = c
            M[i][j] = M[j][i] = d
    np.fill_diagonal(S, 1.0)

    off = S[np.triu_indices(n, k=1)]
    print(f"背景相关分布: min={off.min():.3f} p10={np.percentile(off,10):.3f} "
          f"p50={np.median(off):.3f} p90={np.percentile(off,90):.3f} max={off.max():.3f}")

    labels = [f"{w['seg']}#{w['start']}-{w['end']}({w['len']})" for w in allw]

    # 同段内相邻的窗口一定是不同机位（切镜隔开）⇒ 用它们的相似度标定"不同簇"上界
    same_seg_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if allw[i]["seg"] == allw[j]["seg"]:
                same_seg_pairs.append(S[i][j])
    if same_seg_pairs:
        sp = np.array(same_seg_pairs)
        print(f"同段相邻机位（切镜隔开，一定不同机位）背景相关: "
              f"min={sp.min():.3f} p50={np.median(sp):.3f} max={sp.max():.3f}  n={len(sp)}")

    out = {"windows": [{"label": labels[i], "seg": allw[i]["seg"],
                        "start": allw[i]["start"], "end": allw[i]["end"],
                        "len": allw[i]["len"]} for i in range(n)],
           "verified_cuts": verdict}

    # 多阈值扫描簇数
    for thr in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        cl = avg_link(labels, 1.0 - S, thr)
        print(f"\n--- 距离阈值 d<{thr:.2f} (相关>{1-thr:.2f}) → 簇数 {len(cl)} ---")
        for k, c in enumerate(cl):
            print(f"  簇{k}({len(c)}): " + ", ".join(labels[i] for i in c))

    out["sim_stats"] = {"min": float(off.min()), "p50": float(np.median(off)),
                        "p90": float(np.percentile(off, 90)), "max": float(off.max())}
    dst = AW / "norm_calib" / "shot_clusters_clean14.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(str(AW / "norm_calib" / "shot_bg_sim.npy"), S)
    print("\nwrote", dst)


if __name__ == "__main__":
    main()
