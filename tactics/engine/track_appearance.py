#!/usr/bin/env python3
"""A5.3 外观门关联（老程选 C）：宽松几何门 + 躯干色外观门，防 ID 错并。

动机（A5.2）：`max_missed` + `GATE_POS` 调参能把 ID 从 183 降到 108，但几何门放宽后
**相邻球员串号风险上升**。C = 放开几何门，用**外观**消歧把错并压回去。

实现要点：
  - 外观特征 = 躯干区中位色（复用 `assign_team.torso_median`，**关联特征，非聚类**）。
  - 关联代价 += W_APP · 颜色距离；并设 APP_MAX 硬门（色差过大直接拒绝该匹配）。
  - **独立验证信号** = 「腿部区（0.55–0.85H）中位色」，与关联用的躯干区（0.12–0.45H）
    **不同区域** ⇒ 用它算「合并轨迹的颜色不连续率」，避免用同一特征自证。
  - 阴性对照 = 打乱外观特征（--shuffle）：若外观门真在起作用，置换后纯度应退化。

对比配置：base / B(宽松几何) / C(宽松+外观) / C-shuffle。
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")

import numpy as np  # noqa: E402
from scipy.optimize import linear_sum_assignment  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import assign_team as at  # noqa: E402

W_POS, W_SIZE, W_IOU = 1.0, 0.5, 0.8
CONT_THRESH = 0.22   # 颜色不连续判定阈值（归一化 0–1 尺度）


def foot(b): return ((b[0] + b[2]) / 2.0, b[3])
def bh(b):   return b[3] - b[1]


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def lower_median(img, box):
    """腿部/短裤区中位色（独立于躯干区，用于验证）。"""
    import cv2  # noqa
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    if w < 8 or h < 16:
        return None
    rx1, rx2 = x1 + int(0.25 * w), x1 + int(0.75 * w)
    ry1, ry2 = y1 + int(0.55 * h), y1 + int(0.85 * h)
    rx1, rx2 = max(0, rx1), min(img.shape[1], rx2)
    ry1, ry2 = max(0, ry1), min(img.shape[0], ry2)
    if rx2 - rx1 < 5 or ry2 - ry1 < 5:
        return None
    roi = img[ry1:ry2, rx1:rx2].reshape(-1, 3).astype(np.float32)
    return np.median(roi, axis=0)


def cdist(a, b):
    """归一化颜色距离 0–1（BGR）。"""
    if a is None or b is None:
        return None
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))) / 255.0)


def build_feats(frames, raw, conf_person):
    import cv2
    out = []
    for fr, boxes in zip(frames, raw):
        img = cv2.imread(fr["path"])
        dets = []
        for b in boxes:
            if b[0] != 0 or b[1] < conf_person:
                continue
            box = b[2]
            dets.append({"box": box, "conf": b[1],
                         "torso": at.torso_median(img, box),
                         "lower": lower_median(img, box)})
        out.append(dets)
    return out


def track(feats, frames, H, max_missed, gate_pos, gate_size, w_app, app_max,
          shuffle=False, seed=7):
    rng = np.random.default_rng(seed)
    tracks, nxt, out = {}, 1, []
    for fi, dets in enumerate(feats):
        dets = [dict(d) for d in dets]
        if shuffle:  # 阴性对照：打乱外观特征在检测间的分配
            cols = [d["torso"] for d in dets]
            rng.shuffle(cols)
            for d, c in zip(dets, cols):
                d["torso"] = c
        live = {t: v for t, v in tracks.items() if v["missed"] <= max_missed}
        tids = list(live)
        matched = []
        if tids and dets:
            C = np.full((len(tids), len(dets)), 1e6)
            for i, tid in enumerate(tids):
                tr = live[tid]
                k = tr["missed"] + 1
                pb = [tr["box"][j] + tr["vel"][j % 2] * k for j in range(4)]
                pfx, pfy = foot(pb)
                ph = max(bh(pb), 1.0)
                for j, d in enumerate(dets):
                    dfx, dfy = foot(d["box"])
                    dp = ((dfx - pfx) ** 2 + (dfy - pfy) ** 2) ** 0.5 / H
                    ds = abs(np.log(ph / max(bh(d["box"]), 1.0)))
                    if dp > gate_pos or ds > gate_size:
                        continue
                    c = W_POS * dp + W_SIZE * ds + W_IOU * (1.0 - iou(pb, d["box"]))
                    cd = cdist(tr["color"], d["torso"])
                    if cd is not None:
                        if cd > app_max:      # 外观硬门：色差过大直接拒绝
                            continue
                        c += w_app * cd
                    C[i, j] = c
            ri, ci = linear_sum_assignment(C)
            matched = [(tids[i], ci[k]) for k, i in enumerate(ri) if C[i, ci[k]] < 1e5]
        used_d, used_t = set(), set()
        for tid, di in matched:
            used_t.add(tid); used_d.add(di)
            tr = tracks[tid]; d = dets[di]
            ofx, ofy = foot(tr["box"]); nfx, nfy = foot(d["box"])
            tr["vel"] = (nfx - ofx, nfy - ofy)
            tr["box"] = d["box"]; tr["conf"] = d["conf"]; tr["missed"] = 0
            if tr["color"] is None:
                tr["color"] = d["torso"]
            elif d["torso"] is not None:
                tr["color"] = 0.7 * np.asarray(tr["color"]) + 0.3 * np.asarray(d["torso"])
            tr["frames"].append(fi); tr["lower"].append((fi, d["lower"]))
        for tid in tids:
            if tid not in used_t:
                tracks[tid]["missed"] += 1
        for di, d in enumerate(dets):
            if di in used_d:
                continue
            tracks[nxt] = {"box": d["box"], "vel": (0.0, 0.0), "missed": 0,
                           "conf": d["conf"], "color": d["torso"],
                           "frames": [fi], "lower": [(fi, d["lower"])]}
            nxt += 1
        out.append(len(dets))
    return tracks, out


def metrics(tracks, det_ppl):
    lives = [len(t["frames"]) for t in tracks.values()]
    # 独立验证：合并轨迹内"腿部色"不连续率
    disc = tot = 0
    for t in tracks.values():
        seq = [c for _, c in t["lower"] if c is not None]
        for i in range(1, len(seq)):
            d = cdist(seq[i - 1], seq[i])
            if d is None:
                continue
            tot += 1
            if d > CONT_THRESH:
                disc += 1
    return {"n_ids": len(tracks), "med_life": round(statistics.median(lives), 1),
            "max_life": max(lives), "det_ppl": round(statistics.mean(det_ppl), 2),
            "color_disc_rate": round(disc / max(tot, 1), 3), "n_cmp": tot}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep1_s0")
    ap.add_argument("--imgsz", type=int, default=1280)
    a = ap.parse_args()
    segdir = ROOT / "action_work" / "tactic_notes_batch_full" / "segments" / a.seg
    frames = json.load(open(segdir / "frames.json"))
    raw = json.load(open(ROOT / "action_work" / f"_detcache_{a.seg}_{a.imgsz}.json"))
    from PIL import Image
    _, H = Image.open(frames[0]["path"]).size
    t0 = time.perf_counter()
    feats = build_feats(frames, raw, 0.25)
    print(f"段={a.seg} 帧={len(frames)} H={H} 外观特征提取 {time.perf_counter()-t0:.1f}s")

    cfgs = [
        ("base  mm3  gate.16", 3, 0.16, 0.90, 0.0, 9.9, False),
        ("B60   mm30 gate.60 w0", 30, 0.60, 0.90, 0.0, 9.9, False),
        ("C60   gate.60 w1.0", 30, 0.60, 0.90, 1.0, 0.30, False),
        ("C60   gate.60 w3.0 am.20", 30, 0.60, 0.90, 3.0, 0.20, False),
        ("C60sh gate.60 w3.0 (对照)", 30, 0.60, 0.90, 3.0, 0.20, True),
        ("B90   mm30 gate.90 w0", 30, 0.90, 0.90, 0.0, 9.9, False),
        ("C90   gate.90 w3.0 am.20", 30, 0.90, 0.90, 3.0, 0.20, False),
    ]
    print(f"\n{'配置':<24}{'ID数':>6}{'中位寿命':>9}{'最长':>6}"
          f"{'色不连续率':>11}{'比较次数':>9}")
    rows = []
    for name, mm, gp, gs, wa, am, sh in cfgs:
        tr, dppl = track(feats, frames, H, mm, gp, gs, wa, am, sh)
        m = metrics(tr, dppl); m["name"] = name
        rows.append(m)
        print(f"{name:<24}{m['n_ids']:>6}{m['med_life']:>9}{m['max_life']:>6}"
              f"{m['color_disc_rate']:>11}{m['n_cmp']:>9}")
    out = ROOT / "action_work" / f"track_appearance_{a.seg}.json"
    json.dump({"seg": a.seg, "imgsz": a.imgsz, "rows": rows},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
