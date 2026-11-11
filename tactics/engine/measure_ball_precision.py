#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球检测精度目视测量协议（90% 可用门禁）。

从 w*_rfdetr_tile.json（管线实际使用的分块 RF-DETR 检出）逐窗分层抽样，
把每帧最高 conf 球框渲染成接触表（带上下文裁切），并输出 manifest JSON
（window/frame/conf/bbox/inP/label=null）。人工 Read 接触表逐格判 TP/FP 后回填
label，再用本脚本 --score 模式统计逐窗 + 总体精确度。

用法:
  渲染: measure_ball_precision.py --render [--n 15]
  计分: measure_ball_precision.py --score --labels labels.json
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
WINS = ["w1", "w2", "w3", "w4"]
OUT = Path(str(tactics_data_file("reports/milestone_05/measure")))
OUT.mkdir(parents=True, exist_ok=True)


def load_tiled(w):
    d = json.loads((AW / f"{w}_rfdetr_tile.json").read_text())
    return d


def load_players(w):
    bt = json.loads((AW / f"{w}_poss_tile" / "ball_tracks.json").read_text())
    return bt  # list of frames, index-aligned to sorted tiled keys


def render(w, n, cols, cell, half, minconf):
    d = load_tiled(w)
    bt = load_players(w)
    keys = sorted(d.keys())
    # 仅取有真实检出的帧
    cand = [k for k in keys if d[k]]
    if not cand:
        return [], []
    idx = np.linspace(0, len(cand) - 1, min(n, len(cand))).astype(int)
    samp = [cand[i] for i in idx]
    tiles, mani = [], []
    for f in samp:
        cs = [c for c in d[f] if c["conf"] >= minconf]
        if not cs:
            continue
        c = max(cs, key=lambda x: x["conf"])
        fi = keys.index(f)
        players = bt[fi].get("players", []) if fi < len(bt) else []
        img = cv2.imread(str(AW / w / f))
        if img is None:
            continue
        bx1, by1, bx2, by2 = c["bbox"]
        cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
        h = half
        x1, y1 = int(cx - h), int(cy - h)
        pad = np.zeros((2 * h, 2 * h, 3), np.uint8)
        sx1, sy1 = max(0, x1), max(0, y1)
        sx2, sy2 = min(img.shape[1], x1 + 2 * h), min(img.shape[0], y1 + 2 * h)
        if sx2 > sx1 and sy2 > sy1:
            pad[sy1 - y1:sy2 - y1, sx1 - x1:sx2 - x1] = img[sy1:sy2, sx1:sx2]
        t = cv2.resize(pad, (cell, cell), interpolation=cv2.INTER_CUBIC)
        cv2.rectangle(t, (int((bx1 - x1) * cell / (2 * h)), int((by1 - y1) * cell / (2 * h))),
                      (int((bx2 - x1) * cell / (2 * h)), int((by2 - y1) * cell / (2 * h))),
                      (0, 255, 0), 2)
        inside = any(p["bbox"][0] <= cx <= p["bbox"][2] and p["bbox"][1] <= cy <= p["bbox"][3]
                     for p in players)
        cv2.putText(t, f"{f[1:6]} {c['conf']:.2f}", (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 255, 255), 1)
        cv2.putText(t, "inP" if inside else "-", (3, cell - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 0, 255) if inside else (180, 180, 180), 2)
        tiles.append(t)
        mani.append({"window": w, "frame": f, "conf": round(c["conf"], 3),
                     "bbox": [round(v, 1) for v in c["bbox"]], "inP": bool(inside), "label": None})
    # 接触表
    rows = []
    for i in range(0, len(tiles), cols):
        r = tiles[i:i + cols]
        while len(r) < cols:
            r.append(np.zeros_like(tiles[0]))
        rows.append(np.hstack(r))
    sheet = np.vstack(rows) if rows else np.zeros((cell, cell * cols, 3), np.uint8)
    out = OUT / f"ballsheet_{w}.jpg"
    cv2.imwrite(str(out), sheet)
    print(f"[{w}] 渲染 {len(tiles)} 格 -> {out}")
    return tiles, mani


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--cell", type=int, default=150)
    ap.add_argument("--half", type=int, default=70)
    ap.add_argument("--minconf", type=float, default=0.0)
    ap.add_argument("--labels", default=str(OUT / "labels.json"))
    a = ap.parse_args()

    if a.render:
        all_man = []
        for w in WINS:
            _, man = render(w, a.n, a.cols, a.cell, a.half, a.minconf)
            all_man += man
        (OUT / "manifest.json").write_text(json.dumps(all_man, indent=1, ensure_ascii=False))
        print(f"[manifest] {OUT/'manifest.json'}  ({len(all_man)} 样本)")
        return

    if a.score:
        man = json.loads(Path(a.labels).read_text())
        tp = sum(1 for m in man if m.get("label") is True)
        fp = sum(1 for m in man if m.get("label") is False)
        un = sum(1 for m in man if m.get("label") is None)
        print(f"样本 {len(man)}  已标 {tp+fp}  未标 {un}")
        if tp + fp:
            print(f"总体精度 = {tp/(tp+fp)*100:.1f}%  (TP={tp} FP={fp})")
        for w in WINS:
            wt = [m for m in man if m["window"] == w]
            t = sum(1 for m in wt if m.get("label") is True)
            f = sum(1 for m in wt if m.get("label") is False)
            if t + f:
                print(f"  {w}: {t/(t+f)*100:.1f}%  (TP={t} FP={f})")
        return
    print("需 --render 或 --score")


if __name__ == "__main__":
    raise SystemExit(main())
