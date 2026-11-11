#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 广播像素原生修正验证（老程 2026-10-04 标注驱动）。
读 routing_final.json(A_STEP_FINAL) + 老程逐簇角点标注 → 每簇「朝筐」向量 bw(PAN_DEG 参数)；
对 13 个真实簇(剔除 #3 无场地)跑 axis-aware detect_primitives，扫描 PAN_DEG，
观察 SCREEN.CROSS:DOWN 反转是否被修正（真实篮球 DOWN 应占优），以及 CUT/DRIVE(朝筐) 触发量。
输出：每个 PAN 下 侧翼簇 / 自由簇 的掩护子类计数 + 比例，供老程目视定 PAN。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
import re
import statistics
import sys

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(tactics_data_file("engine")))
from tactic_match import detect_primitives

BASE = str(tactics_data_file("action_work"))
SEG = str(tactics_data_file("action_work/tactic_notes_batch_full/segments"))

# 老程逐簇角点标注 → 可见远角（2026-10-04 全量标注：#6/#13/#19 远左, #9/#12/#16 远右）
VIS = {5:"f_l",8:"f_l",11:"f_l", 6:"f_l",13:"f_l",19:"f_l",
       15:"f_r",18:"f_r",22:"f_r",29:"f_r", 9:"f_r",12:"f_r",16:"f_r"}  # 3 无场地跳过

def bw_of(vis, pan_deg):
    r = math.radians(pan_deg)
    if vis == "f_l":  return (-math.sin(r), -math.cos(r))
    if vis == "f_r":  return ( math.sin(r), -math.cos(r))
    return (0.0, -1.0)   # free / 默认：篮筐在正上

def load_window(seg, start, end):
    d = json.load(open(f"{SEG}/{seg}/tracks.json", encoding="utf-8"))
    frames_all = d["frames"]
    out = []
    for fr in frames_all:
        i = fr["idx"]
        if i < start or i > end:
            continue
        players = {}
        for p in fr.get("players", []):
            b = p.get("box")
            if not b or len(b) < 4:
                continue
            players[p["id"]] = ((b[0]+b[2])/2.0, (b[1]+b[3])/2.0)
        ball = None
        bb = fr.get("ball", {})
        if isinstance(bb, dict) and bb.get("box"):
            ball = ((bb["box"][0]+bb["box"][2])/2.0, (bb["box"][1]+bb["box"][3])/2.0)
        out.append({"t": i, "ball": ball, "players": players})
    return out

def cluster_stats(frames):
    # 实测单帧中位位移 + 中位身高(体长)，供站定门/通行门
    disps = []
    hs = []
    for i in range(1, len(frames)):
        pa, pb = frames[i-1]["players"], frames[i]["players"]
        for tid in set(pa) & set(pb):
            disps.append(math.hypot(pa[tid][0]-pb[tid][0], pa[tid][1]-pb[tid][1]))
    # 体长从原始 tracks 不便拿，这里用 bbox h 近似：退化用固定 80 像素
    return (statistics.median(disps) if disps else 5.0), 80.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pan", type=float, default=60.0, help="锁定用的侧翼簇 pan 角(度)")
    ap.add_argument("--dump", action="store_true", help="把每簇朝筐向量落到 orient_anchors.json")
    a = ap.parse_args()
    rf = json.load(open(f"{BASE}/norm_calib/routing_final.json", encoding="utf-8"))
    ast = rf["buckets"]["A_STEP_FINAL"]["detail"]
    clusters = []
    for txt in ast:
        m = re.match(r"(ep\d+_s\d+)#(\d+)-(\d+)\((\d+)帧\)", txt)
        seg, s, e = m.group(1), int(m.group(2)), int(m.group(3))
        clusters.append((seg, s, e))
    ids = rf["buckets"]["A_STEP_FINAL"]["clusters"]
    assert len(ids) == len(clusters)
    items = [(cid, seg, s, e) for (cid, (seg, s, e)) in zip(ids, clusters) if cid != 3]

    if a.dump:
        anchors = {}
        for cid, seg, s, e in items:
            bw = bw_of(VIS[cid], a.pan)
            anchors[str(cid)] = {"seg": seg, "start": s, "end": e, "visible_far_corner": VIS[cid],
                                 "pan_deg": a.pan, "basket_ward": [round(bw[0],4), round(bw[1],4)],
                                 "note": "广播像素原生;朝筐向量来自老程角点标注+pan角;#3无场地跳过"}
        json.dump({"pan_deg": a.pan, "anchors": anchors},
                  open(f"{BASE}/norm_calib/orient_anchors.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"[dump] orient_anchors.json 写入 {len(anchors)} 簇 (pan={a.pan})")

    pans = [0, 15, 30, 45, 60, 75, 90]
    print(f"{'PAN':>4} | {'全13簇 CROSS:DOWN':>20} | {'f_l(远左)':>14} | {'f_r(远右)':>14} | {'CUT'}")
    print("-"*72)
    for pan in pans:
        b = {k: {"C": 0, "D": 0, "cut": 0} for k in ("f_l", "f_r")}
        for cid, seg, s, e in items:
            vis = VIS[cid]
            bw = bw_of(vis, pan)
            frames = load_window(seg, s, e)
            if len(frames) < 5:
                continue
            disp_med, med_diag = cluster_stats(frames)
            ev = detect_primitives(frames, disp_med=disp_med, med_diag=med_diag, orient=bw)
            for evv in ev:
                if evv["type"] == "SCREEN":
                    if evv["sub"] == "CROSS": b[vis]["C"] += 1
                    elif evv["sub"] == "DOWN": b[vis]["D"] += 1
                elif evv["type"] == "CUT": b[vis]["cut"] += 1
        def ratio(c, d): return f"{d/max(c,1):.2f}x" if c else ("∞" if d else "-")
        tc, td = b["f_l"]["C"]+b["f_r"]["C"], b["f_l"]["D"]+b["f_r"]["D"]
        print(f"{pan:>4} | CROSS {tc:>3}:DOWN {td:>3} ({ratio(tc,td)}) | "
              f"{b['f_l']['C']}:{b['f_l']['D']} | {b['f_r']['C']}:{b['f_r']['D']} | {b['f_l']['cut']+b['f_r']['cut']}")

if __name__ == "__main__":
    main()
