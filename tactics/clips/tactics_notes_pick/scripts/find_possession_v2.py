#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整配合定位 v2 —— 用「镜头序列」而非「活跃度」。
老程 2026-10-07 批评：poss_a 只有一次传球+一次上篮，缺过半场，其余是出手镜头/出手以后。
已实测：框高(person框高中位) 能区分镜头远近
    对照430-436=239.7(远) 前段435-441=279.8 后段448-454=301.6 A候选451.6-459.4=345.6(特写) 454-460=381.6
假说：完整进攻 = **远景(过半场) → 中景(组织) → 特写(终结)** 的镜头序列，
     即框高呈「低→高」的完整跨度；只含特写=只有终结，不合格。
判据：
  ① 回合段：以活跃度低谷(死球/换球权)为界切分
  ② 段内框高跨度：min/median 足够小(有远景) 且 max 足够大(有特写)
  ③ 时长 ≥ 12s（完整进攻需要过半场+落位+终结）
在低分辨率抽流上跑（框高等比换算，只看相对），候选段再用原分辨率精测。
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

os.environ["PYTHONPATH"] = ""
os.environ["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

WEIGHT = str(tactics_data_file("yolov8n.pt"))

SCAN_FPS = 5
SCALE = (480, 270)          # 框高是 1080p 的 1/2.25，仅用于相对比较


def make_stream(src, t0, dur, tmp):
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {dur} -an -vf "fps={SCAN_FPS},scale={SCALE[0]}:{SCALE[1]}" '
                   f'-c:v libx264 -preset ultrafast -crf 26 -pix_fmt yuv420p {tmp}',
                   shell=True)
    return tmp


def measure(stream, sample=1):
    """返回 框高序列 / 每帧人数 / 活跃度序列"""
    from ultralytics import YOLO
    m = YOLO(WEIGHT)
    res = m.track(stream, stream=True, classes=[0], conf=0.30, verbose=False)
    h_med, npf = [], []
    for i, r in enumerate(res):
        if r.boxes is None or len(r.boxes) == 0:
            h_med.append(np.nan); npf.append(0); continue
        xy = r.boxes.xyxy.tolist()
        hs = sorted(xy[j][3] - xy[j][1] for j in range(len(xy)))
        h_med.append(hs[len(hs) // 2])       # 每帧 person 框高中位(抗离群)
        npf.append(len(xy))
    return np.array(h_med, dtype=float), np.array(npf, dtype=float)


def activity_of(stream):
    cap = cv2.VideoCapture(stream)
    fps = cap.get(cv2.CAP_PROP_FPS)
    prev = None; act = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        if prev is not None:
            act.append(float(np.mean(cv2.absdiff(g, prev))))
        prev = g
    cap.release()
    return np.array(act), fps


def find_turnovers(act, low_pct=30, min_gap_s=2.0, fps=SCAN_FPS):
    """活跃度低谷 = 回合间隙（死球/换球权/暂停）"""
    thr = np.percentile(act, low_pct)
    below = act < thr
    runs, cur = [], None
    for j, b in enumerate(below):
        if b:
            cur = [j, j] if cur is None else [cur[0], j]
        else:
            if cur is not None:
                runs.append(cur); cur = None
    if cur:
        runs.append(cur)
    pts = [int((a + b) / 2) for a, b in runs if (b - a) >= 1]
    # 合并过近的
    merged = []
    for p in pts:
        if merged and (p - merged[-1]) / fps < min_gap_s:
            continue
        merged.append(p)
    return merged, thr


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 600.0
    out = sys.argv[4] if len(sys.argv) > 4 else "/tmp/turnovers.json"
    tmp = "/tmp/_poss_v2_stream.mp4"

    print(f"抽流 {t0}~{t0+dur}s ...", flush=True)
    make_stream(src, t0, dur, tmp)
    print("跑检测 ...", flush=True)
    h, npf = measure(tmp)
    act, fps = activity_of(tmp)
    n = min(len(h), len(act) - 1)
    h, npf, act = h[:n], npf[:n], act[:n]
    ts = np.arange(n) / fps + t0
    print(f"  采样 {n} 点  框高中位 {np.nanmedian(h):.1f}(低分)  "
          f"活跃度中位 {np.median(act):.1f}")

    ov, thr = find_turnovers(act)
    bounds = [0] + ov + [n]
    print(f"  回合间隙 {len(ov)} 个  阈值 {thr:.1f}  ⇒ 切出 {len(bounds)-1} 段")

    cands = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        seg_h = h[a:b]; seg_a = act[a:b]; seg_n = npf[a:b]
        valid = ~np.isnan(seg_h)
        if valid.sum() < 10:
            continue
        sh = seg_h[valid]
        s, e = ts[a], ts[b - 1]
        dur_s = e - s
        rec = {"seg": k, "start": round(float(s), 1), "end": round(float(e), 1),
               "dur": round(dur_s, 1),
               "h_min": round(float(np.percentile(sh, 10)), 1),
               "h_med": round(float(np.nanmedian(sh)), 1),
               "h_max": round(float(np.percentile(sh, 90)), 1),
               "people_med": round(float(np.nanmedian(seg_n)), 1),
               "act_med": round(float(np.median(seg_a)), 1),
               "act_max": round(float(seg_a.max()), 1)}
        # 镜头序列判据：有远景(帧最低框高小) + 有特写(帧最高框高大) + 时长够
        rec["has_wide"] = rec["h_min"] < 95.0        # 低分率框高≈1080p 的 95*2.25≈214px
        rec["has_close"] = rec["h_max"] > 130.0
        rec["long_enough"] = dur_s >= 12.0
        rec["pass"] = rec["has_wide"] and rec["has_close"] and rec["long_enough"]
        cands.append(rec)

    good = [c for c in cands if c["pass"]]
    print(f"\n=== 含远景+特写+时长≥12s 的回合段：{len(good)}/{len(cands)} ===")
    print(f"{'起':<8}{'止':<8}{'时长':<7}{'框高min':<9}{'中位':<8}{'max':<8}{'人/帧':<7}{'远':<5}{'特':<5}合格")
    for c in sorted(good, key=lambda x: -x["dur"])[:20]:
        print(f"{c['start']:<8}{c['end']:<8}{c['dur']:<7}{c['h_min']:<9}{c['h_med']:<8}"
              f"{c['h_max']:<8}{c['people_med']:<7}"
              f"{'✓' if c['has_wide'] else '✗':<5}{'✓' if c['has_close'] else '✗':<5}✓")
    print("\n=== 被判不合格的段（对照用）===")
    bad = [c for c in cands if not c["pass"]]
    print(f"{'起':<8}{'止':<8}{'时长':<7}{'框高min':<9}{'中位':<8}{'max':<8}不合格原因")
    for c in sorted(bad, key=lambda x: -x["dur"])[:10]:
        r = []
        if not c["has_wide"]: r.append("缺远景")
        if not c["has_close"]: r.append("缺特写")
        if not c["long_enough"]: r.append("时长<12s")
        print(f"{c['start']:<8}{c['end']:<8}{c['dur']:<7}{c['h_min']:<9}{c['h_med']:<8}"
              f"{c['h_max']:<8}{'、'.join(r)}")

    json.dump({"src": os.path.basename(src), "t0": t0, "dur": dur,
               "scale": SCALE, "fps": fps,
               "candidates": cands, "good": good},
              open(out, "w"), ensure_ascii=False, indent=1)
    print("\nwrote", out)
