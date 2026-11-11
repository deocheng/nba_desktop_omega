#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球检出复核：用颜色/形状判据客观量化"检测框里到底是不是篮球"。

── 为什么需要 ──────────────────────────────────────────────────
目视 22 个抽样的球检出，绝大多数其实是**球场地板上的白色虚线标记**、
观众席、计分屏。检测器的 `conf` 与"是不是球"没有单调关系
（conf 0.44 的可能是一只红球鞋，conf 0.09 的可能是真球）。

靠人眼逐帧看不可扩展，必须换成**客观判据**：

  判据 ① 橙色度（篮球是橙色）
      r, g, b 为框内均值。篮球：R 明显高于 B，G 居中。
      orange_score = (R - B) / 255        —— 越大越像橙
      要求 R > G > B 且 R - B >= 阈值

  判据 ② 尺寸合理性
      1080p 画面里篮球直径约 15–40px（近景 60px 也算）。
      过大的框（> 0.06 * H）必非球；极小的框（< 8px）是噪声。

  判据 ③ 长宽比
      球是圆的，|w - h| / max(w,h) 应很小。
      地板虚线标记是细长的，这项能直接打掉。

输出逐检出的判据值 + 通过率，供下游做球位质量门禁。
"""
import argparse
import json
import os
import statistics
from collections import Counter

from PIL import Image


def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def box_stats(im, box):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    W, H = im.size
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(W, x2), min(H, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    c = im.crop((x1, y1, x2, y2))
    px = list(c.getdata())
    n = len(px)
    r = sum(p[0] for p in px) / n
    g = sum(p[1] for p in px) / n
    b = sum(p[2] for p in px) / n
    return {"r": round(r, 1), "g": round(g, 1), "b": round(b, 1),
            "w": x2 - x1, "h": y2 - y1}


def verdict(s, img_h, min_d, max_frac, orange_thr, round_thr):
    if s is None:
        return "empty", {}
    orange = (s["r"] - s["b"]) / 255.0
    R, G, B = s["r"], s["g"], s["b"]
    ordered = R > G > B
    w, h = s["w"], s["h"]
    d = (w + h) / 2.0
    roundness = abs(w - h) / max(w, h, 1)
    reasons = {}
    reasons["orange"] = orange >= orange_thr and ordered
    reasons["size"] = (min_d <= d <= max_frac * img_h)
    reasons["round"] = roundness <= round_thr
    ok = all(reasons.values())
    return ("ball_like" if ok else "not_ball"), {
        "orange_score": round(orange, 3), "rgb_ordered": ordered,
        "diam_px": round(d, 1), "roundness_dev": round(roundness, 3),
        **reasons}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ball-hi", required=True)
    ap.add_argument("--frames-dir", required=True, help="2fps 帧目录（用于取像素）")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--orange-thr", type=float, default=0.18)
    ap.add_argument("--round-thr", type=float, default=0.45)
    ap.add_argument("--min-diam", type=float, default=8.0)
    ap.add_argument("--max-frac-h", type=float, default=0.06)
    a = ap.parse_args()

    d = load(a.ball_hi)
    img_h = d["meta"]["img_size"][1]
    ball = d["ball_track"]
    os.makedirs(a.outdir, exist_ok=True)

    # 用 2fps 帧做像素取样（10fps 帧没落盘，但颜色判据不需要 10fps 精度）
    cache = {}
    rows = []
    for b in ball:
        if b.get("pred") or not b.get("center"):
            rows.append({"t": b["t"], "pred": True, "verdict": "extrapolated"})
            continue
        fi = int(round((b["t"] - 204.5) / 0.5)) + 1
        p = os.path.join(a.frames_dir, f"f{fi:05d}.jpg")
        if not os.path.exists(p):
            rows.append({"t": b["t"], "verdict": "no_frame"})
            continue
        if p not in cache:
            cache[p] = Image.open(p).convert("RGB")
        im = cache[p]
        # 10fps 与 2fps 分辨率一致（均 1920x1080）
        st = box_stats(im, b["box"])
        v, info = verdict(st, img_h, a.min_diam, a.max_frac_h,
                          a.orange_thr, a.round_thr)
        rows.append({"t": b["t"], "pred": False, "conf": b.get("conf"),
                     "box": b["box"], "verdict": v, **info})

    det = [r for r in rows if not r.get("pred") and r.get("verdict") not in
           ("no_frame", "extrapolated")]
    vc = Counter(r["verdict"] for r in det)
    n_ball = vc.get("ball_like", 0)
    n_all = len(det)

    # 逐理由失败统计
    fr = Counter()
    for r in det:
        if r["verdict"] == "not_ball":
            for k in ("orange", "size", "round"):
                if not r.get(k, False):
                    fr[k] += 1

    # conf 与真伪的关系（检验 conf 是否可作判据）
    cl = [r["conf"] for r in det if r["verdict"] == "ball_like"]
    cn = [r["conf"] for r in det if r["verdict"] == "not_ball"]
    confstat = {
        "ball_like_mean_conf": round(statistics.mean(cl), 3) if cl else None,
        "ball_like_median_conf": round(statistics.median(cl), 3) if cl else None,
        "not_ball_mean_conf": round(statistics.mean(cn), 3) if cn else None,
        "not_ball_median_conf": round(statistics.median(cn), 3) if cn else None,
    }

    # 若 conf 是判据，按 conf 排序后真球应集中在一端 → 用 AUC 近似度量
    pairs = [(r["conf"], 1 if r["verdict"] == "ball_like" else 0) for r in det]
    pairs_sorted = sorted(pairs)
    pos = sum(y for _, y in pairs_sorted)
    neg = len(pairs_sorted) - pos
    auc = None
    if pos and neg:
        rank = 0
        seen_neg = 0
        for _, y in pairs_sorted:
            if y == 1:
                rank += seen_neg
            else:
                seen_neg += 1
        auc = round(rank / (pos * neg), 3)   # AUC=0.5 → conf 无区分力

    out = {
        "meta": {
            "orange_thr": a.orange_thr, "round_thr": a.round_thr,
            "min_diam_px": a.min_diam, "max_frac_h": a.max_frac_h,
            "n_detections": n_all, "n_ball_like": n_ball,
            "ball_like_pct": round(n_ball / n_all * 100, 1) if n_all else 0,
            "verdict_counts": dict(vc),
            "fail_reasons": dict(fr),
            "conf_discriminative_power_auc": auc,
            "note": ("AUC 用 conf 排序真球/非球的能力：0.5 = conf 无区分力，"
                     "1.0 = 完美。若接近 0.5，说明不能靠 conf 过滤，"
                     "必须加颜色/形状判据。"),
        },
        "conf_stats": confstat,
        "rows": rows,
    }
    p = os.path.join(a.outdir, "ball_verify.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("=" * 64)
    print("球检出颜色/形状复核")
    print("=" * 64)
    print(f"  真检出（非外推）: {n_all}")
    print(f"  通过『橙 + 尺寸 + 圆形』: {n_ball}  ({out['meta']['ball_like_pct']}%)")
    print(f"  🔴 判为『不是球』: {n_all - n_ball}"
          f"  ({(n_all-n_ball)/n_all*100:.1f}%)" if n_all else "")
    print(f"  失败理由计数: {dict(fr)}")
    print()
    print("  逐理由：")
    print(f"    橙色不达标（含 R>G>B 顺序）: {fr.get('orange',0)}")
    print(f"    尺寸不合理                : {fr.get('size',0)}")
    print(f"    形状不够圆（地板虚线/细长物）: {fr.get('round',0)}")
    print()
    print("  conf 均值：")
    print(f"    真球   {confstat['ball_like_mean_conf']}"
          f"  (中位 {confstat['ball_like_median_conf']})")
    print(f"    非球   {confstat['not_ball_mean_conf']}"
          f"  (中位 {confstat['not_ball_median_conf']})")
    print(f"  🔴 conf 区分力 AUC = {auc}"
          f"  (0.5 = 无区分力，不能靠 conf 过滤)" if auc is not None else "")
    print(f"\n[out] {p}")


if __name__ == "__main__":
    main()
