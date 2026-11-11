#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.15 跨窗口复验驱动：对 ep24_s1 的多个镜头窗口逐帧跑 v3 推断，
量化 containment / coverage / baseline_angle / ratio_dev，输出 JSON 供老程裁定稳健性。

用法：
  python3 run_window_xval.py --seg ep24_s1 \
      --window A 0 93 _tmp_freq_ep24_s1_w0_93.npy \
      --window B 95 154 _tmp_freq_ep24_s1_w95_154.npy
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
import court_infer_lines as C  # noqa: E402

ACC_TH = C.ACC_TH  # 0.7


def window_s_paint(seg, r0, r1):
    """逐帧 estimate_s_paint 取窗口中位数；失败过多时返回 None。"""
    files = sorted((SEGD / seg / "frames").glob("f*.jpg"))
    vals = []
    n_fail = 0
    for idx in range(r0, r1 + 1):
        img = cv2.imread(str(files[idx]))
        v = C.estimate_s_paint(img)
        if v is None:
            n_fail += 1
        else:
            vals.append(v)
    if len(vals) < max(3, (r1 - r0 + 1) * 0.25):
        return None, n_fail, len(vals)
    return float(np.median(vals)), n_fail, len(vals)


def run_window(seg, name, r0, r1, freq_name):
    files = sorted((SEGD / seg / "frames").glob("f*.jpg"))
    sp, n_fail, n_ok = window_s_paint(seg, r0, r1)
    freq_path = OUT / freq_name
    freq = np.load(str(freq_path)) if freq_path.exists() else None
    H, W = cv2.imread(str(files[r0])).shape[:2]
    rows = []
    for idx in range(r0, r1 + 1):
        img = cv2.imread(str(files[idx]))
        poly, lo, info = C.infer(img, seg, freq_name, s_paint_win=sp)
        rec = {"frame": idx, "ok": poly is not None}
        if poly is not None:
            # 自证 containment / coverage
            m = np.zeros((H, W), np.uint8)
            cv2.fillPoly(m, [poly.astype(np.int32)], 255)
            if freq is not None:
                acc = (freq >= ACC_TH).astype(np.uint8)
                n_acc = int(acc.sum())
                cont = float(acc[m > 0].sum()) / max(n_acc, 1)
                cov = float(acc[m > 0].sum()) / max(int((m > 0).sum()), 1)
                info["containment"] = round(100 * cont, 1)
                info["coverage"] = round(100 * cov, 1)
            rec.update({k: info.get(k) for k in (
                "containment", "coverage", "baseline_angle_deg",
                "baseline_n_inlier", "ratio_dev_pct", "s_paint",
                "s_paint_src", "far_src", "ratio")})
        else:
            rec["why"] = info.get("why")
        rows.append(rec)
    ok = [r for r in rows if r["ok"]]
    fail = [r for r in rows if not r["ok"]]
    def med(key):
        xs = [r[key] for r in ok if r.get(key) is not None]
        return round(float(np.median(xs)), 2) if xs else None
    def mn(key):
        xs = [r[key] for r in ok if r.get(key) is not None]
        return round(float(np.min(xs)), 2) if xs else None
    summary = {
        "name": name, "r0": r0, "r1": r1, "n": len(rows),
        "n_ok": len(ok), "n_fail": len(fail),
        "window_s_paint": round(sp, 1) if sp else None,
        "s_paint_est_fail": n_fail, "s_paint_est_ok": n_ok,
        "median_containment": med("containment"),
        "median_coverage": med("coverage"),
        "min_containment": mn("containment"),
        "min_coverage": mn("coverage"),
        "median_baseline_angle": med("baseline_angle_deg"),
        "median_ratio_dev_pct": med("ratio_dev_pct"),
        "min_ratio_dev_pct": mn("ratio_dev_pct"),
        "far_src_counts": _count(ok, "far_src"),
        "s_paint_src_counts": _count(ok, "s_paint_src"),
    }
    # 压线帧（containment<90 或 ratio_dev 超 ±15%）
    tight = [r["frame"] for r in ok
             if (r.get("containment") is not None and r["containment"] < 90)
             or (r.get("ratio_dev_pct") is not None and abs(r["ratio_dev_pct"]) > 15)]
    summary["tight_frames"] = tight
    summary["fail_frames"] = [r["frame"] for r in fail]
    summary["fail_reasons"] = {r["frame"]: r.get("why") for r in fail}
    return rows, summary


def _count(lst, key):
    d = {}
    for r in lst:
        v = r.get(key)
        if v is not None:
            d[v] = d.get(v, 0) + 1
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--window", nargs=4, action="append",
                    metavar=("NAME", "R0", "R1", "FREQ"),
                    help="窗口名/起帧/止帧/累积掩膜npy")
    a = ap.parse_args()
    if not a.window:
        a.window = [("A", "0", "93", "_tmp_freq_ep24_s1_w0_93.npy"),
                    ("B", "95", "154", "_tmp_freq_ep24_s1_w95_154.npy")]
    all_rows = {}
    summaries = []
    for w in a.window:
        name, r0, r1, freq = w
        r0, r1 = int(r0), int(r1)
        rows, summ = run_window(a.seg, name, r0, r1, freq)
        all_rows[name] = rows
        summaries.append(summ)
        print(f"\n=== 窗口 {name} [{r0},{r1}] ===")
        for k, v in summ.items():
            print(f"  {k}: {v}")
    out = {"seg": a.seg, "summaries": summaries, "rows": all_rows}
    jp = OUT / f"{a.seg}_xval_windows.json"
    json.dump(out, open(jp, "w"), ensure_ascii=False, indent=1)
    print(f"\n-> {jp}")


if __name__ == "__main__":
    main()
