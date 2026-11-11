#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成球检测复核的证据图（可复现），供里程碑报告引用。

产出 4 张图到 outdir：
  ev_ball_samples.jpg  原始球检出抽样 22 帧（每帧裁球框附近）
  ev_mastercard.jpg    橙色反差 top-16 —— 全是场边 LED 广告 Mastercard logo
  ev_audit.jpg         分层抽样目视审计（5 层 × 12 个）
  ev_targeted.jpg      定向核对若干已知时刻

用法：
  python make_evidence_figs.py --ball-verify ball_verify.json \
      --frames-dir seg_possession --outdir reports/milestone_02
"""
import argparse
import json
import os
import random

from PIL import Image, ImageDraw

GREEN = (0, 255, 80)
YELLOW = (255, 220, 60)
RED = (255, 70, 70)


def contrast(im, box, ring=1.6):
    """框内橙色度 − 周围环带橙色度。"""
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    W, H = im.size
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(W, x2), min(H, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    pad = int(max(x2 - x1, y2 - y1) * ring) + 4
    core = im.crop((x1, y1, x2, y2))
    px = list(core.getdata())
    n = len(px)
    br = sum(p[0] for p in px) / n
    bb = sum(p[2] for p in px) / n
    X1, Y1 = max(0, x1 - pad), max(0, y1 - pad)
    X2, Y2 = min(W, x2 + pad), min(H, y2 + pad)
    rim = im.crop((X1, Y1, X2, Y2))
    Wr = rim.size[0]
    keep = [p for k, p in enumerate(rim.getdata())
            if not (x1 - X1 <= k % Wr < x2 - X1 and y1 - Y1 <= k // Wr < y2 - Y1)]
    if not keep:
        return None
    m = len(keep)
    rr = sum(p[0] for p in keep) / m
    rb = sum(p[2] for p in keep) / m
    return (br - bb) / 255.0 - (rr - rb) / 255.0


def tile(im, box, w, label_top, label_bot, half=55):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    c = im.crop((int(cx) - half, int(cy) - half, int(cx) + half, int(cy) + half))
    c = c.resize((w, w), Image.LANCZOS)
    d = ImageDraw.Draw(c)
    q = w // 2
    d.rectangle([(q - 3, q - 3), (q + 3, q + 3)], outline=RED)
    d.text((3, 3), label_top, fill=GREEN)
    if label_bot:
        d.text((3, w - 13), label_bot, fill=YELLOW)
    return c


def grid(tiles, cols, w, out):
    rows = (len(tiles) + cols - 1) // cols
    M = Image.new("RGB", (cols * w, rows * w), (16, 16, 20))
    for k, t in enumerate(tiles):
        M.paste(t, ((k % cols) * w, (k // cols) * w))
    M.save(out, quality=88)
    print(f"  -> {out}  ({len(tiles)} tiles)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ball-verify", required=True)
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    bv = json.load(open(a.ball_verify))
    rows = [r for r in bv["rows"]
            if not r.get("pred") and r.get("box") and r.get("verdict") == "ball_like"]
    cache = {}

    def get(im_path):
        if im_path not in cache:
            cache[im_path] = Image.open(im_path).convert("RGB")
        return cache[im_path]

    def path_of(t):
        fi = int(round((t - 204.5) / 0.5)) + 1
        return os.path.join(a.frames_dir, f"f{fi:05d}.jpg")

    # 计算反差
    for r in rows:
        p = path_of(r["t"])
        if not os.path.exists(p):
            r["_ct"] = None
            continue
        r["_ct"] = contrast(get(p), r["box"])
    rows = [r for r in rows if r["_ct"] is not None]

    # ① 原始检出抽样 22
    step = max(1, len(rows) // 22)
    t1 = []
    for r in rows[::step][:22]:
        p = path_of(r["t"])
        t1.append(tile(get(p), r["box"], 140,
                       f"t{r['t']:.1f}", f"conf{r.get('conf', 0):.2f}", 70))
    grid(t1, 6, 140, os.path.join(a.outdir, "ev_ball_samples.jpg"))

    # ② 反差 top-16
    top = sorted(rows, key=lambda r: -r["_ct"])[:16]
    t2 = []
    for r in top:
        p = path_of(r["t"])
        t2.append(tile(get(p), r["box"], 160,
                       f"t{r['t']:.1f}", f"ct{r['_ct']:+.2f}", 60))
    grid(t2, 8, 160, os.path.join(a.outdir, "ev_mastercard.jpg"))

    # ③ 分层审计
    strata = [("ct>0.40", lambda c: c > 0.40),
              ("0.15<ct<=0.40", lambda c: 0.15 < c <= 0.40),
              ("0.00<ct<=0.15", lambda c: 0.0 < c <= 0.15),
              ("-0.15<ct<=0.00", lambda c: -0.15 < c <= 0.0),
              ("ct<=-0.15", lambda c: c <= -0.15)]
    random.seed(7)
    t3, counts = [], {}
    for name, f in strata:
        sub = [r for r in rows if f(r["_ct"])]
        counts[name] = len(sub)
        for r in random.sample(sub, min(12, len(sub))):
            t3.append(tile(get(path_of(r["t"])), r["box"], 150, name,
                           f"t{r['t']:.0f}", 55))
    grid(t3, 12, 150, os.path.join(a.outdir, "ev_audit.jpg"))
    with open(os.path.join(a.outdir, "ev_audit_counts.json"), "w") as f:
        json.dump(counts, f, ensure_ascii=False, indent=1)
    print(f"  分层计数: {counts}")

    # ④ 定向核对
    want = [204.5, 204.6, 210.0, 226.5, 228.5, 228.6, 247.4, 206.2, 207.2]
    t4 = []
    for r in rows:
        if round(r["t"], 1) in want:
            t4.append(tile(get(path_of(r["t"])), r["box"], 200,
                           f"t{r['t']:.1f}", f"ct{r['_ct']:+.2f}", 65))
    grid(t4, 5, 200, os.path.join(a.outdir, "ev_targeted.jpg"))


if __name__ == "__main__":
    main()
