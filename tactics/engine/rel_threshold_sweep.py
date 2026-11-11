#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rel_threshold_sweep.py — 在本工况（YOLO 框 + pair_weight=1 + 纯关系分）下扫 holding/hitting 阈值。

为什么必须自己扫
----------------
官方 `thresholds.json` 的 regime 是 `boxes=gt, pair_weight=0`，
推荐工作点 ≈0.98；而本系统实测 max 只有 0.51 量级 —— **不是同一工况，不可直接搬用**。

口径（🔴 必须写清楚，否则会被误读成"精度"）
------------------------------------------
参照 = `poss_track_id`，其定义是「距球框矩形最近的球员」= **纯几何**。
因此本扫描标定的是「关系通道在多大分数上能复现几何」，**不是**对真值持球人的精度。
它的用途是：给关系通道一个**可操作的工作点**，使其可作为几何的**独立第二通道**互证。

用法
----
  python engine/rel_threshold_sweep.py [--channel 35|native|both] [--grid 0.05..0.95:0.05]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / den
    return (max(0.0, c - h), min(1.0, c + h))


def sweep(records, key, lo=0.05, hi=0.95, step=0.05):
    """records: [{poss, cand35|candN}]。返回逐阈值 P/R/F1 + 最佳 F1 工作点。"""
    N = len(records)
    rows = []
    t = lo
    while t <= hi + 1e-9:
        tp = fp = 0
        for r in records:
            cand = r.get(key) or []
            hit = [c for c in cand if c["score"] >= t]
            if not hit:
                continue
            top = max(hit, key=lambda c: c["score"])
            if top["sub"] == str(r["poss"]):
                tp += 1
            else:
                fp += 1
        P = tp / (tp + fp) if (tp + fp) else 0.0
        R = tp / N if N else 0.0
        F = 2 * P * R / (P + R) if (P + R) else 0.0
        rows.append({"thr": round(t, 3), "tp": tp, "fp": fp, "fn": N - tp,
                     "precision": round(P, 3), "recall": round(R, 3), "f1": round(F, 3)})
        t += step
    best = max(rows, key=lambda r: (r["f1"], r["recall"])) if rows else None
    return rows, best


def score_split(records, key):
    """正确边 vs 错误边的分数分布（用于看阈值是否真有区分度）。"""
    ok, bad = [], []
    for r in records:
        for c in (r.get(key) or []):
            (ok if c["sub"] == str(r["poss"]) else bad).append(c["score"])
    def st(v):
        if not v:
            return None
        s = sorted(v)
        return {"n": len(v), "min": round(s[0], 4), "p50": round(s[len(s) // 2], 4),
                "max": round(s[-1], 4)}
    return {"correct": st(ok), "wrong": st(bad)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="both", choices=["35", "native", "both"])
    ap.add_argument("--lo", type=float, default=0.05)
    ap.add_argument("--hi", type=float, default=0.95)
    ap.add_argument("--step", type=float, default=0.05)
    a = ap.parse_args()

    rep = json.loads((AW / "validate" / "rel_handler_validate.json").read_text())
    recs = [r for blk in rep["clips"].values() for r in blk["records"]]
    n_by_clip = {c: len(b["records"]) for c, b in rep["clips"].items()}
    print(f"验证帧 {len(recs)}  {n_by_clip}")
    print(f"参照 = poss_track_id（几何最近球员）；随机基线 ≈ {1/max(1,recs[0]['n_player']):.3f}")
    print()

    out = {"n_frames": len(recs), "reference": "poss_track_id (geometric nearest player)",
           "channels": {}}
    for ch, key, name in (("35", "cand35", "官方35 holding/carrying/using → BALL"),
                          ("native", "candN", "native hitting → BALL")):
        if a.channel not in ("both", ch):
            continue
        rows, best = sweep(recs, key, a.lo, a.hi, a.step)
        print(f"=== {name} ===")
        print(f"{'thr':>6} {'TP':>4} {'FP':>4} {'FN':>4} {'P':>7} {'R':>7} {'F1':>7}")
        for r in rows:
            mark = " ★" if best and r["thr"] == best["thr"] else ""
            print(f"{r['thr']:>6} {r['tp']:>4} {r['fp']:>4} {r['fn']:>4} "
                  f"{r['precision']:>7.3f} {r['recall']:>7.3f} {r['f1']:>7.3f}{mark}")
        lo95, hi95 = wilson(best["tp"], best["tp"] + best["fp"]) if best else (0, 0)
        print(f"→ best_f1 工作点 thr={best['thr']}  F1={best['f1']}  "
              f"P={best['precision']} (95%CI {lo95:.3f}–{hi95:.3f})  R={best['recall']}")
        print(f"→ 正确/错误边分数分布: {score_split(recs, key)}")
        print()
        out["channels"][ch] = {"name": name, "rows": rows, "best": best,
                               "best_precision_ci95": [round(lo95, 3), round(hi95, 3)],
                               "score_split": score_split(recs, key)}

    p = AW / "validate" / "rel_threshold_sweep.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[写盘] {p}")


if __name__ == "__main__":
    main()
