#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.12c 第 4 条线索：**球衣号码**（老程：「3也有球衣和号码作参考」）。

判据：场上球员/裁判的球衣上有**大号数字**，观众通常没有。
实现：裁出躯干上部号码区 → 放大 ×4 → 灰度/二值 → tesseract 只认数字。
**不引入任何新模型**（tesseract 是传统 OCR，已在 /opt/homebrew/bin/tesseract）。

先看 crown你们的裁定是否自洽：先用老程已裁定的 ep24_s1 f70（4 观众 + #22 球员）做定向验证，
看 OCR 能否把观众(无数码)与球员(有号码)分开。

用法: jersey_ocr_probe.py --seg ep24_s1 --idx 70 [--dump]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
TESS = "/opt/homebrew/bin/tesseract"
sys.path.insert(0, str(ROOT / "engine"))
from court_filter import _foot, court_mask  # noqa: E402

VERDICT = {3: "观众", 8: "观众", 9: "观众", 13: "观众", 22: "★球员(被丢)"}


def prep_roi(img, box, pad=0.0):
    """躯干上部号码区(y 18%–58%, x 22%–78%)，放大 ×4，二值 + 反色两版。"""
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    a1 = max(0, int(x1 + 0.22 * w)); a2 = min(img.shape[1], int(x1 + 0.78 * w))
    b1 = max(0, int(y1 + 0.18 * h)); b2 = min(img.shape[0], int(y1 + 0.58 * h))
    roi = img[b1:b2, a1:a2]
    if roi.size == 0:
        return None
    g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.6, tileGridSize=(8, 8))
    eq = clahe.apply(big)
    return eq


def ocr(grey, psm):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        p = f.name
        cv2.imwrite(p, grey)
    for inv in (False, True):
        if inv:
            cv2.imwrite(p, cv2.bitwise_not(grey))
        else:
            cv2.imwrite(p, grey)
        try:
            r = subprocess.run(
                [TESS, p, "stdout", "--psm", str(psm), "-l", "eng",
                 "-c", "tessedit_char_whitelist=0123456789"],
                capture_output=True, text=True, timeout=20)
            txt = "".join(ch for ch in r.stdout if ch.isdigit())
            if txt:
                return txt
        except Exception as e:
            return None
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    a = ap.parse_args()

    seg_d = SEGD / a.seg
    items = json.load(open(OUT / f"{a.seg}_f{a.idx}.json"))
    files = sorted((seg_d / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    r = court_mask(img)
    m = r[0] if r and r[0] is not None else None

    def oncourt(b):
        fx, fy = _foot(b)
        return m is not None and 0 <= fx < m.shape[1] and 0 <= fy < m.shape[0] and m[fy, fx] > 0

    print(f"=== {a.seg} f{a.idx}  球衣号码 OCR ===")
    print(f"{'#':>4}{'框H':>6}{'场上':>5}{'号码':>9}{'老程裁定':>12}")
    res = {}
    for it in items:
        roi = prep_roi(img, it["box"])
        if roi is None:
            continue
        best = ""
        for psm in (7, 8, 10):
            t = ocr(roi, psm)
            if t and len(t) > len(best):
                best = t
        res[it["no"]] = best
        it["jersey"] = best
        print(f"{it['no']:>4}{it['h']:>6}{'是' if oncourt(it['box']) else '否':>5}"
              f"{best or '—':>9}{VERDICT.get(it['no'], ''):>12}")

    # 判别力检查
    sp = [res.get(n, "") for n in (3, 8, 9, 13)]
    pl = [res.get(n, "") for n in (1, 2, 4, 5, 6, 7, 10, 11, 12, 22)]
    hit_spec = sum(1 for s in sp if s)
    hit_play = sum(1 for s in pl if s)
    print(f"\n观众 4 人里 OCR 出号码: {hit_spec}/4  （越低越好）")
    print(f"球员 10 人里 OCR 出号码: {hit_play}/10  （越高越好）")
    json.dump(items, open(OUT / f"{a.seg}_f{a.idx}_jersey.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n-> {OUT / f'{a.seg}_f{a.idx}_jersey.json'}")


if __name__ == "__main__":
    main()
