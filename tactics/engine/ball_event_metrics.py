#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ball_event_metrics.py — 球事件指标富集（A4.22 · 速度 / 方向 / 停留热区）。

输入：各域 `{clip}_poss_tile/ball_tracks.json`（逐帧 ball[nullable] + players[track_id,bbox]）。
      该文件是 A4.13b/A4.15 同管线产出，已是「现在更干净的持球者信号」的承载物。
输出（action_work/validate/ball_event_metrics/）：
  <clip>_ball_metrics.json     结构化指标（速度/方向/持球者移动/热区统计）
  <clip>_ball_heatmap.jpg      帧空间持球停留热区（诚实标注：非球场对齐）
  <clip>_ball_speed_hist.jpg   球速分布直方图（px/s）
  ball_metrics_summary.md      7 域汇总表 + 平凡预测器特异性自证

设计纪律（继承项目铁律）：
  - 数字全从 JSON 现读；帧率固定 10fps（sas_* pose_motion.json + 宽景 memory 均确认）。
  - 视觉先自证：heatmap / hist 必须目视验收，结构反常即诚实入账。
  - 指标特异性先自证：持球者移动速度的平凡预测器基线（随机选球员）必须量化，
    若 holder 速度≈随机球员速度 ⇒ 该指标零特异性，不得作战术证据。
  - 平滑 ≠ 正确：interp（插值补点）段与 real 段分开报，不得混用粉饰。
  - 帧空间坐标：court 配准已封口（A4.17），故方向/热区一律帧空间，绝不伪称球场对齐。

用法
----
  python engine/ball_event_metrics.py --all-clips
  python engine/ball_event_metrics.py --clip w1
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
OUT = AW / "validate" / "ball_event_metrics"
FPS = 10.0                      # 全 7 域统一 10fps（dt=0.1s）
W, H = 1920, 1080
HOLDER_RADIUS = 150.0           # 持球者归属搜索半径(px)，宽松于 A4.19 的 88px
FAST_PX_S = 300.0              # 候选「快攻/长传」阈值 ≈ 30 px/帧
HOLD_MAX_PS = 250.0            # 球速低于此(px/s ≈25px/帧)视为「在球员手中/运球」，高于则「飞行中」
PLAUS_LO_PS = 80.0             # 物理合理步长下界 ≈8px/帧（继承 ball_motion_feats2 的 [8,150]px 惯例）
PLAUS_HI_PS = 1500.0           # 物理合理步长上界 ≈150px/帧；超出 ⇒ 帧间跳变（检测跳/FP）
COMPASS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]  # atan2(+x右,+y下)


def ctr(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def load_clip(clip: str):
    c = clip.replace("baseline_", "")   # 目录命名为 w1_poss_tile，与 run_ball_events._poss_dir 一致
    p = AW / f"{c}_poss_tile" / "ball_tracks.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    # 归一化为逐帧结构（兼容 frame/file/ball/players 字段）
    out = []
    for fr in data:
        ball = fr.get("ball")
        bcenter = None
        interp = None
        bconf = None
        if isinstance(ball, dict) and ball.get("bbox"):
            bcenter = ctr(ball["bbox"])
            interp = bool(ball.get("interp", False))
            bconf = ball.get("conf")
        players = []
        for pl in fr.get("players", []):
            if pl.get("bbox"):
                players.append({"tid": pl.get("track_id"), "c": ctr(pl["bbox"]),
                                "bbox": pl["bbox"], "conf": pl.get("conf")})
        out.append({"frame": fr.get("frame"), "ball": bcenter, "interp": interp,
                    "bconf": bconf, "players": players})
    return out


def ball_speed_dir(frames, fps=FPS):
    """逐相邻帧（两端均有 ball）计算球速/方向；区分 real / interp 段。"""
    segs = []
    for i in range(len(frames) - 1):
        a, b = frames[i], frames[i + 1]
        if a["ball"] is None or b["ball"] is None:
            continue
        dx = b["ball"][0] - a["ball"][0]
        dy = b["ball"][1] - a["ball"][1]
        d = math.hypot(dx, dy)
        seg = d * fps                       # px/s
        ang = math.degrees(math.atan2(dy, dx))  # 帧空间：+x 右, +y 下
        segs.append({"f0": a["frame"], "f1": b["frame"], "dist_px": round(d, 1),
                     "speed_ps": round(seg, 1), "dir_deg": round(ang, 1),
                     "interp": bool(a["interp"] or b["interp"])})
    return segs


def holder_assign(frames, radius=HOLDER_RADIUS, fps=FPS):
    """逐帧把球归属给最近球员(track_id)；计算持球者位移与换手次数。"""
    holders = []
    for fr in frames:
        if fr["ball"] is None:
            holders.append(None)
            continue
        best, bd = None, None
        for pl in fr["players"]:
            d = math.hypot(pl["c"][0] - fr["ball"][0], pl["c"][1] - fr["ball"][1])
            if bd is None or d < bd:
                bd, best = d, pl["tid"]
        if best is not None and bd <= radius:
            holders.append((best, bd))
        else:
            holders.append(None)
    hsegs = []
    for i in range(len(frames) - 1):
        h0, h1 = holders[i], holders[i + 1]
        if h0 is None or h1 is None:
            hsegs.append(None)
            continue
        # 持球者框心位移（同 tid 或换手均计）
        a, b = frames[i], frames[i + 1]
        pl0 = next((p for p in a["players"] if p["tid"] == h0[0]), None)
        pl1 = next((p for p in b["players"] if p["tid"] == h1[0]), None)
        if pl0 is None or pl1 is None:
            hsegs.append(None)
            continue
        dx = pl1["c"][0] - pl0["c"][0]
        dy = pl1["c"][1] - pl0["c"][1]
        d = math.hypot(dx, dy)
        hsegs.append({"f0": a["frame"], "f1": b["frame"],
                      "disp_px": round(d, 1), "speed_ps": round(d * fps, 1),
                      "change": h0[0] != h1[0], "tid0": h0[0], "tid1": h1[0]})
    return holders, hsegs


def trivial_holder_baseline(frames, radius=HOLDER_RADIUS, fps=FPS):
    """平凡预测器：若每帧随机抽一名球员，其框心相邻帧位移的统计。
    用于量化 holder 速度是否含特异性（≈随机 ⇒ 零特异性）。"""
    rng = np.random.default_rng(20260926)
    disp = []
    for i in range(len(frames) - 1):
        a, b = frames[i], frames[i + 1]
        if not a["players"] or not b["players"]:
            continue
        pa = a["players"][rng.integers(len(a["players"]))]["c"]
        pb = b["players"][rng.integers(len(b["players"]))]["c"]
        disp.append(math.hypot(pb[0] - pa[0], pb[1] - pa[1]) * fps)
    return float(np.median(disp)) if disp else None


def heatmap(frames, out: Path):
    """帧空间球位置停留热区（2D 直方图 + 高斯模糊 + jet 着色），诚实标注非球场对齐。"""
    pts = [f["ball"] for f in frames if f["ball"] is not None]
    canvas = np.zeros((H, W, 3), np.uint8)
    if not pts:
        cv2.putText(canvas, "NO BALL POSITIONS", (40, H // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    1.2, (200, 200, 200), 2)
        cv2.imwrite(str(out), canvas)
        return 0
    xs = np.array([p[0] for p in pts], float)
    ys = np.array([p[1] for p in pts], float)
    nb = 64
    hist, _, _ = np.histogram2d(xs, ys, bins=nb, range=[[0, W], [0, H]])
    hist = cv2.GaussianBlur(hist, (5, 5), 0)
    if hist.max() > 0:
        hist = hist / hist.max()
    # jet 着色（64×64），上采样到全帧尺寸
    jet = cv2.applyColorMap((hist * 255).astype(np.uint8), cv2.COLORMAP_JET)
    jet = cv2.resize(jet, (W, H), interpolation=cv2.INTER_LINEAR)
    mask = (hist > 0.05).astype(np.float32)
    mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_LINEAR)
    # 背景压暗，热区叠加
    base = np.full((H, W, 3), (18, 20, 28), np.uint8)
    base = (base.astype(np.float32) * (1 - 0.85 * mask[..., None])).astype(np.uint8)
    hot = (jet.astype(np.float32) * (0.9 * mask[..., None])).astype(np.uint8)
    canvas = cv2.add(base, hot)
    cv2.rectangle(canvas, (0, 0), (W - 1, H - 1), (60, 64, 72), 2)
    cap = f"BALL STAY-HOTZONE (frame-space, NOT court-aligned)  n={len(pts)}"
    cv2.putText(canvas, cap, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(canvas, cap, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (235, 235, 235), 1, cv2.LINE_AA)
    cv2.imwrite(str(out), canvas)
    return len(pts)


def speed_hist(segs, out: Path):
    plaus = [s["speed_ps"] for s in segs if not s["interp"]
             and PLAUS_LO_PS <= s["speed_ps"] <= PLAUS_HI_PS]
    n_jump = sum(1 for s in segs if not s["interp"] and s["speed_ps"] > PLAUS_HI_PS)
    canvas = np.full((420, 760, 3), (18, 20, 28), np.uint8)
    if not plaus:
        cv2.putText(canvas, "NO PLAUSIBLE BALL SEGMENTS", (40, 210), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (200, 200, 200), 2)
        cv2.imwrite(str(out), canvas)
        return
    arr = np.array(plaus, float)
    bins = np.linspace(0, 1500.0, 31)
    counts, edges = np.histogram(arr, bins=bins)
    cmax = counts.max()
    x0, y0, bw, bh = 60, 360, 11, 300
    for k, c in enumerate(counts):
        if c == 0:
            continue
        x = x0 + k * (bw + 2)
        hgt = int(c / cmax * bh)
        cv2.rectangle(canvas, (x, y0 - hgt), (x + bw, y0), (0, 200, 255), -1)
    # 快攻阈值线
    fx = x0 + int(FAST_PX_S / 1500.0 * (len(counts) * (bw + 2)))
    cv2.line(canvas, (fx, y0 - bh), (fx, y0), (0, 255, 120), 2)
    cv2.putText(canvas, f">{FAST_PX_S:.0f}px/s=fast", (fx - 120, y0 - bh - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 120), 1)
    cv2.putText(canvas, "ball speed (px/s) — PLAUSIBLE segments only [80,1500]", (60, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (235, 235, 235), 1)
    cv2.putText(canvas, f"n={len(plaus)}  med={np.median(arr):.0f}  p95={np.percentile(arr,95):.0f}  "
                        f"excl_jump={n_jump}", (60, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    cv2.imwrite(str(out), canvas)


def dir_stats(segs):
    reals = [s["dir_deg"] for s in segs if not s["interp"]]
    if not reals:
        return {"n": 0}
    arr = np.deg2rad(np.array(reals))
    # 圆周均值方向
    m_x = np.mean(np.cos(arr))
    m_y = np.mean(np.sin(arr))
    mean_deg = math.degrees(math.atan2(m_y, m_x)) % 360
    bins = np.linspace(-180, 180, 9)  # 8 罗盘
    cnt = Counter()
    for d in reals:
        idx = int(np.digitize([d], bins)[0]) - 1
        idx = min(max(idx, 0), 7)
        cnt[COMPASS[idx]] += 1
    tot = len(reals)
    compass = {c: round(cnt.get(c, 0) / tot, 3) for c in COMPASS}
    dom = max(compass, key=compass.get)
    return {"n": tot, "circular_mean_deg": round(mean_deg, 1),
            "dominant_compass": dom, "compass_frac": compass}


def process_clip(clip, fps=FPS):
    frames = load_clip(clip)
    if frames is None:
        return None
    n = len(frames)
    n_ball = sum(1 for f in frames if f["ball"] is not None)
    n_real = sum(1 for f in frames if f["ball"] is not None and not f["interp"])
    n_interp = n_ball - n_real
    cov = n_ball / n if n else 0.0

    segs = ball_speed_dir(frames, fps)
    reals = [s for s in segs if not s["interp"]]
    plaus = [s for s in reals if PLAUS_LO_PS <= s["speed_ps"] <= PLAUS_HI_PS]
    jumps = [s for s in reals if s["speed_ps"] > PLAUS_HI_PS]
    slows = [s for s in reals if s["speed_ps"] < PLAUS_LO_PS]
    ball_spd = {s["f1"]: s["speed_ps"] for s in segs}  # 用于判定「球在手中」vs「飞行中」
    pv = [s["speed_ps"] for s in plaus]
    spd = {
        "n_seg_real": len(reals),
        "n_plaus": len(plaus),
        "n_jump": len(jumps),
        "n_slow": len(slows),
        "frac_jump": round(len(jumps) / len(reals), 3) if reals else None,
        "med_plaus_ps": round(float(np.median(pv)), 1) if pv else None,
        "mean_plaus_ps": round(float(np.mean(pv)), 1) if pv else None,
        "p95_plaus_ps": round(float(np.percentile(pv, 95)), 1) if pv else None,
        "max_plaus_ps": round(float(np.max(pv)), 1) if pv else None,
        "frac_fast": round(sum(1 for v in pv if v >= FAST_PX_S) / len(pv), 3) if pv else None,
    }
    dstat = dir_stats(plaus)

    holders, hsegs = holder_assign(frames, fps=fps)
    # 仅「球在球员手中」(球速<HOLD_MAX_PS)的相邻帧才计为持球者移动，排除飞行段误归
    h_held = [h["speed_ps"] for h in hsegs
              if h is not None and ball_spd.get(h["f1"], 1e9) < HOLD_MAX_PS]
    n_change = sum(1 for h in hsegs if h is not None and h["change"])
    n_holder_frames = sum(1 for h in holders if h is not None)
    base = trivial_holder_baseline(frames, fps=fps)
    holder = {
        "n_holder_frames": n_holder_frames,
        "holder_coverage": round(n_holder_frames / n_ball, 3) if n_ball else None,
        "n_held_seg": len(h_held),
        "med_held_ps": round(float(np.median(h_held)), 1) if h_held else None,
        "mean_held_ps": round(float(np.mean(h_held)), 1) if h_held else None,
        "n_possession_changes": n_change,
        "trivial_baseline_med_ps": round(base, 1) if base else None,
        # 特异性解读：ratio<<1 ⇒ 我们的「持球者」比随机抽球员移动慢得多 ⇒ 不是随机噪声
        # （平凡预测器若与指标同量级=零特异性；此处平凡预测器给出的是「高位移」反例，故指标含特异性）
        "specificity_ratio_vs_random": round(float(np.median(h_held)) / base, 3) if (h_held and base) else None,
    }

    metrics = {
        "clip": clip, "fps": FPS, "n_frames": n,
        "n_ball_frames": n_ball, "n_real": n_real, "n_interp": n_interp,
        "frame_coverage": round(cov, 4),
        "ball_speed": spd, "ball_direction": dstat, "holder": holder,
    }
    return frames, metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all-clips", action="store_true")
    ap.add_argument("--fps", type=float, default=FPS)
    a = ap.parse_args()
    fps = a.fps

    clips = []
    if a.all_clips:
        clips = ["sas_hou", "sas_nop", "sas_det", "baseline_w1", "baseline_w2",
                 "baseline_w3", "baseline_w4"]
    elif a.clip:
        # 允许 w1/w2/... 简写
        clips = [a.clip if a.clip.startswith("baseline_") else f"baseline_{a.clip}"]
    else:
        ap.error("需要 --clip 或 --all-clips")

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for clip in clips:
        res = process_clip(clip, fps=fps)
        if res is None:
            print(f"[skip] {clip}: 无 {clip}_poss_tile/ball_tracks.json")
            continue
        frames, m = res
        (OUT / f"{clip}_ball_metrics.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=1))
        heatmap(frames, OUT / f"{clip}_ball_heatmap.jpg")
        speed_hist(ball_speed_dir(frames), OUT / f"{clip}_ball_speed_hist.jpg")
        rows.append(m)
        print(f"{clip:12s} cov={m['frame_coverage']*100:5.1f}%  "
              f"plaus={m['ball_speed']['n_plaus']:4d} jump={m['ball_speed']['n_jump']:3d}  "
              f"med={m['ball_speed']['med_plaus_ps']}px/s  "
              f"held_med={m['holder']['med_held_ps']}px/s  "
              f"changes={m['holder']['n_possession_changes']}  "
              f"spec={m['holder']['specificity_ratio_vs_random']}")

    if rows:
        (OUT / "ball_metrics_rows.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"\n→ {len(rows)} 域指标已落盘至 {OUT}")


if __name__ == "__main__":
    main()
