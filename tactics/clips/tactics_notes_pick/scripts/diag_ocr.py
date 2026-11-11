#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR 调用链路诊断：定位「脚本内 subprocess 返回空」的根因。"""
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


def probe(img, psm, tag):
    p = "/tmp/_diag_ocr.png"
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
        print(f"        stdout({len(so)})={so[:100]!r}")
        print(f"        stderr={se[:80]!r}")
        return so
    except subprocess.TimeoutExpired:
        print(f"[{tag}] psm={psm} TIMEOUT after {time.time()-t0:.1f}s")
        return None
    except Exception as e:
        print(f"[{tag}] EXC {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    print("cwd:", os.getcwd())
    print("tess exists:", os.path.exists(TESS))
    src = str(data_file("比赛录像/2025-26/25-26常规赛/2025.12/2025.12.17 NBA杯决赛 马刺 vs 尼克斯/2025.12.17 NBA杯 马刺 vs 尼克斯 上半场.mp4"))
    # 自造一张确知有字的图（纯 numpy，无外部依赖）
    syn = np.full((300, 900), 255, np.uint8)
    cv2.putText(syn, "24", (100, 200), cv2.FONT_HERSHEY_SIMPLEX, 6.0, 0, 12)
    cv2.putText(syn, "Nyk 88 SAS 92", (420, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
    cv2.imwrite("/tmp/_diag_syn.png", syn)
    print("合成图 size:", os.path.getsize("/tmp/_diag_syn.png"))
    probe(syn, 11, "合成图")
    probe(syn, 7, "合成图")

    tmp = "/tmp/_diag.mp4"
    subprocess.run(f'ffmpeg -hide_banner -loglevel error -y -ss 456 -i "{src}" '
                   f'-frames:v 1 -vf "scale=960:540" {tmp}', shell=True)
    fr = cv2.imread(tmp)
    print("视频帧:", None if fr is None else fr.shape)
    if fr is not None:
        probe(fr, 11, "视频帧")
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        probe(g, 11, "视频帧灰度")
