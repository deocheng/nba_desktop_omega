#!/usr/bin/env python3
"""目视核对：把球/持球人/球员框画到帧上，输出叠加图。

只做可视化，不做任何判断 —— 用来快速回答「检测是真球还是误检」这类问题。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os
import sys

from PIL import Image, ImageDraw

from common.nba_paths import workspace_file

SRC = str(workspace_file("action_work/seg_possession"))


def render(d: dict, idxs: list[int], outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    frames = {f["idx"]: f for f in d["frames"]}
    for i in idxs:
        f = frames[i]
        p = os.path.join(SRC, f"f{i+1:05d}.jpg")
        if not os.path.exists(p):
            print(f"  缺帧 {p}")
            continue
        img = Image.open(p).convert("RGB")
        dr = ImageDraw.Draw(img)
        for pl in f["players"]:
            x1, y1, x2, y2 = pl["box"]
            is_h = (pl["id"] == f.get("ball_handler"))
            dr.rectangle([x1, y1, x2, y2],
                         outline=(0, 255, 80) if is_h else (90, 160, 255),
                         width=7 if is_h else 3)
            dr.text((x1 + 4, max(0, y1 - 20)), f"id{pl['id']}",
                    fill=(0, 255, 80) if is_h else (140, 190, 255),
                    stroke_width=2, stroke_fill=(0, 0, 0))
        b = f.get("ball") or {}
        bb = b.get("box")
        if bb and not b.get("pred"):
            dr.rectangle([bb[0] - 12, bb[1] - 12, bb[2] + 12, bb[3] + 12],
                         outline=(255, 60, 60), width=5)
            dr.text((bb[0] - 12, max(0, bb[1] - 34)),
                    f"BALL {b.get('conf')}", fill=(255, 90, 90),
                    stroke_width=2, stroke_fill=(0, 0, 0))
        elif b.get("pred") and b.get("box"):
            dr.rectangle([bb[0] - 12, bb[1] - 12, bb[2] + 12, bb[3] + 12],
                         outline=(255, 200, 40), width=3)
            dr.text((bb[0] - 12, max(0, bb[1] - 34)), "BALL(pred)",
                    fill=(255, 210, 60), stroke_width=2, stroke_fill=(0, 0, 0))
        h = f.get("ball_handler")
        dr.text((14, 14), f"f{i} t={f['t']}s  handler={h} "
                          f"dist={f.get('handler_dist')}",
                fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
        out = os.path.join(outdir, f"chk_{i:03d}.jpg")
        img.resize((960, 540), Image.LANCZOS).save(out, quality=90)
        print(f"  -> {out}")


def main() -> int:
    d = json.load(open(os.path.join(SRC, "tracks.json")))
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SRC, "check")
    idxs = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else \
        [10, 22, 35, 40, 62, 65, 74, 84]
    render(d, idxs, outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
