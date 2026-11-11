#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.9c Top-K 选池 跨段复验（A4.60 教训：不可拿单段当结论）。

判据不是「ID 数」，而是用**独立尺子**验证选池质量：
  尺子 = 脚点是否落在球场地面掩膜内（court_filter，与「运动量」完全独立的信号）。
  若 Top-K 真的挑中了场上的人，则 Top13 的 on_court 比例应显著高于被丢弃组。

同时记录边界间隔（第 K 名 vs 第 K+1 名）分布 —— 间隔越小，说明排序在边界处越接近噪声。

用法:
  topk_crossseg_validate.py --segs ep24_s1,ep1_s0,ep10_s0,ep12_s0,ep5_s1,ep19_s0 [--k 13] [--vis 0]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
sys.path.insert(0, str(ROOT / "engine"))
from court_filter import _foot, court_mask  # noqa: E402

TH, FRAC = 12, 0.6


def gray(f):
    im = cv2.imread(str(f))
    return None if im is None else cv2.GaussianBlur(
        cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (5, 5), 0)


def motion(da, box, frac):
    H, W = da.shape
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    a1 = max(0, int(cx - w * frac / 2)); a2 = min(W, int(cx + w * frac / 2))
    b1 = max(0, int(cy - h * frac / 2)); b2 = min(H, int(cy + h * frac / 2))
    if a2 - a1 < 3 or b2 - b1 < 3:
        return 0.0
    return float((da[b1:b2, a1:a2] > TH).mean())


def seg_mask(files, cache):
    """镜头基本静止(A5.1 探针①: 位移中位 0.29px) ⇒ 场地掩膜整段算一次即可复用。"""
    for f in cache.get("files", [])[:1]:
        pass
    if "m" in cache:
        return cache["m"]
    m = None
    for f in files[:: max(1, len(files) // 12)][:12]:
        im = cv2.imread(str(f))
        if im is None:
            continue
        r = court_mask(im)
        if r is not None and r[0] is not None:
            m = r[0]
            break
    cache["m"] = m
    return m


def run_one(seg, k, tr_name="tracks.json"):
    d = SEGD / seg
    tp = d / tr_name
    if not tp.exists():
        return None
    files = sorted((d / "frames").glob("f*.jpg"))
    tr = json.load(open(tp))
    cache = {}
    m = seg_mask(files, cache)
    if m is None:
        return {"seg": seg, "err": "court_mask 不可靠(整段无可用掩膜)"}

    rows = []
    prev = None
    for fr in tr["frames"]:
        idx = fr["idx"]
        if idx == 0 or idx >= len(files):
            continue
        g = gray(files[idx])
        pg = gray(files[idx - 1]) if (prev is None or prev[0] != idx - 1) else prev[1]
        if g is None or pg is None:
            continue
        da = cv2.absdiff(g, pg)
        items = []
        for p in fr.get("players", []):
            box = p["box"]
            x1, y1, x2, y2 = [int(v) for v in box]
            fx, fy = _foot(box)
            onc = 0
            if 0 <= int(fx) < m.shape[1] and 0 <= int(fy) < m.shape[0]:
                onc = 1 if m[int(fy), int(fx)] > 0 else 0
            items.append({"m": motion(da, box, FRAC), "h": y2 - y1, "fy": fy, "onc": onc})
        if not items:
            continue
        items.sort(key=lambda x: -x["m"])
        sel, rest = items[:k], items[k:]
        if not rest:
            continue
        # 独立对照尺子①：按「框高」排序（尺寸先验），看两把排序选出的池重合多少
        by_h = sorted(items, key=lambda x: -x["h"])[:k]
        sel_idx = set(id(x) for x in sel)
        overlap = sum(1 for x in by_h if id(x) in sel_idx)
        # 独立对照尺子②：motion-Top13 与 height-Top13 的框高/脚点差异（不依赖任何掩膜）
        rows.append({
            "n": len(items),
            "gap": sel[-1]["m"] - rest[0]["m"],
            "sel_onc": float(np.mean([i["onc"] for i in sel])),
            "rest_onc": float(np.mean([i["onc"] for i in rest])),
            "sel_h": float(np.median([i["h"] for i in sel])),
            "rest_h": float(np.median([i["h"] for i in rest])),
            "sel_fy": float(np.median([i["fy"] for i in sel])),
            "rest_fy": float(np.median([i["fy"] for i in rest])),
            "h_overlap": float(overlap / k),
            "h_sel_h": float(np.median([i["h"] for i in by_h])),
        })
        prev = (idx, g)
    if not rows:
        return None
    g_ = np.array([r["gap"] for r in rows])
    base = np.array([r["sel_onc"] for r in rows])  # 保留：相对间隔用 topk_min 无法在此存，改用 gap/sel_h 近似
    return {
        "seg": seg, "n_frames": len(rows),
        "n_det_med": float(np.median([r["n"] for r in rows])),
        "gap_med": float(np.median(g_)),
        "gap_pos_frac": float((g_ > 0).mean()),
        "gap_lt005_frac": float((g_ < 0.005).mean()),
        "sel_onc": float(np.mean([r["sel_onc"] for r in rows])),
        "rest_onc": float(np.mean([r["rest_onc"] for r in rows])),
        "sel_h": float(np.median([r["sel_h"] for r in rows])),
        "rest_h": float(np.median([r["rest_h"] for r in rows])),
        "sel_fy": float(np.median([r["sel_fy"] for r in rows])),
        "rest_fy": float(np.median([r["rest_fy"] for r in rows])),
        "h_overlap": float(np.mean([r["h_overlap"] for r in rows])),
        "h_sel_h": float(np.median([r["h_sel_h"] for r in rows])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segs", default="ep24_s1,ep1_s0,ep10_s0,ep12_s0,ep5_s1,ep19_s0")
    ap.add_argument("--k", type=int, default=13)
    ap.add_argument("--src", default="tracks.json")
    a = ap.parse_args()

    out = []
    print(f"{'段':<10}{'帧':>5}{'检测数':>7}{'间隔中位':>9}{'>0%':>7}{'<0.005%':>9}"
          f"{'TopK框高':>9}{'丢弃框高':>9}{'TopK脚y':>9}{'丢弃脚y':>9}"
          f"{'与框高TopK重合':>14}{'[尺子坏]在场':>13}{'丢弃在场':>10}")
    for seg in a.segs.split(","):
        seg = seg.strip()
        r = run_one(seg, a.k, a.src)
        if r is None:
            print(f"{seg:<10}  (跳过: 无 tracks/无帧)")
            continue
        if "err" in r:
            print(f"{seg:<10}  {r['err']}")
            out.append(r)
            continue
        out.append(r)
        print(f"{seg:<10}{r['n_frames']:>5}{r['n_det_med']:>7.0f}{r['gap_med']:>9.4f}"
              f"{r['gap_pos_frac']*100:>7.1f}{r['gap_lt005_frac']*100:>9.1f}"
              f"{r['sel_h']:>9.0f}{r['rest_h']:>9.0f}{r['sel_fy']:>9.0f}{r['rest_fy']:>9.0f}"
              f"{r['h_overlap']*100:>13.1f}%{r['sel_onc']*100:>12.1f}%{r['rest_onc']*100:>9.1f}%")

    ok = [r for r in out if "sel_onc" in r]
    if ok:
        print(f"\n跨 {len(ok)} 段均值（不依赖掩膜的独立尺子）:")
        dh = np.array([r["sel_h"] - r["rest_h"] for r in ok])
        df = np.array([r["sel_fy"] - r["rest_fy"] for r in ok])
        ov = np.array([r["h_overlap"] for r in ok])
        print(f"  TopK框高 - 丢弃框高 : {np.mean(dh):+.0f}px   (6/6 段同向: {int((dh>0).sum())}/6)")
        print(f"  TopK脚y  - 丢弃脚y  : {np.mean(df):+.0f}px   (6/6 段同向: {int((df<0).sum())}/6)")
        print(f"  与「按框高 TopK」的重合率 : {np.mean(ov):.1%}（越低=运动量与尺寸先验分歧越大）")
        print(f"  边界间隔 <0.005 的帧占比 均值 {np.mean([r['gap_lt005_frac'] for r in ok]):.1%}"
              f"  （越大=第K名与第K+1名越接近并列，边界排序越像噪声）")

    op = ROOT / "action_work" / "track_judge" / "topk_crossseg.json"
    json.dump(out, open(op, "w"), ensure_ascii=False, indent=1)
    print(f"\n-> {op}")


if __name__ == "__main__":
    main()
