#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ball_possession.py — 球检测 + 占有权证据层（里程碑 05 · Phase 1）

定位
----
替换里程碑 12 已证伪的「颜色窗口球检测器」（AUC≈0.522≈随机）。
路线取自 UCD-MMB-Analytics-25-26/basketball_analysis（MIT）：
    player/ball 检测 + 跟踪 + 离球心最近球员 = 占有权。

网络约束现实（沙箱）
------------------
仅 PyPI + Ultralytics 官方权重(GitHub releases) 稳定可达；
UCD-MBB 的篮球域微调 ball_detector_model.pt(Google Drive) 与
第三方仓库内篮球 YOLO(LFS CDN) 均不可达。故本实现落地：
    - 球员：YOLOv8 COCO `person`(class 0)，ByteTrack/BotSort 跟踪（100% 召回）
    - 球：  YOLOv8 COCO `sports ball`(class 32) 低阈值 + **时序插值桥接**
COCO sports-ball 对篮球置信偏低(max≈0.45, 召回~17%稳定)，单帧跟踪缝不
成轨迹；故逐帧取最高置信球框后做**线性插值补洞(≤max_gap帧)**，产出连续
球轨迹，再算占有权。这正是 UCD-MBB/zerodarkthirty 内部做法，无需新权重。
拿到篮球域 .pt 后直接 --ball-model 换上、关掉插值(--no-smooth)即可。

占有权定义（稳健版）
------------------
逐帧球心(检测或插值)：
  1) 球心落在某球员框内 → 该球员占有权（多框包含取中心最近）；
  2) 否则最近球员框中心距 <= poss_radius*帧对角线 → 占有权；
  3) 否则 poss_id=None（球自由/出界/死球）。

输出
----
<out>/ball_tracks.json        逐帧 {frame,file,ball:{bbox,conf,interp}|null,
                                    players:[...], poss_track_id}
<out>/possession_segments.json  RLE 占有权连续段 [{track_id,start,end,n,interp_n}]
<out>/summary.json            帧数/检测率/插值后覆盖率/段数/最长段 等

用法
----
python ball_possession.py <frames_dir> --out <out_dir> \
    [--ball-model yolov8n.pt --ball-conf 0.05 --max-gap 15] \
    [--player-conf 0.3 --poss-radius 0.04 --device mps] [--no-smooth]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

PERSON = 0
BALL = 32


def load_cuts(cuts_path):
    if not cuts_path or not Path(cuts_path).exists():
        return set()
    try:
        data = json.loads(Path(cuts_path).read_text())
    except Exception:
        return set()
    if isinstance(data, list):
        return set(int(x) for x in data)
    for k in ("cuts", "frames", "indices"):
        if k in data and isinstance(data[k], list):
            return set(int(x) for x in data[k])
    return set()


def interpolate_gaps(centers, sizes, max_gap):
    """线性插值补洞；洞长>max_gap 或边界无值则保留 None。返回 filled_centers, filled_sizes, interp_flag[]。"""
    n = len(centers)
    filled_c = list(centers)
    filled_s = list(sizes)
    interp = [False] * n
    i = 0
    while i < n:
        if centers[i] is not None:
            i += 1
            continue
        # 找洞起点
        j = i
        while j < n and centers[j] is None:
            j += 1
        gap = j - i
        left = centers[i - 1] if i > 0 else None
        right = centers[j] if j < n else None
        if left is not None and right is not None and gap <= max_gap:
            for k in range(i, j):
                a = (k - (i - 1)) / (gap + 1)
                filled_c[k] = (left[0] + a * (right[0] - left[0]),
                               left[1] + a * (right[1] - left[1]))
                sa = sizes[i - 1]; sb = sizes[j]
                filled_s[k] = (sa[0] + a * (sb[0] - sa[0]),
                               sa[1] + a * (sb[1] - sa[1]))
                interp[k] = True
        i = j
    return filled_c, filled_s, interp


def assign_possession(ball_bbox, pboxes, poss_radius, frame_diag):
    """占有权 = 距球心最近的球员（用**点到球员框矩形的距离**，非到框中心）。
    理由：球员框高达数百像素，运球时球在脚下/身侧，到框心的距离可达 150-250px，
         但到框矩形的距离≈0——用框心距离会把真占有权误判为 None。
    返回 track_id 或 None（球自由/出界/死球）。"""
    if ball_bbox is None or not pboxes:
        return None
    x1, y1, x2, y2 = ball_bbox
    bx = (x1 + x2) / 2.0
    by = (y1 + y2) / 2.0
    best = None
    bd = 1e9
    for p in pboxes:
        px1, py1, px2, py2 = p["bbox"]
        # 点到矩形距离（在框内为 0）
        dx = max(px1 - bx, 0.0, bx - px2)
        dy = max(py1 - by, 0.0, by - py2)
        d = (dx * dx + dy * dy) ** 0.5
        if d < bd:
            bd = d
            best = p
    if best is not None and bd <= poss_radius * frame_diag:
        return best["track_id"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--player-model", default="yolov8n.pt")
    ap.add_argument("--ball-model", default="yolov8n.pt",
                    help="替换点：UCD-MBB ball_detector_model.pt（需可达）")
    ap.add_argument("--ball-json", default=None,
                    help="外置球检测结果 {frame:[{bbox,conf}..]}，提供后跳过 --ball-model")
    ap.add_argument("--cuts", default=None)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--imgsz", type=int, default=1280,
                    help="🔴 1920x1080 素材必须 1280；默认 640 只检出 2~4 人（实测）")
    ap.add_argument("--tracker", default="botsort.yaml",
                    help="跟踪器配置（可传自定义 yaml 以抑制 ID 碎片，如 engine/botsort_stable.yaml）")
    ap.add_argument("--player-conf", type=float, default=0.3)
    ap.add_argument("--ball-conf", type=float, default=0.05)
    ap.add_argument("--max-gap", type=int, default=15,
                    help="球检测间隔≤此帧数时线性插值补洞")
    ap.add_argument("--poss-radius", type=float, default=0.04)
    ap.add_argument("--poss-hysteresis", type=int, default=3,
                    help="占有权迟滞：新球员需连续 N 帧最近才切换（抑制贴身/自由球抖动）")
    ap.add_argument("--no-smooth", action="store_true",
                    help="关闭插值（仅用原生跟踪，用于对比）")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    player_model = YOLO(args.player_model)
    ball_map = None
    if args.ball_json:
        ball_map = json.loads(Path(args.ball_json).read_text())
        ball_model = None
    else:
        ball_model = YOLO(args.ball_model)

    frames = sorted(Path(args.frames_dir).glob("*.jpg"))
    if args.limit > 0:
        frames = frames[: args.limit]
    if not frames:
        print(f"ERROR: 无帧 {args.frames_dir}", file=sys.stderr)
        sys.exit(1)

    cuts = load_cuts(args.cuts)
    if not cuts and (Path(args.frames_dir) / "cuts.json").exists():
        cuts = load_cuts(str(Path(args.frames_dir) / "cuts.json"))

    # 第一遍：逐帧球员跟踪 + 球检测(最高置信框)
    players_per_frame = []
    ball_det = []  # (bbox, conf) or None
    frame_dims = []
    for i, f in enumerate(frames):
        reset = i in cuts
        img = cv2.imread(str(f))
        h, w = (img.shape[:2] if img is not None else (720, 1280))
        frame_dims.append((w, h))

        pr = player_model.track(
            str(f), classes=[PERSON], persist=not reset,
            tracker=args.tracker, conf=args.player_conf,
            imgsz=args.imgsz,
            device=args.device, verbose=False,
        )[0]
        br = (None if ball_model is None else
              ball_model(str(f), classes=[BALL], conf=args.ball_conf,
                         device=args.device, verbose=False)[0])

        pboxes = []
        if pr.boxes.id is not None:
            ids = pr.boxes.id.int().tolist()
            xyxy = pr.boxes.xyxy.tolist()
            confs = pr.boxes.conf.tolist()
            for (x1, y1, x2, y2), pid, c in zip(xyxy, ids, confs):
                pboxes.append({
                    "track_id": int(pid),
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "conf": float(c),
                })
        players_per_frame.append(pboxes)

        best = None
        if ball_map is not None:
            for c in ball_map.get(f.name, []):
                if c.get("conf", 1.0) < args.ball_conf:
                    continue
                if best is None or c["conf"] > best[1]:
                    best = ([float(v) for v in c["bbox"]], float(c["conf"]))
        elif br is not None and len(br.boxes.xyxy) > 0:
            xyxy = br.boxes.xyxy.tolist()
            confs = br.boxes.conf.tolist()
            for (x1, y1, x2, y2), c in zip(xyxy, confs):
                if best is None or c > best[1]:
                    best = ([float(x1), float(y1), float(x2), float(y2)], float(c))
        ball_det.append(best)

    # 第二遍：插值补洞
    centers = [((d[0][0] + d[0][2]) / 2.0, (d[0][1] + d[0][3]) / 2.0) if d else None
               for d in ball_det]
    sizes = [((d[0][2] - d[0][0]), (d[0][3] - d[0][1])) if d else None
             for d in ball_det]
    if args.no_smooth:
        fcenters, fsizes, interp = centers, sizes, [False] * len(centers)
    else:
        fcenters, fsizes, interp = interpolate_gaps(centers, sizes, args.max_gap)

    # 第三遍：占有权（用插值后球心 + 中位球尺寸合成 bbox）
    det_sizes = [s for s in sizes if s is not None]
    med_w = float(np.median([s[0] for s in det_sizes])) if det_sizes else 30.0
    med_h = float(np.median([s[1] for s in det_sizes])) if det_sizes else 30.0

    # 第三遍：逐帧原始占有权
    ball_outs = []
    raw = []
    for i, f in enumerate(frames):
        w, h = frame_dims[i]
        diag = (w * w + h * h) ** 0.5
        pboxes = players_per_frame[i]
        c = fcenters[i]
        ball_out = None
        pid = None
        if c is not None:
            bx, by = c
            bw = fsizes[i][0] if fsizes[i] else med_w
            bh = fsizes[i][1] if fsizes[i] else med_h
            bbox = [bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2]
            pid = assign_possession(bbox, pboxes, args.poss_radius, diag)
            ball_out = {"bbox": [float(v) for v in bbox],
                        "conf": (ball_det[i][1] if ball_det[i] else None),
                        "interp": bool(interp[i])}
        raw.append(pid)
        ball_outs.append(ball_out)

    # 迟滞平滑：新球员需连续 K 帧最近才切换
    smoothed = list(raw)
    if args.poss_hysteresis > 0:
        cur_p = None
        pend = None
        pc = 0
        for i, p in enumerate(raw):
            if p == cur_p:
                pend = None
                pc = 0
            else:
                if p == pend:
                    pc += 1
                else:
                    pend = p
                    pc = 1
                if pc >= args.poss_hysteresis:
                    cur_p = p
                    pend = None
                    pc = 0
            smoothed[i] = cur_p

    ball_tracks = []
    segments = []
    cur = None
    n_det = sum(1 for d in ball_det if d)
    n_cov = 0
    n_interp_cov = 0

    for i, f in enumerate(frames):
        poss_id = smoothed[i]
        if poss_id is not None:
            n_cov += 1
            if interp[i]:
                n_interp_cov += 1

        if poss_id is None:
            if cur is not None:
                segments.append(_seg(cur, i))
                cur = None
        else:
            if cur is None or cur[0] != poss_id:
                if cur is not None:
                    segments.append(_seg(cur, i))
                cur = (poss_id, i, 0)
            cur = (poss_id, cur[1], cur[2] + (1 if interp[i] else 0))

        ball_tracks.append({
            "frame": i, "file": f.name, "ball": ball_outs[i],
            "players": players_per_frame[i], "poss_track_id": poss_id,
        })

    if cur is not None:
        segments.append(_seg(cur, len(frames)))

    n_frames = len(frames)
    seg_lens = [s["n"] for s in segments]
    summary = {
        "frames_dir": str(args.frames_dir),
        "n_frames": n_frames,
        "ball_detect_rate": round(n_det / n_frames, 4) if n_frames else 0,
        "possession_coverage_after_interp": round(n_cov / n_frames, 4) if n_frames else 0,
        "interp_share_of_possession": round(n_interp_cov / n_cov, 4) if n_cov else 0,
        "n_segments": len(segments),
        "max_segment_len": max(seg_lens) if seg_lens else 0,
        "median_segment_len": float(np.median(seg_lens)) if seg_lens else 0,
        "player_model": args.player_model, "ball_model": args.ball_model,
        "device": args.device, "player_conf": args.player_conf,
        "ball_conf": args.ball_conf, "max_gap": args.max_gap,
        "poss_radius": args.poss_radius, "smooth": (not args.no_smooth),
    }

    (out / "ball_tracks.json").write_text(json.dumps(ball_tracks, indent=1))
    (out / "possession_segments.json").write_text(json.dumps(segments, indent=1))
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def _seg(cur, end):
    return {"track_id": cur[0], "start": cur[1], "end": end - 1,
            "n": end - cur[1], "interp_n": cur[2]}


if __name__ == "__main__":
    main()
