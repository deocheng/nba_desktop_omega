#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球验证头·统一特征模块（训练与推理同源，防口径漂移）。

特征顺序（与 ball_fusion_eval.py 完全一致，共 1565 维）：
  ① 外观 base 256 ⊕ 512 的 CLS（原图与水平翻转平均 = TTA）      → 1536
  ② 几何 conf1, conf2, log1p(w), log1p(h), cy/1080               →    5
  ③ 多帧运动 v1（±5 帧最近候选统计，含 ±10 帧同点复现）           →   10
  ④ 多帧运动 v2（轨迹链 + 物理合理性 + 平直度 + 外推残差）        →    9
  ⑤ 掩膜几何（地板掩膜连续量，非硬门禁）                          →    5

用法（供 ball_verify_head.py 调用）：
  det_index = build_det_index(det_json_dict)      # {int帧号: [((cx,cy), conf2)]}
  X = build_all(rows, det_index, dev="cpu")       # rows: [{window, frame, bbox, conf1, conf2}]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
DINO = "facebook/dinov2-base"
MOT_KEYS = ["d_med", "d_min", "d_max", "d_min_norm", "static_frac", "near25_frac",
            "nframe_with", "ncand_med", "recur20", "conf_std"]
MOT2_KEYS = ["d_prev", "d_next", "plaus_prev", "plaus_next", "chain_tot", "chain_fwd",
             "chain_bwd", "turn_cos", "extrap_resid"]
MSK_KEYS = ["in_floor", "foot_in_floor", "center_dist", "gap_below", "col_floor_frac"]
K, RECUR_R, RECUR_SPAN = 5, 20.0, 10
R_CHAIN, CHAIN_MAX = 130.0, 12


def _ctr(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def build_det_index(det_window: dict):
    """det_window: {frame_str: [ {bbox, conf2}, ... ]} -> {帧号: [((cx,cy), conf2)]}"""
    return {int(f[1:6]): [(_ctr(c["bbox"]), float(c.get("conf2", 0.0))) for c in cs]
            for f, cs in det_window.items()}


def _nearest(cands, x, y, R):
    if not cands:
        return None, None
    d, best = min(((np.hypot(c[0][0] - x, c[0][1] - y), c[0]) for c in cands), key=lambda t: t[0])
    return (best, float(d)) if d <= R else (None, float(d))


def _chain(idx, i, x, y, step, R, maxlen=CHAIN_MAX):
    pts = []
    for k in range(1, maxlen + 1):
        b, _ = _nearest(idx.get(i + step * k, []), x, y, R)
        if b is None:
            break
        x, y = b[0], b[1]
        pts.append((x, y))
    return pts


def motion_feats(idx, i, cx, cy, bw):
    ds, n_cand, confs = [], [], []
    for k in range(-K, K + 1):
        if k == 0:
            continue
        cs = idx.get(i + k, [])
        n_cand.append(len(cs))
        if not cs:
            ds.append(np.nan); continue
        d, cand = min(((np.hypot(c[0][0] - cx, c[0][1] - cy), c) for c in cs),
                      key=lambda t: t[0])
        ds.append(float(d))
        confs.append(float(cand[1]))
    d = np.array(ds, float)
    fin = d[~np.isnan(d)]
    recur = []
    for k in range(-RECUR_SPAN, RECUR_SPAN + 1):
        if k == 0:
            continue
        recur.append(any(np.hypot(c[0][0] - cx, c[0][1] - cy) < RECUR_R
                         for c in idx.get(i + k, [])))
    v1 = [
        float(np.nanmedian(d)) if fin.size else 999.0,
        float(np.nanmin(d)) if fin.size else 999.0,
        float(np.nanmax(d)) if fin.size else 999.0,
        (float(np.nanmin(d)) / max(1.0, bw)) if fin.size else 99.0,
        float(np.mean(fin < 15)) if fin.size else 0.0,
        float(np.mean(fin < 25)) if fin.size else 0.0,
        float(np.mean(np.array(n_cand) > 0)),
        float(np.median(n_cand)),
        float(np.mean(recur)),
        0.0,
    ]
    fw = _chain(idx, i, cx, cy, +1, R_CHAIN)
    bw_ = _chain(idx, i, cx, cy, -1, R_CHAIN)
    d_prev = np.hypot(bw_[0][0] - cx, bw_[0][1] - cy) if bw_ else 999.0
    d_next = np.hypot(fw[0][0] - cx, fw[0][1] - cy) if fw else 999.0
    tc, resid = 0.0, 999.0
    if fw and bw_:
        v1v = np.array([cx - bw_[0][0], cy - bw_[0][1]])
        v2v = np.array([fw[0][0] - cx, fw[0][1] - cy])
        n1, n2 = np.linalg.norm(v1v), np.linalg.norm(v2v)
        if n1 > 1 and n2 > 1:
            tc = float(np.dot(v1v, v2v) / (n1 * n2))
        ex, ey = cx + (cx - bw_[0][0]), cy + (cy - bw_[0][1])
        resid = float(np.hypot(fw[0][0] - ex, fw[0][1] - ey))
    v2 = [float(d_prev), float(d_next), float(8 <= d_prev <= 150), float(8 <= d_next <= 150),
          float(len(fw) + len(bw_)), float(len(fw)), float(len(bw_)), tc, float(min(resid, 999))]
    z1 = np.log1p(np.minimum(np.array(v1, float), 300))
    z2 = np.log1p(np.minimum(np.array(v2, float), 300))
    return z1, z2


def mask_feats(img, cm, box):
    x1, y1, x2, y2 = box
    H, W = cm.shape
    cx = min(max(int((x1 + x2) / 2), 0), W - 1)
    cy = min(max(int((y1 + y2) / 2), 0), H - 1)
    fx = min(max(int((x1 + x2) / 2), 0), W - 1)
    fy = min(max(int(y2), 0), H - 1)
    inside = cm > 0
    dist = cv2.distanceTransform((~inside).astype(np.uint8), cv2.DIST_L2, 3) if inside.any() else None
    cd = float(dist[cy, cx]) if dist is not None else 600.0
    col = inside[:, fx]
    below = np.where(col[fy:])[0]
    gap = float(below[0]) if below.size else 600.0
    v = [float(inside[cy, cx]), float(inside[fy, fx]), min(cd, 600.0), gap, float(col.mean())]
    return np.log1p(np.minimum(np.array(v, float), 600))


def build_all(rows, det_index, dev="cpu", progress=True):
    import sys

    import torch
    from transformers import AutoImageProcessor, AutoModel
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from court_mask import court_mask

    proc = AutoImageProcessor.from_pretrained(DINO)
    model = AutoModel.from_pretrained(DINO).to(dev).eval()
    out, masks = [], {}
    for n, r in enumerate(rows):
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        if img is None:
            raise FileNotFoundError(AW / r["window"] / r["frame"])
        x1, y1, x2, y2 = r["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        vec = []
        for csize in (256, 512):
            h = csize // 2
            X1, Y1 = int(cx - h), int(cy - h)
            c = img[max(0, Y1):min(img.shape[0], Y1 + csize),
                    max(0, X1):min(img.shape[1], X1 + csize)]
            pad = np.zeros((csize, csize, 3), np.uint8)
            ch, cw = min(c.shape[0], csize), min(c.shape[1], csize)
            pad[:ch, :cw] = c[:ch, :cw]
            for fl in (False, True):
                p = pad[:, ::-1] if fl else pad
                rgb = cv2.cvtColor(cv2.resize(p, (224, 224)), cv2.COLOR_BGR2RGB)
                inp = proc(images=rgb, return_tensors="pt").to(dev)
                with torch.no_grad():
                    o = model(**inp).last_hidden_state[:, 0]
                vec.append(o[0].cpu().float().numpy())
        app = np.concatenate([(vec[0] + vec[1]) / 2, (vec[2] + vec[3]) / 2])
        geo = np.array([r.get("conf1", 0.0), r.get("conf2", 0.0), np.log1p(x2 - x1),
                        np.log1p(y2 - y1), cy / 1080.0], float)
        idx = det_index[r["window"]]
        z1, z2 = motion_feats(idx, int(r["frame"][1:6]), cx, cy, x2 - x1)
        mkey = (r["window"], r["frame"])
        if mkey not in masks:
            masks[mkey] = court_mask(img)
        z3 = mask_feats(img, masks[mkey], r["bbox"])
        out.append(np.concatenate([app, geo, z1, z2, z3]))
        if progress and (n + 1) % 60 == 0:
            print(f"  特征 {n+1}/{len(rows)}", flush=True)
    return np.array(out, np.float32)


def load_det_index(paths=("w1", "w2", "w3", "w4"), suffix="_ball_verified"):
    import json
    return {w: build_det_index(json.loads((AW / f"{w}{suffix}.json").read_text())) for w in paths}


if __name__ == "__main__":
    import json
    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    X = build_all(bank, load_det_index(), dev="cpu")
    np.save(MS / "feats_all.npy", X)
    print(f"[out] feats_all.npy  {X.shape}")
