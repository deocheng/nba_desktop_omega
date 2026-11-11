#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全帧混合球追踪（高帧率专线 seg_hi，435 帧 @10fps）。

── 四个判据的串联顺序（为什么是这个顺序）──────────────────────
  候选  = 颜色（第一判据，用户指令）+ 形状（圆/尺寸）        ← 召回
  判据0 = 注意力区（球场 ∪ 球员框 ∪ 篮筐区）                 ← 去观众席
  判据1 = 到最近手腕 ≤ gate（默认 90px）                     ← 「被持/运」球
  判据2 = 时序一致性                                         ← **仅作诊断，绝不用于选择**

── 🔴 判据2 为什么只做诊断 ────────────────────────────────────
本项目吃过一次亏：t=247.1–247.6 出现一条 dx 单调 +25px/帧、尺寸稳定 12±1×16±1、
**到手腕距离单调收敛 155.4→82.4px** 并过门禁的"完美"轨迹；
逐帧目视后 **6 帧全是木地板白色虚线纹理，画面里根本没有球**。
真因是**镜头平移让静止纹理表现出平滑运动**。
⇒ **平滑/连续/收敛三条同时成立，仍然可以完全不是球。**
所以本脚本只把时序一致性写成 `temporal_support` 字段供审计，
不参与打分、不做轨迹平滑、不做插值。

── 注意力区为什么必须含「篮筐区」────────────────────────────
持球上举时球在图像上的投影会落到**场外观众席/广告板**上：
实测 t=219.5 真球 (1236,349) **不在球场掩膜内**，只能靠姿态球员框救回来。
篮筐区同理——球在篮筐上方的飞行段可能压在透明篮板（后面是观众）上。
三条并集各覆盖不同阶段，缺一不可。

── 置信度分级（诚实报告，不掩盖）────────────────────────────
  high  = 恰有 1 个候选通过手腕门禁
  med   = ≥2 个候选通过手腕门禁（有歧义）
  low   = 0 个过门禁但注意力区内有候选（飞行/散球，或门禁太紧）
  none  = 注意力区内无候选
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from court_attention import court_mask as build_court_mask  # noqa: E402


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────── 颜色 + 形状候选 ───────────────────────
def color_candidates(bgr, h_lo=4, h_hi=26, s_min=60, v_min=35,
                     area_min=60, area_max=3000, aspect_max=2.4, fill_min=0.38):
    """球色候选。色相域用**度数**表示：球实测 Hue≈17.2°，木地板≈35.4°。

    ⚠️ H 在 OpenCV 是 0–180 刻度（=度数/2）。红区在 0/180 处**环绕**，
    所以同时取 `H<=h_hi` 与 `H>=180-h_hi` 两支，且**均值必须用中位数**
    （对跨环绕 patch 求算术平均会出垃圾值，实测把 2.5° 算成 92.4°）。
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    Ho, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    lo, hi = h_lo / 2.0, h_hi / 2.0           # 度数 → OpenCV 刻度
    mask = (((Ho >= lo) & (Ho <= hi)) & (S >= s_min) & (V >= v_min)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (area_min <= area <= area_max):
            continue
        ar = w / max(h, 1)
        if not (1 / aspect_max <= ar <= aspect_max):
            continue
        fill = area / float(w * h)
        if fill < fill_min:
            continue
        m = (lab == i)
        hs = Ho[m].astype(float)
        ss = S[m].astype(float)
        vs = V[m].astype(float)
        hue_deg = float(np.median(hs)) * 2.0
        sat = float(np.median(ss)) / 255.0
        val = float(np.median(vs)) / 255.0
        # 圆度：blob 与同面积圆的重叠（粗算：面积 / 外接圆面积）
        circ = area / (math.pi * ((w + h) / 4.0) ** 2 + 1e-6)
        out.append({
            "cx": float(cent[i][0]), "cy": float(cent[i][1]),
            "w": int(w), "h": int(h), "area": int(area),
            "fill": round(float(fill), 3), "circ": round(float(min(circ, 1.0)), 3),
            "hue_deg": round(hue_deg, 1), "sat": round(sat, 3), "val": round(val, 3),
            "diam": round((w + h) / 2.0, 1),
        })
    return out


# ─────────────────────── 姿态 ───────────────────────
def pose_frame(model, path, imgsz, conf, wrist_conf, device):
    res = model.predict(path, imgsz=imgsz, conf=conf, device=device, verbose=False)[0]
    boxes, wrists = [], []
    if res.keypoints is not None and len(res.keypoints):
        kp = res.keypoints.xy.cpu().numpy()
        cf = res.keypoints.conf.cpu().numpy()
        bx = res.boxes.xyxy.cpu().numpy()
        bcf = res.boxes.conf.cpu().numpy()
        for i in range(len(kp)):
            b = [float(v) for v in bx[i]]
            boxes.append({"box": b, "conf": float(bcf[i])})
            for w in (9, 10):
                if cf[i, w] >= wrist_conf:
                    wrists.append({"xy": [float(kp[i, w, 0]), float(kp[i, w, 1])],
                                   "box": b, "conf": float(cf[i, w])})
    return {"boxes": boxes, "wrists": wrists}


# ─────────────────────── 主流程 ───────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--frames-json", required=True)
    ap.add_argument("--pose-weights", required=True)
    ap.add_argument("--hoop-track", default="", help="hoop_track.json（并入注意力区）")
    ap.add_argument("--pose-cache", default="", help="姿态缓存 json（复用/落盘）")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--pose-conf", type=float, default=0.35)
    ap.add_argument("--wrist-conf", type=float, default=0.30)
    ap.add_argument("--gate", type=float, default=90.0)
    ap.add_argument("--attn-pad", type=int, default=24)
    ap.add_argument("--pad-player", type=int, default=14)
    ap.add_argument("--h-lo", type=float, default=4.0)
    ap.add_argument("--h-hi", type=float, default=26.0)
    ap.add_argument("--s-min", type=int, default=60)
    ap.add_argument("--v-min", type=int, default=35)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--qc-every", type=int, default=15, help="每 N 帧出一张 QC 核对图（0=不出）")
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    meta = load_json(a.frames_json)
    rows = [(r["idx"], r["t"], r["path"]) for r in meta]
    if a.limit:
        rows = rows[:a.limit]
    tmap = {i: t for i, t, _ in rows}

    # 篮筐区（只有人工核实窗口内有；窗口外为空）
    hoop_reg = {}
    if a.hoop_track:
        for r in load_json(a.hoop_track) or []:
            if r.get("region"):
                hoop_reg[r["idx"]] = r["region"]
    print(f"帧 {len(rows)}  篮筐区可用 {len(hoop_reg)} 帧")

    cache = load_json(a.pose_cache, default={}) if a.pose_cache else {}
    cache = cache or {}

    from ultralytics import YOLO
    model = YOLO(a.pose_weights)
    print(f"姿态权重 {a.pose_weights}  imgsz={a.imgsz} device={a.device}")

    out, t_start = [], time.time()
    for k, (idx, t, path) in enumerate(rows):
        if not os.path.exists(path):
            continue
        bgr = cv2.imread(path)
        Himg, Wimg = bgr.shape[:2]

        key = str(idx)
        if key in cache:
            pose = cache[key]
        else:
            pose = pose_frame(model, path, a.imgsz, a.pose_conf, a.wrist_conf, a.device)
            cache[key] = pose
        pboxes = [b["box"] for b in pose["boxes"]]
        wrists = pose["wrists"]

        cands = color_candidates(bgr, a.h_lo, a.h_hi, a.s_min, a.v_min)

        court, _poly = build_court_mask(bgr)
        court_d = (cv2.dilate(court, np.ones((2 * a.attn_pad + 1,) * 2, np.uint8))
                   if a.attn_pad > 0 else court)
        pmask = np.zeros_like(court)
        for b in pboxes:
            cv2.rectangle(pmask,
                          (max(0, int(b[0]) - a.pad_player), max(0, int(b[1]) - a.pad_player)),
                          (min(Wimg - 1, int(b[2]) + a.pad_player),
                           min(Himg - 1, int(b[3]) + a.pad_player)), 1, -1)
        hmask = np.zeros_like(court)
        hr = hoop_reg.get(idx)
        if hr:
            cv2.rectangle(hmask, (max(0, int(hr[0])), max(0, int(hr[1]))),
                          (min(Wimg - 1, int(hr[2])), min(Himg - 1, int(hr[3]))), 1, -1)
        attn = ((court_d > 0) | (pmask > 0) | (hmask > 0)).astype(np.uint8)

        kept, killed = [], []
        for c in cands:
            xi = int(max(0, min(Wimg - 1, round(c["cx"]))))
            yi = int(max(0, min(Himg - 1, round(c["cy"]))))
            c["in_court"] = bool(court_d[yi, xi] > 0)
            c["in_player"] = bool(pmask[yi, xi] > 0)
            c["in_hoop"] = bool(hmask[yi, xi] > 0)
            c["in_attn"] = bool(attn[yi, xi] > 0)
            d, wsel = (None, None)
            if wrists:
                d, wsel = min(((math.hypot(c["cx"] - w["xy"][0], c["cy"] - w["xy"][1]), w)
                               for w in wrists), key=lambda z: z[0])
            c["min_wrist_dist"] = round(d, 1) if d is not None else None
            c["pass_wrist_gate"] = bool(d is not None and d <= a.gate)
            c["holder_box"] = wsel["box"] if wsel else None
            hand = 1.0 / (1.0 + (d if d is not None else 999) / 60.0)
            hue_mid = 1.0 - min(abs(c["hue_deg"] - 17.2) / 22.0, 1.0)
            c["score"] = round(hand * 0.46 + c["circ"] * 0.22 + c["fill"] * 0.14
                               + hue_mid * 0.14 + min(c["val"], 0.6) * 0.04, 4)
            (kept if c["in_attn"] else killed).append(c)
        kept.sort(key=lambda c: -c["score"])
        passing = [c for c in kept if c["pass_wrist_gate"]]

        if len(passing) == 1:
            pick, conf = passing[0], "high"
        elif len(passing) > 1:
            pick, conf = passing[0], "med"
        elif kept:
            pick, conf = kept[0], "low"
        else:
            pick, conf = None, "none"

        out.append({
            "idx": idx, "t": round(t, 2), "frame": idx + 1,
            "conf": conf,
            "n_cand": len(cands), "n_killed": len(killed), "n_kept": len(kept),
            "n_pass_gate": len(passing),
            "court_cov": round(float(court.mean()), 4),
            "attn_cov": round(float(attn.mean()), 4),
            "n_pose_box": len(pboxes), "n_wrist": len(wrists),
            "has_hoop_region": bool(hr),
            "pick": ({"cx": round(pick["cx"], 1), "cy": round(pick["cy"], 1),
                      "diam": pick["diam"], "hue_deg": pick["hue_deg"],
                      "sat": pick["sat"], "val": pick["val"],
                      "fill": pick["fill"], "circ": pick["circ"],
                      "min_wrist_dist": pick["min_wrist_dist"],
                      "holder_box": pick["holder_box"],
                      "in_court": pick["in_court"], "in_player": pick["in_player"],
                      "in_hoop": pick["in_hoop"],
                      "score": pick["score"]} if pick else None),
            "top3": [{"cx": round(c["cx"], 1), "cy": round(c["cy"], 1),
                      "score": c["score"], "d": c["min_wrist_dist"]}
                     for c in passing[:3]] or
                     [{"cx": round(c["cx"], 1), "cy": round(c["cy"], 1),
                       "score": c["score"], "d": c["min_wrist_dist"],
                       "gate": False} for c in kept[:3]],
        })

        # ── QC 目视核对图 ────────────────────────────────
        if a.qc_every and (k % a.qc_every == 0):
            vis = bgr.copy()
            ov = np.zeros_like(bgr)
            ov[:, :, 1] = 255
            vis = np.where(attn[:, :, None] > 0, (0.82 * vis + 0.18 * ov).astype(np.uint8), vis)
            for c in killed:
                cv2.drawMarker(vis, (int(c["cx"]), int(c["cy"])), (60, 60, 255),
                               cv2.MARKER_TILTED_CROSS, 16, 2)
            for c in kept:
                col = (0, 255, 0) if c["pass_wrist_gate"] else (0, 215, 255)
                cv2.circle(vis, (int(c["cx"]), int(c["cy"])), max(12, int(c["diam"])), col, 2)
            if pick:
                cv2.drawMarker(vis, (int(pick["cx"]), int(pick["cy"])),
                               (255, 0, 255), cv2.MARKER_CROSS, 40, 4)
                if pick["holder_box"]:
                    hb = pick["holder_box"]
                    cv2.rectangle(vis, (int(hb[0]), int(hb[1])), (int(hb[2]), int(hb[3])),
                                  (255, 120, 0), 3)
            cv2.putText(vis, f"t={t:.1f}s f{idx+1:05d} {conf}  cand={len(cands)} "
                             f"kept={len(kept)} pass={len(passing)}",
                        (14, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            cv2.putText(vis, "green=gate-pass  yellow=in-attn no-gate  x=off-attn  +pick",
                        (14, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 255, 200), 2)
            cv2.imwrite(os.path.join(a.outdir, f"qc_f{idx+1:05d}.jpg"), vis,
                        [cv2.IMWRITE_JPEG_QUALITY, 82])

        if (k + 1) % 25 == 0 or k == len(rows) - 1:
            el = time.time() - t_start
            print(f"  {k+1}/{len(rows)}  用时 {el:.0f}s  "
                  f"预计 {el/(k+1)*len(rows):.0f}s  conf={conf} kept={len(kept)} "
                  f"pass={len(passing)}", flush=True)

    # 落盘
    if a.pose_cache:
        with open(a.pose_cache, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    p = os.path.join(a.outdir, "ball_track_hybrid.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # ── 时序一致性：**仅诊断，不参与选择** ──────────────────
    picks = [(r["idx"], r["pick"]) for r in out]
    def near(a1, b1, tol=120.0):
        if not a1 or not b1:
            return False
        d = math.hypot(a1["cx"] - b1["cx"], a1["cy"] - b1["cy"])
        return d <= tol and max(a1["diam"], b1["diam"]) <= 1.8 * max(1, min(a1["diam"], b1["diam"]))
    for k, (i, pk) in enumerate(picks):
        sup = sum(1 for j in range(max(0, k - 3), min(len(picks), k + 4))
                  if j != k and near(pk, picks[j][1]))
        out[k]["temporal_support"] = sup
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    from collections import Counter
    cc = Counter(r["conf"] for r in out)
    print(f"\n[out] {p}  {len(out)} 帧")
    print("  置信度分布:", dict(cc))
    for k in ("high", "med", "low", "none"):
        if cc.get(k):
            print(f"    {k}: {cc[k]} ({cc[k]/len(out)*100:.1f}%)")
    ts = Counter(r["temporal_support"] for r in out if r["pick"])
    print("  temporal_support 分布（诊断用，非选择依据）:", dict(sorted(ts.items())))
    print("  ⚠️ 平滑性/连续性**不能**当正确性证据——见模块头 t=247 教训")


if __name__ == "__main__":
    main()
