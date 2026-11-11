#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高亮标注(telestration)类别判据 v2 —— 基于目视自证的正确特征。

🔴 v1 证伪（2026-10-06）：HSV 高饱和像素占比 → 召回 20%/特异 41%，比随机还差。
   KEEP 簇(17/22/23/26)得分反而更高 ⇒ 真实比赛画面本身就有高饱和区
   （球衣/木地板/蓝绿球鞋），颜色饱和度**不是**判别特征。

✅ v2 特征（来自老程裁定簇的目视自证，见 clips/probe_telestration/）：
   讲解/高亮标注画面的**两个独有**结构：
     A) 圆形 PiP 放大镜气泡（top-right 大圆，内含二次放大的球员）
        —— 真实转播画面**绝无**此结构 ⇒ 单帧即可判别，特异性理论上≈100%
     B) 场地白色聚光椭圆（spotlight，画在地板上的高亮圈）
   判据 = A 或 B 命中即判 telestration。
   字幕**不是**特征（KEEP 簇 c17 同样有中文字幕）。

与运动指标正交（本项目 §5.2 难点①：运动指标分不清是否比赛），
因此可作为类别自动排除的依据，避免老程反复目测同类内容。

用法：
  python detect_telestration.py --report     # 出全簇报告
  python detect_telestration.py --check      # 用老程裁定做可证伪校验
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

# --- A) PiP 气泡参数 ---
CIRCLE_MIN_R = int(0.13 * 720)     # 半径下限 ≈94px（气泡至少占屏高 13%）
CIRCLE_MAX_R = int(0.42 * 720)     # 半径上限 ≈302px
CIRCLE_MIN_VOTE = 60                # Hough 累加阈值
# --- B) 聚光椭圆参数 ---
SPOT_V_MIN, SPOT_S_MAX = 205, 42    # 极亮 + 极低饱和（白漆）
SPOT_AREA_MIN = 900                 # 连通面积下限 px
SPOT_AREA_MAX = 90000              # 上限（过大=地板/球衣整块，排除）


def spot_score(bgr):
    """场地白色聚光椭圆：极亮(V>=205)且极低饱和(S<=42)的连通域规模占比。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 2] >= SPOT_V_MIN) & (hsv[:, :, 1] <= SPOT_S_MAX)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _lbl, stats, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
    area = 0
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        if SPOT_AREA_MIN <= a <= SPOT_AREA_MAX and w > 25 and h > 12:
            # 聚光圈是"扁椭圆"：宽高比 1.4~8
            ar = w / float(h)
            if 1.4 <= ar <= 8.0:
                area += a
    return area / float(m.size)


def bubble_score(bgr):
    """PiP 圆形放大镜气泡：大圆 Hough 投票峰值。返回 (峰值, 是否命中)。"""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.medianBlur(g, 5)
    circles = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, dp=1.4, minDist=80,
                               param1=110, param2=CIRCLE_MIN_VOTE,
                               minRadius=CIRCLE_MIN_R, maxRadius=CIRCLE_MAX_R)
    if circles is None:
        return 0.0, False
    r = circles[0][:, 2]
    return float(r.max()), True


def frame_feat(path):
    img = cv2.imread(path)
    if img is None:
        return None
    sp = spot_score(img)
    _r, bub = bubble_score(img)
    return dict(spot=sp, bubble=bub, telestration=bool(bub or sp >= 0.010))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--frames", type=int, default=5)
    a = ap.parse_args()

    d = json.load(open(PICKS, encoding="utf-8"))
    seen, rows = set(), []
    for k in ("smooth", "static", "excluded_by_laocheng"):
        for e in d.get(k) or []:
            c = e.get("cluster")
            if c is not None and c not in seen:
                seen.add(c)
                rows.append(e)

    out = {}
    for e in rows:
        fs = sorted(glob.glob(f"{SEG}/{e['seg']}/frames/*.jpg"))
        if not fs:
            continue
        ctr = (int(e["win_start"]) + int(e["win_end"])) // 2
        idx = [ctr + int(round(x)) for x in np.linspace(-6, 6, a.frames)]
        feats = [f for f in (frame_feat(fs[i]) for i in idx if 0 <= i < len(fs)) if f]
        if not feats:
            continue
        ntel = sum(f["telestration"] for f in feats)
        out[e["cluster"]] = dict(
            cluster=e["cluster"], seg=e["seg"], ep=e.get("ep"),
            win=[int(e["win_start"]), int(e["win_end"])],
            verdict=(e.get("laocheng_verdict") or e.get("verdict") or "").upper(),
            reason=e.get("exclude_reason", ""),
            n_frames=len(feats), n_telestration=ntel,
            telestration_rate=round(ntel / len(feats), 3),
            spot_med=round(float(np.median([f["spot"] for f in feats])), 5),
            bubble_any=any(f["bubble"] for f in feats),
            telestration=ntel >= max(2, len(feats) // 3),
        )

    res = f"{NC}/telestration_report_v2.json"
    json.dump(out, open(res, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[写出] {res}  簇数={len(out)}")

    if a.check:
        POS = {"EXCLUDE", "DISREGARD"}    # 老程剔出的都是解说/非比赛画面
        tp = fp = tn = fn = 0
        print("\n簇  裁定      标注帧   气泡  聚光   预测   理由")
        for c, r in sorted(out.items()):
            v = r["verdict"]
            if v not in ("KEEP", "EXCLUDE", "DISREGARD"):
                continue
            truth, pred = v in POS, r["telestration"]
            tp += truth and pred; fn += truth and not pred
            fp += (not truth) and pred; tn += (not truth) and (not pred)
            print(f"{c:>3}  {v:<9} {r['n_telestration']}/{r['n_frames']:<4} "
                  f"{'有' if r['bubble_any'] else '无':<5} {r['spot_med']:<7.5f} "
                  f"{'标注' if pred else '干净':<6} {r['reason'][:26]}")
        print("\n[可证伪校验] 正类=老程剔出  负类=KEEP")
        print(f"  TP={tp} FP={fp} TN={tn} FN={fn}")
        if tp + fn: print(f"  召回={tp/(tp+fn):.1%}")
        if tn + fp: print(f"  特异={tn/(tn+fp):.1%}")
        print(f"  准确率={(tp+tn)/max(1,tp+tn+fp+fn):.1%}")


if __name__ == "__main__":
    main()
