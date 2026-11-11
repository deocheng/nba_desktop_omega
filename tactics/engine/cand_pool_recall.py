#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cand_pool_recall.py —— 候选池召回上界实验（有真值，只读推理，不改现有产物）。

为什么做：补标只解决「头打分」问题，不解决「检测器没提出候选」问题。
本脚本用 sas_det 的 42 个含球帧人工真值，量化：把 top-k 从 4 放开到 6/8/12/全部，
候选池能多覆盖多少真球 —— 即「覆盖率天花板」到底卡在头还是卡在检测器。

判据（小目标，与 A4.19 一致，IoU 对 25px 框不可用）：
  hit_strict : 真球中心落在候选框内 且 中心距 ≤ 12px（约半个球）
  hit_inbox  : 真球中心落在候选框内（宽松，作为上界）

产出：reports/milestone_05/measure/cand_pool_recall_sas_det.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
# 与 validate_clips.py 完全同模型（复用同一口径，禁另找模型）
RF = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
      + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
      + "46c33088c790670a7e81e21e753fa368b2d77a70")
BALL = 0

KS = [1, 2, 4, 6, 8, 12, 16, 24, 999]   # 999 = 全部


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def tiled_all(model, proc, dev, img, tw, th, ov, thresh, nms):
    """与 validate_clips.tiled 同构，但**不截断** top-k，返回 NMS 后全部候选（按 conf 降序）。"""
    H, W = img.shape[:2]
    rec, ntile = [], 0
    for y in range(0, H, th - ov):
        for x in range(0, W, tw - ov):
            x2, y2 = min(W, x + tw), min(H, y + th)
            if x2 - x <= ov or y2 - y <= ov:
                continue
            ntile += 1
            rgb = cv2.cvtColor(img[y:y2, x:x2], cv2.COLOR_BGR2RGB)
            inp = proc(images=rgb, return_tensors="pt").to(dev)
            with torch.no_grad():
                out = model(**inp)
            res = proc.post_process_object_detection(
                out, threshold=thresh, target_sizes=torch.tensor([[y2-y, x2-x]]).to(dev))[0]
            for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(), res["labels"].tolist()):
                if int(l) == BALL:
                    rec.append({"bbox": [b[0]+x, b[1]+y, b[2]+x, b[3]+y], "conf": float(s)})
    rec.sort(key=lambda r: -r["conf"])
    keep = []
    for r in rec:
        if all(iou(r["bbox"], k["bbox"]) < nms for k in keep):
            keep.append(r)
    return keep, ntile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_det")
    ap.add_argument("--bank", default="action_work/validate/sas_det_label_bank_human.json")
    ap.add_argument("--frames-dir", default="action_work/sas_det")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--tw", type=int, default=640)
    ap.add_argument("--th", type=int, default=384)
    ap.add_argument("--ov", type=int, default=96)
    ap.add_argument("--thresh", type=float, default=0.05)   # 与 validate_clips.py tiled() 同口径
    ap.add_argument("--nms", type=float, default=0.4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--probe-frames", default=None,
                    help="帧里有球但真值球心未知的漏检帧（bank meta.reviewer_notes）；"
                         "只报候选统计+落盘候选，不做命中判定（无真值不许编）")
    ap.add_argument("--probe-out", default="action_work/validate/cand_probe_frames.json")
    a = ap.parse_args()

    bank = json.loads((ROOT / a.bank).read_text())
    tp = [r for r in bank["labels"] if r["label"] == "TP"]
    truth = {}
    for r in tp:
        b = r["bbox"]
        truth.setdefault(r["frame"], []).append(((b[0]+b[2])/2.0, (b[1]+b[3])/2.0))
    frames = sorted(truth.keys())
    if a.limit:
        frames = frames[:a.limit]
    print(f"[truth] 含球帧 {len(frames)} （TP 样本 {len(tp)}）  bank={a.bank}")

    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    model = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()
    fdir = ROOT / a.frames_dir
    print(f"[infer] dev={dev}  tile={a.tw}x{a.th} ov={a.ov} thresh={a.thresh} nms={a.nms}")

    # 逐帧：拿到 NMS 后全部候选 → 一次推理算所有 k 的召回
    per_frame = []
    t0 = time.time()
    for n, fr in enumerate(frames):
        img = cv2.imread(str(fdir / fr))
        if img is None:
            print(f"  [miss] {fr} 无帧文件，跳过")
            continue
        keep, ntile = tiled_all(model, proc, dev, img, a.tw, a.th, a.ov, a.thresh, a.nms)
        row = {"frame": fr, "n_cand": len(keep), "ntile": ntile, "hits": {}}
        for k in KS:
            sub = keep[:k] if k < 900 else keep
            hit_s = hit_i = False
            for (gx, gy) in truth[fr]:
                for c in sub:
                    b = c["bbox"]
                    cx, cy = (b[0]+b[2])/2.0, (b[1]+b[3])/2.0
                    inbox = b[0] <= gx <= b[2] and b[1] <= gy <= b[3]
                    if inbox:
                        hit_i = True
                        if np.hypot(gx-cx, gy-cy) <= 12.0:
                            hit_s = True
            row["hits"][str(k)] = {"strict": hit_s, "inbox": hit_i}
        per_frame.append(row)
        if (n+1) % 10 == 0:
            print(f"  {n+1}/{len(frames)}  {time.time()-t0:.0f}s")
    dt = time.time() - t0

    nf = len(per_frame)
    curve = {}
    for k in KS:
        s = sum(1 for r in per_frame if r["hits"][str(k)]["strict"])
        i = sum(1 for r in per_frame if r["hits"][str(k)]["inbox"])
        avg = np.mean([min(r["n_cand"], k if k < 900 else r["n_cand"]) for r in per_frame])
        curve[str(k)] = {"recall_strict": round(s/nf, 4), "recall_inbox": round(i/nf, 4),
                         "avg_cands": round(float(avg), 2)}
        print(f"  top{('all' if k>=900 else k):>3}  严格 {s}/{nf}={s/nf*100:5.1f}%   "
              f"框内 {i}/{nf}={i/nf*100:5.1f}%   平均候选 {avg:.1f}")

    out = {"meta": {"clip": a.clip, "frames": nf, "tile": [a.tw, a.th, a.ov],
                    "thresh": a.thresh, "nms": a.nms, "seconds": round(dt, 1),
                    "judge": "strict=真球中心在候选框内且中心距<=12px; inbox=中心在框内",
                    "note": "候选池召回上界；补标不能提升此值，只能提升头打分"},
           "curve": curve, "per_frame": per_frame}
    op = ROOT / "reports/milestone_05/measure/cand_pool_recall_sas_det.json"
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[out] {op}   {dt:.0f}s")

    # ── 探针模式：漏检帧（有球、真值球心未知）放开 top-k 后检测器到底提出了什么 ──
    if a.probe_frames:
        pf = [f"f{int(t.strip()):05d}.jpg" for t in a.probe_frames.split(",") if t.strip()]
        print(f"\n[probe] 漏检帧 {len(pf)} 帧（有球但候选云无球；只报候选，不判命中）")
        pres = {}
        for fr in pf:
            img = cv2.imread(str(fdir / fr))
            if img is None:
                print(f"  {fr}: 无帧文件"); continue
            keep, _ = tiled_all(model, proc, dev, img, a.tw, a.th, a.ov, a.thresh, a.nms)
            sz = [max(b[2]-b[0], b[3]-b[1]) for b in (c["bbox"] for c in keep)]
            pres[fr] = keep[:16]
            print(f"  {fr}: NMS后候选 {len(keep)} 个  conf p1={keep[0]['conf']:.3f} "
                  f"p4={keep[3]['conf']:.3f} p_last={keep[-1]['conf']:.3f} | "
                  f"尺寸 min/med/max = {min(sz):.0f}/{np.median(sz):.0f}/{max(sz):.0f}" if sz else f"  {fr}: 0 候选")
        (ROOT / a.probe_out).write_text(json.dumps(
            {"meta": {"clip": a.clip, "thresh": a.thresh, "nms": a.nms,
                      "note": "帧内有球但真值球心未知 → 无命中判定，仅供目视复核/扩容潜力判断"},
             "frames": pres}, ensure_ascii=False, indent=1))
        print(f"[out] {a.probe_out}")


if __name__ == "__main__":
    main()
