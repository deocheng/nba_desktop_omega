#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为什么 ep16 不是完整配合？—— 用**活跃度曲线形态**找可证伪判据。
老程裁定真值：ep19(ghost)=✅  ep15(stagger)=✅  ep16(wedge)=❌
假设：完整配合 = [组织(低)→执行(高)→终结]，活跃度应有"低谷后显著上升"；
     单调递减 = 剪到配合尾部/或非配合。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import os
import subprocess
import sys

import cv2
import numpy as np

from common.nba_paths import data_file, tactics_data_file

FF = str(tactics_data_file("clips/tactics_notes_pick"))
TMP = "/tmp/_shape.mp4"


def activity(src, t0, dur, bin_s=0.5):
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
                   f'-t {dur} -an -c:v libx264 -preset veryfast -crf 22 '
                   f'-pix_fmt yuv420p {TMP}', shell=True)
    cap = cv2.VideoCapture(TMP)
    fps = cap.get(cv2.CAP_PROP_FPS)
    step = max(1, int(fps * bin_s))
    prev, vals = None, []
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(fr, None, fx=0.25, fy=0.25), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            vals.append(float(np.mean(cv2.absdiff(g, prev))))
        prev = g
        i += 1
    cap.release()
    binned = [float(np.mean(vals[j:j + step])) for j in range(0, len(vals) - step + 1, step)]
    return np.array(binned)


def shape_features(a):
    """形态特征：是否存在'低谷后显著上升'（组织→执行）"""
    if len(a) < 4:
        return None
    # 去掉首个 bin（常含切镜尖峰）
    b = a[1:] if len(a) > 4 else a
    peak_i = int(np.argmax(b))
    trough_i = int(np.argmin(b[:peak_i + 1])) if peak_i > 0 else 0
    rise = b[peak_i] - b[trough_i]
    ratio = rise / (b[trough_i] + 1e-6)
    # 单调递减检验：Spearman 类似 —— 递减 bin 占比
    dec = sum(1 for j in range(1, len(b)) if b[j] < b[j - 1])
    dec_frac = dec / (len(b) - 1)
    return {"peak_bin": peak_i, "trough_bin": trough_i,
            "trough": round(float(b[trough_i]), 2),
            "peak": round(float(b[peak_i]), 2),
            "rise": round(float(rise), 2),
            "rise_ratio": round(float(ratio), 2),
            "dec_frac": round(dec_frac, 2),
            "has_setup_then_exec": bool(trough_i < peak_i and rise > 3.0)}


CASES = [
    ("ep19 ghost ✅", str(data_file("NBA战术笔记/第19期：看探花秀亨德森如何巧妙利用“Ghostscreen”.mp4")), 77.9, 6.6),
    ("ep15 stagger ✅", str(data_file("NBA战术笔记/第15期：总决赛G2热火队的“Staggerscreen”战术让射手群完美参团.mp4")), 97.6, 5.8),
    ("ep16 wedge ❌", str(data_file("NBA战术笔记/第16期：布劳恩如何发起小个给大个掩护的“wedgescreen”战术.mp4")), 95.4, 5.6),
]

print(f"{'样本':<20}{'曲线(每0.5s)':<52}形态")
print("-" * 100)
res = []
for name, src, t0, dur in CASES:
    a = activity(src, t0, dur)
    f = shape_features(a)
    res.append((name, f))
    curve = " ".join(f"{v:.0f}" for v in a)
    flag = "✅有组织→执行" if f["has_setup_then_exec"] else "❌无上升段"
    print(f"{name:<20}{curve:<52}{flag}")
    print(f"{'':<20}低谷bin{f['trough_bin']}({f['trough']}) 峰bin{f['peak_bin']}({f['peak']}) "
          f"升幅={f['rise']} 倍数={f['rise_ratio']} 递减占比={f['dec_frac']}")

print("\n=== 判据可分性检验 (n=3，样本极小，仅作候选) ===")
for name, f in res:
    exp = "✅" if "✅" in name else "❌"
    got = "✅" if f["has_setup_then_exec"] else "❌"
    print(f"  {name:<20} 真值={exp}  判据={got}  {'一致' if exp == got else '❌不一致'}")
