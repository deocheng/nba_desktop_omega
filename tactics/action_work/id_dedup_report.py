# -*- coding: utf-8 -*-
"""
id_dedup_report.py — ID 碎片化量化（Task 5③ 临时方案，纯报告不阻塞）
总原则：所有指标改用「每帧可见人数」近似真实人数；track_id 数因 ID 不稳定被系统性虚高。
本脚本用 bbox IoU>0.3 做逐帧贪婪 NMS 合并，估计「真实同时在场人数」，与 track_id 数对比，
量化碎片化倍数（fragmentation_x = track_id 数 / 去重后每帧中位人数）。
仅读 tracks.json（磁盘），不改任何管线。
用法：python id_dedup_report.py [--segs ep12_s1 ep18_s0 ...]  （默认读 smooth_tracks_game20 的 11 段）
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import statistics
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
BASE = f"{ROOT}/action_work"
NC = f"{BASE}/norm_calib"
SEG = f"{BASE}/tactic_notes_batch_full/segments"
IOU_T = 0.3

ap = argparse.ArgumentParser()
ap.add_argument("--segs", nargs="*", default=None)
a = ap.parse_args()

if a.segs:
    segs = a.segs
else:
    segs = sorted({f.stem.split("_")[1] + "_" + f.stem.split("_")[2]
                   for f in Path(f"{NC}/smooth_tracks_game20").glob("*.json")})
    # 上面解析不稳，改直接读 tracks 文件名的 seg 段
    segs = []
    for f in sorted(Path(f"{NC}/smooth_tracks_game20").glob("*.json")):
        tr = json.load(open(f, encoding="utf-8"))
        if tr["seg"] not in segs:
            segs.append(tr["seg"])

def iou(b1, b2):
    x0 = max(b1[0], b2[0]); y0 = max(b1[1], b2[1])
    x1 = min(b1[2], b2[2]); y1 = min(b1[3], b2[3])
    iw = max(0, x1 - x0); ih = max(0, y1 - y0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    return inter / (a1 + a2 - inter)

def nms_count(boxes):
    boxes = sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    kept = []
    for b in boxes:
        if all(iou(b, k) < IOU_T for k in kept):
            kept.append(b)
    return len(kept)

out = {}
print(f"{'段':<10}{'track_id数':>10}{'去重人数/帧':>12}{'碎片化x':>9}")
for seg in segs:
    tr = json.load(open(f"{SEG}/{seg}/tracks.json", encoding="utf-8"))
    frames = tr["frames"]
    tids = set()
    dedup_per_frame = []
    for f in frames:
        pl = f.get("players", [])
        boxes = [p["box"] for p in pl if p.get("box")]
        for p in pl:
            tids.add(p["id"])
        dedup_per_frame.append(nms_count(boxes))
    med_dedup = round(statistics.median(dedup_per_frame), 1) if dedup_per_frame else 0
    fx = round(len(tids) / med_dedup, 2) if med_dedup else None
    out[seg] = {"n_track_ids": len(tids), "dedup_people_per_frame_median": med_dedup,
                "fragmentation_x": fx}
    print(f"{seg:<10}{len(tids):>10}{med_dedup:>12}{str(fx):>9}")

json.dump({"iou_thresh": IOU_T, "by_seg": out},
          open(f"{NC}/id_dedup_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n[写出] {NC}/id_dedup_report.json  （碎片化x = track_id 数 / IoU去重后每帧中位人数；>1 即虚高）")
