#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR 调用链路诊断 v2：改用项目目录作为中间文件落点（/tmp 在 sandbox 里子进程不可见）。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import os
import subprocess
import sys
import time

import cv2
import numpy as np

from common.nba_paths import data_file

TESS = "/opt/homebrew/bin/tesseract"
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")


def probe(img, psm, tag):
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)
    p = os.path.join(SCRATCH, "ocr_in.png")
    ok = cv2.imwrite(p, img)
    sz = os.path.getsize(p) if os.path.exists(p) else -1
    t0 = time.time()
    try:
        r = subprocess.run([TESS, p, "stdout", "--psm", str(psm)],
                           capture_output=True, timeout=30)
        dt = time.time() - t0
        so = r.stdout.decode("utf-8", "ignore").strip()
        se = r.stderr.decode("utf-8", "ignore").strip()
        print(f"[{tag}] psm={psm} imwrite={ok} size={sz} rc={r.returncode} {dt:.2f}s")
        print(f"        stdout({len(so)})={so[:120]!r}")
        if se:
            print(f"        stderr={se[:100]!r}")
        return so
    except subprocess.TimeoutExpired:
        print(f"[{tag}] TIMEOUT {time.time()-t0:.1f}s")
        return None
    except Exception as e:
        print(f"[{tag}] EXC {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    print("cwd:", os.getcwd())
    print("SCRATCH:", SCRATCH)
    # 1) 合成图
    syn = np.full((300, 900), 255, np.uint8)
    cv2.putText(syn, "24", (100, 210), cv2.FONT_HERSHEY_SIMPLEX, 6.0, 0, 12)
    probe(syn, 11, "合成图")
    # 2) 视频帧：ffmpeg 直接写 SCRATCH，主进程读
    src = str(data_file("比赛录像/2025-26/25-26常规赛/2025.12/2025.12.17 NBA杯决赛 马刺 vs 尼克斯/2025.12.17 NBA杯 马刺 vs 尼克斯 上半场.mp4"))
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)
    mp4 = os.path.join(SCRATCH, "f.mp4")
    r = subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss 456 -i "{src}" '
                       f'-frames:v 1 -vf "scale=960:540" "{mp4}"', shell=True,
                       capture_output=True)
    print(f"\nffmpeg rc={r.returncode} err={r.stderr.decode()[:200]!r}")
    print("mp4 exists:", os.path.exists(mp4), os.path.getsize(mp4) if os.path.exists(mp4) else -1)
    fr = cv2.imread(mp4)
    print("cv2.imread:", None if fr is None else fr.shape)
    if fr is not None:
        probe(fr, 11, "视频帧")
        probe(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), 11, "视频帧灰度")
