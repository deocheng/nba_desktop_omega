#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_validate3.py — 在 3 个独立高品质片段上汇总「任务级事件可用性」门禁验证。

对每片段、每阈值(th∈{0.90,0.95,0.975})、每口径(raw / 宽景<60px)计算：
  覆盖、片段数、均长、中位步长、可跟踪率 + Wilson 95% CI。
产出: action_work/validate/validate3_summary.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
from pathlib import Path

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
GAP = 3
SMOOTH = 80.0
Z = 1.96
CLIPS = ["sas_hou", "sas_nop", "sas_det"]
THS = [0.90, 0.95, 0.975]


def wilson(k, n):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def metrics(claims, frames_total):
    # claims: dict num -> (diag, cx, cy, prob)
    nums = sorted(claims)
    cov = len(claims) / frames_total if frames_total else 0.0
    eps, cur, last = [], [], None
    for n in nums:
        if last is not None and n - last > GAP + 1 and cur:
            eps.append(cur)
            cur = []
        cur.append(n)
        last = n
    if cur:
        eps.append(cur)
    ep_lens = [len(e) for e in eps]
    steps = [math.hypot(claims[b][1] - claims[a][1], claims[b][2] - claims[a][2])
             for e in eps for a, b in zip(e, e[1:])]
    med = sorted(steps)[len(steps) // 2] if steps else float("nan")
    k = sum(1 for d in steps if d < SMOOTH)
    n = len(steps)
    tr = k / n if n else float("nan")
    lo, hi = wilson(k, n)
    return {"n_claims": len(claims), "frame_coverage": round(cov, 4),
            "n_episodes": len(eps),
            "mean_episode_len": round(sum(ep_lens) / len(ep_lens), 2) if ep_lens else 0.0,
            "median_step_px": round(med, 1) if not math.isnan(med) else None,
            "n_steps": n, "trackable_frac": round(tr, 4) if not math.isnan(tr) else None,
            "trackable_ci95": [round(lo, 3), round(hi, 3)] if n else None}


def main():
    summary = {}
    for clip in CLIPS:
        sjson = AW / "validate" / f"{clip}_scores.json"
        scores = json.loads(sjson.read_text())[clip]
        frames_total = len(scores)
        clip_summary = {"n_frames": frames_total}
        for th in THS:
            raw = {}
            for fn, cs in scores.items():
                hs = [c for c in cs if c["prob"] > th]
                if not hs:
                    continue
                best = max(hs, key=lambda c: c["prob"])
                num = int(fn[1:6])
                b = best["bbox"]
                raw[num] = (math.hypot(b[2] - b[0], b[3] - b[1]),
                            (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, best["prob"])
            wide = {n: v for n, v in raw.items() if v[0] < 60}
            clip_summary[f"th{th}"] = {
                "raw": metrics(raw, frames_total),
                "wide_lt60px": metrics(wide, frames_total),
            }
        summary[clip] = clip_summary
        # 打印
        print(f"\n=== {clip} ({frames_total} 帧) ===")
        for th in THS:
            r = clip_summary[f"th{th}"]["raw"]
            w = clip_summary[f"th{th}"]["wide_lt60px"]
            print(f" th={th}: raw cov={r['frame_coverage']*100:.1f}% n={r['n_claims']} "
                  f"ep={r['n_episodes']} step={r['median_step_px']} trk={r['trackable_frac']} "
                  f"(CI {r['trackable_ci95']}) | wide(<60px) n={w['n_claims']} "
                  f"ep={w['n_episodes']} step={w['median_step_px']} trk={w['trackable_frac']} "
                  f"(CI {w['trackable_ci95']})")
    (AW / "validate" / "validate3_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))
    print("\n→ action_work/validate/validate3_summary.json")


if __name__ == "__main__":
    main()
