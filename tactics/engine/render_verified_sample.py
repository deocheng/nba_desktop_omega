#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盲测终验渲染：从 w*_ball_verified.json（验证后输出）抽全新样本渲染接触表 + manifest2。
抽样与调参集错开：只取调参 60 帧以外的帧。
用法: render_verified_sample.py [--n 15] [--vconf 0.4]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MEAS = Path(str(tactics_data_file("reports/milestone_05/measure")))
WINS = ["w1", "w2", "w3", "w4"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--cell", type=int, default=150)
    ap.add_argument("--half", type=int, default=70)
    ap.add_argument("--src", default="_ball_verified")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    # 排除所有已标注过的帧（measure/ 下一切 manifest*.json）
    used = set()
    for mf in sorted(MEAS.glob("manifest*.json")):
        used |= {(m["window"], m["frame"]) for m in json.loads(mf.read_text())}
    print(f"[排除] 已标注 {len(used)} 样本（{len(list(MEAS.glob('manifest*.json')))} 个 manifest）")

    all_man = []
    for w in WINS:
        det = json.loads((AW / f"{w}{a.src}.json").read_text())
        keys = sorted(k for k in det.keys() if det[k] and (w, k) not in used)
        if not keys:
            print(f"[{w}] 无可用新样本")
            continue
        idx = np.linspace(0, len(keys) - 1, min(a.n, len(keys))).astype(int)
        samp = [keys[i] for i in idx]
        tiles = []
        for f in samp:
            c = max(det[f], key=lambda x: x["conf2"])
            img = cv2.imread(str(AW / w / f))
            if img is None:
                continue
            bx1, by1, bx2, by2 = c["bbox"]
            cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
            h = a.half
            x1, y1 = int(cx - h), int(cy - h)
            pad = np.zeros((2 * h, 2 * h, 3), np.uint8)
            sx1, sy1 = max(0, x1), max(0, y1)
            sx2, sy2 = min(img.shape[1], x1 + 2 * h), min(img.shape[0], y1 + 2 * h)
            if sx2 > sx1 and sy2 > sy1:
                pad[sy1 - y1:sy2 - y1, sx1 - x1:sx2 - x1] = img[sy1:sy2, sx1:sx2]
            t = cv2.resize(pad, (a.cell, a.cell), interpolation=cv2.INTER_CUBIC)
            cv2.rectangle(t, (int((bx1 - x1) * a.cell / (2 * h)), int((by1 - y1) * a.cell / (2 * h))),
                          (int((bx2 - x1) * a.cell / (2 * h)), int((by2 - y1) * a.cell / (2 * h))),
                          (0, 255, 0), 2)
            cv2.putText(t, f"{f[1:6]} {c['conf2']:.2f}", (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 255, 255), 1)
            tiles.append(t)
            all_man.append({"window": w, "frame": f, "conf1": c["conf1"], "conf2": c["conf2"],
                            "bbox": c["bbox"], "label": None})
        rows = []
        for i in range(0, len(tiles), a.cols):
            r = tiles[i:i + a.cols]
            while len(r) < a.cols:
                r.append(np.zeros_like(tiles[0]))
            rows.append(np.hstack(r))
        cv2.imwrite(str(MEAS / f"verifysheet_{w}{a.tag}.jpg"), np.vstack(rows))
        print(f"[{w}] 新样本 {len(tiles)} -> verifysheet_{w}{a.tag}.jpg")
    (MEAS / f"manifest2{a.tag}.json").write_text(json.dumps(all_man, indent=1, ensure_ascii=False))
    print(f"[manifest2{a.tag}] {len(all_man)} 样本")


if __name__ == "__main__":
    raise SystemExit(main())
