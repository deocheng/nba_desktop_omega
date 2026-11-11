#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.9d 尺子自证：court_mask 在跨段复验用的 6 段上到底抠对了没有？

跨段复验给出 ep10_s0「TopK在场 28%」、ep12_s0「26%」——与「每帧 17–28 个检测、
场上应约 11 人(≈40–60%)」矛盾 ⇒ 怀疑是**尺子本身错了**，不是 Top-K 错了。
本脚本把掩膜半透明叠在原帧上，并把全部检测框画出来(绿=脚点在场, 红=脚点不在场)，目视自证。

用法: courtmask_selfcheck.py --segs a,b,c [--n 2]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
sys.path.insert(0, str(ROOT / "engine"))
from court_filter import _foot, court_mask  # noqa: E402

OUT = ROOT / "action_work" / "track_judge" / "courtmask_selfcheck"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segs", default="ep24_s1,ep1_s0,ep10_s0,ep12_s0,ep5_s1,ep19_s0")
    ap.add_argument("--n", type=int, default=2, help="每段出几帧")
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    for seg in a.segs.split(","):
        seg = seg.strip()
        d = SEGD / seg
        files = sorted((d / "frames").glob("f*.jpg"))
        tp = d / "tracks.json"
        if not files or not tp.exists():
            print(f"{seg}: 无帧/tracks，跳过")
            continue
        tr = json.load(open(tp))
        picks = np.linspace(0, len(files) - 1, a.n + 2).astype(int)[1:-1]
        for pi in picks:
            im = cv2.imread(str(files[pi]))
            if im is None:
                continue
            r = court_mask(im)
            if r is None or r[0] is None:
                print(f"{seg} f{pi}: court_mask 返回 None（判据不可用）")
                m = None
                vis = im.copy()
                cv2.putText(vis, "court_mask = None", (40, 90),
                            cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 255), 5)
                area = -1.0
            else:
                m, mode = r[0], (r[1] if len(r) > 1 else "?")
                area = float(m.mean())
                overlay = im.copy()
                overlay[m > 0] = (0.55 * overlay[m > 0] + 0.45 * np.array([40, 200, 40])).astype(np.uint8)
                vis = cv2.addWeighted(overlay, 0.75, im, 0.25, 0)
                cv2.putText(vis, f"{seg} f{pi}  mask_area={area:.2f} mode={mode}", (30, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 0), 4)
            n_on = n_off = 0
            for fr in tr["frames"]:
                if fr["idx"] != int(pi):
                    continue
                for p in fr.get("players", []):
                    box = p["box"]
                    x1, y1, x2, y2 = [int(v) for v in box]
                    fx, fy = _foot(box)
                    onc = False
                    if m is not None and 0 <= fx < m.shape[1] and 0 <= fy < m.shape[0]:
                        onc = m[fy, fx] > 0
                    n_on += onc; n_off += (not onc)
                    cv2.rectangle(vis, (x1, y1), (x2, y2),
                                  (0, 255, 0) if onc else (0, 0, 255), 3)
                    cv2.circle(vis, (fx, fy), 5, (255, 0, 255), -1)
                break
            tot = n_on + n_off
            cv2.putText(vis, f"green(on-court)={n_on}  red(off)={n_off}  total={tot}", (30, 140),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 4)
            op = OUT / f"{seg}_f{int(pi)}_mask.png"
            cv2.imwrite(str(op), cv2.resize(vis, (1280, int(1280 * vis.shape[0] / vis.shape[1]))))
            print(f"{seg} f{int(pi)}: mask_area={area:.2f}  on={n_on} off={n_off} total={tot} -> {op.name}")


if __name__ == "__main__":
    main()
