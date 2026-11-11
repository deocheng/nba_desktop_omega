#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ball_fp_filter.py — 球事件 FP 过滤（里程碑 05 · A4.19 降 FP）

立场（先说清楚，避免过度承诺）
------------------------------
本片段**没有可信真值**（A4.11/12 已封口：判读者一致率仅 76.7%，AI 自标被拒）。
因此本模块**不宣称「FP 下降了 X%」**。它做的只是一件事：

    对每条球轨迹，检查它是否**至少有一个点落在球员附近**（物理可支撑）。
    一条 ≥3 帧的轨迹，若全程离所有球员都 >88px，则它不是"球在飞行中"，
    而更可能是静态/半静态的伪目标（观众席光斑、LED、广告牌、篮网高光）。

被滤掉的轨迹会**逐条列出证据**（距离/位置/运动量/尺寸/置信），
判定权留给读者 —— 不把"过滤"包装成"精度提升"。

过滤规则（分层，保守）
----------------------
  R1 轨迹级支撑：轨迹内存在 ≥1 个点的 d_rect(球心→最近球员框矩形) <= support_px
     → KEEP（保护传球/投篮在飞行段：轨迹两端总有一端靠近球员）
  R2 无支撑（R1 失败）→ 再查运动性：
     - mean_step >= min_step_px（真球在动，伪目标静止/微抖）→ 仍可能是飞行中的球 → KEEP_MARK
     - 否则 → DROP
  默认 min_step_px=0 ⇒ R2 关闭，即「无支撑即剔除」（最严格，与用户"强过滤"一致）。
  置 --min-step 8 可开 R2 保护。

复用：球员框直接读 <clip>_poss_tile/ball_tracks.json（A4.18 已产出，400 帧全量），
      **零额外 GPU 计算**。

产出
----
  action_work/validate/<clip>_ballfeed_fp.json     过滤后喂入（ball_possession --ball-json 格式）
  action_work/validate/<clip>_fp_filter.json       逐轨迹证据 + KEEP/DROP 判定
  action_work/validate/<clip>_gate_after_fp.json   过滤后门禁指标（同一 track_metrics 口径）

用法
----
  python engine/ball_fp_filter.py --clip sas_hou
  python engine/ball_fp_filter.py --all [--support-px 88] [--min-step 0] [--dry-run]
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

import court_render as cr
import track_ball as tb


def rect_dist(bx, by, box):
    x1, y1, x2, y2 = box
    dx = max(x1 - bx, 0.0, bx - x2)
    dy = max(y1 - by, 0.0, by - y2)
    return (dx * dx + dy * dy) ** 0.5


def load_player_boxes(clip):
    """{frame_no: [bbox,...]}，来自 A4.18 已产出的 ball_tracks.json（全 400 帧）。

    🔴 键必须用**文件名的 1-based 编号**(f00209.jpg → 209)，与 `track_ball.fid()`
       (`int(fn[1:6])`) 对齐 —— 不是 ball_tracks.json 的 0-based `frame` 字段。
    （踩坑记录：初版用 `f["frame"]` 建键，导致过滤时查的是**错位一帧**的球员框。）
    """
    p = AW / f"{clip}_poss_tile" / "ball_tracks.json"
    if not p.exists():
        return None
    out = {}
    for f in json.loads(p.read_text()):
        out[int(str(f["file"])[1:6])] = [pl["bbox"] for pl in f.get("players", [])]
    return out


def analyze(clip, support_px=88.0, min_track=3, min_step=0.0, dry=False):
    frames = cr.load_scores(clip)
    th = cr.operating_th(clip)
    tracks = tb.track_clip(frames, th, birth=th, gap=8)
    tracks = [t for t in tracks if len(t["frames"]) >= min_track]
    pboxes = load_player_boxes(clip)
    if pboxes is None:
        raise SystemExit(f"[缺球员框] {clip}: 需先跑 ball_possession 产出 _poss_tile/ball_tracks.json")

    # 中心 → 原始 bbox（与 make_ballfeed 完全一致）
    center2box = {}
    for fn, cands in frames.items():
        m = {}
        for c in cands:
            b = c["bbox"]
            m.setdefault((round((b[0] + b[2]) / 2, 1), round((b[1] + b[3]) / 2, 1)),
                         [float(v) for v in b])
        center2box[fn] = m

    rows = []
    for ti, t in enumerate(tracks):
        ds, ys, sizes, steps = [], [], [], []
        confs = []
        no_player_frames = 0
        for k, (f, c, p) in enumerate(zip(t["frames"], t["centers"], t["probs"])):
            fi = int(f)
            bx, by = float(c[0]), float(c[1])
            boxes = pboxes.get(fi, [])
            if not boxes:
                no_player_frames += 1
                ds.append(None)
            else:
                ds.append(min(rect_dist(bx, by, b) for b in boxes))
            ys.append(by)
            confs.append(float(p))
            fn = f"f{fi:05d}.jpg"
            box = center2box.get(fn, {}).get((round(bx, 1), round(by, 1)))
            sizes.append(max(box[2] - box[0], box[3] - box[1]) if box else None)
            if k:
                pc = t["centers"][k - 1]
                steps.append(((bx - pc[0]) ** 2 + (by - pc[1]) ** 2) ** 0.5)
        dnum = [d for d in ds if d is not None]
        n_sup = sum(1 for d in dnum if d <= support_px)
        mean_step = sum(steps) / len(steps) if steps else 0.0
        span = ((t["centers"][-1][0] - t["centers"][0][0]) ** 2 +
                (t["centers"][-1][1] - t["centers"][0][1]) ** 2) ** 0.5

        keep = n_sup >= 1
        reason = "R1 有球员支撑" if keep else None
        if not keep and min_step > 0 and mean_step >= min_step:
            keep = True
            reason = f"R2 无支撑但在动(mean_step={mean_step:.1f}px)"
        if not keep:
            reason = (f"DROP: 全程离球员最近 {min(dnum):.0f}px > {support_px:.0f}px"
                      if dnum else "DROP: 该轨迹所在帧无球员框，无法支撑")

        rows.append({
            "track": ti, "n_pts": len(t["frames"]),
            "frames": [int(x) for x in t["frames"]],
            "centers": [[round(float(c[0]), 1), round(float(c[1]), 1)] for c in t["centers"]],
            "probs": [round(float(p), 3) for p in t["probs"]],
            "n_sup": n_sup,
            "d_min": round(min(dnum), 1) if dnum else None,
            "d_mean": round(sum(dnum) / len(dnum), 1) if dnum else None,
            "y_mean": round(sum(ys) / len(ys), 1),
            "conf_mean": round(sum(confs) / len(confs), 3),
            "size_mean": (round(sum(s for s in sizes if s) / len([s for s in sizes if s]), 1)
                          if any(sizes) else None),
            "mean_step": round(mean_step, 1),
            "span": round(span, 1),
            "no_player_frames": no_player_frames,
            "keep": keep, "reason": reason,
        })

    kept_idx = [i for i, r in enumerate(rows) if r["keep"]]
    kept_tracks = [tracks[i] for i in kept_idx]

    before = tb.track_metrics(tracks, 400, min_track=min_track)
    after = tb.track_metrics(kept_tracks, 400, min_track=min_track)

    feed = {}
    n_pts = 0
    for t in kept_tracks:
        for f, c, p in zip(t["frames"], t["centers"], t["probs"]):
            fn = f"f{int(f):05d}.jpg"
            bx, by = float(c[0]), float(c[1])
            box = center2box.get(fn, {}).get((round(bx, 1), round(by, 1)))
            if box is None:
                box = [bx - 10, by - 10, bx + 10, by + 10]
            feed.setdefault(fn, []).append({"bbox": box, "conf": float(p)})
            n_pts += 1

    return {"clip": clip, "th": th, "support_px": support_px, "min_step": min_step,
            "rows": rows, "before": before, "after": after,
            "feed": feed, "n_pts": n_pts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--support-px", type=float, default=88.0)
    ap.add_argument("--min-track", type=int, default=3)
    ap.add_argument("--min-step", type=float, default=0.0,
                    help=">0 则开启 R2：无支撑但 mean_step>=该值 的轨迹保留")
    ap.add_argument("--dry-run", action="store_true", help="只诊断，不写喂入文件")
    a = ap.parse_args()
    clips = (["sas_hou", "sas_nop", "sas_det"] if a.all
             else ([a.clip] if a.clip else []))
    if not clips:
        ap.error("需要 --clip 或 --all")

    for c in clips:
        r = analyze(c, a.support_px, a.min_track, a.min_step, a.dry_run)
        rows = r["rows"]
        nk = sum(1 for x in rows if x["keep"])
        print(f"\n{'='*78}")
        print(f"{c}  th={r['th']}  support<={a.support_px:.0f}px  min_step={a.min_step}")
        print(f"轨迹 {len(rows)} → 保留 {nk} / 剔除 {len(rows)-nk}")
        print(f"\n  门禁 before: tracks={r['before']['n_tracks']} claims={r['before']['n_claims']} "
              f"cov={r['before']['frame_coverage']:.3f} med_step={r['before']['median_step_px']} "
              f"n_steps={r['before']['n_steps']} trackable={r['before']['trackable_frac']}")
        print(f"  门禁 after : tracks={r['after']['n_tracks']} claims={r['after']['n_claims']} "
              f"cov={r['after']['frame_coverage']:.3f} med_step={r['after']['median_step_px']} "
              f"n_steps={r['after']['n_steps']} trackable={r['after']['trackable_frac']}")
        print("\n  剔除轨迹证据（判定权交读者）：")
        print(f"  {'trk':>3} {'pts':>3} {'d_min':>6} {'d_mean':>7} {'y_mean':>7} "
              f"{'size':>5} {'conf':>5} {'step':>6} {'span':>6} {'noPl':>4}  reason")
        for x in rows:
            if x["keep"]:
                continue
            d_min = f"{x['d_min']:.0f}" if x["d_min"] is not None else "NA"
            d_mean = f"{x['d_mean']:.0f}" if x["d_mean"] is not None else "NA"
            size = f"{x['size_mean']:.0f}" if x["size_mean"] else "NA"
            print(f"  {x['track']:>3} {x['n_pts']:>3} {d_min:>6} {d_mean:>7} "
                  f"{x['y_mean']:>7.0f} {size:>5} {x['conf_mean']:>5.2f} "
                  f"{x['mean_step']:>6.1f} {x['span']:>6.1f} "
                  f"{x['no_player_frames']:>4}  {x['reason']}")

        od = AW / "validate"
        od.mkdir(parents=True, exist_ok=True)
        if not a.dry_run:
            (od / f"{c}_ballfeed_fp.json").write_text(json.dumps(r["feed"], indent=1))
        (od / f"{c}_fp_filter.json").write_text(json.dumps(
            {"clip": c, "th": r["th"], "support_px": a.support_px, "min_step": a.min_step,
             "min_track": a.min_track, "before": r["before"], "after": r["after"],
             "n_pts_feed": r["n_pts"], "rows": rows}, ensure_ascii=False, indent=1))
        print(f"\n  [写盘] {od}/{c}_fp_filter.json"
              + ("" if a.dry_run else f" , {od}/{c}_ballfeed_fp.json"))


if __name__ == "__main__":
    main()
