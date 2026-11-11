#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测 poss_full 各叙事段的运动指标（与 pick_smooth_offense_ext.py 同口径）。
目的：为 narrative_role() 的阈值提供**真实标定值**，而不是猜。
老程指认：poss_full 前5秒 = 抢下篮板快速到前场 = 由守到攻转换。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import json
import math
import os
import statistics
import sys
from collections import defaultdict

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

os.environ["PYTHONPATH"] = ""
os.environ["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

CLIP = str(tactics_data_file("clips/sas_scrimmage_pick/poss_full_1958.2-1972.4.mp4"))
OUT = str(tactics_data_file("clips/sas_scrimmage_pick/verify_trans/poss_full_tracks.json"))
WEIGHT = str(tactics_data_file("yolov8n.pt"))

# ---- 与 pick_smooth_offense_ext.score_window 完全同口径 ----
def score_window(players, ball, i0, i1, mover_net=25.0, mv_min_frames=5, mv_disp=1.5,
                 hs=None, pfn=None):
    n = i1 - i0
    med_people = min_people = None
    if pfn:
        seg = pfn[i0:i1]
        if seg:
            med_people = round(statistics.median(seg), 1)
            min_people = min(seg)
    scale_h = None
    if hs:
        vals = [h for k in range(i0, i1) for h in hs.get(k, [])]
        if vals:
            scale_h = round(statistics.median(vals), 1)
    cand = []
    for tid, pos in players.items():
        idx = sorted(k for k in pos if i0 <= k < i1)
        if len(idx) < 4:
            continue
        pts = [pos[k] for k in idx]
        disp = [(pts[j+1][0]-pts[j][0], pts[j+1][1]-pts[j][1]) for j in range(len(pts)-1)]
        path = sum(math.hypot(*d) for d in disp)
        net = math.hypot(pts[-1][0]-pts[0][0], pts[-1][1]-pts[0][1])
        moving = [d for d in disp if math.hypot(*d) > mv_disp]
        cand.append({"net": net, "path": path, "spans": len(idx)/n,
                     "straight": min(1.0, net/path) if path > 1e-6 else 0.0,
                     "disp": disp, "n_moving": len(moving)})
    movers = [c for c in cand if c["net"] > mover_net and c["n_moving"] >= mv_min_frames]
    if not movers:
        return None
    speeds, straight, spans = [], [], []
    unit_vecs = defaultdict(list)
    for c in movers:
        spans.append(c["spans"]); straight.append(c["straight"])
        for j, (dx, dy) in enumerate(c["disp"]):
            d = math.hypot(dx, dy)
            if d > mv_disp:
                speeds.append(d); unit_vecs[j].append((dx/d, dy/d))
    if not speeds:
        return None
    co = []
    for _, vs in unit_vecs.items():
        sx = sum(v[0] for v in vs); sy = sum(v[1] for v in vs)
        co.append(math.hypot(sx, sy)/len(vs))
    bs = [b for b in ball[i0:i1] if b]
    real = [b for b in bs if not b.get("pred")]
    bpts = [(b["cx"], b["cy"]) for b in bs]
    bjump = sum(1 for j in range(len(bpts)-1)
                if math.hypot(bpts[j+1][0]-bpts[j][0], bpts[j+1][1]-bpts[j][1]) > 60)
    return {"straightness": round(statistics.median(straight), 3),
            "coordination": round(statistics.median(co), 3),
            "stability": round(statistics.median(spans), 3),
            "median_speed_px": round(statistics.median(speeds), 2),
            "camera_scale_h": scale_h,
            "median_people_per_frame": med_people,
            "min_people_per_frame": min_people,
            "n_movers": len(movers), "n_players_seen": len(cand),
            "ball_real_rate": round(len(real)/n, 3), "ball_teleports": bjump,
            "ball_coverage": round(len(bs)/n, 3)}


def track(clip, weight, out):
    from ultralytics import YOLO
    m = YOLO(weight)
    cap = cv2.VideoCapture(clip)
    fps = cap.get(cv2.CAP_PROP_FPS)
    res = m.track(clip, stream=True, persist=False,
                  classes=[0], conf=0.35, tracker="bytetrack.yaml", verbose=False)
    frames, players, ball, hs, pfn = [], defaultdict(lambda: {}), [], defaultdict(list), []
    for i, r in enumerate(res):
        fr = {"players": []}
        bx = r.boxes.xyxy.tolist() if r.boxes is not None else []
        bconf = r.boxes.conf.tolist() if r.boxes is not None else []
        bid = r.boxes.id.tolist() if (r.boxes is not None and r.boxes.id is not None) else [None]*len(bx)
        n_person = 0
        for j in range(len(bx)):
            x0, y0, x1, y1 = bx[j]
            h = y1 - y0
            tid = int(bid[j]) if bid[j] is not None else -1
            players[tid][i] = ((x0+x1)/2, (y0+y1)/2)
            hs[i].append(round(h, 1))
            fr["players"].append({"id": tid, "box": [x0, y0, x1, y1], "h": round(h, 1)})
            n_person += 1
        pfn.append(n_person)
        ball.append(None)
        frames.append(fr)
    cap.release()
    json.dump({"fps": fps, "n_frames": len(frames), "frames": frames},
              open(out, "w"), ensure_ascii=False)
    return dict(players), ball, dict(hs), pfn, fps, len(frames)


if __name__ == "__main__":
    if not os.path.exists(OUT):
        players, ball, hs, pfn, fps, nf = track(CLIP, WEIGHT, OUT)
    else:
        d = json.load(open(OUT))
        players, ball, hs, pfn = defaultdict(lambda: {}), [], defaultdict(list), []
        for i, f in enumerate(d["frames"]):
            for p in f.get("players", []):
                x0, y0, x1, y1 = p["box"]
                players[p["id"]][i] = ((x0+x1)/2, (y0+y1)/2)
                hs[i].append(p.get("h", 0))
            pfn.append(len(f.get("players", [])))
            ball.append(None)
        fps, nf = d["fps"], d["n_frames"]
    print(f"clip={os.path.basename(CLIP)} fps={fps} frames={nf}")
    print(f"track IDs={len(players)}  框高中位={statistics.median([h for v in hs.values() for h in v]):.1f}px")
    print(f"每帧人数: 中位={statistics.median(pfn):.1f} 最小={min(pfn)} 最大={max(pfn)}")

    # 老程指认的叙事分段（片内秒）
    SEGS = [("前5秒_抢篮板转换", 0.0, 5.0, "transition(老程指认)"),
            ("5-10秒_转换后组织", 5.0, 10.0, "origin?"),
            ("10秒后_投篮", 10.0, nf/fps, "result?")]
    out = {"fps": fps, "n_frames": nf, "segments": []}
    print(f"\n{'段':<22}{'帧区间':<14}{'n_mv':<6}{'coord':<7}{'spd':<7}"
          f"{'straight':<9}{'stab':<7}{'scale_h':<9}{'人/帧':<8}判据角色")
    for name, t0, t1, expect in SEGS:
        i0, i1 = int(t0*fps), min(int(t1*fps), nf)
        if i1 - i0 < 8:
            print(f"{name:<22} 帧数不足({i1-i0}) 跳过"); continue
        m = score_window(players, ball, i0, i1, hs=hs, pfn=pfn)
        if m is None:
            print(f"{name:<22}{i0}-{i1:<9} 无 mover"); continue
        nmv, c, s = m["n_movers"], m["coordination"], m["median_speed_px"]
        # 现有 narrative_role 门（复制自 pick_smooth_offense_ext）
        if nmv >= 3 and c >= 0.90 and s >= 6.0:  cur = "transition"
        elif nmv >= 3 and c >= 0.85 and s < 6.0: cur = "origin"
        elif s >= 8.0: cur = "result"
        else: cur = "unknown"
        print(f"{name:<22}{i0}-{i1:<9}{nmv:<6}{c:<7}{s:<7}"
              f"{m['straightness']:<9}{m['stability']:<7}{str(m['camera_scale_h']):<9}"
              f"{str(m['median_people_per_frame']):<8}{cur}  (真值={expect})")
        out["segments"].append({"name": name, "i0": i0, "i1": i1, "expect": expect,
                                "metrics": m, "current_gate": cur})
    json.dump(out, open(OUT.replace("_tracks.json", "_metrics.json"), "w"),
              ensure_ascii=False, indent=1)
    print("\nwrote", OUT.replace("_tracks.json", "_metrics.json"))
