#!/usr/bin/env python3
"""占有权参数扫描（从 ball_tracks.json 重算，不重复跑模型）。

为什么需要
----------
「距球最近的球员」在 10fps 上会频繁易主（传球、贴身争抢、检测抖动），
直接用它当「球权」会把一个回合切成十几段。本脚本在**同一份检测/跟踪结果**上
重算占有权，扫 (poss_radius × hysteresis) 网格，用「段数是否落进真实回合量级」
来判定参数是否可用——而不是挑一个好看的数字。

真实量级参照：NBA 单回合 ~14–24s；本素材 4 个窗口合计 178.5s 运行时间
≈ 8–13 个球队回合（每次投篮/失误/篮板换一次球权）。

用法: poss_sweep.py <w1_poss> <w2_poss> ... [--out poss_sweep.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def pt_to_rect(bx, by, box):
    """球心到球员框矩形的距离（框内=0）。"""
    x1, y1, x2, y2 = box
    dx = max(x1 - bx, 0.0, bx - x2)
    dy = max(y1 - by, 0.0, by - y2)
    return (dx * dx + dy * dy) ** 0.5


def assign(ball_box, players, radius_frac, diag):
    bx = (ball_box[0] + ball_box[2]) / 2.0
    by = (ball_box[1] + ball_box[3]) / 2.0
    best, bd = None, 1e18
    for p in players:
        d = pt_to_rect(bx, by, p["bbox"])
        if d < bd:
            bd, best = d, p
    if best is not None and bd <= radius_frac * diag:
        return best["track_id"]
    return None


def hysteresis(raw, k):
    if k <= 0:
        return list(raw)
    out = list(raw)
    cur, pend, pc = None, None, 0
    for i, p in enumerate(raw):
        if p == cur:
            pend, pc = None, 0
        else:
            if p == pend:
                pc += 1
            else:
                pend, pc = p, 1
            if pc >= k:
                cur, pend, pc = p, None, 0
        out[i] = cur
    return out


def rle(seq):
    segs = []
    for i, v in enumerate(seq):
        if v is None:
            continue
        if segs and segs[-1]["track_id"] == v and segs[-1]["end"] == i - 1:
            segs[-1]["end"] = i
            segs[-1]["n"] += 1
        else:
            segs.append({"track_id": v, "start": i, "end": i, "n": 1})
    return segs


def load(path):
    d = json.loads(Path(path, "ball_tracks.json").read_text())
    return d


def run(tracks, radius_frac, hyst, diag):
    raw = []
    for fr in tracks:
        b = fr.get("ball")
        if not b or "bbox" not in b:
            raw.append(None)
            continue
        raw.append(assign(b["bbox"], fr.get("players", []), radius_frac, diag))
    sm = hysteresis(raw, hyst)
    return raw, sm, rle(sm)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("poss_dirs", nargs="+")
    ap.add_argument("--diag", type=float, default=0.0,
                    help="0=用 1920x1080 对角；窗口帧尺寸不一致时显式给")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    diag = a.diag if a.diag > 0 else (1920 ** 2 + 1080 ** 2) ** 0.5
    radii = [0.025, 0.035, 0.05, 0.07]
    hysts = [1, 3, 6, 10, 15, 25]
    total_sec = 0.0
    data = {}
    for p in a.poss_dirs:
        name = Path(p).name.replace("_poss", "")
        tr = load(p)
        n = len(tr)
        total_sec += n * 0.1
        data[name] = tr

    print(f"对角 diag={diag:.0f}px   合计运行时间 {total_sec:.1f}s "
          f"（NBA 真实回合量级 ≈ {total_sec/24:.0f}–{total_sec/14:.0f} 次球权）\n")
    print(f"{'radius':>7} {'hyst':>5} | " +
          " ".join(f"{k:>6}" for k in data) + " | {'总段数':>6} {'覆盖%':>6} {'中位段长':>8}")

    cells = []
    for r in radii:
        for h in hysts:
            tot = 0
            cov_num = cov_den = 0
            all_lens = []
            per = {}
            for name, tr in data.items():
                raw, sm, segs = run(tr, r, h, diag)
                per[name] = len(segs)
                tot += len(segs)
                cov_num += sum(1 for v in sm if v is not None)
                cov_den += len(sm)
                all_lens += [s["n"] for s in segs]
            med = statistics.median(all_lens) if all_lens else 0
            cov = cov_num / cov_den if cov_den else 0
            cells.append({"radius": r, "hyst": h, "per_window": per,
                          "total_segments": tot, "coverage": round(cov, 4),
                          "median_len_frames": med})
            print(f"{r:>7} {h:>5} | " +
                  " ".join(f"{per[k]:>6}" for k in data) +
                  f" | {tot:>6} {cov*100:>5.1f}% {med:>8.0f}")

    if a.out:
        Path(a.out).write_text(json.dumps(
            {"diag": round(diag, 1), "total_sec": round(total_sec, 1),
             "windows": list(data), "cells": cells}, indent=1))
        print(f"\n[写] {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
