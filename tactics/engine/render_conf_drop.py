#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_conf_drop —— 「被 conf 门槛滤掉的框」到底是不是球员？（视觉自证）

缘起（本轮实测）：
  gate_v2 有 8 段因并发 <8 不过门①-A 的绝对带 [8,16]。三级计数显示这些段的
  「被滤掉框」conf 中位只有 0.30~0.32、框高 65~163px —— 既不是远处小球员
  （框高不小），也不像噪点（框高在球员量级）。
  ⇒ 必须上视觉自证：把「保留」和「被滤掉」的框分开画，看被滤的那几个是不是真人。

画法（同一帧一张图）：
  绿 = conf>=CONF_MIN 且被 topn 保留
  黄 = 0<conf<CONF_MIN（被 conf 门槛滤掉）
  灰 = conf<=0
  框上标 conf 与框高，肉眼判读：黄框落在人身上 ⇒ conf 门槛砍了真人；
  黄框落在看台/广告牌/地面 ⇒ 是噪点，砍得对。

用法:
  python3 render_conf_drop.py --seg ep4_s1 ep41_s1 --conf 0.40 --topn 12 --out /tmp/conf_drop.png
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2

from common.nba_paths import tactics_data_file

SEGDIR = Path(str(tactics_data_file("action_work/tactic_notes_batch_full/segments")))
FRAMEDIR = SEGDIR / "frames"


def frames_of(seg):
    return sorted((SEGDIR / seg / "frames").glob("*.jpg")) or \
        sorted((SEGDIR / seg / "frames").glob("*.png"))


def draw(img, p, color, tag=True):
    x1, y1, x2, y2 = [int(round(v)) for v in p["bbox"]]
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    if tag:
        h = y2 - y1
        s = f"c{p['conf']:.2f} h{h}"
        cv2.putText(img, s, (x1, max(14, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", nargs="+", required=True)
    ap.add_argument("--frame", type=int, nargs="+", default=[], help="帧序号(0-based)，缺省取窗中位")
    ap.add_argument("--conf", type=float, default=0.40)
    ap.add_argument("--topn", type=int, default=12)
    ap.add_argument("--out", default="/tmp/conf_drop.png")
    ap.add_argument("--cols", type=int, default=3)
    a = ap.parse_args()

    cells = []
    for seg in a.seg:
        fs = frames_of(seg)
        d = json.loads((SEGDIR / seg / "ball_tracks.json").read_text(encoding="utf-8"))
        nf = len(d)
        fin = a.frame if a.frame else [nf // 2]
        for fi in fin:
            if fi >= nf or fi >= len(fs):
                continue
            im = cv2.imread(str(fs[fi]))
            if im is None:
                continue
            im = cv2.resize(im, (720, 405))
            keep, drop = [], []
            for p in (d[fi].get("players") or []):
                c = p.get("conf") or 0.0
                if c >= a.conf:
                    keep.append(p)
                elif c > 0:
                    drop.append(p)
            if a.topn and len(keep) > a.topn:
                keep = sorted(keep, key=lambda p: -(p["bbox"][3] - p["bbox"][1]))[: a.topn]
            for p in keep:
                draw(im, p, (0, 255, 0))
            for p in drop:
                draw(im, p, (0, 255, 255))
            lab = (f"{seg} f{fi}   绿=保留(conf>={a.conf}) {len(keep)}个   "
                   f"黄=被conf门槛滤掉 {len(drop)}个")
            cv2.putText(im, lab, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 0), 2)
            cv2.putText(im, "框上 c=conf  h=框高  黄框落在人身上 ⇒ conf门槛砍了真人",
                        (8, 400 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cells.append(im)

    if not cells:
        print("无有效帧")
        return
    h, w = cells[0].shape[:2]
    cols = a.cols
    rows = (len(cells) + cols - 1) // cols
    import numpy as np
    cv2_ = np.zeros((h * rows, w * cols, 3), np.uint8)
    for i, im in enumerate(cells):
        r, c = divmod(i, cols)
        cv2_[r * h:(r + 1) * h, c * w:(c + 1) * w] = im
    cv2.imwrite(a.out, cv2_)
    print(f"wrote {a.out}  单元格 {len(cells)}")


if __name__ == "__main__":
    main()
