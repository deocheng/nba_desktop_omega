#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""track_ball.py — 路径 C：卡尔曼 + 匈牙利（贪心最近）时序跟踪器，替代朴素 GAP_TOL 片段拼接。

设计目标
--------
原 calibrate_gate / emit_ball_tracks 的片段拼接是「贪心取每帧最佳候选 + 间隔>GAP_TOL 即断」。
本跟踪器在**同一批 per-frame 检测（prob>th 且 bbox<60px）**之上做跨帧关联：
  - 每条轨迹一个恒速 Kalman 滤波器预测下一帧球心；
  - 用预测位置与当前帧候选做最近匹配（距离门限 120px），匹配上则更新、未匹配检测高置信则 birth 新轨迹；
  - 轨迹最多允许 GAP_TOL 帧无检测（靠预测续命），超则死亡。
**只消费真实检测，不把预测帧算进覆盖率/步长**——对门禁诚实。

用法
----
  python engine/track_ball.py --all-clips          # 3 片段 + 基线四窗
  python engine/track_ball.py --clip sas_det       # 单片段
  python engine/track_ball.py --clip sas_det --dump sas_det_tracked.json
产出
----
  action_work/validate/gate_tracked.json   （跟踪器版 7 域校准全表）
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
AW = Path(ROOT) / "action_work"
TH_GRID = [0.80, 0.85, 0.90, 0.95, 0.975]
MAX_PX = 60.0
GAP_TOL = 8            # 跟踪器允许的最大无检测间隔（预测续命）
SMOOTH_PX = 80.0
Z = 1.96
MIN_STEPS = 10
MIN_PROB_BIRTH = 0.85  # 仅高置信未匹配检测才 birth 新轨迹
MIN_TRACK = 1          # 计入门禁指标的最小轨迹长度（持续轨迹过滤）
ASSIGN_GATE = 120.0    # 预测-检测匹配的距离门限(px)


def wilson(k, n):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


class KF:
    """4 态恒速 Kalman：x, y, vx, vy。"""
    def __init__(self, x, y):
        self.x = np.array([x, y, 0.0, 0.0], float)
        self.P = np.eye(4) * 10.0
        self.F = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], float)
        self.H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], float)
        self.R = np.eye(2) * 4.0
        self.Q = np.eye(4) * 1.0

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x[:2]

    def update(self, z):
        z = np.asarray(z, float)
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P


def frame_dets(frames, fn, th):
    out = []
    for c in frames.get(fn, []):
        if c["prob"] > th:
            b = c["bbox"]
            if math.hypot(b[2] - b[0], b[3] - b[1]) < MAX_PX:
                out.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, float(c["prob"])))
    return out


def track_clip(frames, th, birth=MIN_PROB_BIRTH, gap=GAP_TOL):
    def fid(fn):
        return int(fn[1:6])

    keys = sorted(frames, key=fid)
    tracks = []
    active = []  # {"kf":KF, "ti":int, "last":int}
    for fn in keys:
        f = fid(fn)
        dets = frame_dets(frames, fn, th)
        preds = [t["kf"].predict() for t in active]
        matched_d, matched_t = set(), set()
        if dets and active:
            # 贪心最近匹配（规模小，O(n^2) 可接受；距离门限防错连）
            pairs = []
            for i, p in enumerate(preds):
                for j, d in enumerate(dets):
                    d_ = math.hypot(p[0] - d[0], p[1] - d[1])
                    if d_ <= ASSIGN_GATE:
                        pairs.append((d_, i, j))
            pairs.sort()
            for d_, i, j in pairs:
                if i in matched_t or j in matched_d:
                    continue
                active[i]["kf"].update(dets[j][:2])
                t = tracks[active[i]["ti"]]
                t["frames"].append(f)
                t["centers"].append([round(dets[j][0], 1), round(dets[j][1], 1)])
                t["probs"].append(round(dets[j][2], 3))
                active[i]["last"] = f
                matched_d.add(j); matched_t.add(i)
        for j, d in enumerate(dets):
            if j in matched_d:
                continue
            if d[2] >= birth:
                tracks.append({"frames": [f], "centers": [[round(d[0], 1), round(d[1], 1)]],
                               "probs": [round(d[2], 3)]})
                active.append({"kf": KF(d[0], d[1]), "ti": len(tracks) - 1, "last": f})
        active = [t for t in active if f - t["last"] <= gap]
    return tracks


def track_metrics(tracks, n_frames, min_track=MIN_TRACK):
    tracks = [t for t in tracks if len(t["frames"]) >= min_track]
    if not tracks:
        return {"n_tracks": 0, "n_claims": 0, "frame_coverage": 0.0,
                "median_step_px": None, "n_steps": 0, "trackable_frac": None,
                "trackable_ci95": None}
    real = sum(len(t["frames"]) for t in tracks)
    cov = real / n_frames if n_frames else 0.0
    steps = []
    for t in tracks:
        for k in range(len(t["frames"]) - 1):
            steps.append(math.hypot(t["centers"][k + 1][0] - t["centers"][k][0],
                                     t["centers"][k + 1][1] - t["centers"][k][1]))
    if steps:
        med = sorted(steps)[len(steps) // 2]
        k = sum(1 for d in steps if d < SMOOTH_PX)
        tr = k / len(steps)
        lo, hi = wilson(k, len(steps))
    else:
        med, tr, lo, hi = float("nan"), float("nan"), None, None
    return {"n_tracks": len(tracks), "n_claims": real, "frame_coverage": round(cov, 4),
            "median_step_px": round(med, 1) if not math.isnan(med) else None,
            "n_steps": len(steps), "trackable_frac": round(tr, 4) if not math.isnan(tr) else None,
            "trackable_ci95": [round(lo, 3), round(hi, 3)] if lo is not None else None}


def calibrate(frames, n_frames, ths=TH_GRID, birth=MIN_PROB_BIRTH, gap=GAP_TOL, min_track=MIN_TRACK):
    per_th = {}
    for th in ths:
        per_th[th] = track_metrics(track_clip(frames, th, birth, gap), n_frames, min_track)
    chosen = None
    for th in ths:
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


def _print(name, per_th, chosen, verdict):
    print(f"\n=== {name} [tracker]  verdict={verdict}  operating_th={chosen} ===")
    for th in per_th:
        m = per_th[th]
        tk = f"{m['trackable_frac']*100:.1f}%" if m["trackable_frac"] is not None else "NA"
        ci = m["trackable_ci95"] if m["trackable_ci95"] else "-"
        print(f"  th={th}: cov={m['frame_coverage']*100:.1f}% trk={tk} (CI {ci}) "
              f"step={m['median_step_px']} nsteps={m['n_steps']} tracks={m['n_tracks']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all-clips", action="store_true")
    ap.add_argument("--dump", default=None, help="把某 clip 的跟踪轨迹 JSON 写到该路径")
    ap.add_argument("--th", type=float, default=None, help="单阈值模式（否则扫 TH_GRID）")
    ap.add_argument("--birth", type=float, default=None, help="birth 置信门槛（默认 MIN_PROB_BIRTH）")
    ap.add_argument("--gap", type=int, default=None, help="预测续命最大间隔（默认 GAP_TOL）")
    ap.add_argument("--min-track", type=int, default=None, help="计入门禁的最小轨迹长度（默认 MIN_TRACK）")
    a = ap.parse_args()
    out = {}
    if a.all_clips:
        targets = [("sas_hou", AW / "validate" / "sas_hou_scores.json"),
                   ("sas_nop", AW / "validate" / "sas_nop_scores.json"),
                   ("sas_det", AW / "validate" / "sas_det_scores.json")]
        base = json.loads((AW / "ball_cand_scores_v2.json").read_text())
        for w, fr in base.items():
            targets.append((f"baseline_{w}", None, fr))
    elif a.clip:
        targets = [(a.clip, AW / "validate" / f"{a.clip}_scores.json")]
    else:
        ap.error("需要 --clip 或 --all-clips")

    birth = a.birth if a.birth is not None else MIN_PROB_BIRTH
    gap = a.gap if a.gap is not None else GAP_TOL
    min_track = a.min_track if a.min_track is not None else MIN_TRACK
    for item in targets:
        name = item[0]
        if len(item) == 3:
            frames = item[2]
        else:
            frames = json.loads(item[1].read_text())[name]
        if a.th is not None:
            ths = [a.th]
        else:
            ths = TH_GRID
        per_th, chosen, verdict = calibrate(frames, len(frames), ths, birth, gap, min_track)
        out[name] = {"per_th": {str(t): per_th[t] for t in ths},
                     "operating_th": chosen, "verdict": verdict,
                     "operating_metrics": per_th[chosen] if chosen is not None else None}
        _print(name, per_th, chosen, verdict)
        if a.dump and name == a.clip:
            th = chosen if chosen is not None else (a.th if a.th is not None else 0.85)
            tracks = track_clip(frames, th, birth, gap)
            Path(a.dump).write_text(json.dumps(tracks, ensure_ascii=False, indent=1))
            print(f"→ tracks dumped: {a.dump} ({len(tracks)} tracks)")

    (AW / "validate" / "gate_tracked.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\n→ action_work/validate/gate_tracked.json")


if __name__ == "__main__":
    main()
