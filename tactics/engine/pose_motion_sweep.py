#!/usr/bin/env python3
"""动作信号对齐检验的**参数稳健性扫描** —— 防止「挑出显著的那一格」。

🔴 为什么必须有这个脚本（本轮教训）：
    `pose_motion.py` v2 在默认参数（half_win=1.5, air=0.15）下给出
    「4 次跳跃、命中 4/5 个 PBP 事件、p = 0.0415 → 显著」。
    单看这一格会直接写成正向结论。但**参数是人为选的**，
    在 15 个合理组合里只要有 1 格 p<0.05，就与 α=0.05 下的偶然率（期望 0.75 格）
    没有区别 —— 这叫**花园小径（garden of forking paths）**。
    本脚本把扫描结果**整体**落盘并统计"显著格数 / 总格数"，
    只有当显著比例明显高于 α 时才允许说"稳健"。

用法:
  pose_motion_sweep.py <pose_cache> <frames> <possession> <clock_table> <out.json>
                       [--half-wins 1.0,1.5,2.0,2.5,3.0] [--airs 0.10,0.15,0.20]
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import statistics
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pose_motion as PM  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pose_cache")
    ap.add_argument("frames_json")
    ap.add_argument("possession_json")
    ap.add_argument("clock_table")
    ap.add_argument("out_json")
    ap.add_argument("--half-wins", default="1.0,1.5,2.0,2.5,3.0")
    ap.add_argument("--airs", default="0.10,0.15,0.20")
    ap.add_argument("--n-perm", type=int, default=2000)
    a = ap.parse_args()

    hws = [float(x) for x in a.half_wins.split(",")]
    airs = [float(x) for x in a.airs.split(",")]
    tmpdir = tempfile.mkdtemp(prefix="pm_sweep_")

    rows = []
    for hw, air in itertools.product(hws, airs):
        out = os.path.join(tmpdir, f"pm_{hw}_{air}.json")
        argv = ["pose_motion.py", a.pose_cache, a.frames_json, a.possession_json,
                a.clock_table, out, "--half-win", str(hw), "--air", str(air),
                "--n-perm", str(a.n_perm)]
        old = sys.argv
        sys.argv = argv
        try:
            PM.main()                      # 让它打印，扫描过程可审计
        finally:
            sys.argv = old
        d = json.load(open(out))
        al = d["alignment"]
        rows.append({
            "half_win": hw, "air_thr": air,
            "n_jumps": d["counts"]["n_jumps"],
            "jump_rate_per_sec": d["jump_rate_per_sec"],
            "obs_hits": al["jumps"]["observed_hits"],
            "null_mean": al["jumps"]["null_mean"],
            "p_jumps": al["jumps"]["p_value"],
            "sig_jumps": al["jumps"]["significant_at_0.05"],
            "p_contests": al["contests"]["p_value"],
            "n_contests": d["counts"]["n_contests"],
        })
        print(f"  hw={hw} air={air}  跳跃={rows[-1]['n_jumps']:>3}  "
              f"rate={rows[-1]['jump_rate_per_sec']:.3f}/s  "
              f"命中={rows[-1]['obs_hits']}/5  p={rows[-1]['p_jumps']:.4f}  "
              f"{'✅' if rows[-1]['sig_jumps'] else '⚠️'}")

    n_sig = sum(1 for r in rows if r["sig_jumps"])
    n_tot = len(rows)
    res = {
        "_about": "动作信号（骨架 air_dyn 局部极大）与 PBP 事件对齐检验的参数扫描。"
                  "用于判定单格显著性是否为花园小径。",
        "design": {"half_wins": hws, "air_thresholds": airs, "n_perm": a.n_perm,
                   "seed": 20260926},
        "rows": rows,
        "summary": {
            "n_cells": n_tot,
            "n_significant": n_sig,
            "significant_share": round(n_sig / n_tot, 4),
            "expected_share_under_alpha0.05": 0.05,
            "verdict": ("稳健：显著比例明显高于 α" if n_sig / n_tot >= 0.30 else
                        "⚠️ 不稳健：显著格数与 α=0.05 下的偶然期望无实质差别"),
        },
    }
    with open(a.out_json, "w") as fp:
        json.dump(res, fp, ensure_ascii=False, indent=1)
    s = res["summary"]
    print(f"\n[扫描] {s['n_significant']}/{s['n_cells']} 格显著 "
          f"（比例 {s['significant_share']:.3f}，α=0.05 下期望 {s['expected_share_under_alpha0.05']}）")
    print(f"[判定] {s['verdict']}")
    print(f"[out] {a.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
