#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选审计图 —— 为「球在哪」建立**人工目视真值**。

── 为什么必须做这一步 ────────────────────────────────────────
全帧管线跑下来 435 帧全是 `med`（26 个候选过手腕门禁），**没有区分力**。
在不知道真值的情况下调 gate/hue/score 权重 = 瞎蒙，
而本项目铁律是「未目视核实的结论不许写进报告」。
所以先用分层抽样把真值立起来，再谈召回/精确率。

── 双证据源合并 ──────────────────────────────────────────────
  A) 我们的颜色候选（色相 4–26° + 注意力区）
  B) 已有 YOLO 球检测（`ball_hi.json`，imgsz=1280, conf≥0.06 → 1585 个候选）
YOLO **召回高、精确低**（实测 conf 区分真/假 AUC=0.522，方向都反了）；
颜色+注意力**精确高、召回未知**。两者互补，但要先有真值才能量化。

产出（每帧一张）：
  audit_f{idx:05d}.jpg  —— 左：整帧（全部候选编号打点）；右：Top-8 候选 1.8× 放大剪裁
  audit_index.json      —— 编号 → 全部特征的对照表（供人工判定后回填 truth）
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from court_attention import court_mask as build_court_mask  # noqa: E402


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def color_candidates(bgr, h_lo=4.0, h_hi=26.0, s_min=60, v_min=35,
                     area_min=60, area_max=3000, aspect_max=2.4, fill_min=0.38):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    Ho, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    lo, hi = h_lo / 2.0, h_hi / 2.0
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
        out.append({
            "src": "color",
            "cx": float(cent[i][0]), "cy": float(cent[i][1]),
            "w": int(w), "h": int(h), "area": int(area),
            "fill": round(float(fill), 3),
            "circ": round(float(min(area / (math.pi * ((w + h) / 4.0) ** 2 + 1e-6), 1.0)), 3),
            "hue_deg": round(float(np.median(Ho[m].astype(float))) * 2.0, 1),
            "sat": round(float(np.median(S[m].astype(float))) / 255.0, 3),
            "val": round(float(np.median(V[m].astype(float))) / 255.0, 3),
            "diam": round((w + h) / 2.0, 1), "yolo_conf": None,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--frames-json", required=True)
    ap.add_argument("--yolo-json", default="", help="ball_hi.json（YOLO 球候选）")
    ap.add_argument("--hoop-track", default="")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--times", required=True, help="逗号分隔的抽样时刻")
    ap.add_argument("--topn", type=int, default=8)
    ap.add_argument("--crop", type=int, default=110)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    meta = {r["idx"]: r for r in load_json(a.frames_json)}
    t2i = {round(r["t"], 2): r["idx"] for r in load_json(a.frames_json)}
    hoop_reg = {}
    if a.hoop_track:
        for r in load_json(a.hoop_track) or []:
            if r.get("region"):
                hoop_reg[r["idx"]] = r["region"]
    yolo = {}
    if a.yolo_json:
        y = load_json(a.yolo_json, default={})
        for f in y.get("frames", []):
            yolo[f["idx"]] = f.get("cands", [])

    index = {}
    for tv in [float(x) for x in a.times.split(",")]:
        idx = min(meta.keys(), key=lambda i: abs(meta[i]["t"] - tv))
        path = meta[idx]["path"]
        bgr = cv2.imread(path)
        Himg, Wimg = bgr.shape[:2]

        cands = color_candidates(bgr)

        court, _ = build_court_mask(bgr)
        court_d = cv2.dilate(court, np.ones((49, 49), np.uint8))
        pmask = np.zeros_like(court)
        # 姿态框此处不重跑（慢）：用球场 ∪ 篮筐区即可，审计图看的是候选本身
        hmask = np.zeros_like(court)
        hr = hoop_reg.get(idx)
        if hr:
            cv2.rectangle(hmask, (int(hr[0]), int(hr[1])), (int(hr[2]), int(hr[3])), 1, -1)
        attn = ((court_d > 0) | (pmask > 0) | (hmask > 0)).astype(np.uint8)

        merged = []
        for c in cands:
            xi = int(max(0, min(Wimg - 1, round(c["cx"]))))
            yi = int(max(0, min(Himg - 1, round(c["cy"]))))
            c["in_attn"] = bool(attn[yi, xi] > 0)
            c["in_hoop"] = bool(hmask[yi, xi] > 0)
            merged.append(c)
        # 并入 YOLO 候选（去重：与已有候选中心 <12px 视为同一目标）
        for (x1, y1, x2, y2, cf) in yolo.get(idx, []):
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            dup = None
            for c in merged:
                if math.hypot(c["cx"] - cx, c["cy"] - cy) < 12:
                    dup = c
                    break
            if dup:
                dup["yolo_conf"] = round(float(cf), 3)
                dup["src"] = "both"
                continue
            xi = int(max(0, min(Wimg - 1, round(cx))))
            yi = int(max(0, min(Himg - 1, round(cy))))
            merged.append({
                "src": "yolo", "cx": float(cx), "cy": float(cy),
                "w": int(x2 - x1), "h": int(y2 - y1),
                "area": int((x2 - x1) * (y2 - y1)),
                "fill": round(float(cf), 3), "circ": None,
                "hue_deg": None, "sat": None, "val": None,
                "diam": round(((x2 - x1) + (y2 - y1)) / 2.0, 1),
                "yolo_conf": round(float(cf), 3),
                "in_attn": bool(attn[yi, xi] > 0), "in_hoop": bool(hmask[yi, xi] > 0),
            })

        # 排序：注意力区内优先 → YOLO 置信 + 色相贴合 + 圆度
        def rk(c):
            ina = 1.0 if c["in_attn"] else 0.0
            yc = c["yolo_conf"] or 0.0
            hm = 1.0 - min(abs((c["hue_deg"] or 17.2) - 17.2) / 22.0, 1.0)
            ci = c["circ"] or 0.3
            return ina * 2.0 + yc * 1.4 + hm * 0.6 + ci * 0.4
        merged.sort(key=lambda c: -rk(c))
        top = merged[:a.topn]

        for k, c in enumerate(top, 1):
            c["rank"] = k

        # ── 画图 ────────────────────────────────────────────
        sc = 940.0 / Wimg
        vis = cv2.resize(bgr, (940, int(Himg * sc)))
        for c in merged:
            px, py = int(c["cx"] * sc), int(c["cy"] * sc)
            big = c in top
            col = (0, 255, 255) if c["src"] == "color" else (
                (255, 0, 255) if c["src"] == "yolo" else (0, 255, 0))
            if c["in_attn"]:
                col = (col[0], col[1], 255)
            r = 13 if big else 5
            cv2.circle(vis, (px, py), r, col, 2)
            if big:
                cv2.putText(vis, str(c["rank"]), (px + 12, py - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)

        # 右侧 Top-N 放大剪裁
        C = a.crop
        cell = 235
        cols = 2
        rows_n = (a.topn + cols - 1) // cols
        grid = np.zeros((rows_n * (cell + 26), cols * cell, 3), np.uint8)
        for k, c in enumerate(top):
            cx, cy = int(round(c["cx"])), int(round(c["cy"]))
            x0 = int(max(0, min(Wimg - C, cx - C // 2)))
            y0 = int(max(0, min(Himg - C, cy - C // 2)))
            patch = bgr[y0:y0 + C, x0:x0 + C].copy()
            if patch.size == 0:
                continue
            patch = cv2.resize(patch, (cell, cell), interpolation=cv2.INTER_NEAREST)
            # 目标点在剪裁内的位置
            mx, my = int((c["cx"] - x0) * cell / C), int((c["cy"] - y0) * cell / C)
            cv2.drawMarker(patch, (mx, my), (255, 0, 255), cv2.MARKER_CROSS, 30, 2)
            r_, cn_ = k // cols, k % cols
            lab = np.zeros((26, cell, 3), np.uint8)
            txt = (f"#{c['rank']} {c['src']} y={c['yolo_conf'] if c['yolo_conf'] else '-'} "
                   f"h={c['hue_deg'] if c['hue_deg'] else '-'}")
            cv2.putText(lab, txt, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1, cv2.LINE_AA)
            grid[r_ * (cell + 26):r_ * (cell + 26) + 26, cn_ * cell:(cn_ + 1) * cell] = lab
            grid[r_ * (cell + 26) + 26:r_ * (cell + 26) + 26 + cell,
                 cn_ * cell:(cn_ + 1) * cell] = patch

        hh = max(vis.shape[0], grid.shape[0])
        if vis.shape[0] < hh:
            vis = np.vstack([vis, np.zeros((hh - vis.shape[0], 940, 3), np.uint8)])
        if grid.shape[0] < hh:
            grid = np.vstack([grid, np.zeros((hh - grid.shape[0], grid.shape[1], 3), np.uint8)])
        canvas = np.hstack([vis, grid])
        bar = np.zeros((44, canvas.shape[1], 3), np.uint8)
        cv2.putText(bar, f"t={meta[idx]['t']:.1f}s  frame f{idx+1:05d}   "
                         f"color-cand={len(cands)} yolo-cand={len(yolo.get(idx,[]))} "
                         f"merged={len(merged)}  in-attn={sum(1 for c in merged if c['in_attn'])}",
                    (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (255, 255, 255), 2, cv2.LINE_AA)
        canvas = np.vstack([bar, canvas])
        outp = os.path.join(a.outdir, f"audit_f{idx+1:05d}.jpg")
        cv2.imwrite(outp, canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])

        index[str(idx)] = {
            "t": meta[idx]["t"], "frame": idx + 1, "img": outp,
            "n_color": len(cands), "n_yolo": len(yolo.get(idx, [])), "n_merged": len(merged),
            "top": [{k2: v2 for k2, v2 in c.items() if v2 is not None} for c in top],
        }
        print("=" * 92)
        print(f"t={meta[idx]['t']:.1f}s f{idx+1:05d}  颜色候选 {len(cands)}   "
              f"YOLO 候选 {len(yolo.get(idx,[]))}   合并 {len(merged)}   "
              f"注意力内 {sum(1 for c in merged if c['in_attn'])}")
        print(f"  {'#':>2} {'src':<6}{'中心':<15}{'直径':>5}{'yolo':>6}{'色相':>7}"
              f"{'S':>6}{'V':>6}{'圆度':>6}{'填充':>6}{'注意':>5}")
        for c in top:
            print(f"  {c['rank']:>2} {c['src']:<6}"
                  f"({c['cx']:6.0f},{c['cy']:5.0f}){c['diam']:>6.0f}"
                  f"{(c['yolo_conf'] if c['yolo_conf'] is not None else -1):>6.3f}"
                  f"{(c['hue_deg'] if c['hue_deg'] is not None else -1):>7.1f}"
                  f"{(c['sat'] if c['sat'] is not None else -1):>6.2f}"
                  f"{(c['val'] if c['val'] is not None else -1):>6.2f}"
                  f"{(c['circ'] if c['circ'] is not None else -1):>6.2f}"
                  f"{c['fill']:>6.2f}{'Y' if c['in_attn'] else '.':>5}")

    p = os.path.join(a.outdir, "audit_index.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"\n[out] {p}")


if __name__ == "__main__":
    main()
