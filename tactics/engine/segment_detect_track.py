#!/usr/bin/env python3
"""第 2+3 层：检测 + 追踪 + **球的单体锁定**（球为主线）。

设计（2026-09-23 用户定调后重构）：
    战术回合的语义主线是「球的转移」——球在谁手上 → 传给谁 → 相关球员怎么动
    → 其他人怎么动 → 出手即回合结束。
    所以**球必须被稳定锁住**，它是整个系统的锚点，人和关系都围着它算。

三层做三件事：

  1. 检测（YOLO，person + sports ball）—— **单次检测，缓存复用**
     - 全局极低 conf（0.02）先捞够候选；person 与 ball **分别**用不同阈值后过滤。
       球在 1080p 只有 ~17px，conf 天然低，用 0.25 会几乎全漏。

  2. 人的追踪（SORT-lite + scipy 匈牙利）
     - 代价用**脚点（框底中心）**而非 IoU —— 人的框在遮挡/缩放时中心漂移大，
       脚点才是稳定量；再加尺寸对数比惩罚（防大小突变串号）
     - 速度外推预测 + 门控 + 允许漏检 coasting
     - 画面里 30–57 个 person（含观众/替补/裁判），靠下游「运动持久性」剔掉
       （观众不动、球员满场跑，这是相机无关判据）

  3. 球的单体锁定（本层核心）
     - 球是**唯一物体**，但每帧 0–4 个候选（误检多）。
     - 用「匀速外推 + 门控 + 最低代价」逐帧选**唯一**球位，而不是每帧独立取 top-1。
     - 球漏检时进入 coasting（外推），连续丢失超限则清空重捕获。

输出 `tracks.json`：
  frames[]    每帧 {idx,t,players[],ball{},ball_handler}
  tracks{}    每条轨迹统计
  ball_track  球的完整轨迹点列
  meta        耗时/参数

用法：
  segment_detect_track.py <frames.json> <outdir> [--imgsz 1280] [--conf-ball 0.08]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
import time

from common.nba_paths import workspace_file

os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")

import numpy as np  # noqa: E402
from scipy.optimize import linear_sum_assignment  # noqa: E402
from ultralytics import YOLO  # noqa: E402

DEFAULT_W = str(workspace_file("action_work/weights/yolo11n.pt"))
PERSON, BALL = 0, 32

W_POS, W_SIZE, W_IOU = 1.0, 0.5, 0.8
GATE_POS = 0.16          # 脚点位移 / 画面高
GATE_SIZE = 0.90         # |log(h_pred/h_det)|
LOST_RESET = 3           # 球连续丢失多少帧后清空重捕获


def iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def foot(b): return ((b[0] + b[2]) / 2.0, b[3])
def ctr(b):  return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
def bh(b):   return b[3] - b[1]


def predict_box(tr: dict) -> list[float]:
    k = tr["missed"] + 1
    vx, vy = tr["vel"]
    b = tr["box"]
    return [b[0] + vx * k, b[1] + vy * k, b[2] + vx * k, b[3] + vy * k]


# ------------------------------------------------------------ 1) 检测（单次）

def detect_all(model, frames, imgsz, conf_person, conf_ball) -> list[dict]:
    """逐帧检测一次，person / ball 各自按阈值过滤后缓存。"""
    out = []
    for fr in frames:
        r = model.predict(fr["path"], imgsz=imgsz, conf=0.02,
                          verbose=False, device="cpu")[0]
        ps, bs = [], []
        for b in r.boxes:
            cls = int(b.cls[0])
            cf = float(b.conf[0])
            box = [float(v) for v in b.xyxy[0].tolist()]
            if cls == PERSON and cf >= conf_person:
                ps.append({"box": box, "conf": cf})
            elif cls == BALL and cf >= conf_ball:
                bs.append({"box": box, "conf": cf})
        out.append({"person": ps, "ball": bs})
    return out


# ------------------------------------------------------------ 2) 人的追踪

def track_people(dets, frames, H, max_missed):
    tracks: dict[int, dict] = {}
    nxt = 1
    out = []

    for fi, fr in enumerate(frames):
        pdets = dets[fi]["person"]
        live = {t: v for t, v in tracks.items() if v["missed"] <= max_missed}
        tids = list(live)

        matched = []
        if tids and pdets:
            C = np.full((len(tids), len(pdets)), 1e6)
            for i, tid in enumerate(tids):
                pb = predict_box(live[tid])
                pfx, pfy = foot(pb)
                ph = max(bh(pb), 1.0)
                for j, d in enumerate(pdets):
                    dfx, dfy = foot(d["box"])
                    dp = math.hypot(dfx - pfx, dfy - pfy) / H
                    ds = abs(math.log(ph / max(bh(d["box"]), 1.0)))
                    if dp > GATE_POS or ds > GATE_SIZE:
                        continue
                    C[i, j] = W_POS * dp + W_SIZE * ds + W_IOU * (1.0 - iou(pb, d["box"]))
            ri, ci = linear_sum_assignment(C)
            matched = [(tids[i], ci[k]) for k, i in enumerate(ri) if C[i, ci[k]] < 1e5]

        used_d, used_t = set(), set()
        for tid, di in matched:
            used_t.add(tid)
            used_d.add(di)
            tr = tracks[tid]
            nb = pdets[di]["box"]
            ofx, ofy = foot(tr["box"])
            nfx, nfy = foot(nb)
            tr["vel"] = (nfx - ofx, nfy - ofy)
            tr["box"] = nb
            tr["conf"] = pdets[di]["conf"]
            tr["missed"] = 0
            tr["boxes"].append(nb)
            tr["frames"].append(fi)
            tr["path"].append((nfx, nfy))

        for tid in tids:
            if tid not in used_t:
                tracks[tid]["missed"] += 1

        for di, d in enumerate(pdets):
            if di in used_d:
                continue
            tracks[nxt] = {"box": d["box"], "vel": (0.0, 0.0), "missed": 0,
                           "conf": d["conf"], "boxes": [d["box"]],
                           "frames": [fi], "path": [foot(d["box"])]}
            nxt += 1

        plist = [{"id": t, "box": [round(v, 1) for v in v["box"]],
                  "conf": round(v["conf"], 4), "h": round(bh(v["box"]), 1)}
                 for t, v in tracks.items()
                 if v["missed"] == 0 and v["frames"] and v["frames"][-1] == fi]
        out.append({"idx": fi, "t": fr["t"], "n_person_det": len(pdets),
                    "players": plist})
    return out, tracks


# ------------------------------------------------------------ 3) 球的单体锁定

def track_ball(dets, frames, img_h=1080):
    """球的单体锁定（高帧率专线）。

    物理约束（本层的核心动机）：**2fps 追不住球**。
      帧间隔 0.5s 时，一次传球球可位移 300–600px（≈0.5–1 m），
      远大于球框本身（~17px），任何连续性假设都会断。
      所以球必须走**高帧率专线**（≥10fps，位移降到 ~50px/帧）。

    门控尺度不用球框高度（太小、不稳），改用**画面尺度的固定比例**：
      - 追踪态：gate = 0.09 * 画面高（1080p ≈ 97px）
      - 重捕获态（连续丢失后）：gate 放大到 0.30 * 画面高，并要求取门控内最高 conf
    另加尺寸合理性判定（球框高 < 6% 画面高），挡掉把人/鞋检成球的候选。
    """
    pts, lost = [], 0
    box, vel = None, (0.0, 0.0)
    n_det = n_pred = n_reacq = 0
    gate_track = 0.09 * img_h
    gate_reacq = 0.30 * img_h
    max_h = 0.06 * img_h

    for fi, fr in enumerate(frames):
        raw = [c for c in dets[fi]["ball"] if bh(c["box"]) <= max_h]
        chosen = None

        if box is not None:
            pb = [box[0] + vel[0], box[1] + vel[1], box[2] + vel[0], box[3] + vel[1]]
            pcx, pcy = ctr(pb)
            gate = gate_track if lost == 0 else gate_reacq
            best, bc = None, 1e9
            for c in raw:
                ccx, ccy = ctr(c["box"])
                dp = math.hypot(ccx - pcx, ccy - pcy)
                if dp > gate:
                    continue
                cost = dp / gate - 0.45 * c["conf"]
                if cost < bc:
                    bc, best = cost, c
            chosen = best
            if chosen is not None and lost > 0:
                n_reacq += 1
        elif raw:
            chosen = max(raw, key=lambda c: c["conf"])

        if chosen is not None:
            nb = chosen["box"]
            ocx, ocy = ctr(box) if box else ctr(nb)
            ncx, ncy = ctr(nb)
            vel = (ncx - ocx, ncy - ocy)
            if lost > 0:
                vel = (vel[0] / 1.0, vel[1] / 1.0)
            box, lost = nb, 0
            n_det += 1
            pts.append({"t": fr["t"], "box": [round(v, 1) for v in nb],
                        "center": [round(ncx, 1), round(ncy, 1)],
                        "h": round(bh(nb), 1),
                        "conf": round(chosen["conf"], 4), "pred": False})
        else:
            lost += 1
            if box is not None and lost <= LOST_RESET:
                pb = [box[0] + vel[0] * lost, box[1] + vel[1] * lost,
                      box[2] + vel[0] * lost, box[3] + vel[1] * lost]
                cx, cy = ctr(pb)
                n_pred += 1
                pts.append({"t": fr["t"], "box": [round(v, 1) for v in pb],
                            "center": [round(cx, 1), round(cy, 1)],
                            "h": round(bh(pb), 1),
                            "conf": 0.0, "pred": True})
            else:
                box, vel = None, (0.0, 0.0)
                pts.append({"t": fr["t"], "box": None, "center": None,
                            "h": None, "conf": 0.0, "pred": True})
    return pts, {"n_frames": len(frames), "n_detected": n_det,
                 "n_predicted": n_pred, "n_reacquired": n_reacq,
                 "n_missing": len(frames) - n_det - n_pred,
                 "coverage_pct": round((n_det + n_pred) / max(len(frames), 1) * 100, 1),
                 "gate_track_px": round(gate_track, 1),
                 "gate_reacq_px": round(gate_reacq, 1)}


# ------------------------------------------------------------ 4) 球-人归属

def assign_ball_handler(pframes, ball_pts, reach_k=0.45):
    """把球归属给最近的球员框（允许球在框外一个「手臂伸展」范围内）。

    篮球持球时球常在手部/框边缘之外，所以不能要求「球心在框内」，
    改用脚点距离归一化：d = |ball_center - foot| / box_h，取最小且小于阈值的。
    """
    for f, bp in zip(pframes, ball_pts):
        if not bp["center"] or not f["players"]:
            f["ball_handler"] = None
            f["handler_dist"] = None
            continue
        bx, by = bp["center"]
        best, bd = None, 1e9
        for p in f["players"]:
            x1, y1, x2, y2 = p["box"]
            h = max(p["h"], 1.0)
            fx, fy = (x1 + x2) / 2.0, y2
            d = math.hypot(bx - fx, by - fy) / h
            if d < bd:
                bd, best = d, p["id"]
        f["ball_handler"] = best
        f["handler_dist"] = round(bd, 3)
    return pframes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_json")
    ap.add_argument("outdir")
    ap.add_argument("--weights", default=DEFAULT_W)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--conf-person", type=float, default=0.25)
    ap.add_argument("--conf-ball", type=float, default=0.08)
    ap.add_argument("--max-missed", type=int, default=3)
    ap.add_argument("--ball-only", action="store_true",
                    help="只跑球的单体锁定（高帧率专线用，跳过人的追踪省算力）")
    ap.add_argument("--tag", default="tracks.json", help="输出文件名")
    a = ap.parse_args()

    frames = json.load(open(a.frames_json))
    os.makedirs(a.outdir, exist_ok=True)
    from PIL import Image
    W, H = Image.open(frames[0]["path"]).size

    model = YOLO(a.weights)
    t0 = time.perf_counter()
    dets = detect_all(model, frames, a.imgsz, a.conf_person, a.conf_ball)
    t_det = time.perf_counter() - t0
    ball_pts, ball_meta = track_ball(dets, frames)

    if a.ball_only:
        n_cand = sum(len(d["ball"]) for d in dets)
        with open(os.path.join(a.outdir, a.tag), "w") as f:
            json.dump({"ball_track": ball_pts, "ball_meta": ball_meta,
                       "frames": [{"idx": fr["idx"], "t": fr["t"],
                                   "n_ball_cand": len(d["ball"]),
                                   "cands": [[round(v, 1) for v in c["box"]] +
                                             [round(c["conf"], 3)] for c in d["ball"]]}
                                  for fr, d in zip(frames, dets)],
                       "meta": {"n_frames": len(frames), "img_size": [W, H],
                                "imgsz": a.imgsz, "conf_ball": a.conf_ball,
                                "n_ball_candidates": n_cand,
                                "det_sec": round(t_det, 1),
                                "ms_per_frame": round(t_det * 1000 / len(frames), 1),
                                "fps": round(len(frames) / (frames[-1]["t"] - frames[0]["t"]), 2)
                                       if len(frames) > 1 else None}},
                      f, ensure_ascii=False, indent=1)
        bm = ball_meta
        print(f"[ball-only] {len(frames)} 帧 @ {W}x{H} | "
              f"{round(t_det*1000/len(frames),1)}ms/帧 | "
              f"候选数 {n_cand} ({n_cand/len(frames):.2f}/帧)")
        print(f"[ball]  检出 {bm['n_detected']} / 外推 {bm['n_predicted']} / "
              f"丢失 {bm['n_missing']}  -> 覆盖 {bm['coverage_pct']}%")
        print(f"[out] {os.path.join(a.outdir, a.tag)}")
        return 0

    pframes, tracks = track_people(dets, frames, H, a.max_missed)
    pframes = assign_ball_handler(pframes, ball_pts)
    dt = time.perf_counter() - t0

    for f, bp in zip(pframes, ball_pts):
        f["ball"] = {k: bp[k] for k in ("box", "conf", "pred")}

    stats = {}
    for tid, tr in tracks.items():
        p = tr["path"]
        pl = sum(math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1])
                 for i in range(1, len(p)))
        net = math.hypot(p[-1][0] - p[0][0], p[-1][1] - p[0][1]) if len(p) > 1 else 0.0
        hs = [bh(b) for b in tr["boxes"]]
        stats[tid] = {"id": tid, "n_frames": len(tr["frames"]),
                      "first_frame": tr["frames"][0], "last_frame": tr["frames"][-1],
                      "path_len": round(pl, 1), "net_disp": round(net, 1),
                      "mean_h": round(sum(hs) / len(hs), 1),
                      "min_h": round(min(hs), 1), "max_h": round(max(hs), 1),
                      "start_foot": [round(v, 1) for v in p[0]],
                      "end_foot": [round(v, 1) for v in p[-1]]}

    meta = {"n_frames": len(frames), "n_tracks": len(tracks),
            "img_size": [W, H], "imgsz": a.imgsz,
            "conf_person": a.conf_person, "conf_ball": a.conf_ball,
            "det_sec": round(t_det, 1), "elapsed_sec": round(dt, 1),
            "ms_per_frame": round(dt * 1000 / max(len(frames), 1), 1),
            "ball": ball_meta}

    with open(os.path.join(a.outdir, "tracks.json"), "w") as f:
        json.dump({"frames": pframes, "tracks": stats,
                   "ball_track": ball_pts, "meta": meta},
                  f, ensure_ascii=False, indent=1)

    bm = ball_meta
    print(f"[track] {len(frames)} 帧 @ {W}x{H} | 检测 {meta['det_sec']}s | "
          f"总 {dt:.1f}s ({meta['ms_per_frame']}ms/帧)")
    print(f"[ball]  检出 {bm['n_detected']} / 外推 {bm['n_predicted']} / "
          f"丢失 {bm['n_missing']}  -> 覆盖 {bm['coverage_pct']}%")
    nh = sum(1 for f in pframes if f.get("ball_handler"))
    print(f"[handler] {nh}/{len(pframes)} 帧成功归属持球人 "
          f"({nh/len(pframes)*100:.0f}%)")
    print(f"[people] {len(tracks)} 条轨迹")
    print(f"\n{'id':>4} {'n帧':>5} {'路径长':>8} {'净位移':>8} {'均高':>6}")
    for s in sorted(stats.values(), key=lambda z: -z["path_len"])[:26]:
        print(f"{s['id']:>4} {s['n_frames']:>5} {s['path_len']:>8.0f} "
              f"{s['net_disp']:>8.0f} {s['mean_h']:>6.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
