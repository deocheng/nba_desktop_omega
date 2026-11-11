#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""detect_cuts.py — 廉价切镜检测（广播片段镜头切换）。

为什么需要
----------
`sas_*` 是转播片段，镜头频繁切换。ball_possession 的 BotSort 默认 persist 跨帧保持 ID，
切镜后画面完全不同 ⇒ 旧轨迹消失、新人物重新分配 ID ⇒ **track_id 碎片化**
（实测 sas_hou 400 帧竟出现 256 个 track_id，而场上只有 ~10 名球员）。
给 ball_possession 的 `--cuts` 传入切镜帧索引，可在切镜处 reset 跟踪器，
使**同一镜头内** ID 稳定（这是按球员聚合战术指标的前提）。

方法
----
逐帧降采样灰度图，算与前一帧的平均绝对差（MAD）。切镜时 MAD 会出现数量级跳变。
阈值用数据驱动：先报分布，再取 `max(base, k × 中位)`，并打印被判定的切镜点供人工核对。

用法
----
  python engine/detect_cuts.py sas_hou [--k 6 --base 12] [--dump]
输出
----
  action_work/validate/<clip>_cuts.json   （0-based 帧索引列表，直接喂 --cuts）
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
AW = ROOT / "action_work"


def frame_diffs(frames_dir: Path):
    files = sorted(frames_dir.glob("*.jpg"))
    prev = None
    diffs = []
    for f in files:
        img = cv2.imread(str(f))
        if img is None:
            diffs.append(0.0); continue
        g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (64, 36))
        g = g.astype(np.float32)
        if prev is None:
            diffs.append(0.0)
        else:
            diffs.append(float(np.abs(g - prev).mean()))
        prev = g
    return diffs, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--k", type=float, default=6.0, help="阈值 = k × 中位MAD")
    ap.add_argument("--base", type=float, default=12.0, help="阈值下界（防静止片段把噪声当切镜）")
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    d = AW / a.clip
    diffs, files = frame_diffs(d)
    arr = np.array(diffs)
    med = float(np.median(arr[1:])) if len(arr) > 1 else 0.0
    thr = max(a.base, a.k * med)
    cuts = [int(i) for i in range(1, len(arr)) if arr[i] > thr]

    q = np.percentile(arr[1:], [50, 90, 99]) if len(arr) > 1 else (0, 0, 0)
    print(f"{a.clip}: 帧数={len(files)}  MAD 中位={q[0]:.2f} p90={q[1]:.2f} p99={q[2]:.2f} max={arr.max():.2f}")
    print(f"  阈值 = max({a.base}, {a.k}×{med:.2f}) = {thr:.2f}")
    print(f"  判定切镜 {len(cuts)} 处 (0-based 帧索引): {cuts[:20]}{' ...' if len(cuts)>20 else ''}")
    if cuts:
        seg_lens = np.diff([0] + cuts + [len(files)])
        print(f"  镜头段数={len(seg_lens)}  段长 中位={np.median(seg_lens):.0f} 最大={seg_lens.max()}")
    if a.dump:
        out = AW / "validate" / f"{a.clip}_cuts.json"
        out.write_text(json.dumps(cuts))
        print(f"  → {out}")


if __name__ == "__main__":
    main()
