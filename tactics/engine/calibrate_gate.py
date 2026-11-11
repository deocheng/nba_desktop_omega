#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calibrate_gate.py — 路径 A 门禁：宽景尺度滤过 + 按域自监督重标定工作点。

设计（防调参造假）
--------------
1. 宽景尺度滤过：1080p 全场画面里真球 bbox 对角 ≈ 25–50px；取 max_px=60（≈2× 中位，物理动机，
   非调出来的超参）。基线四窗 claim 全部 <60px（max 55）⇒ 滤过对基线是**无操作**，向后兼容。
2. 按域重标定：对每个域（片段/窗口）在**固定网格** th∈{0.80,0.85,0.90,0.95,0.975} 上扫，
   选「最低 th 且 可跟踪率≥0.80 且 n_steps≥10（可测）」为工作点。
   —— 统一规则、不按片段挑 th；若网格内无 th 满足 ⇒ 该域 FAIL（诚实报告最佳尝试）。
3. 门禁裁定（同 A4.12 路径 C）：可跟踪率≥0.80 且 中位步长<80px 且 n_steps≥10 ⇒ PASS。

用法
----
  python engine/calibrate_gate.py --scores action_work/validate/sas_hou_scores.json
  python engine/calibrate_gate.py --scores action_work/validate/sas_nop_scores.json \
      --scores action_work/validate/sas_det_scores.json
  python engine/calibrate_gate.py --baseline   # 同时重算基线四窗（验证向后兼容）
  python engine/calibrate_gate.py --all-clips  # 3 片段 + 基线
产出
----
  action_work/validate/gate_calibrated.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
AW = Path(ROOT) / "action_work"
TH_GRID = [0.80, 0.85, 0.90, 0.95, 0.975]
MAX_PX = 60.0          # 宽景球尺度上限（物理动机）
GAP_TOL = 3
SMOOTH_PX = 80.0
Z = 1.96
MIN_STEPS = 10         # 可测下限：步数太少，可跟踪率无统计意义


def wilson(k, n):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def frame_claims_wide(frames, th):
    present = {}
    for fn, cs in frames.items():
        hs = [c for c in cs if c["prob"] > th]
        if not hs:
            continue
        best = max(hs, key=lambda c: c["prob"])
        b = best["bbox"]
        diag = math.hypot(b[2] - b[0], b[3] - b[1])
        if diag >= MAX_PX:
            continue
        num = int(fn[1:6])
        present[num] = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, float(best["prob"]), diag)
    return present


def metrics(present, n_frames):
    nums = sorted(present)
    cov = len(present) / n_frames if n_frames else 0.0
    eps, cur, last = [], [], None
    for f in nums:
        if last is not None and f - last > GAP_TOL + 1 and cur:
            eps.append(cur)
            cur = []
        cur.append(f)
        last = f
    if cur:
        eps.append(cur)
    steps = [math.hypot(present[b][0] - present[a][0], present[b][1] - present[a][1])
             for e in eps for a, b in zip(e, e[1:])]
    if steps:
        med = sorted(steps)[len(steps) // 2]
        k = sum(1 for d in steps if d < SMOOTH_PX)
        tr = k / len(steps)
        lo, hi = wilson(k, len(steps))
    else:
        med, tr, lo, hi = float("nan"), float("nan"), None, None
    return {"n_claims": len(present), "frame_coverage": round(cov, 4),
            "n_episodes": len(eps),
            "mean_episode_len": round(sum(len(e) for e in eps) / len(eps), 2) if eps else 0.0,
            "median_step_px": round(med, 1) if not math.isnan(med) else None,
            "n_steps": len(steps), "trackable_frac": round(tr, 4) if not math.isnan(tr) else None,
            "trackable_ci95": [round(lo, 3), round(hi, 3)] if lo is not None else None}


def calibrate(frames, n_frames):
    per_th = {th: metrics(frame_claims_wide(frames, th), n_frames) for th in TH_GRID}
    chosen = None
    for th in TH_GRID:           # 升序：取最低满足条件的 th（最大召回）
        m = per_th[th]
        if m["n_steps"] >= MIN_STEPS and m["trackable_frac"] is not None and m["trackable_frac"] >= 0.80:
            chosen = th
            break
    if chosen is not None:
        cm = per_th[chosen]
        verdict = "PASS" if (cm["trackable_frac"] >= 0.80 and (cm["median_step_px"] is None or cm["median_step_px"] < SMOOTH_PX) and cm["n_steps"] >= MIN_STEPS) else "FAIL"
    else:
        verdict = "FAIL"
    return per_th, chosen, verdict


def run_scores(scores_path: Path, out: dict):
    d = json.loads(scores_path.read_text())
    for clip, frames in d.items():
        per_th, chosen, verdict = calibrate(frames, len(frames))
        out[clip] = {"per_th": {str(t): per_th[t] for t in TH_GRID},
                     "operating_th": chosen, "verdict": verdict,
                     "operating_metrics": per_th[chosen] if chosen is not None else None}
        _print(clip, per_th, chosen, verdict)


def run_baseline(out: dict):
    d = json.loads((AW / "ball_cand_scores_v2.json").read_text())
    for w, frames in d.items():
        per_th, chosen, verdict = calibrate(frames, len(frames))
        out[f"baseline_{w}"] = {"per_th": {str(t): per_th[t] for t in TH_GRID},
                                "operating_th": chosen, "verdict": verdict,
                                "operating_metrics": per_th[chosen] if chosen is not None else None}
        _print(f"baseline_{w}", per_th, chosen, verdict)


def _print(name, per_th, chosen, verdict):
    print(f"\n=== {name}  verdict={verdict}  operating_th={chosen} ===")
    for th in TH_GRID:
        m = per_th[th]
        tk = f"{m['trackable_frac']*100:.1f}%" if m["trackable_frac"] is not None else "NA"
        ci = m["trackable_ci95"] if m["trackable_ci95"] else "-"
        print(f"  th={th}: cov={m['frame_coverage']*100:.1f}% n={m['n_claims']} "
              f"ep={m['n_episodes']} step={m['median_step_px']} trk={tk} (CI {ci}) nsteps={m['n_steps']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", action="append", default=[])
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--all-clips", action="store_true")
    a = ap.parse_args()
    out = {}
    if a.all_clips:
        a.scores = [str(AW / "validate" / f"{c}_scores.json") for c in ("sas_hou", "sas_nop", "sas_det")]
        a.baseline = True
    for s in a.scores:
        run_scores(Path(s), out)
    if a.baseline:
        run_baseline(out)
    (AW / "validate" / "gate_calibrated.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\n→ action_work/validate/gate_calibrated.json")


if __name__ == "__main__":
    main()
