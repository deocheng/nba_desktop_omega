#!/usr/bin/env python3
"""A5.5 诊断：B 的 ID 减少到底是「正确缝合」还是「错误合并」？

动机（老程裁定）：ID 数 −55% 但目视"没有准确识别" ⇒ 数量指标可疑，
可能是放宽门(gate.60)把**不同的人**并成了一条轨迹（错并）的假象。

判据（不依赖目视、不依赖手写物理常量，用**段内相对量**）：
  1. 每条轨迹的「帧间位移/帧」分布 → 段内中位 step。
  2. **跳变率** = step > K×段内中位step 的步数占比（K=5）。
     真跟踪应平滑；错并会在合并点产生远超本人运动的大跳。
  3. **长轨迹质量**：≥20 步的轨迹，其 step 的 p90/中位 比值（越接近1越平滑）。
  4. 对比 base(tracks.json) 与 B(tracks_b.json)。
"""
import json
import statistics
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
SEGS = ["ep12_s0", "ep25_s1", "ep7_s0", "ep1_s0", "ep10_s0", "ep24_s1", "ep5_s1", "ep46_s0"]
K_JUMP = 5.0


def steps_of(tr):
    """每条轨迹的 (step_per_frame 列表)，以及 foot 点序列。"""
    by = {}
    for x in tr.get("frames") or []:
        for p in x.get("players") or []:
            b = p["box"]
            by.setdefault(p["id"], []).append((x["idx"], (b[0] + b[2]) / 2, b[3]))
    out = {}
    for tid, seq in by.items():
        seq.sort()
        st = []
        for i in range(1, len(seq)):
            df = seq[i][0] - seq[i - 1][0]
            if df <= 0:
                continue
            d = ((seq[i][1] - seq[i - 1][1]) ** 2 + (seq[i][2] - seq[i - 1][2]) ** 2) ** 0.5
            st.append(d / df)
        if st:
            out[tid] = st
    return out


def summarize(tr):
    st = steps_of(tr)
    allst = [v for s in st.values() for v in s]
    if not allst:
        return None
    med = statistics.median(allst)
    jump = sum(1 for v in allst if v > K_JUMP * med) / len(allst)
    # 长轨迹(>=20步)平滑度
    longr = []
    for s in st.values():
        if len(s) >= 20:
            m = statistics.median(s)
            if m > 0:
                longr.append(np.percentile(s, 90) / m)
    return {"n_tracks": len(st), "n_steps": len(allst),
            "med_step": round(med, 1), "max_step": round(max(allst), 1),
            "jump_rate": round(jump, 4),
            "n_long": len(longr),
            "long_p90_over_med": round(statistics.median(longr), 2) if longr else None}


def main():
    print(f"{'seg':10s}{'版本':<6}{'轨迹数':>7}{'步数':>7}{'中位步长':>9}{'最大步长':>9}"
          f"{'跳变率':>8}{'长迹数':>7}{'长迹p90/中位':>12}")
    rows = []
    for seg in SEGS:
        d = SEGD / seg
        if not (d / "tracks.json").exists() or not (d / "tracks_b.json").exists():
            continue
        for tag, fn in (("base", "tracks.json"), ("B", "tracks_b.json")):
            s = summarize(json.load(open(d / fn)))
            if not s:
                continue
            rows.append({"seg": seg, "ver": tag, **s})
            print(f"{seg:10s}{tag:<6}{s['n_tracks']:>7}{s['n_steps']:>7}"
                  f"{s['med_step']:>9.1f}{s['max_step']:>9.1f}"
                  f"{s['jump_rate']:>8.3f}{s['n_long']:>7}"
                  f"{str(s['long_p90_over_med']):>12}")
    # 汇总
    print("\n=== 汇总(中位) ===")
    for tag in ("base", "B"):
        sub = [r for r in rows if r["ver"] == tag]
        if not sub:
            continue
        print(f"{tag:<6} 轨迹数={statistics.median(r['n_tracks'] for r in sub):.0f}  "
              f"中位步长={statistics.median(r['med_step'] for r in sub):.1f}  "
              f"跳变率={statistics.median(r['jump_rate'] for r in sub):.3f}  "
              f"长迹p90/中位={statistics.median([r['long_p90_over_med'] for r in sub if r['long_p90_over_med']]):.2f}")
    out = ROOT / "action_work" / "track_quality_probe.json"
    json.dump({"K_JUMP": K_JUMP, "rows": rows}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
