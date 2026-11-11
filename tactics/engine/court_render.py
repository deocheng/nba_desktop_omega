#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""court_render.py — 把球轨迹画在**真·球场坐标**上（替换 run_ball_events 的占位 courtmap）。

为什么需要它（用户指出原 courtmap 只有半场中线+中圈，且球坐标是帧像素、与球场错位）：
  · 规范球场几何来自 court_model.build_model()（NBA 94×50ft，米制，全量线点集）。
  · 帧→球场位姿来自 court_fit（LookCam）：用规范球场模型反解相机 (C,T,f,roll)。
  · LookCam.to_court(uv) 把图像像素逆映射回球场地面 (x,y) —— 这是球轨迹落到真球场的关键。

两类片段的处理（诚实区分）：
  · 宽景四窗 w1–w4：固定机位 ⇒ 每窗配准 1 帧，整窗复用单位姿。
  · 转播 sas_hou/nop/det：机位会动 ⇒ 只配准「球轨迹涉及的唯一帧」，warm-start 逐帧精修；
    含球场线的全景帧才映射成功，特写帧无可映射点 ⇒ 诚实跳过（不画假球场）。

用法
----
  python engine/court_render.py --clip sas_hou
  python engine/court_render.py --all-clips
输出
----
  action_work/validate/<clip>_court_truth.jpg   （真比例球场 + 球轨迹按真实球场坐标绘制）
  action_work/validate/<clip>_court_cams.json   （配准结果：每帧位姿 + 拟合质量）
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

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))

from court_fit import OVERLAY_BOXES, LookCam, Scorer, grid_search, make_cam, refine, template
from court_lines import floor_roi
from court_model import HALF_L, HALF_W, LANE_HW, R_3PT, R_CENTER, R_FT, X_LANE, Y_3PT_CORNER, build_model

# ---------------- 球场画布（米 → 像素） ----------------
SCALE = 42.0          # px / m
MARGIN = 60.0         # 边距 px
CANVAS_W = int(2 * HALF_L * SCALE) + 2 * int(MARGIN)
CANVAS_H = int(2 * HALF_W * SCALE) + 2 * int(MARGIN)
BG = (18, 20, 28)     # 深色底


def w2c(x, y):
    """世界 (x,y) 米 → 画布像素。+x 向右(指向右篮)，+y 向上。"""
    px = MARGIN + (x + HALF_L) * SCALE
    py = MARGIN + (HALF_W - y) * SCALE
    return int(round(px)), int(round(py))


def draw_court_base():
    cv = np.full((CANVAS_H, CANVAS_W, 3), BG, np.uint8)
    segs = build_model()
    for nm, pts in segs:
        if nm.endswith(("rim", "bb_top", "bb_bot", "bb_lft", "bb_rgt")):
            continue  # 地板图只画 z≈0 的线；篮圈/篮板是 3D，跳过
        P = np.asarray(pts, float)
        cs = [w2c(float(p[0]), float(p[1])) for p in P]
        is_center = nm in ("midline", "circle_c")
        col = (255, 255, 255) if is_center else (210, 214, 222)
        th = 3 if is_center else 2
        for k in range(len(cs) - 1):
            cv2.line(cv, cs[k], cs[k + 1], col, th)
    return cv


# ---------------- 配准（封装 court_fit） ----------------
def register_frame(img_path, seed=None, verbose=False, top=4, require_ok=True):
    """返回 (p | None, detail)。p = [Cx,Cy,Cz,Tx,Ty,f,roll]。

    require_ok=False 时即使未达 fit 门禁也返回最佳位姿 —— 诊断脚本需要拿到位姿本身
    去做线像素归因/ROI 收紧（分析「为什么不达标」的前提是先有位姿）。

    性能要点（实测踩坑）：grid_search 很快（用预计算 DT），**瓶颈是 refine** ——
    每次 obj() 调用都要做一次全图 distanceTransform + 折线绘制，Powell 7 维×3 轮
    会产生数千次 score 调用。top 从 24 降到 4、并先预筛掉 score=1e6 的死候选，
    可把单帧配准从 ~10–40min 压到 ~1–3min。
    """
    img = cv2.imread(str(img_path))
    if img is None:
        return None, {"err": "no_img"}
    roi, _ = floor_roi(img)
    mask = roi.copy()
    for (x0, y0, x1, y1) in OVERLAY_BOXES:
        mask[y0:y1, x0:x1] = 0
    P, segs = template(1)
    sc = Scorer(img, P, segs, mask, verbose=verbose)
    if seed is not None:
        cands = [(0.0, tuple(float(v) for v in seed))]
    else:
        raw = grid_search(sc, 4)
        if not raw:
            return None, {"err": "no_cands", "n_line": sc.n_line}
        # 预筛：用真正的 score() 排掉早返回 1e6 的死候选，避免精修空跑
        live = []
        for _, p in raw:
            cam = make_cam(p)
            s = sc.score(cam)
            if isinstance(s, tuple):          # 防御：早返回
                s = s[0]
            if np.isfinite(s) and s < 1e5:
                live.append((float(s), tuple(p)))
        live.sort(key=lambda r: r[0])
        if not live:
            return None, {"err": "cands_all_dead", "n_line": sc.n_line}
        cands = live[:top]
    finals = []
    for _, p in cands:
        s, p = refine(sc, np.array(p, float))
        finals.append((s, p))
    finals.sort(key=lambda r: r[0])
    s, p = finals[0]
    cam = make_cam(p)
    _, det = sc.score(cam, ret_detail=True)
    n_vis = det.get("n_vis", 0)
    n_trust = det.get("n_trust", 0)
    fit = (det.get("F", 99) or 99) + (det.get("R", 99) or 99)
    ok = (n_vis >= 150 and n_trust >= 120 and fit < 9.0)
    detail = {"score": float(s), "F": det.get("F"), "R": det.get("R"),
              "n_vis": n_vis, "n_trust": n_trust, "fit": round(fit, 2), "ok": ok}
    return (p if (ok or not require_ok) else None), detail


def load_cam(p):
    return make_cam(p)


# ---------------- 球轨迹 → 球场坐标 ----------------
def map_tracks(tracks, mode, cams):
    """tracks: list of {frames:[int], centers:[[cx,cy],...]}.
    mode='single' → cams=LookCam（整窗复用）；mode='frames' → cams={fidx:LookCam}。
    返回 mapped: list of {frames:[], pts:[(x,y),...]}（只保留界内点）。"""
    mapped = []
    for t in tracks:
        fr = t.get("frames", [])
        ce = t.get("centers", [])
        out_f, out_p = [], []
        for f, c in zip(fr, ce):
            cam = cams if mode == "single" else cams.get(int(f))
            if cam is None:
                continue
            xy, _ = cam.to_court(np.array([c], float))
            x, y = float(xy[0][0]), float(xy[0][1])
            if abs(x) <= HALF_L + 0.6 and abs(y) <= HALF_W + 0.6:
                out_f.append(int(f)); out_p.append((round(x, 3), round(y, 3)))
        if len(out_p) >= 2:
            mapped.append({"frames": out_f, "pts": out_p})
    return mapped


def render_court_map(clip, mapped, out: Path):
    cv = draw_court_base()
    palette = [(0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 255, 0),
               (255, 128, 0), (0, 200, 255), (200, 0, 255), (0, 255, 180)]
    for i, t in enumerate(mapped):
        col = palette[i % len(palette)]
        cs = [w2c(x, y) for x, y in t["pts"]]
        for k in range(len(cs) - 1):
            cv2.line(cv, cs[k], cs[k + 1], col, 3)
        for p in cs:
            cv2.circle(cv, p, 5, col, -1)
    cv2.imwrite(str(out), cv)
    return len(mapped)


# ---------------- 分数 / 轨迹装载（与 run_ball_events 同口径） ----------------
def load_scores(clip):
    if clip.startswith("baseline_"):
        w = clip[len("baseline_"):]
        d = json.loads((AW / "ball_cand_scores_v2.json").read_text())
        return d[w]
    d = json.loads((AW / "validate" / f"{clip}_scores.json").read_text())
    return d[clip]


def frame_img(clip, fidx):
    if clip.startswith("baseline_"):
        w = clip[len("baseline_"):]
        return AW / w / f"f{fidx:05d}.jpg"
    return AW / clip / f"f{fidx:05d}.jpg"


def operating_th(clip):
    p = AW / "validate" / "gate_tracked_recalib.json"
    if p.exists():
        d = json.loads(p.read_text())
        if clip in d and d[clip].get("operating_th") is not None:
            return d[clip]["operating_th"]
    return 0.3


def compute_tracks(clip, tb):
    import track_ball as _tb
    frames = load_scores(clip)
    th = operating_th(clip)
    tracks = _tb.track_clip(frames, th, birth=th, gap=8)
    tracks = [t for t in tracks if len(t["frames"]) >= 3]
    return tracks


def register_clip(clip, tracks):
    """返回 (mode, cams, detail_json)。"""
    if clip.startswith("baseline_"):
        w = clip[len("baseline_"):]
        rep = AW / w / "f00100.jpg"
        p, det = register_frame(rep, seed=None, verbose=False)
        if p is None:
            return None, None, {"mode": "single", "ok": False, "detail": det}
        cam = make_cam(p)
        return "single", cam, {"mode": "single", "ok": True, "rep": str(rep),
                               "p": [float(v) for v in p], "fit": det.get("fit"),
                               "n_vis": det.get("n_vis")}
    # sas_*：只配准球轨迹涉及的唯一帧
    fidxs = sorted({int(f) for t in tracks for f in t["frames"]})
    cams = {}
    details = {}
    seed = None
    for fi in fidxs:
        img = frame_img(clip, fi)
        p, det = register_frame(img, seed=seed, verbose=False)
        details[fi] = det
        if p is not None:
            cams[fi] = make_cam(p)
            seed = p  # warm-start 下一帧
    ok_n = sum(1 for fi in cams)
    return "frames", cams, {"mode": "frames", "ok": ok_n > 0,
                            "n_frames": len(fidxs), "n_registered": ok_n,
                            "details": details}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all-clips", action="store_true")
    a = ap.parse_args()
    import track_ball as tb

    if a.all_clips:
        clips = ["sas_hou", "sas_nop", "sas_det",
                 "baseline_w1", "baseline_w2", "baseline_w3", "baseline_w4"]
    elif a.clip:
        clips = [a.clip]
    else:
        ap.error("需要 --clip 或 --all-clips")

    for clip in clips:
        tracks = compute_tracks(clip, tb)
        mode, cams, reg = register_clip(clip, tracks)
        print(f"\n=== {clip}  轨迹={len(tracks)}  配准={reg.get('mode')} "
              f"ok={reg.get('ok')}  {('fit='+str(reg.get('fit'))) if 'fit' in reg else ('n_reg='+str(reg.get('n_registered'))+'/'+str(reg.get('n_frames',0)))}")
        if mode is None:
            print("  配准失败，跳过：", reg.get("detail"))
            continue
        mapped = map_tracks(tracks, mode, cams)
        # 丢弃未映射成功的轨迹（<2 点）
        dropped = len(tracks) - len(mapped)
        out = AW / "validate" / f"{clip}_court_truth.jpg"
        n = render_court_map(clip, mapped, out)
        (AW / "validate" / f"{clip}_court_cams.json").write_text(
            json.dumps(reg, ensure_ascii=False, indent=1))
        print(f"  → {clip}_court_truth.jpg（绘制 {n} 条轨迹，丢弃 {dropped} 条未映射）")


if __name__ == "__main__":
    main()
