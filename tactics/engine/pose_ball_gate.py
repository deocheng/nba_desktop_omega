#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双模型协同验证：姿态模型的手腕先验，能否把假球从球候选里筛掉？

── 背景（2026-09-23 用户指出 + 实测）─────────────────────────────
`pos_t02195.jpg` 里红圈标出的"球"其实在地板上（木地板上的橙色印记），
而**真球在 30 号（CHAMPAGNE / pid32）手里**，约在原图 (1236, 349)。
→ 球检测器把地板印记当球，持球人因此被错误归属给 pid19。

用户指令：**球的追踪应该把颜色作为第一识别条件**。
实测：颜色判据只能救回一部分 ——
  · 真球在阴影里，暗且不饱和（球区 H≈4–18°, S≈0.32–0.56, V≈0.39–0.54）
  · 木地板色相 H≈32–38°（确实能靠色相分开）
  · **但观众席有大量红色衣物**，纯色相掩膜会捞出 62 个候选、全是观众
  ⇒ 颜色不足以单独定位球，需要第二个模型给**空间先验**。

── 本层的协同机制 ──────────────────────────────────────────────
姿态模型（yolo11n-pose，COCO 17 关键点）给出**手腕位置**。
物理约束：**球在持球/运球时必然贴近某只手**；而地板印记、LED 广告板上的
赞助商 logo、观众席都不在任何人的手边。于是：

    ball_score = 1 / (1 + min_wrist_dist / ref)
    若 min_wrist_dist > gate → 判为静态/离体目标，剔除

这是**双向辅助**：
  · 姿态 → 球：给空间先验，剔除离体假目标
  · 球 → 姿态：球的位置反过来锁定持球人（比"离脚点最近"可靠得多）

── 自验 ────────────────────────────────────────────────────────
用已知群体做对照：真球帧 vs 地板误检帧 vs Mastercard logo 帧，
输出各自"到手最近距离"的分布与分离度。
"""
import argparse
import json
import math
import os
import statistics
import sys

import numpy as np

WRIST_L, WRIST_R = 9, 10          # COCO 关键点索引


def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ball-verify", required=True)
    ap.add_argument("--frames-dir", required=True, help="10fps 帧目录（seg_hi）")
    ap.add_argument("--pose-weights", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--wrist-conf", type=float, default=0.30)
    ap.add_argument("--gate", type=float, default=90.0,
                    help="到手距离门限（原图像素），超过判为离体目标")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--t0", type=float, default=204.5)
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 帧（调试）")
    a = ap.parse_args()

    from ultralytics import YOLO

    bv = load(a.ball_verify)
    dets = [r for r in bv["rows"] if not r.get("pred") and r.get("box")]
    # 按时间分组到 10fps 帧
    by_frame = {}
    for r in dets:
        fi = int(round((r["t"] - a.t0) * a.fps)) + 1
        by_frame.setdefault(fi, []).append(r)
    frames = sorted(by_frame)
    if a.limit:
        frames = frames[:a.limit]

    model = YOLO(a.pose_weights)
    os.makedirs(a.outdir, exist_ok=True)

    out_rows = []
    n_wrist_total = 0
    t_pose = 0.0
    import time
    for k, fi in enumerate(frames):
        p = os.path.join(a.frames_dir, f"f{fi:05d}.jpg")
        if not os.path.exists(p):
            continue
        st = time.time()
        res = model.predict(p, imgsz=a.imgsz, conf=a.conf,
                            device=a.device, verbose=False)[0]
        t_pose += time.time() - st
        if res.keypoints is None or len(res.keypoints) == 0:
            wrists = []
        else:
            kp = res.keypoints.xy.cpu().numpy()
            cf = res.keypoints.conf.cpu().numpy()
            bx = res.boxes.xyxy.cpu().numpy()
            wrists = []
            for i in range(len(kp)):
                for w in (WRIST_L, WRIST_R):
                    if cf[i, w] >= a.wrist_conf:
                        wrists.append({
                            "person_idx": int(i),
                            "side": "L" if w == WRIST_L else "R",
                            "xy": [float(kp[i, w, 0]), float(kp[i, w, 1])],
                            "conf": float(cf[i, w]),
                            "person_box": [float(v) for v in bx[i]],
                        })
            n_wrist_total += len(wrists)
        for r in by_frame[fi]:
            cx = (r["box"][0] + r["box"][2]) / 2
            cy = (r["box"][1] + r["box"][3]) / 2
            if wrists:
                d, wsel = min(
                    ((math.hypot(cx - w["xy"][0], cy - w["xy"][1]), w) for w in wrists),
                    key=lambda x: x[0])
            else:
                d, wsel = None, None
            keep = (d is not None and d <= a.gate)
            out_rows.append({
                "t": r["t"], "frame": fi,
                "box": r["box"], "center": [round(cx, 1), round(cy, 1)],
                "verdict_color": r.get("verdict"),
                "orange_score": r.get("orange_score"),
                "conf": r.get("conf"),
                "min_wrist_dist": round(d, 1) if d is not None else None,
                "nearest_wrist": wsel,
                "pass_pose_gate": bool(keep),
                "n_wrists": len(wrists),
            })
        if (k + 1) % 40 == 0:
            print(f"  ... {k+1}/{len(frames)} 帧", file=sys.stderr)

    n = len(out_rows)
    kept = [r for r in out_rows if r["pass_pose_gate"]]
    ds = [r["min_wrist_dist"] for r in out_rows if r["min_wrist_dist"] is not None]

    # 已知对照组
    # logo_known：由橙反差 Top-16 目视确认的 Mastercard logo 时刻
    LOGO_T = {206.2, 206.7, 207.2, 208.2, 209.2, 224.7, 225.2, 225.7,
              226.7, 227.2, 227.7, 228.2, 228.6, 228.7}
    REAL_T = {210.0, 247.4}          # 定向核对确认的真球命中
    GC = {"real": [], "logo_known": [], "upper_band": [], "floorish": []}
    for r in out_rows:
        t = round(r["t"], 1)
        if t in REAL_T:
            GC["real"].append(r)
        elif t in LOGO_T:
            GC["logo_known"].append(r)
        elif 240 <= r["box"][1] <= 380 and r["box"][3] <= 400:
            GC["upper_band"].append(r)
        else:
            GC["floorish"].append(r)

    os.makedirs(a.outdir, exist_ok=True)
    summary = {
        "meta": {
            "imgsz": a.imgsz, "device": a.device, "wrist_conf": a.wrist_conf,
            "gate_px": a.gate, "frames_processed": len(frames),
            "pose_total_sec": round(t_pose, 1),
            "pose_ms_per_frame": round(t_pose / max(len(frames), 1) * 1000, 1),
            "n_detections": n, "n_pass_pose_gate": len(kept),
            "pass_rate_pct": round(len(kept) / n * 100, 1) if n else 0,
            "n_wrists_total": n_wrist_total,
            "note": ("物理约束：球在持球/运球时必然贴近某只手。"
                     "地板印记、LED 广告板 logo、观众席都不在任何人的手边。"),
        },
        "groups": {},
        "rows": out_rows,
    }
    for g, rs in GC.items():
        dd = [r["min_wrist_dist"] for r in rs if r["min_wrist_dist"] is not None]
        pk = sum(1 for r in rs if r["pass_pose_gate"])
        summary["groups"][g] = {
            "n": len(rs),
            "n_with_wrist": len(dd),
            "dist_median": round(statistics.median(dd), 1) if dd else None,
            "dist_min": round(min(dd), 1) if dd else None,
            "dist_max": round(max(dd), 1) if dd else None,
            "n_pass_gate": pk,
            "pass_pct": round(pk / len(rs) * 100, 1) if rs else 0,
        }

    p = os.path.join(a.outdir, "pose_ball_gate.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    print("=" * 66)
    print("姿态 × 球：手腕先验门禁（双模型协同验证）")
    print("=" * 66)
    print(f"  处理 {len(frames)} 帧 | 姿态推理 {summary['meta']['pose_ms_per_frame']}ms/帧"
          f" (imgsz={a.imgsz}, device={a.device})")
    print(f"  球检出 {n} 个 | 通过手腕门禁 {len(kept)} 个 ({summary['meta']['pass_rate_pct']}%)")
    if ds:
        print(f"  到手距离分布: 中位 {statistics.median(ds):.1f}px"
              f"  p25 {sorted(ds)[len(ds)//4]:.1f}  p75 {sorted(ds)[3*len(ds)//4]:.1f}"
              f"  max {max(ds):.1f}")
    print()
    print("  分组对照：")
    print(f"    {'组':<12}{'n':>5}{'到手中位':>10}{'最小':>8}{'最大':>8}{'过门禁':>9}{'比例':>8}")
    for g in ("real", "logo_known", "upper_band", "floorish"):
        s = summary["groups"][g]
        md = f"{s['dist_median']}" if s["dist_median"] is not None else "NA"
        mn = f"{s['dist_min']}" if s["dist_min"] is not None else "NA"
        mx = f"{s['dist_max']}" if s["dist_max"] is not None else "NA"
        print(f"    {g:<12}{s['n']:>5}{md:>10}{mn:>8}{mx:>8}{s['n_pass_gate']:>9}{s['pass_pct']:>7.1f}%")
    print()
    rm = summary["groups"]["real"]["dist_median"]
    lm = summary["groups"]["logo_known"]["dist_median"]
    fm = summary["groups"]["floorish"]["dist_median"]
    if rm and lm and fm:
        print(f"  🔎 分离度：真球 {rm}px  vs  Mastercard logo {lm}px ({lm/rm:.1f}×)"
              f"  vs  地板类 {fm}px ({fm/rm:.1f}×)")
        ok = lm > rm * 2 and fm > rm * 2
        print(f"  → {'✅ 可分离' if ok else '❌ 分离不足'}")
    print(f"\n[out] {p}")


if __name__ == "__main__":
    main()
