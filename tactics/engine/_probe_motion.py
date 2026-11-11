#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_probe_motion.py — 「镜动残差」信号探针（R4 污染的最后一个候选判据）。

物理含义
--------
一个**坐着的人**（观众/替补）在画面里**只随镜头动**：若把全局相机位移扣掉，其框内残差 ≈ 0。
一个**场上球员**相对镜头有自主位移（跑动、转身、抬手），残差显著大于 0。
该判据**不依赖颜色/球场几何/身高**，因此不受"地板掩膜跨域残缺"与"近端观众框很大"两个
已实测问题的牵连（见 `player_pollution_filter.py` 的失败记录）。

算法
----
逐相邻帧对 (t, t+1)：
  1. 灰度降到 0.25 尺度，Farneback 稠密光流 → flow(dx,dy)；
  2. 全局相机位移 `g` = 全帧光流中位数（画面大部分像素是背景：看台/地板/LED）；
  3. 对帧 t 的每个框，取框内（内缩 20%）光流中位 → `f_box`；
  4. **残差** `r = |f_box − g|`（0.25 尺度像素，可乘 4 还原全分辨率近似）。
逐 track 汇总 `r_med`、`r_p90`，供与目视标签比对。

用法
    python engine/_probe_motion.py --clips w1,sas_hou
    python engine/_probe_motion.py --clips w1 --report   # 打印指定 track 残差
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
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
OUT = AW / "validate"
SC = 0.25


def flow_pair(g0, g1):
    return cv2.calcOpticalFlowFarneback(
        g0, g1, None, pyr_scale=0.5, levels=3, winsize=15, iterations=3,
        poly_n=5, poly_sigma=1.1, flags=0)


def run_clip(clip, suffix="_poss_tile"):
    recs = json.loads((AW / f"{clip}{suffix}" / "ball_tracks.json").read_text())
    order = sorted(range(len(recs)), key=lambda i: str(recs[i].get("file", "")))
    grays = {}
    rows = []
    prev_g = None
    prev_rec = None
    for n, i in enumerate(order):
        r = recs[i]
        img = cv2.imread(str(AW / clip / str(r["file"])))
        if img is None:
            continue
        small = cv2.resize(img, (int(img.shape[1] * SC), int(img.shape[0] * SC)),
                           interpolation=cv2.INTER_AREA)
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev_g is not None and prev_rec is not None:
            fl = flow_pair(prev_g, g)
            gx = float(np.median(fl[:, :, 0]))
            gy = float(np.median(fl[:, :, 1]))
            Hh, Ww = g.shape
            for pl in prev_rec.get("players", []):
                x1, y1, x2, y2 = [v * SC for v in pl["bbox"]]
                bw, bh = x2 - x1, y2 - y1
                x1i, x2i = int(x1 + 0.2 * bw), int(x2 - 0.2 * bw)
                y1i, y2i = int(y1 + 0.2 * bh), int(y2 - 0.2 * bh)
                x1i, x2i = max(0, x1i), min(Ww, x2i)
                y1i, y2i = max(0, y1i), min(Hh, y2i)
                if x2i - x1i < 3 or y2i - y1i < 3:
                    continue
                sub = fl[y1i:y2i, x1i:x2i]
                bx = float(np.median(sub[:, :, 0]))
                by = float(np.median(sub[:, :, 1]))
                rr = float(np.hypot(bx - gx, by - gy))
                rows.append({"file": prev_rec["file"], "frame": int(str(prev_rec["file"])[1:6]),
                             "track_id": pl["track_id"], "resid": round(rr, 3),
                             "resid_px": round(rr / SC, 2),
                             "h": round(y2 / SC - y1 / SC, 1),
                             "foot_y": round(pl["bbox"][3], 1),
                             "glob_px": round(float(np.hypot(gx, gy)) / SC, 2)})
        prev_g, prev_rec = g, r
        if n % 200 == 0:
            print(f"  {clip} {n}/{len(order)}")
    tr = {}
    for r in rows:
        tr.setdefault(r["track_id"], []).append(r)
    summ = {}
    for t, v in tr.items():
        rr = np.array([z["resid_px"] for z in v], float)
        summ[t] = {"n": len(v), "r_med": round(float(np.median(rr)), 2),
                   "r_p90": round(float(np.percentile(rr, 90)), 2),
                   "r_mean": round(float(rr.mean()), 2),
                   "glob_med": round(float(np.median([z["glob_px"] for z in v])), 2),
                   "h_med": round(float(np.median([z["h"] for z in v])), 1),
                   "foot_med": round(float(np.median([z["foot_y"] for z in v])), 1)}
    Out = OUT / f"motion_{clip}.json"
    Out.write_text(json.dumps({"rows": rows, "tracks": summ}, ensure_ascii=False))
    print(f"[out] {Out}  框帧={len(rows)} tracks={len(tr)}")
    return {"rows": rows, "tracks": summ}


LABELS = {
    # (clip, frame) -> {"on": [...], "off": [...], "ref": [...]}  目视确认的 track_id
    ("w1", 421): {"off": [2768, 3019, 3048, 3062, 3135, 3030, 3159, 3160, 2693,
                          2946, 2874, 2980, 3157, 3004, 2641],
                  "on": [2900, 2218, 3049, 1892, 2912, 3068, 2552, 2991, 3026, 2888]},
    ("sas_hou", 1): {"on": [1, 2, 3, 4, 5, 6, 7, 8, 11],
                     "off": [12, 13, 14],
                     "ref": [10]},
}


def report(clips):
    for (clip, fr), lab in LABELS.items():
        if clip not in clips:
            continue
        p = OUT / f"motion_{clip}.json"
        if not p.exists():
            print(f"[缺] {p}，先跑 --clips {clip}")
            continue
        d = json.loads(p.read_text())
        rows = {r["track_id"]: r for r in d["rows"] if r["frame"] == fr}
        print(f"\n=== {clip} f{fr:05d} 镜动残差 ===")
        print(f"{'label':>6} {'track':>6} {'resid_px':>9} {'glob_px':>8} {'h':>6} {'foot_y':>7}")
        for kind in ("on", "ref", "off"):
            for t in lab.get(kind, []):
                r = rows.get(t)
                if not r:
                    print(f"{kind:>6} {t:>6}   （该帧无此 track）")
                    continue
                print(f"{kind:>6} {t:>6} {r['resid_px']:>9.2f} {r['glob_px']:>8.1f} "
                      f"{r['h']:>6.0f} {r['foot_y']:>7.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default="w1,sas_hou,sas_nop,sas_det")
    ap.add_argument("--suffix", default="_poss_tile")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cs = [c.strip() for c in a.clips.split(",") if c.strip()]
    if not a.report:
        for c in cs:
            run_clip(c, a.suffix)
    report(set(cs))


if __name__ == "__main__":
    main()
