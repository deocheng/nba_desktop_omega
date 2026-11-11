#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_track_ids —— 把一段稳定化产物画到原帧上，人工/模型看「多出来的人是谁」。

用法:
  python3 render_track_ids.py <ball_tracks.json> <imgdir> --frame 100 --out /tmp/ep77.png
  python3 render_track_ids.py <ball_tracks.json> <imgdir> --frame 100 --side 1
      --side 1 只画 id 最大的 12 条（看超密段的多余轨）；--side 0 画全部
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

PALETTE = [(255, 60, 60), (60, 255, 120), (90, 120, 255), (255, 220, 60),
           (220, 80, 255), (60, 230, 230), (255, 140, 40), (40, 255, 200),
           (200, 200, 60), (255, 60, 200), (120, 255, 60), (60, 90, 255)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tracks")
    ap.add_argument("imgdir")
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--side", type=int, default=0, help="1=只画寿命前12的轨 0=全画")
    ap.add_argument("--img-h", type=int, default=1080)
    a = ap.parse_args()

    d = json.loads(Path(a.tracks).read_text(encoding="utf-8"))
    if isinstance(d, dict):
        for k in ("tracks", "records", "frames"):
            if k in d:
                d = d[k]
                break
    r = d[min(a.frame, len(d) - 1)]
    fn = r.get("frame") or r.get("img") or r.get("filename")
    stem = Path(str(fn)).stem if fn else None
    img = None
    if stem:
        for c in (Path(a.imgdir) / f"{stem}.jpg", Path(a.imgdir) / f"{stem}.png"):
            if c.exists():
                img = cv2.imread(str(c))
                break
    if img is None:
        cands = sorted(Path(a.imgdir).glob("*.jpg"))
        idx = min(a.frame, len(cands) - 1)
        img = cv2.imread(str(cands[idx]))
        print(f"[warn] 帧名 {fn} 未找到，改用 {cands[idx].name}")
    h0, w0 = img.shape[:2]
    img = cv2.resize(img, (int(w0 * a.img_h / h0), a.h0 if False else a.img_h))

    ps = [p for p in (r.get("players") or []) if p.get("track_id") is not None]
    ps.sort(key=lambda p: -p["track_id"] if a.side else p["track_id"])
    if a.side:
        alive = {}
        for rr in d:
            for p in (rr.get("players") or []):
                alive[p["track_id"]] = alive.get(p["track_id"], 0) + 1
        top = sorted(alive, key=lambda t: -alive[t])[:12]
        ps = [p for p in ps if p["track_id"] in top]

    for i, p in enumerate(ps):
        tid = p["track_id"]
        x1, y1, x2, y2 = [int(v) for v in p["bbox"]]
        c = PALETTE[int(tid) % len(PALETTE)]
        cv2.rectangle(img, (x1, y1), (x2, y2), c, 2)
        cv2.putText(img, f"id{tid}", (x1, max(0, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, c, 2)
    cv2.putText(img, f"frame={a.frame} n={len(ps)}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(a.out, img)
    print("wrote", a.out, " 框数", len(ps))


if __name__ == "__main__":
    main()
