#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_type_filter (v1) — 远景/半场/特写逐帧镜头类型过滤器（老程 2026-09-26 提议落地）。

定位（🔴 红线）：
  本过滤器只服务两件事—— ①训练/标注池策展（第 1 步 50–80 帧分层抽样、第 2 步联合训练
  的负样本配比）；②frame_state 语义富集（shot_type 标签）。
  **禁止**用作检测后处理去"救"覆盖率/门禁数字——那是 A6「后处理过滤全家」封口的死路。

v1.2 规则（目视验收两轮修正——🔴 max_h 信号被前排观众/替补席大框污染：w1 全宽景被误判
  56.6% close，而真特写帧反而检测缺框落 none。框数量 n 才是主判据）：
  每帧统计: n_players, median_h, max_h（只统计 player 类，referee 单列）。
  片级参考: H0 = median(median_h)（有框帧，仅诊断用）。
    close: n ≤ CL_N(=4) 或 median_h ≥ CL_REL(1.5)·H0
           ← v1.4 新增相对高度判据：sas_lal 真值实证特写段 n=7–11（大特写连后排观众都被
             数成"球员"）但 med_rel 2.06–4.37；点选含球帧 med_rel ≤1.11 —— 1.5 在干净间隙中。
    wide : n ≥ W_N(=12) 且 median_h ≤ W_REL(0.85)·H0（双条件：数量多+明显比片均小）
    half : 其余球场视角（转播机位近恒定变焦——sas_det/w1 med_rel p10-p90=0.91-1.14 实证）
  🔴 校准史：v1.2 的 w_n=14 单 n 判据在 RF-DETR 源失效（全帧 384² 漏宽景小目标，
     w1/sas_det n 分布同为 p50≈10——A2 根因在球员检测侧重现），v1.3 改双条件。
  ⚠️ 阈值来源=w1/sas_det 两参照集分布校准+两轮目视验收；apply 后必看 --sheet（视觉先自证）。

用法:
  # ① 校准：看参照集分布
  python engine/shot_type_filter.py calibrate --boxes w1=action_work/w1_players.json \
      sas_det=action_work/sas_det_players.json
  # ② 应用（阈值可用 --cl-max 等覆盖校准默认）
  python engine/shot_type_filter.py apply --boxes action_work/sas_lal_players.json \
      --out action_work/validate/sas_lal_shot_types.json --sheet action_work/probe_new/sas_lal_shot_sheet.jpg \
      --frames-dir action_work/sas_lal
产出:
  shot_types.json: {"meta":{...阈值...}, "frames": {"f00001.jpg": {"type":"wide|half|close|none",
      "n":12, "median_h":51.0, "max_h":88.0, "n_ref":1}}, "counts": {...}}
  --sheet: 每类抽 8 帧拼接触表（视觉验收必看，禁只看 JSON 计数）。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import statistics
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))

# 默认阈值 = 校准产物（w1/sas_det 两参照集 + 两轮目视验收），apply 可覆盖
DEFAULTS = dict(cl_n=4, cl_rel=1.5, w_n=12, w_rel=0.85)


def load_boxes(path: Path, clip: str):
    """统一转成 {fn: [(x1,y1,x2,y2,cls), ...]}。支持两种来源：
    ① detect_players_rfdetr.py 输出 {fn: [{bbox,cls,conf}]}
    ② poss_tile/ball_tracks.json 格式 [{file, players:[{bbox}]}]（校准用，无 cls → player）
    """
    d = json.loads(path.read_text())
    out = {}
    if isinstance(d, list):  # poss_tile 格式
        for row in d:
            fn = row["file"] if isinstance(row.get("file"), str) else f"f{int(row['file']):05d}.jpg"
            out[fn] = [(p["bbox"][0], p["bbox"][1], p["bbox"][2], p["bbox"][3], "player")
                       for p in row.get("players", [])]
    else:  # rfdetr 格式
        for fn, recs in d.items():
            out[fn] = [(r["bbox"][0], r["bbox"][1], r["bbox"][2], r["bbox"][3], r.get("cls", "player"))
                       for r in recs]
    return out


def frame_stats(boxlist):
    hs = [b[3] - b[1] for b in boxlist if b[4] == "player"]
    n_ref = sum(1 for b in boxlist if b[4] == "referee")
    if not hs:
        return dict(n=0, median_h=0.0, max_h=0.0, n_ref=n_ref)
    return dict(n=len(hs), median_h=round(statistics.median(hs), 1),
                max_h=round(max(hs), 1), n_ref=n_ref)


def classify_all(stats_by_fn, th):
    """两遍：先算片级 H0，再分类（v1.3：close=n≤4；wide=n≥W_N 且 med_h≤W_REL·H0）。"""
    meds = [s["median_h"] for s in stats_by_fn.values() if s["n"] > 0]
    H0 = statistics.median(meds) if meds else 0.0
    out = {}
    for fn, st in stats_by_fn.items():
        if st["n"] <= th["cl_n"] or (H0 > 0 and st["median_h"] >= th["cl_rel"] * H0):
            out[fn] = "close"        # 低球员数 或 球员框明显放大（特写/近景）
        elif st["n"] >= th["w_n"] and H0 > 0 and st["median_h"] <= th["w_rel"] * H0:
            out[fn] = "wide"
        else:
            out[fn] = "half"
    return out, round(H0, 1)


def cmd_calibrate(a):
    for spec in a.boxes:
        clip, p = spec.split("=", 1)
        boxes = load_boxes(Path(p), clip)
        rows = [frame_stats(v) for v in boxes.values()]
        if not rows:
            print(f"[{clip}] 空框集"); continue
        med = sorted(r["median_h"] for r in rows if r["n"])
        mx = sorted(r["max_h"] for r in rows if r["n"])
        nn = sorted(r["n"] for r in rows)
        q = lambda arr, p: arr[min(len(arr) - 1, int(len(arr) * p))] if arr else None
        print(f"[{clip}] 帧 {len(rows)} 有框帧 {len(med)}")
        print(f"  n      p10/50/90 = {q(nn,.1)}/{q(nn,.5)}/{q(nn,.9)}")
        print(f"  med_h  p10/50/90 = {q(med,.1)}/{q(med,.5)}/{q(med,.9)}  min/max={med[0] if med else '-'}/{med[-1] if med else '-'}")
        print(f"  max_h  p10/50/90 = {q(mx,.1)}/{q(mx,.5)}/{q(mx,.9)}")
        # 阈值建议位置提示
        if med:
            print(f"  wide 建议 w_med≈p60({q(med,.6)})  close 建议 cl_max≈p97({q(mx,.97)})")


def cmd_apply(a):
    th = dict(DEFAULTS)
    if a.cl_n: th["cl_n"] = a.cl_n
    if a.cl_rel: th["cl_rel"] = a.cl_rel
    if a.w_n: th["w_n"] = a.w_n
    if a.w_rel: th["w_rel"] = a.w_rel
    boxes = load_boxes(Path(a.boxes), "clip")
    stats = {fn: frame_stats(bl) for fn, bl in sorted(boxes.items())}
    types, H0 = classify_all(stats, th)
    frames = {fn: {**stats[fn], "type": types[fn]} for fn in stats}
    counts = {}
    for v in frames.values():
        counts[v["type"]] = counts.get(v["type"], 0) + 1
    out = {"meta": {"source": a.boxes, "H0": H0, **th}, "counts": counts, "frames": frames}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[out] {a.out}  (H0={H0}px)")
    tot = sum(counts.values())
    for k in ("wide", "half", "close", "none"):
        c = counts.get(k, 0)
        print(f"  {k:6s} {c:4d}  ({c/tot*100:.1f}%)")

    if a.sheet and a.frames_dir:
        render_sheet(frames, Path(a.frames_dir), Path(a.sheet))
        print(f"[sheet] {a.sheet}（每类 8 帧，视觉验收必看）")


def render_sheet(frames, fdir: Path, out: Path, per=8):
    by = {}
    for fn, v in frames.items():
        by.setdefault(v["type"], []).append(fn)
    tiles = []
    for typ in ("wide", "half", "close"):
        fns = by.get(typ, [])[:per]
        row = []
        for i in range(per):
            if i < len(fns):
                img = cv2.imread(str(fdir / fns[i]))
                img = cv2.resize(img, (320, 180)) if img is not None else np.full((180, 320, 3), 40, np.uint8)
            else:
                img = np.full((180, 320, 3), 40, np.uint8)
            cv2.putText(img, f"{typ} {fns[i][1:6] if i < len(fns) else '-'}", (4, 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            row.append(img)
        band = np.hstack(row)
        cv2.putText(band, typ.upper(), (4, 172), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 0, 255), 2, cv2.LINE_AA)
        tiles.append(band)
    cv2.imwrite(str(out), np.vstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 88])


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--boxes", nargs="+", help="clip=path 逐个参照集")
    s = sub.add_parser("apply")
    s.add_argument("--boxes", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--sheet", default=None)
    s.add_argument("--frames-dir", default=None)
    s.add_argument("--cl-n", type=int, default=None)
    s.add_argument("--cl-rel", type=float, default=None)
    s.add_argument("--w-n", type=int, default=None)
    s.add_argument("--w-rel", type=float, default=None)
    a = ap.parse_args()
    if a.cmd == "calibrate":
        cmd_calibrate(a)
    else:
        cmd_apply(a)


if __name__ == "__main__":
    main()
