#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持球时刻核对图：把『门禁后的球位 + 遴选球员 + 持球人归属』画到帧上。

与 render_check_overlay.py 的区别：
  · 那个画的是**原始检测列表**（含观众），用来判断检测真伪；
  · 这个画的是**遴选+追踪后的 10 名球员**，用来核对**持球归属判断**本身。

颜色约定：
  🟢 粗绿框 + HOLDER   = 该帧被判定为持球人的球员
  🔵 细蓝框 + pid      = 其余入选球员
  🔴 红圈 + 置信度      = 真检出的球（本层唯一采信的球位）
  🟡 黄圈 + EXTRAP     = 外推球位（**不采信**，仅显示以供对照）
"""
import argparse
import json
import os

from PIL import Image, ImageDraw

GREEN = (0, 255, 90)
BLUE = (90, 165, 255)
RED = (255, 70, 70)
YELLOW = (255, 205, 60)
WHITE = (255, 255, 255)
DARK = (12, 12, 16)


def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--sel", required=True)
    ap.add_argument("--ball-hi", required=True)
    ap.add_argument("--gated", required=True)
    ap.add_argument("--audit", default=None)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--times", required=True,
                    help="逗号分隔的时刻，如 204.5,219.5,229.0")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--tag", default="pos")
    a = ap.parse_args()

    sel = load(a.sel)
    ball = load(a.ball_hi)["ball_track"]
    gated = load(a.gated)
    tls = {r["idx"]: r for r in gated["timeline"]}
    os.makedirs(a.outdir, exist_ok=True)

    tlist = [float(x) for x in a.times.split(",")]
    idxs = []
    for t in tlist:
        i = min(range(len(sel["frames"])),
                key=lambda k: abs(sel["frames"][k]["t"] - t))
        idxs.append(i)

    made = []
    for i in idxs:
        fr = sel["frames"][i]
        src = os.path.join(a.frames_dir, f"f{i+1:05d}.jpg")
        if not os.path.exists(src):
            print(f"  缺帧 {src}")
            continue
        img = Image.open(src).convert("RGB")
        W, H = img.size
        sc = a.width / W
        img = img.resize((a.width, int(H * sc)), Image.LANCZOS)
        dr = ImageDraw.Draw(img)

        row = tls.get(i, {})
        holder = row.get("holder")
        bpt = row.get("ball_pt")

        # 球员框
        for p in fr["players"]:
            x1, y1, x2, y2 = [v * sc for v in p["box"]]
            is_h = (p["pid"] == holder)
            dr.rectangle([x1, y1, x2, y2],
                         outline=GREEN if is_h else BLUE,
                         width=8 if is_h else 3)
            lab = ("HOLDER pid%d" % p["pid"]) if is_h else f"pid{p['pid']}"
            dr.text((x1 + 4, max(0, y1 - 22)), lab,
                    fill=GREEN if is_h else BLUE,
                    stroke_width=2, stroke_fill=(0, 0, 0))

        # 球：10fps 专线上取最近帧
        tnow = fr["t"]
        bt = min(ball, key=lambda b: abs(b["t"] - tnow))
        if bt.get("center"):
            cx, cy = bt["center"][0] * sc, bt["center"][1] * sc
            r = 26
            if bt.get("pred"):
                dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=YELLOW, width=4)
                dr.text((cx + r + 4, cy - 12), "EXTRAP（不采信）",
                        fill=YELLOW, stroke_width=2, stroke_fill=(0, 0, 0))
            else:
                dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RED, width=6)
                dr.text((cx + r + 4, cy - 12), f"BALL {bt['conf']:.2f}",
                        fill=RED, stroke_width=2, stroke_fill=(0, 0, 0))

        # 信息条
        ev = row.get("evidence", "none")
        conf = row.get("ball_conf")
        dist = row.get("dist")
        line1 = (f"t={tnow:.1f}s   持球人: "
                 f"{'pid%d' % holder if holder is not None else '无证据'}"
                 f"   dist={dist if dist is not None else 'NA'}"
                 f"   ball_conf={conf if conf is not None else 'NA'}")
        line2 = (f"球位来源: {'真检出 ✅' if ev == 'detected' else '无可信球位 ❌'}"
                 f"   |   场上入选球员 {len(fr['players'])} 名"
                 f"   |   镜头 t=204.5–247.7s")
        for k, txt in enumerate([line1, line2]):
            dr.rectangle([(0, k * 30 + 6), (a.width, k * 30 + 30)], fill=DARK)
            dr.text((12, k * 30 + 9), txt, fill=WHITE)

        out = os.path.join(a.outdir, f"{a.tag}_t{int(tnow*10):05d}.jpg")
        img.save(out, quality=88)
        made.append(out)
        print(f"  -> {out}   (idx={i}, holder={holder}, ev={ev})")

    print(f"[ok] {len(made)} 张")


if __name__ == "__main__":
    main()
