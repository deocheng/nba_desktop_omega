#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""混合球检测：颜色（第一判据）× 姿态手腕（空间先验）—— 双模型协同。

── 为什么单靠颜色不行（实测）──────────────────────────────────
用户指令：球追踪应把**颜色**作为第一识别条件。实测支持色相判别：
  · 真球区  H ≈ 4–18°（红橙），S ≈ 0.32–0.56，V ≈ 0.39–0.54（**暗、不饱和**，在阴影里）
  · 木地板  H ≈ 32–38°（橙黄/木色）→ **能靠色相分开**
但**纯色相掩膜捞出 62 个候选，全是观众席红色衣物** —— 颜色不足以单独定位球。

── 为什么单靠姿态也不行 ──────────────────────────────────────
手腕先验（球必须贴近某只手）在 333 个 YOLO 检出上实测：
  真球到手中位 60.8px vs logo 145.2px(2.4×) vs 地板类 166.9px(2.7×)
能砍掉 ~85% 假目标，**但管不了「飞行/散球」**（球不在手边）。

── 本层：三者串联 ────────────────────────────────────────────
    候选  = 颜色掩膜（色相 ∈ 球色域）+ 形状（圆、尺寸合理）
    判据0 = **落在注意力区内**（球场 ∪ 球员框）  → 去观众席（用户指令）
    判据1 = 到最近手腕距离 ≤ gate                → 「被持/运」球
    判据2 = 位于注意力区内且离篮筐不远           → 「飞行/散」球
    打分  = 颜色贴合度 × 手部贴近度 × 形状圆度
再叠加**时序**（球在相邻帧位移连续）做最终锁定。

**判据0 为什么是必要的**：纯色相掩膜在实拍帧上捞出 62 个候选，**全部是
观众席红色衣物**（y≈900–1050）。颜色的污染源不是木地板，是观众席。
注意力掩膜（`court_attention.court_mask`）把球场 + 球员框并起来后，
这些候选全部落在区外，可被一刀切掉。

本脚本在用户指出的 t=219.5 上验证：
当前 YOLO 报 (1016,669)（地板橙色印记、错），真球在 (1236,349)（#30 手里）。
混合法应命中真球，并把持球人从 pid19 修正为 pid32。
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from court_attention import court_mask as build_court_mask  # noqa: E402


def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def color_candidates(bgr, h_max=13, s_min=60, v_min=35,
                     area_min=110, area_max=3000,
                     aspect_max=2.4, fill_min=0.40):
    """颜色 + 形状候选。h_max 是 OpenCV 色相刻度（13 ≈ 26°）。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (((H <= h_max) | (H >= 180 - h_max)) & (S >= s_min) & (V >= v_min))
    mask = mask.astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            np.ones((3, 3), np.uint8))
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
        cx, cy = cent[i]
        # 颜色贴合度：取该 blob 像素的色相/饱和度均值
        m = (lab == i)
        hs, ss = H[m].astype(float), S[m].astype(float)
        out.append({
            "cx": float(cx), "cy": float(cy), "w": int(w), "h": int(h),
            "area": int(area), "fill": round(float(fill), 3),
            "hue_deg": round(float(np.median(hs)) * 2, 1),
            "sat": round(float(np.median(ss)) / 255, 3),
            "diam": round((w + h) / 2.0, 1),
        })
    return out, mask


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--pose-weights", required=True)
    ap.add_argument("--times", required=True, help="逗号分隔，如 219.5,210.0")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--t0", type=float, default=204.5)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--gate", type=float, default=90.0)
    ap.add_argument("--wrist-conf", type=float, default=0.30)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--expect-xy", default="",
                    help="期望真球位置。两种写法：'1236,349'（全时刻通用）"
                         "或 '219.5:1236,349;210.0:900,300'（逐时刻）")
    ap.add_argument("--no-attn", action="store_true",
                    help="关闭球场注意力门禁（对照用）")
    ap.add_argument("--attn-pad", type=int, default=24,
                    help="球场掩膜外扩像素（容忍球员/球贴边）")
    ap.add_argument("--pad-player", type=int, default=14,
                    help="姿态球员框外扩像素")
    a = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(a.pose_weights)
    os.makedirs(a.outdir, exist_ok=True)

    tlist = [float(x) for x in a.times.split(",")]
    expect = None
    if a.expect_xy:
        xs = [float(v) for v in a.expect_xy.split(",")]
        expect = (xs[0], xs[1])

    report = []
    for t in tlist:
        fi = int(round((t - a.t0) * a.fps)) + 1
        p = os.path.join(a.frames_dir, f"f{fi:05d}.jpg")
        if not os.path.exists(p):
            print(f"  缺帧 {p}")
            continue
        bgr = cv2.imread(p)
        H, W = bgr.shape[:2]
        cands, cmask_color = color_candidates(bgr)

        # ── 姿态（先跑，球员框要并入注意力区）────────────────────
        res = model.predict(p, imgsz=a.imgsz, conf=0.35,
                            device=a.device, verbose=False)[0]
        wrists, pboxes = [], []
        if res.keypoints is not None and len(res.keypoints):
            kp = res.keypoints.xy.cpu().numpy()
            cf = res.keypoints.conf.cpu().numpy()
            bx = res.boxes.xyxy.cpu().numpy()
            for i in range(len(kp)):
                pboxes.append([float(v) for v in bx[i]])
                for w in (9, 10):
                    if cf[i, w] >= a.wrist_conf:
                        wrists.append({"xy": (float(kp[i, w, 0]), float(kp[i, w, 1])),
                                       "box": pboxes[-1],
                                       "conf": float(cf[i, w])})

        # ── 注意力区 = 球场 ∪ 球员框（用户指令：去掉观众席）────────
        court, poly = build_court_mask(bgr)
        if a.attn_pad > 0:
            k = 2 * a.attn_pad + 1
            court_d = cv2.dilate(court, np.ones((k, k), np.uint8))
        else:
            court_d = court
        pmask = np.zeros_like(court)
        pd = a.pad_player
        for b in pboxes:
            x1, y1, x2, y2 = [int(v) for v in b]
            cv2.rectangle(pmask, (max(0, x1 - pd), max(0, y1 - pd)),
                          (min(W - 1, x2 + pd), min(H - 1, y2 + pd)), 1, -1)
        attn = ((court_d > 0) | (pmask > 0)).astype(np.uint8)

        # ── 逐候选打标 ─────────────────────────────────────────
        for c in cands:
            xi = max(0, min(W - 1, int(round(c["cx"]))))
            yi = max(0, min(H - 1, int(round(c["cy"]))))
            c["in_court"] = bool(court_d[yi, xi] > 0)
            c["in_player"] = bool(pmask[yi, xi] > 0)
            c["in_attn"] = bool(attn[yi, xi] > 0)
            if wrists:
                d, wsel = min(((math.hypot(c["cx"] - w["xy"][0], c["cy"] - w["xy"][1]), w)
                               for w in wrists), key=lambda x: x[0])
            else:
                d, wsel = None, None
            c["min_wrist_dist"] = round(d, 1) if d is not None else None
            c["pass_wrist_gate"] = bool(d is not None and d <= a.gate)
            c["nearest_wrist"] = (list(wsel["xy"]) if wsel else None)
            c["holder_box"] = (wsel["box"] if wsel else None)
            hand = 1.0 / (1.0 + (d if d is not None else 999) / 60.0)
            hue_mid = 1.0 - min(abs(c["hue_deg"] - 12.0) / 25.0, 1.0)
            c["score"] = round(hand * 0.6 + c["fill"] * 0.2 + hue_mid * 0.2, 4)

        killed = [c for c in cands if not c["in_attn"]]
        kept = [c for c in cands if c["in_attn"]]
        if a.no_attn:                       # 对照：不做注意力门禁
            kept, killed = list(cands), []
        kept.sort(key=lambda c: -c["score"])
        killed.sort(key=lambda c: -c["score"])
        passing = [c for c in kept if c["pass_wrist_gate"]]
        cut_pct = 100.0 * len(killed) / max(1, len(cands)) if not a.no_attn else 0.0

        print("=" * 78)
        print(f"t={t}s  (frame f{fi:05d})  球场覆盖 {court.mean()*100:.1f}%"
              f"  注意力覆盖 {attn.mean()*100:.1f}%  姿态人框 {len(pboxes)}")
        print("=" * 78)
        print(f"  颜色+形状候选 {len(cands)}  →  注意力剔除 {len(killed)} ({cut_pct:.1f}%)"
              f"  保留 {len(kept)}  →  通过手腕门禁(≤{a.gate}px) {len(passing)}")
        hdr = (f"  {'':2}{'中心':<13}{'直径':>6}{'色相':>7}{'圆度':>6}{'到手':>7}"
               f"{'球内':>5}{'人内':>5}{'保留':>5}{'通过':>5}{'打分':>8}")
        print(hdr)
        for c in kept[:10]:
            d = c["min_wrist_dist"]
            print(f"  {'★' if c['pass_wrist_gate'] else ' ':<2}"
                  f"({c['cx']:5.0f},{c['cy']:4.0f}){c['diam']:>6.0f}"
                  f"{c['hue_deg']:>7.1f}{c['fill']:>6.2f}"
                  f"{(f'{d:.0f}' if d is not None else 'NA'):>7}"
                  f"{('Y' if c['in_court'] else '.'):>5}"
                  f"{('Y' if c['in_player'] else '.'):>5}"
                  f"{'Y':>5}{('Y' if c['pass_wrist_gate'] else '.'):>5}{c['score']:>8.3f}")
        if killed:
            print("  ── 被注意力剔除的前 6 个（观众席/场外）──")
            for c in killed[:6]:
                print(f"    ({c['cx']:5.0f},{c['cy']:4.0f})  直径{c['diam']:>4.0f}"
                      f"  色相{c['hue_deg']:>5.1f}  打分{c['score']:.3f}")

        best, de = None, None
        if expect:
            best = passing[0] if passing else (kept[0] if kept else None)
            if best:
                de = math.hypot(best["cx"] - expect[0], best["cy"] - expect[1])
                print(f"\n  🎯 期望真球 ({expect[0]:.0f},{expect[1]:.0f})"
                      f"  →  混合法首选 ({best['cx']:.0f},{best['cy']:.0f})"
                      f"  误差 {de:.1f}px  {'✅ 命中' if de < 40 else '❌ 偏了'}")
                if best["holder_box"]:
                    hb = best["holder_box"]
                    print(f"     推定持球人框 [{hb[0]:.0f},{hb[1]:.0f},{hb[2]:.0f},{hb[3]:.0f}]")

        # ── 目视核对图 ─────────────────────────────────────────
        vis = bgr.copy()
        ov = np.zeros_like(bgr)
        ov[:, :, 1] = 255
        vis = np.where(attn[:, :, None] > 0,
                       (0.80 * vis + 0.20 * ov).astype(np.uint8), vis)
        cv2.polylines(vis, [poly.reshape(-1, 1, 2)], True, (0, 255, 255), 2)
        for c in killed:
            cv2.drawMarker(vis, (int(c["cx"]), int(c["cy"])), (60, 60, 255),
                           cv2.MARKER_TILTED_CROSS, 16, 2)
        for c in kept:
            col = (0, 255, 0) if c["pass_wrist_gate"] else (0, 215, 255)
            r = max(12, int(c["diam"]))
            cv2.circle(vis, (int(c["cx"]), int(c["cy"])), r, col, 3 if c["pass_wrist_gate"] else 1)
        if best:
            bx_, by_ = int(best["cx"]), int(best["cy"])
            cv2.drawMarker(vis, (bx_, by_), (255, 0, 255), cv2.MARKER_CROSS, 34, 3)
            if best["holder_box"]:
                hb = best["holder_box"]
                cv2.rectangle(vis, (int(hb[0]), int(hb[1])), (int(hb[2]), int(hb[3])),
                              (255, 120, 0), 3)
                cv2.putText(vis, "HOLDER", (int(hb[0]), max(20, int(hb[1]) - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 120, 0), 2)
        if expect:
            cv2.drawMarker(vis, (int(expect[0]), int(expect[1])), (255, 255, 255),
                           cv2.MARKER_STAR, 26, 2)
        cv2.putText(vis, f"t={t}s  cand={len(cands)} kept={len(kept)} "
                         f"killed={len(killed)} ({cut_pct:.0f}%)  gate_pass={len(passing)}",
                    (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.66, (255, 255, 255), 2)
        cv2.putText(vis, "o keep  x killed(off-court)  O gate-pass  + pick  * truth",
                    (12, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 255, 200), 2)
        outp = os.path.join(a.outdir, f"hyb_t{int(t*10):05d}.jpg")
        cv2.imwrite(outp, vis, [cv2.IMWRITE_JPEG_QUALITY, 88])

        report.append({"t": t, "n_candidates": len(cands),
                       "n_killed_attn": len(killed), "n_kept": len(kept),
                       "attn_cut_pct": round(cut_pct, 2),
                       "court_coverage": round(float(court.mean()), 4),
                       "attn_coverage": round(float(attn.mean()), 4),
                       "n_pose_boxes": len(pboxes),
                       "n_pass_gate": len(passing),
                       "pick": ({"cx": best["cx"], "cy": best["cy"],
                                 "in_court": best["in_court"],
                                 "min_wrist_dist": best["min_wrist_dist"],
                                 "holder_box": best["holder_box"],
                                 "score": best["score"]} if best else None),
                       "err_px": (round(de, 1) if de is not None else None),
                       "kept": kept[:10], "killed": killed[:10],
                       "vis": outp})

    out = os.path.join(a.outdir, "hybrid_ball.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n[out] {out}")
    for r in report:
        print(f"  t={r['t']:>6.1f}  候选 {r['n_candidates']:>3}  注意力剔除 "
              f"{r['n_killed_attn']:>3} ({r['attn_cut_pct']:>5.1f}%)  保留 {r['n_kept']:>3}"
              f"  过门禁 {r['n_pass_gate']:>2}  误差 "
              f"{r['err_px'] if r['err_px'] is not None else 'NA'}")


if __name__ == "__main__":
    main()
