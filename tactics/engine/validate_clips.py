#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_clips.py — 在录像库挑出的高品质片段上复跑里程碑 05 球检测管线，验证「任务级事件可用性」门禁。

复用的正是里程碑 05 的最终管线（数字口径一致）：
  ① tile 检测 (ball_tile_ab.tiled: 640x384 overlap96, NMS IoU<0.4, top-4/帧) → conf1
  ② 256px 裁切放大 384 二次 RF-DETR 验证 → conf2  (detect_ball_verified.py)
  ③ 验证头打分 (ball_feats_all.build_all + ball_head_v2.joblib) → prob
  ④ ball_event_usability 同口径（th=0.975 高置信点）算覆盖率/片段/可跟踪率

用法:
  python engine/validate_clips.py --clip sas_hou --frames-dir action_work/validate/sas_hou \
      [--limit 0] [--device mps] [--vconf -1]
产出:
  action_work/validate/<clip>_scores.json        (与 ball_cand_scores_v2.json 同格式)
  action_work/validate/<clip>_usability.json     (单窗可用性实测)
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
MS = ROOT / "reports/milestone_05/measure"
RF = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
      + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
      + "46c33088c790670a7e81e21e753fa368b2d77a70")
BALL = 0
TH = 0.975
GAP_TOL = 3
SMOOTH_PX = 80.0


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def tiled(proc, model, dev, img, tw, th, ov, thresh, topk=4):
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
        if all(iou(r["bbox"], k["bbox"]) < 0.4 for k in keep):
            keep.append(r)
    # topk<=0 = 不截断（返回全部 NMS 保留）；topk>0 = 保留前 k。
    # 🔴 A4.42 修复：原 `keep[:topk]` 在 topk=0 时返回 []（Python 切片语义），
    # 导致 gen_cands_tiled --topk 0 产出全空候选池（烟雾测试 f00001 0 候选抓到）。
    return (keep if topk <= 0 else keep[:topk]), ntile


def infer_ball(proc, model, dev, bgr, thresh):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    inp = proc(images=rgb, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model(**inp)
    res = proc.post_process_object_detection(
        out, threshold=thresh, target_sizes=torch.tensor([[h, w]]).to(dev))[0]
    return [{"bbox": [float(v) for v in b], "conf": float(s)}
            for b, s, l in zip(res["boxes"].tolist(), res["scores"].tolist(),
                               res["labels"].tolist()) if int(l) == BALL]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--vconf", type=float, default=-1.0)
    ap.add_argument("--tw", type=int, default=640)
    ap.add_argument("--th", type=int, default=384)
    ap.add_argument("--ov", type=int, default=96)
    ap.add_argument("--topk", type=int, default=4,
                    help="每帧保留候选数；0=不截断(返回全部NMS保留)。A4.41 small_480 验证用 0。")
    a = ap.parse_args()

    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    model = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()

    fdir = Path(a.frames_dir)
    frames = sorted(fdir.glob("*.jpg"))
    if a.limit:
        frames = frames[:a.limit]
    print(f"[tile+verify] {len(frames)} 帧  dev={dev}")

    cands = {}
    t0 = time.time()
    for n, f in enumerate(frames):
        img = cv2.imread(str(f))
        if img is None:
            cands[f.name] = []
            continue
        tile_rec, _ = tiled(proc, model, dev, img, a.tw, a.th, a.ov, 0.05, a.topk)
        keep = []
        for c in tile_rec:
            x1, y1, x2, y2 = c["bbox"]
            cx, cy = (x1+x2)/2, (y1+y2)/2
            h = 128
            X1, Y1 = int(cx-h), int(cy-h)
            sx1, sy1 = max(0, X1), max(0, Y1)
            sx2, sy2 = min(img.shape[1], X1+256), min(img.shape[0], Y1+256)
            crop = img[sy1:sy2, sx1:sx2]
            if crop.shape[0] < 30 or crop.shape[1] < 30:
                keep.append({"bbox": c["bbox"], "conf1": c["conf"], "conf2": 0.0})
                continue
            sc = 384.0 / crop.shape[1]
            mb = [(x1-X1)*sc, (y1-Y1)*sc, (x2-X1)*sc, (y2-Y1)*sc]
            rgb = cv2.cvtColor(cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC),
                              cv2.COLOR_BGR2RGB)
            inp = proc(images=rgb, return_tensors="pt").to(dev)
            with torch.no_grad():
                o = model(**inp)
            res = proc.post_process_object_detection(
                o, threshold=0.05, target_sizes=torch.tensor([[384, 384]]).to(dev))[0]
            best = 0.0
            for b, s, li in zip(res["boxes"].tolist(), res["scores"].tolist(), res["labels"].tolist()):
                if int(li) == BALL and iou(b, mb) > 0.3:
                    best = max(best, float(s))
            if best > a.vconf:
                keep.append({"bbox": [float(v) for v in c["bbox"]], "conf1": float(c["conf"]),
                             "conf2": round(best, 3)})
        cands[f.name] = keep
        if (n+1) % 50 == 0:
            print(f"  {n+1}/{len(frames)}  {time.time()-t0:.0f}s", flush=True)

    cands_path = AW / "validate" / f"{a.clip}_cands.json"
    cands_path.write_text(json.dumps({a.clip: cands}))
    print(f"[cands] {cands_path}  候选帧 {sum(1 for v in cands.values() if v)}/{len(cands)}")

    # ---- ③ 验证头打分（加载已训好的 ball_head_v2.joblib，不重训）----
    import sys
    sys.path.insert(0, str(ROOT / "engine"))
    import ball_feats_all as B
    import joblib
    head = joblib.load(MS / "ball_head_v2.joblib")
    pipe = head["pipe"]
    idx = {a.clip: B.build_det_index(cands)}
    rows = [{"window": a.clip, "frame": fn, "bbox": c["bbox"],
             "conf1": c["conf1"], "conf2": c["conf2"]}
            for fn, cs in cands.items() for c in cs]
    print(f"[head] 特征 {len(rows)} 候选 ...")
    X = B.build_all(rows, idx, dev="cpu")
    pp = pipe.predict_proba(X)[:, 1]
    scores = {a.clip: {}}
    k = 0
    for fn, cs in cands.items():
        scores[a.clip][fn] = [{"bbox": c["bbox"], "prob": float(pp[k])} for c in cs]
        k += len(cs)
    scores_path = AW / "validate" / f"{a.clip}_scores.json"
    scores_path.write_text(json.dumps(scores))
    print(f"[scores] {scores_path}")

    # ---- ④ 可用性（单窗，同 ball_event_usability 口径）----
    # 注意：帧号是 int，present 键是 "fNNNNN.jpg" 字符串 —— 必须用 num→(fn,center) 映射，
    # 不能写 `num in present`（int 永不匹配 str 键，会把片段/可跟踪全算成 0）。
    present_int = {}
    for fn, cs in scores[a.clip].items():
        hs = [c for c in cs if c["prob"] > TH]
        if not hs:
            continue
        best = max(hs, key=lambda c: c["prob"])
        num = int(fn[1:6])
        present_int[num] = ((best["bbox"][0]+best["bbox"][2])/2,
                            (best["bbox"][1]+best["bbox"][3])/2)
    top1 = present_int
    nums = sorted(present_int.keys())
    cov = len(present_int)/len(frames)
    eps, cur, last = [], [], None
    for num in nums:
        if last is not None and num-last > GAP_TOL+1 and cur:
            eps.append(cur); cur = []
        cur.append(num); last = num
    if cur:
        eps.append(cur)
    ep_lens = [len(e) for e in eps]
    steps = []
    for e in eps:
        for a_, b_ in zip(e, e[1:]):
            if a_ in top1 and b_ in top1:
                steps.append(math.hypot(top1[b_][0]-top1[a_][0], top1[b_][1]-top1[a_][1]))
    med = sorted(steps)[len(steps)//2] if steps else 0.0
    track = sum(1 for d in steps if d < SMOOTH_PX)/len(steps) if steps else 0.0
    usab = {"clip": a.clip, "th": TH, "n_frames": len(frames),
            "frame_coverage": round(cov, 4), "n_episodes": len(eps),
            "mean_episode_len": round(sum(ep_lens)/len(ep_lens), 2) if ep_lens else 0.0,
            "median_step_px": round(med, 1), "trackable_frac": round(track, 4),
            "n_claim_frames": len(present_int)}
    (AW / "validate" / f"{a.clip}_usability.json").write_text(json.dumps(usab, ensure_ascii=False, indent=1))
    print(f"[usability] 覆盖 {cov*100:.1f}%  片段 {len(eps)}  均长 {usab['mean_episode_len']}  "
          f"中位步长 {med:.0f}px  可跟踪 {track*100:.1f}%")
    print(f"→ {AW/'validate'/f'{a.clip}_usability.json'}")


if __name__ == "__main__":
    main()
