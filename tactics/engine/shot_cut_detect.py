#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_cut_detect —— 用**像素**找段内切镜（不碰 id，因为 id 已被污染）。

🔴 为什么不能用 id 集找切镜（本脚本的立论前提，全部已取证）：
  · 稳定化用 track_buffer=300 / zombie_buffer=600，跟踪器会把 id **直接拖过切镜点**。
    实测 ep24_s1：第 90 帧 ids={1,2,3,4,6,8,9,11,12,13,14,15}、
    第 96 帧 ids={1,2,3,5,6,8,10,11,12,14,15,16} —— 12 个里 10 个是老 id。
  · ⇒ 任何「相邻帧 id 重合率骤降 ⇒ 切镜」的判据都失效（这是 A5.31c 那版 68/177
    「含切镜」的噪源）。
  · 框高也不行：ep24_s1 跨切镜框高 111→119→116，几乎不跳（两镜头取景相似）。

  ⇒ 唯一没被污染的信号是**像素**：真切镜前后两帧画面内容完全不同，
    平均绝对差(MAD)会出现远超镜头运动的尖峰。

用法:
  python3 shot_cut_detect.py --root ...segments --out action_work/norm_calib/shotcuts.json
  python3 shot_cut_detect.py --seg ep24_s1 --debug        # 打印该段 MAD 序列
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

SEGBASE = Path(str(tactics_data_file("action_work/tactic_notes_batch_full/segments")))
W, H = 160, 90          # 缩到很小就够判切镜，省 IO/CPU
SPIKE = 3.5             # MAD 相邻比 > SPIKE 且 MAD 超全局中位 MAD 若干倍 ⇒ 切镜
                        # 刻度：ep24_s1 已知切镜 f94/f155 ⇒ 5.1x / 4.8x；
                        #       故阈值取 3.5x（留余量），6.0x 会把真切镜漏掉。
MAD_K = 3.0             # 相对段内 MAD 中位数的倍数下限


def frame_gray(p: Path):
    im = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    return cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA)


def mad_series(paths):
    """逐帧读图算相邻帧平均绝对差。返回 (mad 列表, 有效帧索引列表)"""
    mad, idxs = [], []
    prev = None
    for i, p in enumerate(paths):
        g = frame_gray(p)
        if g is None:
            continue
        if prev is not None:
            mad.append(float(np.abs(g.astype(np.float32) - prev.astype(np.float32)).mean()))
            idxs.append(i)
        prev = g
    return mad, idxs


def cuts(mad, idxs, spike=SPIKE, k=MAD_K, min_gap=8):
    """MAD 尖峰 → 切镜帧。min_gap 防止同一切镜被拆成两处。"""
    if not mad:
        return []
    med = float(np.median(mad))
    hits = []
    for j, m in enumerate(mad):
        r = m / med if med > 1e-6 else 0.0
        if r > spike and m > k * med:
            hits.append((idxs[j], r))
    # 合并间距过近的
    out = []
    for i, r in hits:
        if out and i - out[-1][0] < min_gap:
            if r > out[-1][1]:
                out[-1] = (i, r)
        else:
            out.append((i, r))
    return out


def seg_frames(seg):
    d = SEGBASE / seg / "frames"
    fs = sorted(d.glob("*.jpg"))
    if not fs:
        fs = sorted(d.glob("*.png"))
    return fs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(SEGBASE))
    ap.add_argument("--seg", nargs="*", default=[])
    ap.add_argument("--out", default="action_work/norm_calib/shotcuts.json")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()

    if a.seg:
        targets = a.seg
    else:
        targets = sorted(d.name for d in Path(a.root).iterdir() if d.is_dir())

    # 先跑一段看看量级
    if a.debug and a.seg:
        for s in a.seg:
            fs = seg_frames(s)
            mad, idxs = mad_series(fs)
            print(f"== {s}  帧 {len(fs)}  MAD中位 {np.median(mad):.2f}  "
                  f"MAD最大 {max(mad):.2f}")
            print("   前 30 个 MAD:", [round(v, 1) for v in mad[:30]])
            print("   MAD 尖峰(>3x中位):", [(i, round(r, 1)) for i, r in cuts(mad, idxs)])
        return

    def work(s):
        fs = seg_frames(s)
        if not fs:
            return s, [], 0
        mad, idxs = mad_series(fs)
        return s, cuts(mad, idxs), len(fs)

    res = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for s, cs, nf in ex.map(work, targets):
            res[s] = {"n_frames": nf, "cuts": [{"frame": i, "ratio": round(r, 2)} for i, r in cs]}
            print(f"{s:<12} {nf:>5} 帧  切镜 {len(cs)} 处  "
                  f"{[c['frame'] for c in res[s]['cuts']]}")

    n_cut = sum(1 for v in res.values() if v["cuts"])
    print(f"\n含切镜段数 {n_cut}/{len(res)}")
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
