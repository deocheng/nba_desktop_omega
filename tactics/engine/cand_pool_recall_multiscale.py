#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cand_pool_recall_multiscale.py —— 多尺度/更密分块诊断（A4.41，只读，不改现有产物）。

目的：量化「换分块策略（更小 tile / 更密 overlap / 多尺度）」能把检测器候选召回从当前天花板抬多少。
复用 cand_pool_recall.py 的 tiled_all + 判定口径（分母 = 独立真值帧，非候选派生，A4.34 教训）。

GT 分母：bank 中 label=="TP" 的帧（球确实在场、有中心真值）。
判定（与 A4.34 一致，小目标 IoU 对 25px 框不可用）：
  strict : 真球中心落在候选框内 且 中心距 ≤ 12px（约半个球）
  inbox  : 真球中心落在候选框内（宽松上界）
  near50 : 真球中心距某候选中心 ≤ 50px（极宽松，作恢复上界）
空云探针：12 个「检测器完全没提出候选」的硬漏检帧（GT 中心未知）→ 只报结构可恢复性
          （更密分块后是否出现球尺寸候选 + 数量），不编命中。

配置：
  baseline   : 640x384 ov96   （A4.33 现役口径）
  finer_ov160: 640x384 ov160  （更密 overlap，回球分辨率）
  small_480  : 480x384 ov192  （更小 tile，球相对更大）
  multiscale : 640x384 ov96 与 480x384 ov192 双网格合并后 NMS

产出：reports/milestone_05/measure/cand_pool_recall_multiscale.json
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
RF = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
      + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
      + "46c33088c790670a7e81e21e753fa368b2d77a70")
BALL = 0
THRESH = 0.05   # 与 validate_clips.py tiled() 同口径（不截断）
NMS = 0.4

CONFIGS = {
    "baseline":    [{"tw": 640, "th": 384, "ov": 96}],
    "finer_ov160": [{"tw": 640, "th": 384, "ov": 160}],
    "small_480":   [{"tw": 480, "th": 384, "ov": 192}],
    "multiscale":  [{"tw": 640, "th": 384, "ov": 96}, {"tw": 480, "th": 384, "ov": 192}],
}


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def tiled_grid(model, proc, dev, img, tw, th, ov, thresh, nms):
    H, W = img.shape[:2]
    rec = []
    for y in range(0, H, th - ov):
        for x in range(0, W, tw - ov):
            x2, y2 = min(W, x + tw), min(H, y + th)
            if x2 - x <= ov or y2 - y <= ov:
                continue
            rgb = cv2.cvtColor(img[y:y2, x:x2], cv2.COLOR_BGR2RGB)
            inp = proc(images=rgb, return_tensors="pt").to(dev)
            with torch.no_grad():
                out = model(**inp)
            res = proc.post_process_object_detection(
                out, threshold=thresh, target_sizes=torch.tensor([[y2-y, x2-x]]).to(dev))[0]
            for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(), res["labels"].tolist()):
                if int(l) == BALL:
                    rec.append({"bbox": [b[0]+x, b[1]+y, b[2]+x, b[3]+y], "conf": float(s)})
    return rec


def infer_config(model, proc, dev, img, grids):
    rec = []
    for g in grids:
        rec += tiled_grid(model, proc, dev, img, g["tw"], g["th"], g["ov"], THRESH, NMS)
    rec.sort(key=lambda r: -r["conf"])
    keep = []
    for r in rec:
        if all(iou(r["bbox"], k["bbox"]) < NMS for k in keep):
            keep.append(r)
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default="action_work/validate/sas_lal_label_bank_final351.json")
    ap.add_argument("--frames-dir", default="action_work/sas_lal")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--probe-frames",
                    default="action_work/validate/sas_lal_miss_frames.json",
                    help="含 empty_cloud 列表的 json")
    ap.add_argument("--probe-key", default="empty_cloud")
    ap.add_argument("--only-probe", action="store_true",
                    help="只跑 12 空云帧（快，决定性测试）")
    ap.add_argument("--out", default="reports/milestone_05/measure/cand_pool_recall_multiscale.json")
    a = ap.parse_args()

    bank = json.loads((ROOT / a.bank).read_text())
    tp = [r for r in bank["labels"] if r["label"] == "TP"]
    gt = {}
    for r in tp:
        b = r["bbox"]
        gt.setdefault(r["frame"], []).append(((b[0]+b[2])/2.0, (b[1]+b[3])/2.0))
    gt_frames = sorted(gt.keys())
    print(f"[gt] TP 帧 {len(gt_frames)}  bank={a.bank}")

    if a.only_probe:
        mf = json.loads((ROOT / a.probe_frames).read_text())
        probe = sorted(set(mf.get(a.probe_key, [])))
        gt_frames = []   # 只跑探针
        print(f"[probe] 仅空云帧 {len(probe)}")
    else:
        mf = json.loads((ROOT / a.probe_frames).read_text())
        probe = sorted(set(mf.get(a.probe_key, [])))

    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    model = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()
    fdir = ROOT / a.frames_dir
    print(f"[infer] dev={dev} thresh={THRESH} nms={NMS}")

    all_frames = list(gt_frames) + [f for f in probe if f not in gt_frames]
    results = {}
    t0 = time.time()
    for ci, (cname, grids) in enumerate(CONFIGS.items()):
        per = {}
        for n, fr in enumerate(all_frames):
            img = cv2.imread(str(fdir / fr))
            if img is None:
                per[fr] = {"n_cand": -1}
                continue
            keep = infer_config(model, proc, dev, img, grids)
            row = {"n_cand": len(keep)}
            if fr in gt:
                hits = {"strict": False, "inbox": False, "near50": False}
                for (gx, gy) in gt[fr]:
                    for c in keep:
                        b = c["bbox"]
                        cx, cy = (b[0]+b[2])/2.0, (b[1]+b[3])/2.0
                        inbox = b[0] <= gx <= b[2] and b[1] <= gy <= b[3]
                        if inbox:
                            hits["inbox"] = True
                            if np.hypot(gx-cx, gy-cy) <= 12.0:
                                hits["strict"] = True
                        if np.hypot(gx-cx, gy-cy) <= 50.0:
                            hits["near50"] = True
                row["hits"] = hits
            if keep:
                sz = [max(b[2]-b[0], b[3]-b[1]) for b in (c["bbox"] for c in keep)]
                row["size_min"] = round(float(min(sz)), 1)
                row["size_med"] = round(float(np.median(sz)), 1)
                row["size_max"] = round(float(max(sz)), 1)
                row["ballrange_n"] = int(sum(1 for s in sz if 15 <= s <= 45))
            per[fr] = row
            if (n+1) % 20 == 0:
                print(f"  [{cname}] {n+1}/{len(all_frames)}  {time.time()-t0:.0f}s")
        results[cname] = per
        # 汇总
        gt_hit = [per[f]["hits"] for f in gt_frames if f in per and "hits" in per[f]]
        nf = len(gt_hit)
        if nf:
            s = sum(1 for h in gt_hit if h["strict"])
            i = sum(1 for h in gt_hit if h["inbox"])
            n5 = sum(1 for h in gt_hit if h["near50"])
            print(f"  [{cname}] GT召回(分母{nf}): strict {s/nf*100:.1f}%  "
                  f"inbox {i/nf*100:.1f}%  near50 {n5/nf*100:.1f}%")
    dt = time.time() - t0

    # 空云恢复矩阵
    empty_frames = [f for f in probe if f in results["baseline"] and results["baseline"][f].get("n_cand", -1) == 0]
    recovery = {}
    for f in empty_frames:
        recovery[f] = {c: results[c].get(f, {}).get("n_cand", -1) for c in CONFIGS}

    out = {"meta": {"bank": a.bank, "gt_frames": len(gt_frames), "probe_frames": len(probe),
                    "thresh": THRESH, "nms": NMS, "configs": CONFIGS,
                    "seconds": round(dt, 1),
                    "judge": "strict=中心在框内且距<=12px; inbox=中心在框内; near50=距<=50px",
                    "note": "只读诊断；分母=独立真值帧；空云帧无GT只报结构可恢复性"},
            "recall_per_config": {},
            "empty_cloud_recovery": recovery,
            "per_frame": results}
    # 召回汇总
    for cname in CONFIGS:
        gh = [results[cname][f]["hits"] for f in gt_frames if f in results[cname] and "hits" in results[cname][f]]
        nf = len(gh)
        out["recall_per_config"][cname] = {
            "n_gt": nf,
            "strict": round(sum(1 for h in gh if h["strict"])/nf, 4) if nf else None,
            "inbox": round(sum(1 for h in gh if h["inbox"])/nf, 4) if nf else None,
            "near50": round(sum(1 for h in gh if h["near50"])/nf, 4) if nf else None,
        }
    op = ROOT / a.out
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[out] {op}  {dt:.0f}s")


if __name__ == "__main__":
    main()
