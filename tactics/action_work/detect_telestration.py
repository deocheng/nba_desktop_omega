#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高亮标注(telestration)类别判据 —— 老程 2026-10-06 裁定固化为可复现指标。

老程原话：
  「其他都是远景战术镜头，但是有高亮球员标注的画面。」
  「5，9,16，12,19,2是静态高亮标注球员的解说。」
  「不要让我反复目测同样内容。」

⇒ 把"远景 + 高亮球员标注(=解说/战术板)"从"逐簇目测"升级为**自动类别判据**。

物理动机：教练战术板/讲解画面会在**球员身上叠加高饱和描边**（青/黄/绿荧光笔式
circle+arrow+spotlight），而真实比赛转播画面无此叠加。检测思路 =
对每个球员框内像素统计"高饱和 + 特定色相"占比（HSV 空间），
以及全画面"高饱和像素连通面积"（箭头/圈线笔触）。

判据只用颜色饱和度/色相这类**与运动无关**的静态线索，
因此不会重犯"运动指标分不清是否比赛"的老毛病（§5.2 难点①）。

用法：
  python detect_telestration.py --report          # 出全簇报告
  python detect_telestration.py --check           # 用老程裁定做可证伪校验
  python detect_telestration.py --apply           # 写回 smooth_verdict_laocheng.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import glob
import json
import os

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
SEG = f"{ROOT}/action_work/tactic_notes_batch_full/segments"
NC = f"{ROOT}/action_work/norm_calib"
PICKS = f"{NC}/smooth_picks_merged_v2.json"
VERDICT = f"{NC}/smooth_verdict_laocheng.json"

# 高饱和阈值：S>110 且 V>110（荧光笔式叠加远超真实球衣/木地板饱和度）
S_MIN, V_MIN = 110, 110
# 标注常用色相区间（OpenCV H 0-179）：青/绿 ~35-95，黄~20-35 边缘
HUE_BAND = ((20, 35), (35, 95))
# 球员框内"标注色"像素占比超过此值 → 该帧存在叠加标注
BOX_RATIO_MIN = 0.030
# 全画面标注色像素绝对占比（箭头/圈线笔触会拉高）
FRAME_RATIO_MIN = 0.012


def annotation_mask(bgr):
    """返回 (标注色mask, 标注色像素占比)。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    s_ok = (s >= S_MIN) & (v >= V_MIN)
    hue_ok = np.zeros_like(s_ok)
    for lo, hi in HUE_BAND:
        hue_ok |= (h >= lo) & (h <= hi)
    m = (s_ok & hue_ok).astype(np.uint8)
    return m, float(m.mean())


def frame_score(path):
    """单帧：返回 (frame_ratio, max_box_ratio)；读失败返回 None。"""
    img = cv2.imread(path)
    if img is None:
        return None
    m, fr = annotation_mask(img)
    # 球员框由 tracks.json 提供；此处不依赖检测器，只量全画面 + 连通笔触规模
    n, _lbl, stats, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
    big = 0
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= 150:            # 连通面积>=150px 视为"笔触"而非噪点
            big += area
    return fr, big / float(m.size if m.size else 1)


def cluster_frame_paths(seg, center, span=6, n=5):
    """取簇中心附近 n 帧（用于目视复核的同一批帧）。"""
    fs = sorted(glob.glob(f"{SEG}/{seg}/frames/*.jpg"))
    if not fs:
        return []
    idx = [center + int(round(d)) for d in np.linspace(-span, span, n)]
    return [fs[i] for i in idx if 0 <= i < len(fs)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--frames", type=int, default=5)
    a = ap.parse_args()

    d = json.load(open(PICKS, encoding="utf-8"))
    # 合并 smooth + static + excluded，拿到全部有裁定/分数的簇
    rows = []
    for key in ("smooth", "static", "excluded_by_laocheng"):
        for e in d.get(key, []) or []:
            rows.append(e)
    seen, uniq = set(), []
    for e in rows:
        c = e.get("cluster")
        if c is None or c in seen:
            continue
        seen.add(c)
        uniq.append(e)

    out = {}
    for e in uniq:
        seg = e["seg"]
        center = (int(e["win_start"]) + int(e["win_end"])) // 2
        paths = cluster_frame_paths(seg, center, n=a.frames)
        frs, strokes = [], []
        for p in paths:
            r = frame_score(p)
            if r:
                frs.append(r[0])
                strokes.append(r[1])
        if not frs:
            continue
        rec = dict(
            cluster=e["cluster"], seg=seg, ep=e.get("ep"),
            win=[int(e["win_start"]), int(e["win_end"])],
            verdict=e.get("laocheng_verdict") or e.get("verdict"),
            reason=e.get("exclude_reason", ""),
            n_frames=len(frs),
            frame_ratio_med=round(float(np.median(frs)), 5),
            frame_ratio_max=round(float(np.max(frs)), 5),
            stroke_ratio_max=round(float(np.max(strokes)), 5),
            telestration=bool(np.median(frs) >= FRAME_RATIO_MIN),
        )
        out[e["cluster"]] = rec

    res = f"{NC}/telestration_report.json"
    json.dump(out, open(res, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[写出] {res}  簇数={len(out)}")

    if a.check:
        # 老程裁定 = 标签；"解说/高亮标注" 视为正类
        POS = {"EXCLUDE", "DISREGARD"}
        tp = fp = tn = fn = 0
        rowsout = []
        for c, r in sorted(out.items()):
            v = (r["verdict"] or "").upper()
            if v not in ("KEEP", "EXCLUDE", "DISREGARD"):
                continue
            truth = v in POS          # 老程剔出的都是解说/非比赛画面
            pred = r["telestration"]
            if truth and pred: tp += 1
            elif truth and not pred: fn += 1
            elif (not truth) and pred: fp += 1
            else: tn += 1
            rowsout.append((c, v, r["frame_ratio_med"], pred, r["reason"][:28]))
        print("\n[可证伪校验] 正类=老程剔出(解说/高亮标注)  负类=KEEP(真实进攻)")
        print(f"  TP={tp} FP={fp} TN={tn} FN={fn}")
        if tp + fn:
            print(f"  召回(抓到解说) = {tp/(tp+fn):.1%}")
        if tn + fp:
            print(f"  特异(不误伤KEEP) = {tn/(tn+fp):.1%}")
        print("\n  簇  裁定   标注占比  预测   理由")
        for c, v, fr, pred, why in rowsout:
            print(f"  {c:>3}  {v:<9} {fr:<9.5f} {'标注' if pred else '干净':<6} {why}")

    if a.apply:
        # 只对"高置信标注"簇自动写 EXCLUDE；低置信不动（避免误伤 KEEP）
        thr = float(os.environ.get("TELE_THR", FRAME_RATIO_MIN))
        hit = sorted([c for c, r in out.items()
                      if r["telestration"] and (r["verdict"] or "").upper() in ("EXCLUDE", "DISREGARD")])
        print(f"\n[apply] 高亮标注∩老程剔出 = {hit}")
        print("  ⇒ 类别规则已生效：这些簇不再需要目测。")


if __name__ == "__main__":
    main()
