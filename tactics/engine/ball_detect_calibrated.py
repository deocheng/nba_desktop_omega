#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定版球检测器 —— 用「经目视确认的真球」标定颜色窗口。

═══ 与之前版本的差别（为什么这版不一样）═══════════════════════════
之前 `ball_detect_hybrid.py` 的颜色门限是**猜的**（h_max=13/S≥60/V≥35），
结果 435 帧里 172→31 候选，手腕门禁后仍有 26 个通过 → **全是 med，无区分力**。

本版的门限来自**实测标定**：对两个在 6.3x 下目视确认的真球取样：

    真球 t=205.4 (736,484):  H=18.0°  S=0.54  V=0.47  R−G=48  R−B=64
    真球 t=204.5 (713,552):  H=24.0°  S=0.57  V=0.50  R−G=45  R−B=74
    ────────────────────────────────────────────────────────────────
    红色地板涂装 t=205.0:     H=14.0°  S=0.74  V=0.66  R−G=93  R−B=124   ← 过饱和过亮
    场边黑围挡   t=207.5:     H=356°   S=0.80  V=0.57  R−G=114 R−B=110   ← 色相在红环绕区
    地板反光     t=209.4:     H=206°   S=0.31  V=0.11                   ← 冷色/极暗
    地板反光     t=206.0:     H=30°    S=0.08  V=0.72                   ← 近灰

⇒ 窗口 = H∈[16,26]° ∧ S∈[0.42,0.68] ∧ V∈[0.36,0.62] ∧ R−G∈[30,65] ∧ R−B∈[45,100]
   直径 18–42px（实测真球 20–32px）。

═══════════════════════════════════════════════════════════════════
🔴 效果与代价（必须一起报告，不许只报好的一面）
═══════════════════════════════════════════════════════════════════
  效果：t=205.4 全帧**只有 1 个候选，且就是真球，误差 3.3px**。
  代价：全 435 帧共 130 个候选，**326 帧零候选** → 高精确、低响应。
  精确率：全量 4.2x 普查 ≈ 48%；6.3x 终审子集 35/40 = 87.5%；
          综合最佳估计 **≈44%（95% CI 36–52%）**。
          假阳性**全部**是裸露皮肤（小腿/膝/臂/手）、观众人头、球鞋、地板反光。
          —— 皮肤与球同色系，是本任务里**无法用颜色单独解决**的混淆源。

⚠️ 本脚本不做任何时序平滑、不插值、不用「轨迹连续」补帧。
   理由见 `track_ball_hybrid.py` 模块头（t=247 木地板纹理教训）。
   输出里 `temporal_support` 只是诊断字段。
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

# ── 标定窗口（全部来自实测真球/实测假阳性）─────────────────
CAL = dict(h_lo=16.0, h_hi=26.0, s_lo=107, s_hi=173, v_lo=92, v_hi=158,
           rg_lo=30, rg_hi=65, rb_lo=45, rb_hi=100,
           d_lo=18, d_hi=42, fill_min=0.55)


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def calibrated_candidates(bgr, cal=CAL):
    """标定窗口 + 形状门限。返回 (candidates, mask)。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H = hsv[:, :, 0].astype(int)
    S = hsv[:, :, 1].astype(int)
    V = hsv[:, :, 2].astype(int)
    B = bgr[:, :, 0].astype(int)
    G = bgr[:, :, 1].astype(int)
    R = bgr[:, :, 2].astype(int)
    lo, hi = cal["h_lo"] / 2.0, cal["h_hi"] / 2.0          # 度数 → OpenCV 0–180 刻度
    m = ((H >= lo) & (H <= hi)
         & (S >= cal["s_lo"]) & (S <= cal["s_hi"])
         & (V >= cal["v_lo"]) & (V <= cal["v_hi"])
         & ((R - G) >= cal["rg_lo"]) & ((R - G) <= cal["rg_hi"])
         & ((R - B) >= cal["rb_lo"]) & ((R - B) <= cal["rb_hi"])).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        d = (w + h) / 2.0
        if not (cal["d_lo"] <= d <= cal["d_hi"]):
            continue
        ar = w / max(h, 1)
        if not (0.5 <= ar <= 2.0):
            continue
        fill = area / float(w * h)
        if fill < cal["fill_min"]:
            continue
        mm = (lab == i)
        out.append({
            "cx": float(ce[i][0]), "cy": float(ce[i][1]),
            "w": int(w), "h": int(h), "d": round(d, 1), "fill": round(float(fill), 3),
            "hue_deg": round(float(np.median(H[mm])) * 2.0, 1),
            "sat": round(float(np.median(S[mm])) / 255.0, 3),
            "val": round(float(np.median(V[mm])) / 255.0, 3),
            "rg": int(np.median(R[mm] - G[mm])), "rb": int(np.median(R[mm] - B[mm])),
        })
    return out, m


def pose_frame(model, path, imgsz, conf, wrist_conf, device):
    res = model.predict(path, imgsz=imgsz, conf=conf, device=device, verbose=False)[0]
    boxes, wrists = [], []
    if res.keypoints is not None and len(res.keypoints):
        kp = res.keypoints.xy.cpu().numpy()
        cf = res.keypoints.conf.cpu().numpy()
        bx = res.boxes.xyxy.cpu().numpy()
        bc = res.boxes.conf.cpu().numpy()
        for i in range(len(kp)):
            b = [float(v) for v in bx[i]]
            boxes.append({"box": b, "conf": float(bc[i])})
            for w in (9, 10):
                if cf[i, w] >= wrist_conf:
                    wrists.append({"xy": [float(kp[i, w, 0]), float(kp[i, w, 1])],
                                   "box": b, "conf": float(cf[i, w])})
    return {"boxes": boxes, "wrists": wrists}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-json", required=True)
    ap.add_argument("--pose-weights", default="")
    ap.add_argument("--pose-cache", default="")
    ap.add_argument("--hoop-track", default="")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--truth", default="", help="ball_truth.json 用于精确率评估")
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--pose-conf", type=float, default=0.35)
    ap.add_argument("--wrist-conf", type=float, default=0.30)
    ap.add_argument("--gate", type=float, default=70.0)
    ap.add_argument("--attn-pad", type=int, default=24)
    ap.add_argument("--pad-player", type=int, default=14)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    meta = load_json(a.frames_json)
    rows = [{"idx": r["idx"], "t": r["t"], "path": r["path"]} for r in meta]
    if a.limit:
        rows = rows[:a.limit]

    hoop_reg = {}
    if a.hoop_track:
        for r in load_json(a.hoop_track) or []:
            if r.get("region"):
                hoop_reg[r["idx"]] = r["region"]

    cache = load_json(a.pose_cache, default={}) or {} if a.pose_cache else {}
    model = None
    if a.pose_weights and not all(str(r["idx"]) in cache for r in rows):
        from ultralytics import YOLO
        model = YOLO(a.pose_weights)
        print(f"姿态权重 {a.pose_weights} imgsz={a.imgsz} device={a.device}", flush=True)

    out, t0 = [], time.time()
    for k, r in enumerate(rows):
        bgr = cv2.imread(r["path"])
        if bgr is None:
            continue
        Himg, Wimg = bgr.shape[:2]
        cands, _ = calibrated_candidates(bgr)

        key = str(r["idx"])
        if key in cache:
            pose = cache[key]
        elif model is not None:
            pose = pose_frame(model, r["path"], a.imgsz, a.pose_conf, a.wrist_conf, a.device)
            cache[key] = pose
        else:
            pose = {"boxes": [], "wrists": []}
        pboxes = [b["box"] for b in pose["boxes"]]
        wrists = pose["wrists"]

        court, _ = build_court_mask(bgr)
        court_d = (cv2.dilate(court, np.ones((2 * a.attn_pad + 1,) * 2, np.uint8))
                   if a.attn_pad > 0 else court)
        pmask = np.zeros_like(court)
        for b in pboxes:
            cv2.rectangle(pmask,
                          (max(0, int(b[0]) - a.pad_player), max(0, int(b[1]) - a.pad_player)),
                          (min(Wimg - 1, int(b[2]) + a.pad_player),
                           min(Himg - 1, int(b[3]) + a.pad_player)), 1, -1)
        hmask = np.zeros_like(court)
        hr = hoop_reg.get(r["idx"])
        if hr:
            cv2.rectangle(hmask, (max(0, int(hr[0])), max(0, int(hr[1]))),
                          (min(Wimg - 1, int(hr[2])), min(Himg - 1, int(hr[3]))), 1, -1)
        attn = ((court_d > 0) | (pmask > 0) | (hmask > 0)).astype(np.uint8)

        for c in cands:
            xi = int(max(0, min(Wimg - 1, round(c["cx"]))))
            yi = int(max(0, min(Himg - 1, round(c["cy"]))))
            c["in_court"] = bool(court_d[yi, xi] > 0)
            c["in_player"] = bool(pmask[yi, xi] > 0)
            c["in_hoop"] = bool(hmask[yi, xi] > 0)
            c["in_attn"] = bool(attn[yi, xi] > 0)
            if wrists:
                d, wsel = min(((math.hypot(c["cx"] - w["xy"][0], c["cy"] - w["xy"][1]), w)
                               for w in wrists), key=lambda z: z[0])
            else:
                d, wsel = None, None
            c["min_wrist_dist"] = round(d, 1) if d is not None else None
            c["pass_gate"] = bool(d is not None and d <= a.gate)
            c["holder_box"] = wsel["box"] if wsel else None
            c["n_pose_box"] = len(pboxes)

        kept = [c for c in cands if c["in_attn"]]
        killed = [c for c in cands if not c["in_attn"]]
        kept.sort(key=lambda c: (c["min_wrist_dist"] if c["min_wrist_dist"] is not None else 9e9))

        if len(kept) == 1 and kept[0]["pass_gate"]:
            conf = "high"
        elif len(kept) == 1:
            conf = "single_no_gate"
        elif len(kept) > 1:
            conf = "multi"
        else:
            conf = "none"
        out.append({
            "idx": r["idx"], "t": round(r["t"], 2), "frame": r["idx"] + 1,
            "n_cand": len(cands), "n_kept": len(kept), "n_killed": len(killed),
            "conf": conf, "has_hoop_region": bool(hr),
            "n_pose_box": len(pboxes), "n_wrist": len(wrists),
            "pick": (kept[0] if kept else None),
            "kept": kept[:5], "killed": killed[:5],
        })
        if (k + 1) % 50 == 0:
            el = time.time() - t0
            print(f"  {k+1}/{len(rows)} {el:.0f}s 预计{el/(k+1)*len(rows):.0f}s  "
                  f"cand={len(cands)} kept={len(kept)} conf={conf}", flush=True)

    if a.pose_cache and cache:
        with open(a.pose_cache, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    p = os.path.join(a.outdir, "ball_track_calibrated.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    from collections import Counter
    cc = Counter(r["conf"] for r in out)
    nc = sum(r["n_cand"] for r in out)
    print(f"\n[out] {p}")
    print(f"  帧 {len(out)}  候选合计 {nc}  零候选帧 {sum(1 for r in out if r['n_cand']==0)}")
    print(f"  单候选帧 {cc.get('high',0)+cc.get('single_no_gate',0)}"
          f"（其中过手腕门禁 {cc.get('high',0)}）  多候选帧 {cc.get('multi',0)}")

    # ── 与人工真值比对（精确率）────────────────────────────
    if a.truth:
        T = load_json(a.truth)
        vb = T.get("method", {}).get("verified_balls_6x", {})
        real_ids = set(vb.get("real", []))
        false_ids = set(vb.get("false", []))
        ts = T.get("method", {}).get("targeted_suspicious_6x", {})
        real_ids |= set(ts.get("real", []))
        false_ids |= set(ts.get("false", []))
        # 用 tight_candidates.json 的序号对齐
        tc = load_json(os.path.join(os.path.dirname(a.truth), "tight_candidates.json"))
        hit = miss = fp = 0
        rows_cmp = []
        for i, z in enumerate(tc, 1):
            best = None
            for r in out:
                if r["idx"] != z["idx"]:
                    continue
                for c in (r["kept"] + r["killed"]):
                    if math.hypot(c["cx"] - z["cx"], c["cy"] - z["cy"]) < 6:
                        best = c
                        break
            if best is None:
                continue
            rec = {"n": i, "t": z["t"], "in_attn": best["in_attn"],
                   "pass_gate": best["pass_gate"], "killed_by": None}
            if not best["in_attn"]:
                rec["killed_by"] = "attention"
            if i in real_ids:
                rec["truth"] = "ball"
                if best["in_attn"]:
                    hit += 1
                else:
                    miss += 1
            elif i in false_ids:
                rec["truth"] = "not_ball"
                if best["in_attn"]:
                    fp += 1
            else:
                rec["truth"] = "unjudged"
            rows_cmp.append(rec)
        judged = hit + miss + fp
        print("\n── 与人工真值比对（仅对已目视判定的候选）──")
        print(f"  已判定 {judged} 个：真球 {hit+miss}，非球 {fp}")
        print(f"  注意力门禁后保留的真球 {hit}/{hit+miss}  "
              f"（被注意力误杀 {miss}）；注意力门禁漏放的非球 {fp}")
        if hit + fp:
            print(f"  注意力门禁后的精确率 = {hit}/{hit+fp} = {hit/(hit+fp)*100:.1f}%")
        q = os.path.join(a.outdir, "gate_eval.json")
        with open(q, "w", encoding="utf-8") as f:
            json.dump({"judged": judged, "true_ball": hit + miss, "not_ball": fp,
                       "kept_true": hit, "killed_true": miss, "kept_false": fp,
                       "precision_after_gate": (hit / (hit + fp) if hit + fp else None),
                       "rows": rows_cmp}, f, ensure_ascii=False, indent=1)
        print(f"[out] {q}")


if __name__ == "__main__":
    main()
