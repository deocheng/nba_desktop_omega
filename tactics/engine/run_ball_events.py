#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_ball_events.py — 球事件信号端到端产品（一键、零人工）。

把「scores → 跟踪器 → 门禁 → 球事件轨迹」收敛为一命令，对任意片段产出：
  1) <clip>_ball_events.json   球事件轨迹（持续轨迹，min_track=3）
  2) <clip>_ball_courtmap.jpg  1920×1080 球场空间图（各轨迹同色连球心）
  3) 控制台打印门禁裁定
集成接口（详见报告）：tactical_movement.py 的 handler_id 已读取 fr["ball"]；
  把本工具每帧球心写成 fr["ball"]["bbox"]≈[cx-r,cy-r,cx+r,cy+r] 即完成与球员移动战术分析的拼接
  （前提：该片段有球员 tracking —— 当前仅宽景四窗 w1–w4 具备）。

用法
----
  python engine/run_ball_events.py --clip sas_hou
  python engine/run_ball_events.py --all-clips          # 7 域统一跑（复用 gate_tracked_recalib.json 工作点）
工作点 th：默认取 gate_tracked_recalib.json 的 operating_th（sas_nop/sas_det 各 0.3/0.8），
  缺省回退 0.3；birth=th、gap=8、min_track=3 —— 与 A4.15 的 7/7 全 PASS 口径一致。
  A4.42 转正：默认 --preset multiscale（dense 头打分候选池 validate/ball_cand_scores_dense_a442_<clip>_joint.json），
  legacy 预设回退旧 top-4 池(validate/<clip>_scores.json)；final351 留作旧池官方头。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import importlib.util
import json
import math
import random
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
AW = Path(ROOT) / "action_work"
GAP = 8
MIN_TRACK = 3


def _load_track_ball():
    spec = importlib.util.spec_from_file_location(
        "tb", str(Path(ROOT) / "engine" / "track_ball.py"))
    tb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tb)
    return tb


def _load_fp_filter():
    spec = importlib.util.spec_from_file_location(
        "bff", str(Path(ROOT) / "engine" / "ball_fp_filter.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── A4.19：FP 过滤（球不在任何球员附近 ⇒ 剔除） ─────────────────────────────
DIAG = (1920.0 ** 2 + 1080.0 ** 2) ** 0.5
SUPPORT_PX = round(0.04 * DIAG, 1)     # = 88.1px，与 ball_possession 的 poss_radius 同源


def _poss_dir(clip):
    """片段名 → 球员框目录（baseline_w1 → w1_poss_tile）。"""
    c = clip.replace("baseline_", "")
    return AW / f"{c}_poss_tile" / "ball_tracks.json"


def load_player_boxes(clip):
    """{frame_no: [bbox,...]}；键用文件名的 1-based 编号，与 track_ball.fid() 对齐。"""
    p = _poss_dir(clip)
    if not p.exists():
        return None
    out = {}
    for f in json.loads(p.read_text()):
        out[int(str(f["file"])[1:6])] = [pl["bbox"] for pl in f.get("players", [])]
    return out


def filter_tracks(tracks, boxes, support_px=SUPPORT_PX, min_step=0.0):
    """逐轨迹判定：至少 1 个球点落在球员附近 ⇒ 保留；否则（可选：还在动）⇒ 剔除。

    返回 (kept, rows)。理由：一条 ≥3 帧的球轨迹若全程离所有球员 >88px，
    在 NBA 转播语境下不是"球在飞行"，而是观众席/LED/转播包装等伪目标
    （A4.19 目视证据：36/36 个被剔除点画面内均无球）。
    """
    bff = _load_fp_filter()
    kept, rows = [], []
    for ti, t in enumerate(tracks):
        ds = []
        for f, c in zip(t["frames"], t["centers"]):
            box = boxes.get(int(f), [])
            ds.append(min(bff.rect_dist(c[0], c[1], b) for b in box) if box else None)
        dn = [d for d in ds if d is not None]
        n_sup = sum(1 for d in dn if d <= support_px)
        steps = [math.hypot(t["centers"][k + 1][0] - t["centers"][k][0],
                            t["centers"][k + 1][1] - t["centers"][k][1])
                 for k in range(len(t["centers"]) - 1)]
        ms = sum(steps) / len(steps) if steps else 0.0
        keep = n_sup >= 1 or (min_step > 0 and ms >= min_step)
        rows.append({"track": ti, "n_pts": len(t["frames"]), "n_sup": n_sup,
                     "d_min": round(min(dn), 1) if dn else None,
                     "mean_step": round(ms, 1), "keep": keep})
        if keep:
            kept.append(t)
    return kept, rows


def operating_th(clip, tb):
    p = AW / "validate" / "gate_tracked_recalib.json"
    if p.exists():
        d = json.loads(p.read_text())
        if clip in d and d[clip]["operating_th"] is not None:
            return d[clip]["operating_th"]
    return 0.3


def resolve_scores(clip, scores_arg, preset):
    """默认 scores 解析（A4.42 转正）：multiscale 预设优先用 dense 头打分候选池，
    缺失则回退旧 top-4 池路径；legacy 预设直读旧池；显式 --scores 最高优先。"""
    if scores_arg:
        d = json.loads(Path(scores_arg).read_text())
        return d[clip] if clip in d else d
    if preset == "multiscale":
        ms = AW / "validate" / f"ball_cand_scores_dense_a442_{clip}_joint.json"
        if ms.exists():
            return json.loads(ms.read_text())[clip]
    # legacy 默认：旧 top-4 池（final351 官方头对应路径）
    return json.loads((AW / "validate" / f"{clip}_scores.json").read_text())[clip]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all-clips", action="store_true")
    ap.add_argument("--scores", default=None,
                    help="覆盖默认打分源（如 HUMAN 头: validate/sas_det_scores_human.json）；"
                         "文件须含 <clip> 顶层键")
    ap.add_argument("--tag", default=None,
                    help="产物文件名后缀（如 human → sas_det_human_ball_events.json），避免覆盖旧产物")
    ap.add_argument("--court", action="store_true",
                    help="额外跑 court_render 配准 + 产出真·球场坐标图（较重，需先配准成功）")
    ap.add_argument("--no-fp-filter", action="store_true",
                    help="关闭 A4.19 球员邻近性 FP 过滤（默认开启）")
    ap.add_argument("--support-px", type=float, default=SUPPORT_PX,
                    help=f"球点到最近球员框的距离阈值（默认 {SUPPORT_PX}px = 0.04×帧对角线）")
    ap.add_argument("--min-step", type=float, default=0.0,
                    help=">0 则开启 R2：无球员支撑但 mean_step≥该值的轨迹仍保留（保护飞行段）")
    ap.add_argument("--preset", default="multiscale", choices=["multiscale", "legacy"],
                    help="默认 multiscale=dense头打分候选池(validate/ball_cand_scores_dense_a442_<clip>_joint.json)；"
                         "legacy=旧 top-4 池(validate/<clip>_scores.json)。final351 留作旧池官方头。")
    a = ap.parse_args()
    tb = _load_track_ball()
    do_fp = not a.no_fp_filter
    if do_fp:
        print(f"[FP 过滤] 开  support≤{a.support_px:.0f}px  min_step={a.min_step}")

    targets = []
    if a.scores:
        if not a.clip:
            ap.error("--scores 需配合 --clip")
        d = json.loads(Path(a.scores).read_text())
        frames = d[a.clip] if a.clip in d else d
        targets.append((a.clip, frames))
    elif a.all_clips:
        for c in ("sas_hou", "sas_nop", "sas_det"):
            targets.append((c, resolve_scores(c, None, a.preset)))
        base = json.loads((AW / "ball_cand_scores_v2.json").read_text())
        for w, fr in base.items():
            targets.append((f"baseline_{w}", fr))
    elif a.clip:
        targets = [(a.clip, resolve_scores(a.clip, None, a.preset))]
    else:
        ap.error("需要 --clip 或 --all-clips")

    print(f"{'域':12s} {'th':5s} {'覆盖':6s} {'可跟踪':7s} {'步长':6s} {'步数':5s} {'轨迹':5s} 裁定")
    for name, frames in targets:
        th = operating_th(name, tb)
        tracks = tb.track_clip(frames, th, birth=th, gap=GAP)
        m0 = tb.track_metrics(tracks, len(frames), MIN_TRACK)
        fp_note = ""
        if do_fp:
            boxes = load_player_boxes(name)
            if boxes is None:
                fp_note = " [无球员框，过滤跳过]"
            else:
                tracks, frows = filter_tracks(tracks, boxes, a.support_px, a.min_step)
                m_tmp = tb.track_metrics(tracks, len(frames), MIN_TRACK)
                fp_note = (f" [FP过滤 {m0['n_tracks']}→{m_tmp['n_tracks']}轨 "
                           f"{m0['n_claims']}→{m_tmp['n_claims']}点]")
        m = tb.track_metrics(tracks, len(frames), MIN_TRACK)
        ok = (m["n_steps"] >= tb.MIN_STEPS and m["trackable_frac"] is not None
              and m["trackable_frac"] >= 0.80 and (m["median_step_px"] is None or m["median_step_px"] < tb.SMOOTH_PX))
        verdict = "PASS" if ok else "FAIL"
        cov = m["frame_coverage"] * 100 if m["frame_coverage"] else 0.0
        trk = f"{m['trackable_frac']*100:.1f}%" if m["trackable_frac"] is not None else "—"
        step = str(m["median_step_px"]) if m["median_step_px"] is not None else "—"
        print(f"{name:12s} {th:<5} {cov:5.1f}% {trk:7s} {step:6s} {m['n_steps']:<5} {m['n_tracks']:<5} {verdict}{fp_note}")

        if not a.all_clips:  # 单片段才落盘工件
            clip = name
            sfx = f"_{a.tag}" if a.tag else ""
            kept = [t for t in tracks if len(t["frames"]) >= MIN_TRACK]
            (AW / "validate" / f"{clip}{sfx}_ball_events.json").write_text(
                json.dumps(kept, ensure_ascii=False, indent=1))
            if do_fp and boxes is not None:
                (AW / "validate" / f"{clip}{sfx}_fp_events.json").write_text(json.dumps(
                    {"clip": clip, "th": th, "support_px": a.support_px,
                     "min_step": a.min_step, "before": m0, "after": m,
                     "rows": frows}, ensure_ascii=False, indent=1))
            _framespace(kept, AW / "validate" / f"{clip}{sfx}_framespace_tracks.jpg", clip)
            print(f"→ {clip}{sfx}_ball_events.json ({len(kept)} 轨迹) · "
                  f"{clip}{sfx}_framespace_tracks.jpg（帧空间，非球场）")
            if a.court:  # 真·球场坐标图（配准较重，按需触发）
                import court_render as cr
                mode, cams, reg = cr.register_clip(clip, kept)
                if mode is None:
                    print(f"  配准失败，无真球场图：{reg.get('detail')}")
                else:
                    mapped = cr.map_tracks(kept, mode, cams)
                    out = AW / "validate" / f"{clip}_court_truth.jpg"
                    n = cr.render_court_map(clip, mapped, out)
                    print(f"  → {clip}_court_truth.jpg（真球场坐标，{n}/{len(kept)} 条轨迹成功映射）")


def _framespace(tracks, out: Path, title=""):
    """帧空间球轨迹图（**诚实版**：不画伪球场线，明确标注未对齐球场）。

    历史教训：旧 `_courtmap` 只画「半场中线+中圈」两条装饰图元，却被命名为 courtmap,
    让人误以为球轨迹落在球场上——实际球坐标是**帧像素**(1920×1080)，转播片段尤为明显。
    真·球场坐标图见 `<clip>_court_truth.jpg`（由 court_render.py 产出，需先配准）。
    """
    W, H = 1920, 1080
    cv = np.full((H, W, 3), (18, 20, 28), np.uint8)
    cv2.rectangle(cv, (0, 0), (W - 1, H - 1), (60, 64, 72), 2)  # 仅画帧边界，不伪造成球场
    palette = [(0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 255, 0), (255, 128, 0),
               (0, 200, 255), (200, 0, 255), (0, 255, 180)]
    for i, t in enumerate(tracks):
        col = palette[i % len(palette)]
        pts = [(int(c[0]), int(c[1])) for c in t["centers"]]
        for j in range(len(pts) - 1):
            cv2.line(cv, pts[j], pts[j + 1], col, 3)
        for p in pts:
            cv2.circle(cv, p, 5, col, -1)
    cap = "FRAME-SPACE ball tracks - NOT court-aligned"
    if title:
        cap = f"{title}  |  {cap}"
    cv2.putText(cv, cap, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(cv, cap, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                (235, 235, 235), 1, cv2.LINE_AA)
    cv2.imwrite(str(out), cv)


if __name__ == "__main__":
    main()
