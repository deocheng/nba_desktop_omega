#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球权信号质量诊断 —— 判「持球者」是不是一个可信构造。

动机
----
Phase 1.5 的对齐检验为阴性。阴性可能是「检测器不准」，也可能是「构造本身错」。
本脚本用三个**可证伪**的判据把两者分开：

  判据 1（贴球度）球心到被判持球者框矩形的距离分布。
       真正的持球者：球在自己框内 ⇒ 距离 0；若中位数逼近半径上限 ⇒ 幽灵分配。
  判据 2（身份复用）同一个 track_id 的框中心空间散布（四分位距）。
       真球员在一段球权内位移有限；散布巨大 ⇒ BotSort 复用了 ID，
       所谓「同一人持球 19s」是假连续。
  判据 3（持球时长）段长分布 vs 篮球常识（个体连续持球极少 >6s）。

用法: poss_diag.py --windows w1 w2 w3 w4 [--radius 0.035] [--hysts 1 3 6 10]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import statistics
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))


def pt_to_rect(bx, by, box):
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
        return best["track_id"], bd, [(p["bbox"][0] + p["bbox"][2]) / 2,
                                      (p["bbox"][1] + p["bbox"][3]) / 2]
    return None, None, None


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
            segs.append({"track_id": int(v), "start": i, "end": i, "n": 1})
    return segs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", nargs="+", default=["w1", "w2", "w3", "w4"])
    ap.add_argument("--radius", type=float, default=0.035)
    ap.add_argument("--hysts", nargs="+", type=int, default=[3, 6, 10])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    diag = (1920 ** 2 + 1080 ** 2) ** 0.5
    R = a.radius * diag

    report = {}
    for w in a.windows:
        tracks = json.loads((AW / f"{w}_poss" / "ball_tracks.json").read_text())
        # 逐帧原始分配 + 贴球距离 + 被选球员框中心
        raw, dists, centers, npl = [], [], [], []
        for fr in tracks:
            b = fr.get("ball")
            ps = fr.get("players", [])
            npl.append(len(ps))
            if not b or "bbox" not in b:
                raw.append(None); dists.append(None); centers.append(None); continue
            tid, d, c = assign(b["bbox"], ps, a.radius, diag)
            raw.append(tid); dists.append(d); centers.append(c)

        r = {"n_frames": len(tracks), "median_players_per_frame": statistics.median(npl)}
        # 判据 1：贴球度
        dd = [x for x in dists if x is not None]
        if dd:
            r["judge1_ball_dist"] = {
                "n_assigned": len(dd),
                "median_px": round(statistics.median(dd), 1),
                "p90_px": round(sorted(dd)[int(0.9 * len(dd))], 1),
                "frac_zero(球在框内)": round(sum(1 for x in dd if x == 0) / len(dd), 3),
                "frac_gt_half_radius": round(
                    sum(1 for x in dd if x > R / 2) / len(dd), 3),
                "radius_px": round(R, 1),
            }
        # 判据 2/3：按 hyst 看段
        r["per_hyst"] = {}
        for h in a.hysts:
            sm = hysteresis(raw, h)
            segs = rle(sm)
            # 判据 2：同一 track_id 的框中心散布
            byid = {}
            for i, tid in enumerate(sm):
                if tid is not None and centers[i] is not None:
                    byid.setdefault(tid, []).append(centers[i])
            spread = {}
            for tid, cs in byid.items():
                if len(cs) < 5:
                    continue
                arr = np.array(cs)
                spread[tid] = {
                    "n": len(cs),
                    "iqr_x": round(float(np.percentile(arr[:, 0], 75) -
                                         np.percentile(arr[:, 0], 25)), 1),
                    "iqr_y": round(float(np.percentile(arr[:, 1], 75) -
                                         np.percentile(arr[:, 1], 25)), 1),
                }
            worst = sorted(spread.items(), key=lambda kv: -(kv[1]["iqr_x"] + kv[1]["iqr_y"]))[:5]
            lens = [s["n"] for s in segs]
            # 判据 4（决定性）：迟滞冻结占比 —— 平滑段内有观测支撑(raw==该ID)的帧占比
            obs_tot = sum(sum(1 for i in range(s["start"], s["end"] + 1)
                              if raw[i] == s["track_id"]) for s in segs)
            tot = sum(s["n"] for s in segs) or 1
            longest = max(segs, key=lambda s: s["n"]) if segs else None
            lsup = None
            if longest:
                lo = sum(1 for i in range(longest["start"], longest["end"] + 1)
                         if raw[i] == longest["track_id"])
                lsup = {"track_id": longest["track_id"],
                        "n_frames": longest["n"],
                        "support_frames": lo,
                        "support_share": round(lo / longest["n"], 3)}
            r["per_hyst"][h] = {
                "n_segments": len(segs),
                "support_share": round(obs_tot / tot, 3),
                "longest_segment": lsup,
                "median_len_frames": statistics.median(lens) if lens else 0,
                "max_len_frames": max(lens) if lens else 0,
                "max_len_sec": round((max(lens) if lens else 0) * 0.1, 1),
                "n_seg_gt_6s": sum(1 for L in lens if L > 60),
                "top5_identity_spread": {str(k): v for k, v in worst},
            }
        report[w] = r

        print(f"\n===== {w} =====")
        print(f"  帧数 {r['n_frames']}  每帧球员数中位 {r['median_players_per_frame']}")
        j1 = r.get("judge1_ball_dist")
        if j1:
            print(f"  判据1 贴球度: 中位 {j1['median_px']}px   p90 {j1['p90_px']}px   "
                  f"球在框内占比 {j1['frac_zero(球在框内)']}   "
                  f">半径半 {j1['frac_gt_half_radius']}  (半径上限 {j1['radius_px']}px)")
        for h, v in r["per_hyst"].items():
            print(f"  判据2/3 hyst={h:<3} 段数 {v['n_segments']:>3}  "
                  f"段长中位 {v['median_len_frames']:>4.0f}帧  最长 {v['max_len_sec']}s  "
                  f">6s 段 {v['n_seg_gt_6s']}")
            top = list(v["top5_identity_spread"].items())[:2]
            for tid, sp in top:
                print(f"        ID {tid} 出现 {sp['n']} 帧  框中心散布 IQR "
                      f"x={sp['iqr_x']}px y={sp['iqr_y']}px")

    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"\n[写] {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
