#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate_gate_fp.py — A4.19：在「FP 过滤后」的轨迹集合上重跑门禁按域标定。

为什么需要重标定
----------------
A4.15 确立的流程是「网格搜 th → 取**最低达标** th 为工作点」。
FP 过滤改变了流程的**输入**（轨迹集合），因此必须把同一流程在新输入上重跑一遍，
不能沿用旧工作点直接下结论（旧工作点是在含 FP 的集合上选的）。

同时诚实记录一件事：过滤后 sas_nop 的工作点会从 0.3 上移到 0.4 ——
原因不是"调参凑达标"，而是**门禁指标 trackable_frac 与精度反相关**：
被滤掉的观众席/LED 伪目标本身是"平滑"的（步长 0–20px），
它们免费抬高可跟踪率；去掉后剩下的步骤更"跳"，指标自然下降。

产出
----
  action_work/validate/gate_tracked_recalib_fp.json   过滤后 7 域全表（含 before/after）

用法
----
  python engine/calibrate_gate_fp.py [--support-px 88] [--min-step 0]
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

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))

import run_ball_events as rbe
import track_ball as tb

TH_GRID = [0.3, 0.4, 0.5, 0.6, 0.8]
N_FRAMES = 400


def domains():
    out = []
    for c in ("sas_hou", "sas_nop", "sas_det"):
        out.append((c, json.loads((AW / "validate" / f"{c}_scores.json").read_text())[c]))
    base = json.loads((AW / "ball_cand_scores_v2.json").read_text())
    for w, fr in base.items():
        out.append((f"baseline_{w}", fr))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--support-px", type=float, default=rbe.SUPPORT_PX)
    ap.add_argument("--min-step", type=float, default=0.0)
    a = ap.parse_args()

    table = {}
    print(f"FP 过滤后门禁重标定  support<={a.support_px:.0f}px  min_step={a.min_step}")
    print(f"{'域':13s} {'th':5s} {'轨迹':5s} {'点':5s} {'覆盖':7s} {'可跟踪':8s} "
          f"{'步长':6s} {'步数':5s} 裁定")
    print("-" * 84)
    for name, frames in domains():
        boxes = rbe.load_player_boxes(name)
        per_th, chosen, verdict = {}, None, "FAIL"
        for th in TH_GRID:
            tr = tb.track_clip(frames, th, birth=th, gap=8)
            if boxes is not None:
                tr, _ = rbe.filter_tracks(tr, boxes, a.support_px, a.min_step)
            m = tb.track_metrics(tr, len(frames), 3)
            ok = (m["n_steps"] >= tb.MIN_STEPS and m["trackable_frac"] is not None
                  and m["trackable_frac"] >= 0.80
                  and (m["median_step_px"] is None or m["median_step_px"] < tb.SMOOTH_PX))
            per_th[str(th)] = m
            if ok and chosen is None:
                chosen, verdict = th, "PASS"
            tk = f"{m['trackable_frac']*100:.1f}%" if m["trackable_frac"] is not None else "—"
            mark = " ★" if ok and chosen == th else ""
            print(f"{name:13s} {th:<5} {m['n_tracks']:<5} {m['n_claims']:<5} "
                  f"{m['frame_coverage']*100:6.1f}% {tk:8s} {str(m['median_step_px']):6s} "
                  f"{m['n_steps']:<5} {'PASS' if ok else 'FAIL'}{mark}")
        om = per_th[str(chosen)] if chosen is not None else None
        print(f"{'':13s} → 工作点 th={chosen}  裁定={verdict}"
              + (f"  可跟踪={om['trackable_frac']*100:.1f}% 步数={om['n_steps']} "
                 f"覆盖={om['frame_coverage']*100:.1f}%" if om else "  (无达标 th)"))
        print()
        table[name] = {"per_th": per_th, "operating_th": chosen, "verdict": verdict,
                       "operating_metrics": om, "support_px": a.support_px,
                       "min_step": a.min_step, "has_player_boxes": boxes is not None}

    outp = AW / "validate" / "gate_tracked_recalib_fp.json"
    outp.write_text(json.dumps(table, ensure_ascii=False, indent=1))
    npass = sum(1 for v in table.values() if v["verdict"] == "PASS")
    print(f"[写盘] {outp}")
    print(f"[汇总] FP 过滤后 {npass}/{len(table)} 域达标")


if __name__ == "__main__":
    main()
