#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""景别序列 + 死球边界 → 定位「完整进攻」。

对应老程两条镜头语言判据的**可计算等价物**：
  ① 「记分牌小 ⇒ 中近景关键镜头」
     → 等价：person 框高**大** = 特写 = 出手/终结镜头
     （已实证：对照段 239.7px=远景 vs poss_a 段 345.6px=特写）
  ② 「往前推，找到 24 秒 = 回合开始」
     → 等价：往前推到**上一次死球/活动归零点**，且该点之后 person 框高
             处于低位平台（远景）⇒ 过半场已展开

输出：逐 0.5s 的框高/人数/活跃度 + 景别段划分 + 完整进攻候选

用法：shot_scale_seq.py <src> <t0> <t1> [out_json] [step]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import json
import os
import subprocess
import sys

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
# 🔴 禁用 yolo11_basketball.pt（person 头被篮球微调打塌，见 MEMORY A0）
MODEL = str(tactics_data_file("yolov8n.pt"))

# 🔴 记分牌叠加层 ROI（1920×1080 坐标，来自 find_overlay_diff 实测：x978~1186,y943~986）
# 老程裁定(cand1244)：中近景**有**记分牌=裁判吹停转场(EXCLUDE)；**无**记分牌=进攻镜头语言(KEEP)。
# 用 ROI 帧间静态差检测「记分牌在否」，无需 OCR。
SB_X0, SB_X1 = 978, 1186
SB_Y0, SB_Y1 = 943, 986
SB_THR = 12.0  # 灰度帧差均值阈值：<此值=ROI 静态=记分牌在
def sb_roi_box(w, h):
    """把 1920x1080 的记分牌 ROI 映射到当前抽流分辨率 w×h。"""
    return (int(round(SB_X0 / 1920 * w)), int(round(SB_Y0 / 1080 * h)),
            int(round(SB_X1 / 1920 * w)) + 1, int(round(SB_Y1 / 1080 * h)) + 1)


def ensure():
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)


def grab_seq(src, t0, t1, step, w=1280, h=720):
    ensure()
    tmp = os.path.join(SCRATCH, "ss.mp4")
    # 🔴 防陈旧复用（曾导致 H2 读到上半场内容）：抽流前先删旧 ss.mp4。
    #   否则本次抽流失败/未覆盖时，cv2 会读到上一轮（上半场）的 ss.mp4，
    #   产出"下半场=上半场"逐点全等的静默假数据。
    if os.path.exists(tmp):
        os.remove(tmp)
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {t1 - t0} -an -vf "fps={1.0/step:.6f},scale={w}:{h}" '
                   f'-c:v libx264 -preset ultrafast -crf 20 -pix_fmt yuv420p -g 1 "{tmp}"',
                   shell=True, capture_output=True)
    cap = cv2.VideoCapture(tmp)
    frs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frs.append(fr)
    cap.release()
    # 🔴 抽流有效性守卫：0 帧=抽流失败，必须报错退出而非静默产出空/坏数据。
    if not frs:
        raise SystemExit(f"🔴 grab_seq 抽流 0 帧：src={src} t={t0}~{t1}s（抽流失败，拒绝产出假数据）")
    return frs


def detect_person_h(model, fr):
    """返回 (最大 person 框高, person 框数, 所有框高列表)。"""
    res = model.predict(fr, classes=[0], verbose=False, device="mps")[0]
    hs = []
    for b in res.boxes:
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        hs.append(y2 - y1)
    hs.sort(reverse=True)
    return (hs[0] if hs else 0.0), len(hs), hs


def ascii_series(t, vals, vmin, vmax, unit="", title=""):
    lines = [title, f"      {t[0]:.1f}s" + " " * 46 + f"{t[-1]:.1f}s"]
    bar = []
    for v in vals:
        k = 0 if vmax <= vmin else int((v - vmin) / (vmax - vmin) * 39)
        bar.append(RAMP[max(0, min(9, k))])
    lines.append("      " + "".join(bar))
    lines.append(f"      {vmin:.0f}{' ' * 37}{vmax:.0f} {unit}")
    return "\n".join(lines)


RAMP = "0123456789"


def ascii_series_ramp(t, vals, vmin, vmax, unit="", title="", lo_ch=".", hi_ch="#"):
    lines = [title]
    bar = []
    for v in vals:
        k = 0 if vmax <= vmin else int((v - vmin) / (vmax - vmin) * 59)
        bar.append(lo_ch + RAMP[max(0, min(9, k // 6))] * 0 +
                   "0123456789"[min(9, int(k / 6.6))])
    lines.append(f"   {t[0]:6.1f}s " + "".join(bar) + f" {t[-1]:.1f}s")
    lines.append(f"   {'':<8}{' ' * 0}[{vmin:.0f} → {vmax:.0f} {unit}]  数字越大=框越高=越特写")
    return "\n".join(lines)


def segment_by_scale(ts, hmax, thr_lo, thr_hi, min_len=2.0):
    """按最大 person 框高分三档：远景(<thr_lo) / 中景 / 特写(>thr_hi)。"""
    labels = []
    for h in hmax:
        if h < thr_lo:
            labels.append("远")
        elif h > thr_hi:
            labels.append("特")
        else:
            labels.append("中")
    segs, cur = [], None
    for i, L in enumerate(labels):
        if cur is None or cur[0] != L:
            if cur and ts[i - 1] - ts[cur[1]] >= min_len:
                segs.append((cur[0], ts[cur[1]], ts[i - 1], labels.count(L)))
            cur = (L, i)
    if cur:
        segs.append((cur[0], ts[cur[1]], ts[-1], labels.count(cur[0])))
    return [s for s in segs if s[3] >= 2], labels


if __name__ == "__main__":
    from ultralytics import YOLO
    src = sys.argv[1]
    t0 = float(sys.argv[2]); t1 = float(sys.argv[3])
    out = sys.argv[4] if len(sys.argv) > 4 else "/tmp/shot_scale.json"
    step = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5

    frs = grab_seq(src, t0, t1, step)
    print(f"抽流 {len(frs)} 帧 @{step}s  {frs[0].shape[1]}x{frs[0].shape[0]}  "
          f"t={t0}~{t1}s")
    if not frs:
        print("无帧"); sys.exit(1)

    model = YOLO(MODEL)
    ts, hmax, nper, act, sb_arr = [], [], [], [], []
    prev_small = None
    prev_roi = None
    for i, fr in enumerate(frs):
        h, n, hs = detect_person_h(model, fr)
        small = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (160, 90))
        a = float(np.mean(cv2.absdiff(small, prev_small))) if prev_small is not None else -1.0
        # 记分牌 ROI 静态差检测（无需 OCR）
        x0, y0, x1, y1 = sb_roi_box(fr.shape[1], fr.shape[0])
        roi = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)[y0:y1, x0:x1]
        if prev_roi is not None:
            sbd = float(np.mean(cv2.absdiff(roi, prev_roi)))
            sb = bool(sbd < SB_THR)
        else:
            sb = False
        prev_roi = roi
        ts.append(round(t0 + i * step, 2))
        hmax.append(round(h, 1)); nper.append(n)
        act.append(round(a, 2)); sb_arr.append(sb)
        prev_small = small
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(frs)}  t={ts[-1]:.1f}  框高={h:.0f} 人数={n} 活跃={a:.1f} 记分牌={sb}")

    hmax = np.array(hmax); act = np.array(act); ts = np.array(ts)
    valid = hmax[hmax > 0]
    print(f"\n框高: min={valid.min():.0f} p25={np.percentile(valid,25):.0f} "
          f"中位={np.median(valid):.0f} p75={np.percentile(valid,75):.0f} max={valid.max():.0f}")
    print(f"人数: 中位={int(np.median(nper))} 范围{min(nper)}~{max(nper)}")

    print()
    print(ascii_series_ramp(ts, hmax, float(valid.min()), float(valid.max()),
                            "px", "【person 最大框高序列】（特写→框高大）"))
    print()
    va = act[act >= 0]
    print(ascii_series_ramp(ts[act >= 0], va, float(np.percentile(va, 10)),
                            float(np.percentile(va, 95)), "灰度差",
                            "【帧间活跃度】（死球→趋 0）"))

    thr_lo = float(np.percentile(valid, 30))
    thr_hi = float(np.percentile(valid, 75))
    print(f"\n景别阈值: 远景<{thr_lo:.0f}px  特写>{thr_hi:.0f}px")
    segs, labels = segment_by_scale(ts, hmax, thr_lo, thr_hi)
    print("\n=== 景别段（≥2 采样点）===")
    for L, a, b, n in segs:
        idx = [k for k in range(len(ts)) if a <= ts[k] <= b]
        print(f"  {L}景  t={a:.1f}~{b:.1f} ({b-a:.1f}s)  "
              f"框高中位={np.median(hmax[idx]):.0f}")

    # 完整进攻候选：起点 = 特写段往前第一个「远景段」；终点 = 特写段末 + 3s
    cands = []
    for si, (L, a, b, n) in enumerate(segs):
        if L != "特":
            continue
        prev = None
        for sj in range(si - 1, -1, -1):
            if segs[sj][0] == "远":
                prev = segs[sj]
                break
        if prev is None:
            continue
        mid = [s for s in segs[:si] if s[0] == "中" and s[2] > prev[2]]
        if not mid:
            continue
        cands.append({"far_start": round(prev[1], 1), "mid": [round(mid[0][1], 1), round(mid[-1][2], 1)],
                      "close_start": round(a, 1), "close_end": round(b, 1),
                      "clip": [round(prev[1] - 1.5, 1), round(b + 3.0, 1)],
                      "dur": round(b + 3.0 - (prev[1] - 1.5), 1)})
    print("\n=== 完整进攻候选（远景→中景→特写 顺序成立）===")
    print(f"{'远景起':<9}{'中景':<16}{'特写起':<9}{'特写止':<9}{'建议剪':<18}{'时长'}")
    for c in sorted(cands, key=lambda x: -x["dur"])[:20]:
        print(f"{c['far_start']:<9}{str(c['mid']):<16}{c['close_start']:<9}"
              f"{c['close_end']:<9}{str(c['clip']):<18}{c['dur']}")

    json.dump({"src": os.path.basename(src), "t0": t0, "t1": t1, "step": step,
               "ts": ts.tolist(), "hmax": hmax.tolist(), "nper": nper,
               "act": act.tolist(), "sb": sb_arr, "segs": segs, "cands": cands,
               "thr_lo": thr_lo, "thr_hi": thr_hi},
              open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {out}")
