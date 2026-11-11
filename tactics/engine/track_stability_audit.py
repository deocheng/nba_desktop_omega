#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""track_stability_audit —— 追踪 ID 稳定化验收（部署 Valen 前的红线门之一）。

验收门槛（来自 engine/botsort_stable.yaml 注释里老程定的标准）：
  · 每帧球员数仍在 ~10–13（骤降说明真实球员被吞 ⇒ 不合格）
  · 中位寿命显著提升（基线：默认 botsort 中位 10 帧；调参后 botsort_stable 中位 8 帧）

指标（全部可证伪，禁止只报好看的那个）：
  n_ids            distinct track_id 总数            ↓好（场上实约 10–13 人）
  med_life         每 track 出现帧数的中位数          ↑好
  p90_life         同上 90 分位
  ppl_per_frame    每帧平均球员框数（未去重）
  concurrency      每帧 distinct id 的中位数         应 ≈10–13
  new_ids_per_fr   平均每帧新出现的 track_id 数       ↓好（ID 碎片直接指标）
  long_ratio       寿命 ≥ --long-thr 的 track 占比    ↑好
  churn_frame_ratio 出现"新 ID"的帧占比               ↓好

⚠️ 硬规则：new_ids_per_fr 与 n_ids 必须**同时**看。只把 n_ids 压下去很可能是
   错并（把多人并成一个 ID），此时 concurrency 会同步崩 —— 故 concurrency 是硬门。

用法:
  python3 track_stability_audit.py --all
  python3 track_stability_audit.py action_work/sas_det_poss_tile/ball_tracks.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import statistics
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
ACT = ROOT / "action_work"


def load_tracks(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(d, dict):
        for k in ("tracks", "records", "frames"):
            if k in d:
                d = d[k]
                break
    return d


def audit(path, long_thr=60):
    d = load_tracks(path)
    life, per_frame, conc, new_ids, frames_with_new = {}, [], [], [], 0
    # ⭐ gap 诊断：区分「短断链(可救)」vs「长断链/漏检(救不回来)」
    #    每个 track 记录它出现的帧号 → 相邻出现的帧号差
    frames_of = {}
    seen = set()
    prev_ids = None
    for i, r in enumerate(d):
        ps = r.get("players", []) or []
        ids = [p.get("track_id") for p in ps if p.get("track_id") is not None]
        per_frame.append(len(ids))
        uq = set(ids)
        conc.append(len(uq))
        for t in ids:
            life[t] = life.get(t, 0) + 1
            frames_of.setdefault(t, []).append(int(r.get("frame", i)))
        new = uq - seen if prev_ids is not None else set()
        new_ids.append(len(new))
        if new:
            frames_with_new += 1
        seen |= uq
        prev_ids = uq

    # gap 统计
    gaps = []          # 所有 track 的所有相邻帧号差（gap==1 表示连续可见）
    n_track_with_gap = 0
    for t, fs in frames_of.items():
        fs = sorted(set(fs))
        g = [b - a for a, b in zip(fs, fs[1:])]
        if not g:
            continue
        gaps += g
        if max(g) >= 2:
            n_track_with_gap += 1
    gaps = np.array(gaps) if gaps else np.array([1])
    gv = int(gaps.size)

    # ⭐ 位移连续性检查（防「ID switch 伪装成长寿命」）：
    #    同一 track 相邻可见帧之间，脚点位移应 ≤ 门控。若放宽 gate 后位移虚高，
    #    说明长寿命是「一个 ID 在不同人之间跳」换来的 ⇒ 结论不可信。
    steps = []
    maxstep_of = {}
    for t, fs in frames_of.items():
        pts = {}
        for r in d:
            if r.get("frame") not in fs:
                continue
            for p in r.get("players", []) or []:
                if p.get("track_id") == t and p.get("bbox"):
                    bb = p["bbox"]
                    pts[r["frame"]] = ((bb[0] + bb[2]) / 2.0, bb[3])
                    break
        ks = sorted(pts)
        st = [math.hypot(pts[b][0] - pts[a][0], pts[b][1] - pts[a][1])
              for a, b in zip(ks, ks[1:])]
        if st:
            steps += st
            maxstep_of[t] = max(st)
    steps = np.array(steps) if steps else np.array([0.0])
    ms = np.array(sorted(maxstep_of.values())) if maxstep_of else np.array([0.0])
    res_step = {
        "step_p50": round(float(np.percentile(steps, 50)), 1),
        "step_p95": round(float(np.percentile(steps, 95)), 1),
        "step_max": round(float(steps.max()), 1),
        "track_maxstep_p95": round(float(np.percentile(ms, 95)), 1),
        "track_maxstep_max": round(float(ms.max()), 1),
    }

    res_gap = {
        "gap_mean": round(float(gaps.mean()), 2),
        "track_with_gap": n_track_with_gap,
        "gap_cont_ratio": round(float((gaps == 1).sum()) / gv, 3),
        "gap_short_ratio": round(float(((gaps >= 2) & (gaps <= 3)).sum()) / gv, 3),
        "gap_long_ratio": round(float((gaps >= 4).sum()) / gv, 3),
        "gap_ratio_total": round(n_track_with_gap / max(len(frames_of), 1), 3),
    }

    lv = np.array(sorted(life.values())) if life else np.array([0])
    n_fr = max(len(d), 1)
    res = {
        "file": str(path),
        "n_frames": len(d),
        "n_ids": int(len(life)),
        "med_life": float(np.median(lv)),
        "p90_life": float(np.percentile(lv, 90)) if len(lv) else 0.0,
        "max_life": int(lv.max()),
        "ppl_per_frame": round(float(np.mean(per_frame)), 2) if per_frame else 0.0,
        "concurrency_med": float(np.median(conc)) if conc else 0.0,
        "new_ids_per_fr": round(float(np.mean(new_ids)), 3) if new_ids else 0.0,
        "churn_frame_ratio": round(frames_with_new / n_fr, 3),
        "long_ratio": round(float((lv >= long_thr).mean()), 3),
        "long_thr": long_thr,
    }
    res.update(res_gap)
    res.update(res_step)
    # 判定：concurrency 必须在 8–16 之间（低于 8 = 人被吞/被错并；高于 16 = 碎片+噪声）
    c = res["concurrency_med"]
    res["gate_concurrency"] = "PASS" if 8.0 <= c <= 16.0 else "FAIL"
    res["gate_medlife"] = "PASS" if res["med_life"] >= 30 else "FAIL"
    res["VERDICT"] = ("PASS" if res["gate_concurrency"] == "PASS"
                      and res["gate_medlife"] == "PASS" else "FAIL")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true", help="扫 action_work 下所有 *_poss*/stab* 的 ball_tracks.json")
    ap.add_argument("--long-thr", type=int, default=60)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    files = list(a.files)
    if a.all or not files:
        pats = ["*_poss*/ball_tracks.json", "*stab*/ball_tracks.json"]
        seen = set()
        for p in pats:
            for f in sorted(ACT.glob(p)):
                if str(f) not in seen:
                    seen.add(str(f))
                    files.append(str(f))
    if not files:
        print("未找到 ball_tracks.json")
        return

    rows = [audit(f, a.long_thr) for f in files]
    hdr = f"{'目录':<34}{'ID数':>6}{'中位寿':>7}{'p90':>7}{'并发':>6}{'新ID/帧':>8}{'长轨%':>7}  判定"
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(rows, key=lambda x: -x["med_life"]):
        name = Path(r["file"]).parent.name
        print(f"{name:<34}{r['n_ids']:>6}{r['med_life']:>7.0f}{r['p90_life']:>7.0f}"
              f"{r['concurrency_med']:>6.1f}{r['new_ids_per_fr']:>8.2f}"
              f"{r['long_ratio']*100:>6.1f}%  {r['VERDICT']}"
              f"{'' if r['gate_concurrency']=='PASS' else '(并发'+r['gate_concurrency']+')'}"
              f"{'' if r['gate_medlife']=='PASS' else '(寿命'+r['gate_medlife']+')'}")

    npass = sum(1 for r in rows if r["VERDICT"] == "PASS")
    print(f"\n合计 {len(rows)} 个产物，通过 {npass} 个。"
          f" 门槛：并发∈[8,16] 且 中位寿命≥30帧")
    if a.out:
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print("wrote", a.out)


if __name__ == "__main__":
    main()
