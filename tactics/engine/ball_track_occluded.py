#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4.54 球遮挡追踪 —— 遮挡段逐帧 holder-attachment(参考 PBP 持球队)。

背景(A4.53 收口后, 老程裁定):
  top1 球源覆盖 58.8%(sas_det); live 帧球无检测 66 段/139 帧(38.1%)。当前球轨迹在遮挡段
  直接断(None) → 可视化/FLY-HOLD 运动学缺这段。老程要求"参考 PBP 数据"补全。

裁定(老程, 本会话):
  - 范围 A: 遮挡补全只进 BALL TRACK / 可视化 / FLY-HOLD; A4.53 占有权 gate 完全不动,
    teamID QUALIFIED 不变。本脚本不输出占有权, 不碰 t3b。
  - 纪律: holder-attachment 的球位置来自「独立球员轨迹 + PBP 队」, 非对球自身轨迹插值;
    每帧显式标记 source=pbp_holder / occluded=True, 下游可区分(不伪造测量值)。

方法(零新模型, 守无插值铁律):
  ① 遮挡段 = live 且 top1 无检测的连续帧。
  ② 段内 PBP possession 队作锚(已实测 66/66 段内 100% 稳定)。
  ③ 逐帧选持球者: 候选 = 该帧存在且 Otsu 队色 == PBP 队的球员(剔除裁判/场边观众);
     打分(软代价, 非硬门控) = 距上一帧 handler/球位 + 同 tid 连续性奖励; argmin 即持球者,
     ball_pos = 该球员 bbox 中心, 标记 source=pbp_holder。
  ④ 无候选(散球/无持球队球员在场) → 保守 None(不挂)。
  ⑤ 球轨迹 = detected(top1) + attached(遮挡段); 可视化/FLY-HOLD 复用。

验收(证据驱动, 非自报):
  - 覆盖提升: 58.8% → 估计 ~90%+。
  - 边界连续性(非循环论证): 段前最后检测球 ↔ 段首 attached, 段尾 attached ↔ 段后首检测球,
    在容差内比例。
  - 选择性: GT(可见球 154 帧) 上 augmented 的 detected 部分 == top1(遮挡段无 GT, 无法直验,
    如实声明); 真值验证靠 老程目视裁定(见 render_*.py)。

用法: ball_track_occluded.py [--clip sas_det] [--out JSON] [--no-render]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))

TH = 0.30
DIAG_MAX = 60
POSS_RADIUS = 0.04
N_FRAMES = 400
FPS = 10.0
HOLD_MAX = 250.0
CONT_PEN = 50.0          # 换手惩罚(px 等价): 偏好同持球者, 除非他人明显更近
TOL_NEAR = 2.0 * POSS_RADIUS * math.hypot(1920, 1080)   # 边界连续性容差 ≈174px
ADJUDGED_REFEREES = {"sas_det": "31,33,38,44,64", "sas_lal": "7,8,38"}


def top1(cands):
    best = None
    for c in cands:
        b = c["bbox"]
        d = max(b[2] - b[0], b[3] - b[1])
        if c["prob"] >= TH and d < DIAG_MAX:
            if best is None or c["prob"] > best["prob"]:
                best = c
    return best


def ctr(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_det")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    CLIP = a.clip
    EXCL = {int(t) for t in ADJUDGED_REFEREES.get(CLIP, "").split(",") if t.strip()}
    if a.out is None:
        a.out = str(AW / "validate" / f"{CLIP}_ball_track_occluded.json")

    SCORES = AW / "validate" / f"ball_cand_scores_dense_a442_{CLIP}_joint.json"
    OLD_TRACKS = AW / f"{CLIP}_poss_tile_stab" / "ball_tracks.json"
    STATES = AW / "validate" / f"{CLIP}_frame_states.json"
    T3A = AW / "validate" / f"{CLIP}_t3a_semantic.json"
    GT = AW / "validate" / f"{CLIP}_human_ball_events.json"
    FR = AW / CLIP
    for need in (SCORES, OLD_TRACKS, STATES, T3A, GT):
        if not Path(need).exists():
            sys.exit(f"[err] 缺前置 {need}")

    scores = json.loads(SCORES.read_text())[CLIP]
    old = json.loads(OLD_TRACKS.read_text())
    states = {r["fid"]: r for r in json.loads(STATES.read_text())["rows"]}
    live_of = {k: v["live_state"] for k, v in states.items()}
    poss_of = {k: v["possession"] for k, v in states.items()}
    t3a = json.loads(T3A.read_text())
    sem_of = {int(k): v["semantic"] for k, v in t3a["frame_annotations"].items()}
    gt = json.loads(GT.read_text())
    gt_frames = set()
    for seg in gt:
        gt_frames.update(seg["frames"])

    # ---- 逐帧 top1 检测球 ----
    det = [None] * N_FRAMES
    for i in range(N_FRAMES):
        fk = i + 1
        t = top1(scores.get(f"f{fk:05d}.jpg", []))
        if t is not None:
            b = t["bbox"]
            det[i] = ctr(b)

    # ---- 逐帧球员轨迹(tid->bbox, 剔除非球员) ----
    tid_bbox = [{} for _ in range(N_FRAMES)]
    for i, fr in enumerate(old[:N_FRAMES]):
        for pl in fr.get("players", []):
            if pl.get("bbox") and pl.get("track_id") not in EXCL:
                tid_bbox[i][pl["track_id"]] = pl["bbox"]

    # ---- Otsu 队色(与 t3b 同口径) ----
    tid_vals = {}
    for i in range(N_FRAMES):
        fk = i + 1
        if live_of.get(fk) != "live":
            continue
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        if img is None:
            continue
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        for tid, b in tid_bbox[i].items():
            x0, y0, x1, y1 = (max(0, int(b[0])), max(0, int(b[1])),
                              min(1920, int(b[2])), min(1080, int(b[3])))
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            tid_vals.setdefault(tid, []).append(float(np.median(hsv[y0:y1, x0:x1, 2])))
    tid_med = {t: float(np.median(v)) for t, v in tid_vals.items() if len(v) >= 10}
    vals = np.array(sorted(tid_med.values()), np.float32)
    hist, edges = np.histogram(vals, bins=64, range=(vals.min(), vals.max() + 1e-6))
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist); w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centers); s1 = s0[-1] - s0
    valid = (w0 > 0) & (w1 > 0)
    mu0 = np.where(valid, s0 / np.maximum(w0, 1), 0)
    mu1 = np.where(valid, s1 / np.maximum(w1, 1), 0)
    between = np.where(valid, w0 * w1 * (mu0 - mu1) ** 2, -1)
    thr = float(centers[int(np.argmax(between))])
    tid_team = {t: ("SAS" if v >= thr else "DET") for t, v in tid_med.items()}

    # ---- 遮挡段 ----
    gaps = []
    i = 0
    while i < N_FRAMES:
        fk = i + 1
        if live_of.get(fk) == "live" and det[i] is None:
            j = i
            while j + 1 < N_FRAMES and live_of.get(j + 2) == "live" and det[j + 1] is None:
                j += 1
            gaps.append((i, j))
            i = j + 1
        else:
            i += 1

    # ---- 逐帧 holder-attachment ----
    ball = list(det)                  # 增强球轨迹(检测 + 吸附)
    src = ["detect" if d is not None else "none" for d in det]
    occ = [False] * N_FRAMES
    holder = [None] * N_FRAMES
    attach_n = 0
    cont_pass = 0
    cont_total = 0
    gap_detail = []
    for (a0, b0) in gaps:
        fa, fb = a0 + 1, b0 + 1
        # 段内 PBP 队众数(应稳定)
        modes = {}
        for k in range(fa, fb + 1):
            p = poss_of.get(k)
            if p in ("SAS", "DET"):
                modes[p] = modes.get(p, 0) + 1
        team = max(modes, key=modes.get) if modes else None
        if team is None:
            gap_detail.append({"gap": f"{fa}-{fb}", "team": None, "attached": 0,
                               "note": "无 PBP 队(死球/跳球边界)"})
            continue
        # 段前 handler(检测帧 a0-1 的最近持球队球员)
        pre_det = det[a0 - 1] if a0 > 0 else None          # 边界连续性用(段前最后检测球)
        prev_pos = pre_det                                   # 段内 handoff 滚动起点
        prev_tid = None
        if prev_pos is not None:
            best = (1e18, None)
            for tid, bb in tid_bbox[a0 - 1].items():
                if tid_team.get(tid) != team:
                    continue
                d = math.hypot(ctr(bb)[0] - prev_pos[0], ctr(bb)[1] - prev_pos[1])
                if d < best[0]:
                    best = (d, tid)
            prev_tid = best[1]
        at_start = None
        attached_here = 0
        for f in range(a0, b0 + 1):
            cands = [(tid, ctr(bb)) for tid, bb in tid_bbox[f].items()
                     if tid_team.get(tid) == team]
            if not cands:
                ball[f] = None
                src[f] = "none"
                continue
            best = (1e18, None, None)
            for tid, c in cands:
                d = math.hypot(c[0] - (prev_pos[0] if prev_pos else c[0]),
                               c[1] - (prev_pos[1] if prev_pos else c[1]))
                pen = 0.0 if tid == prev_tid else CONT_PEN
                cost = d + pen
                if cost < best[0]:
                    best = (cost, tid, c)
            _, tid, c = best
            ball[f] = c
            src[f] = "pbp_holder"
            occ[f] = True
            holder[f] = tid
            attached_here += 1
            attach_n += 1
            prev_pos, prev_tid = c, tid
            if f == a0:
                at_start = c
        at_end = ball[b0]
        # 边界连续性(段前最后检测球 prev_pos ↔ 段首 attached; 段尾 attached ↔ 段后首检测球)
        next_det = det[b0 + 1] if b0 + 1 < N_FRAMES else None
        cont_total += 1
        ok_s = at_start is not None and pre_det is not None and \
            math.hypot(at_start[0] - pre_det[0], at_start[1] - pre_det[1]) <= TOL_NEAR
        ok_e = at_end is not None and next_det is not None and \
            math.hypot(at_end[0] - next_det[0], at_end[1] - next_det[1]) <= TOL_NEAR
        if ok_s and ok_e:
            cont_pass += 1
        sem = "occluded" if any(sem_of.get(k) == "occluded" for k in range(fa, fb + 1)) else (
              "candidate_miss" if any(sem_of.get(k) == "candidate_miss" for k in range(fa, fb + 1)) else "-")
        gap_detail.append({"gap": f"{fa}-{fb}", "len": fb - fa + 1, "team": team,
                           "attached": attached_here, "sem": sem,
                           "boundary_ok": bool(ok_s and ok_e),
                           "start_dist_px": round(math.hypot(at_start[0] - pre_det[0], at_start[1] - pre_det[1]), 1)
                                           if (at_start and pre_det) else None,
                           "end_dist_px": round(math.hypot(at_end[0] - next_det[0], at_end[1] - next_det[1]), 1)
                                           if (at_end and next_det) else None})

    # ---- 覆盖 / 选择性 ----
    n_det = sum(1 for s in src if s == "detect")
    n_att = sum(1 for s in src if s == "pbp_holder")
    n_none = sum(1 for s in src if s == "none")
    cov = (n_det + n_att) / N_FRAMES * 100
    # 选择性: GT 帧上 augmented 的 detected 部分须 == top1(遮挡段无 GT)
    gt_det_match = sum(1 for f in gt_frames if det[f - 1] is not None and src[f - 1] == "detect")
    gt_det_total = sum(1 for f in gt_frames if det[f - 1] is not None)
    # ---- FLY/HOLD(增强轨迹) ----
    # 速度只用「上一检测帧」作基准, 跳过遮挡吸附帧, 避免 gap 边缘 detect<->attached 跳变
    # 伪造 FLY(吸附段本身恒为 HOLD, 不计入速度)。
    spd = [None] * N_FRAMES
    prev_det_i = None
    for i in range(N_FRAMES):
        if src[i] == "detect" and ball[i] is not None:
            if prev_det_i is not None:
                g = i - prev_det_i
                spd[i] = math.hypot(ball[i][0] - ball[prev_det_i][0],
                                    ball[i][1] - ball[prev_det_i][1]) * FPS / g
            prev_det_i = i
    state = ["NONE"] * N_FRAMES
    rad = POSS_RADIUS * math.hypot(1920, 1080)
    for i in range(N_FRAMES):
        if src[i] == "detect":
            s = spd[i]
            near = min((math.hypot(ctr(bb)[0] - ball[i][0], ctr(bb)[1] - ball[i][1])
                        for bb in tid_bbox[i].values()), default=1e18)
            state[i] = "FLY" if (s is not None and s >= HOLD_MAX) or near > rad else "HOLD"
        elif src[i] == "pbp_holder":
            state[i] = "HOLD"   # 球推断在持球者手中
        else:
            state[i] = "NONE"

    n_hold = sum(1 for s in state if s == "HOLD")
    n_fly = sum(1 for s in state if s == "FLY")

    print(f"[ball] top1 检测覆盖 {n_det}/{N_FRAMES} ({n_det/N_FRAMES*100:.1f}%)")
    print(f"[att] 遮挡段吸附 {n_att} 帧, 仍无球(散球/无候选) {n_none} 帧, 球轨迹总覆盖 {cov:.1f}%")
    pass_s = sum(1 for g in gap_detail if g.get("start_dist_px") is not None and g["start_dist_px"] <= TOL_NEAR)
    pass_e = sum(1 for g in gap_detail if g.get("end_dist_px") is not None and g["end_dist_px"] <= TOL_NEAR)
    print(f"[cont] 边界连续性 两端都过 {cont_pass}/{cont_total} | 仅首端过 {pass_s}/{cont_total} | "
          f"仅尾端过 {pass_e}/{cont_total} (容差 {TOL_NEAR:.0f}px; 抢断/传球段天然单边失败, 属预期)")
    print(f"[sel]  GT 帧 detected 部分与 top1 一致 {gt_det_match}/{gt_det_total} "
          f"(遮挡段无 GT, 无法直验 — 真值靠目视裁定)")
    print(f"[kin] 增强轨迹: HOLD={n_hold} FLY={n_fly} NONE={sum(1 for s in state if s=='NONE')}")

    out = {"meta": {"clip": CLIP, "method": "per-frame holder-attachment (PBP possession anchor)",
                    "no_interp": True, "scope": "ball_track_only (A4.53 possession gate untouched)",
                    "ball_source": "top1(detect) + pbp_holder(occluded, inferred)",
                    "otsu_thr_V": round(thr, 1), "excluded_tids": sorted(EXCL),
                    "continuity_penalty_px": CONT_PEN, "boundary_tol_px": round(TOL_NEAR, 1),
                    "fps": FPS, "hold_max_px_s": HOLD_MAX},
           "coverage": {"top1_detect_pct": round(n_det / N_FRAMES * 100, 1),
                        "attached_pct": round(n_att / N_FRAMES * 100, 1),
                        "augmented_total_pct": round(cov, 1),
                        "none_pct": round(n_none / N_FRAMES * 100, 1)},
           "validation": {"boundary_continuity_pass": cont_pass, "boundary_continuity_total": cont_total,
                          "gt_detect_match": gt_det_match, "gt_detect_total": gt_det_total,
                          "gt_note": "occluded frames have no human-labeled ball; direct GT check impossible"},
           "kinematics": {"n_hold": n_hold, "n_fly": n_fly,
                          "n_none": sum(1 for s in state if s == "NONE")},
           "frame": [{"fid": i + 1, "ball": [round(ball[i][0], 1), round(ball[i][1], 1)] if ball[i] else None,
                      "source": src[i], "occluded": occ[i], "holder_tid": holder[i],
                      "state": state[i]} for i in range(N_FRAMES)],
           "gap_detail": gap_detail}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"[out] {a.out}")

    # ---- 覆盖时间线 PNG ----
    if not a.no_render:
        render_timeline(CLIP, src, occ, poss_of, live_of, a.out)


def render_timeline(CLIP, src, occ, poss_of, live_of, out_json):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    N = N_FRAMES
    fig, ax = plt.subplots(figsize=(13, 3.2))
    for i in range(N):
        fk = i + 1
        if live_of.get(fk) != "live":
            ax.axvspan(i - 0.5, i + 0.5, color="#444444", alpha=0.25, lw=0)
        col = "#2ca02c" if src[i] == "detect" else ("#ff7f0e" if src[i] == "pbp_holder" else "#bbbbbb")
        ax.vlines(i, 0, 1, color=col, lw=1.6)
    # PBP possession 队带(顶部)
    for i in range(N):
        fk = i + 1
        p = poss_of.get(fk)
        if p == "SAS":
            ax.axvspan(i - 0.5, i + 0.5, ymin=1.02, ymax=1.10, color="#1f77b4", lw=0)
        elif p == "DET":
            ax.axvspan(i - 0.5, i + 0.5, ymin=1.02, ymax=1.10, color="#d62728", lw=0)
    ax.set_xlim(-1, N)
    ax.set_ylim(0, 1.18)
    ax.set_yticks([])
    ax.set_xlabel("frame (1..400)")
    ax.set_title(f"{CLIP} ball coverage: green=detected  orange=occluded-attached(PBP holder)  grey=none")
    leg = [Patch(color="#2ca02c", label="detected (top1)"),
           Patch(color="#ff7f0e", label="occluded-attached (inferred)"),
           Patch(color="#bbbbbb", label="none (loose/uncertain)"),
           Patch(color="#1f77b4", label="PBP SAS"), Patch(color="#d62728", label="PBP DET"),
           Patch(color="#444444", label="dead ball")]
    ax.legend(handles=leg, ncol=6, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    fig.tight_layout()
    png = str(Path(out_json).with_suffix("")) + "_timeline.png"
    fig.savefig(png, dpi=130, bbox_inches="tight")
    print(f"[render] {png}")


if __name__ == "__main__":
    main()
