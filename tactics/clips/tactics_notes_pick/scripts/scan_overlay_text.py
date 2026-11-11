#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描整场比赛：找出「画面里存在清晰文本叠加层（记分牌）」的时间点。

🔴 两个已踩坑（2026-10-07）：
  ① /tmp 在 Bash sandbox 里**子进程互相不可见** ⇒ tesseract 读 /tmp/*.png 报
     "failed to open locally"，OCR 永远返回空。必须写**项目目录**。
  ② ffmpeg 单帧抽取存 .mp4 ⇒ cv2.imread 读不出（无关键帧）。必须存 .png。
  （两条都已在 diag_ocr2.py 实测确认）

双重用途：
  ① 记分牌出现/消失时刻 → 印证老程判据「记分牌变小 = 中近景关键镜头」
  ② 有记分牌 = 电视标准机位（远/中景），是回合开始的先验

用法：scan_overlay_text.py <src> <t0> <t1> <step> <out_json>
"""
import json
import os
import re
import subprocess
import sys

import cv2
import numpy as np

TESS = "/opt/homebrew/bin/tesseract"
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")


def ensure_dir():
    if not os.path.isdir(SCRATCH):
        os.makedirs(SCRATCH, exist_ok=True)
    return SCRATCH


def grab_seq(src, t0, t1, step, w=960, h=540):
    """一次性抽流（避免逐帧 seek 超时）。"""
    ensure_dir()
    fps = 1.0 / step
    tmp = os.path.join(SCRATCH, "seq.mp4")
    subprocess.run(
        f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{src}" '
        f'-t {t1 - t0} -an -vf "fps={fps:.6f},scale={w}:{h}" '
        f'-c:v libx264 -preset ultrafast -crf 22 -pix_fmt yuv420p -g 1 "{tmp}"',
        shell=True, capture_output=True)
    cap = cv2.VideoCapture(tmp)
    frs = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frs.append(fr)
    cap.release()
    return frs


def ocr(g, psm=11, wl=None):
    """OCR 单图。中间文件必须落在项目目录（见模块 docstring 坑①）。"""
    ensure_dir()
    p = os.path.join(SCRATCH, "ocr_in.png")
    cv2.imwrite(p, g)
    args = [TESS, p, "stdout", "--psm", str(psm)]
    if wl:
        args += ["-c", f"tessedit_char_whitelist={wl}"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.decode("utf-8", "ignore").strip()


def strip_only(fr):
    """只取画面**上下 1/5**（记分牌通常在这两带），提亮后 OCR。"""
    H = fr.shape[0]
    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    top = g[:int(H * 0.22), :]
    bot = g[int(H * 0.78):, :]
    out = []
    for band in (top, bot):
        band = cv2.resize(band, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        band = cv2.createCLAHE(3.0, (8, 8)).apply(band)
        _, b = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        out.append(b)
    return out


if __name__ == "__main__":
    src = sys.argv[1]
    t0 = float(sys.argv[2])
    t1 = float(sys.argv[3])
    step = float(sys.argv[4]) if len(sys.argv) > 4 else 4.0
    out = sys.argv[5] if len(sys.argv) > 5 else "/tmp/overlay_text.json"

    frs = grab_seq(src, t0, t1, step)
    print(f"抽流 {len(frs)} 帧  t0={t0} t1={t1} step={step}s  {frs[0].shape[1]}x{frs[0].shape[0]}")
    if not frs:
        print("无帧！ffmpeg 抽流失败"); sys.exit(1)

    rows = []
    for i, fr in enumerate(frs):
        t = round(t0 + i * step, 1)
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        full = ocr(g, 11)
        top_b, bot_b = strip_only(fr)
        tt = ocr(top_b, 7)
        tb = ocr(bot_b, 7)
        nums_full = re.findall(r"\d+", full or "")
        nums_strip = re.findall(r"\d+", (tt or "") + " " + (tb or ""))
        best = nums_strip if len(nums_strip) >= len(nums_full) else nums_full
        rows.append({"t": t, "full": full or "", "top": tt or "", "bot": tb or "",
                     "nums_full": nums_full, "nums_strip": nums_strip})
        flag = "★" if len(best) >= 2 else ("·" if best else " ")
        print(f"{flag} t={t:<8} full={nums_full} strip={nums_strip} "
              f"{'' if not tt else repr((tt or '')[:40])} {'' if not tb else repr((tb or '')[:40])}")

    hit = [r for r in rows if max(len(r["nums_full"]), len(r["nums_strip"])) >= 2]
    print(f"\n=== 含 ≥2 个数字串的帧: {len(hit)}/{len(rows)} ===")
    for r in hit[:50]:
        print(f"  t={r['t']:<8} full={r['nums_full']} strip={r['nums_strip']} "
              f"{r['top'][:50]!r} {r['bot'][:50]!r}")

    json.dump({"src": os.path.basename(src), "t0": t0, "t1": t1, "step": step,
               "rows": rows}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {out}")
