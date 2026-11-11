#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""id_stability_ab —— 净化门 conf 门槛的配对 A/B（A5.31d 待裁定项）。

背景：A5.31d 用三级计数 + 视觉自证证明「并发<8 的真因是 conf>=0.40 砍掉真人」
（被滤框 conf 中位 0.31、框高 65~163px、黄框落在真人身上）。
但那只是**输入侧**证据；要把「降 conf 能救回那 8 段」这句话说完，必须证明
**稳定化输出**在 conf 0.30 下确实涨了，而且没把保真率搞坏。

本脚本把两套产物（如 action_work/norm_g3 与 action_work/norm_c30）
**逐段配对**比，不挑段、不挑好看的方向：
  · 并发中位 / 输入框中位 / 保真率 / 中位寿命 / 寿命比 两列对照
  · 三口径（甲绝对、乙保真、丙窗口）两边各过多少
  · Δ 方向：并发涨 ⇒ conf 门槛确实在砍人；保真率跌破 1.00 ⇒ 低 conf 里混进了重复/噪点

用法:
  python3 id_stability_ab.py --a action_work/norm_g3 --b action_work/norm_c30 --conf-b 0.30
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from id_stability_gate_v2 import (  # noqa: E402
    BAND_HI,
    BAND_LO,
    FID_HI,
    FID_LO,
    LIFE_RATIO,
    LIFE_THR,
    MIN_WIN,
    conc_life,
    input_frames,
    med,
    out_frames,
)


def seg_row(root: Path, seg: str):
    fr = out_frames(root / seg / "ball_tracks.json")
    nf = len(fr)
    conc, life = conc_life(fr)
    c = med(conc)
    ml = med(list(life.values())) if life else 0.0
    # 输入侧：当前 G.CONF_MIN 决定口径（A/B 两侧门槛不同，必须各自按自己的门槛读源）
    cnt, hs = input_frames(seg)
    inp = med(cnt)
    fid = c / inp if inp else 0.0
    return {"n_frames": nf, "input": inp, "conc": c, "fidelity": fid, "med_life": ml,
            "life_ratio": ml / nf if nf else 0.0,
            "gate_abs": BAND_LO <= c <= BAND_HI and ml >= LIFE_THR,
            "gate_fid": FID_LO <= fid <= FID_HI and ml >= LIFE_THR}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="action_work/norm_g3")
    ap.add_argument("--b", default="action_work/norm_c30")
    ap.add_argument("--conf-b", type=float, default=0.30, help="B 侧的输入口径 conf（A 侧恒为 0.40）")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()

    ra, rb = Path(a.a), Path(a.b)
    segs = sorted(d.name for d in ra.iterdir()
                  if d.is_dir() and (d / "ball_tracks.json").exists())
    # B 侧可能段数不同（断点续跑），并集取段
    segs = sorted(set(segs) | {d.name for d in rb.iterdir()
                               if d.is_dir() and (d / "ball_tracks.json").exists()})

    import id_stability_gate_v2 as G
    old = G.CONF_MIN
    rows = []
    for s in segs:
        pa = ra / s / "ball_tracks.json"
        pb = rb / s / "ball_tracks.json"
        if not pa.exists():
            continue
        G.CONF_MIN = 0.40
        ra_row = seg_row(ra, s)
        G.CONF_MIN = a.conf_b
        rb_row = seg_row(rb, s) if pb.exists() else None
        G.CONF_MIN = old
        if rb_row is None:
            continue
        rows.append({"seg": s, "a": ra_row, "b": rb_row})

    hdr = (f"{'段':<11}{'输入A':>6}{'输入B':>6}{'并发A':>7}{'并发B':>7}{'保真A':>7}"
           f"{'保真B':>7}{'寿命A':>7}{'寿命B':>7}{'甲':>5}{'乙A':>5}{'乙B':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows[: a.top]:
        A, B = r["a"], r["b"]
        print(f"{r['seg']:<11}{A['input']:>6.0f}{B['input']:>6.0f}{A['conc']:>7.1f}{B['conc']:>7.1f}"
              f"{A['fidelity']:>7.2f}{B['fidelity']:>7.2f}{A['med_life']:>7.0f}{B['med_life']:>7.0f}"
              f"{'P' if A['gate_abs'] else 'F':>5}"
              f"{'P' if A['gate_fid'] else 'F':>5}{'P' if B['gate_fid'] else 'F':>5}")

    n = len(rows)
    ka = sum(r["a"]["gate_abs"] for r in rows)
    kba = sum(r["a"]["gate_fid"] for r in rows)
    kb = sum(r["b"]["gate_fid"] for r in rows)
    print(f"\n配对段数 {n}")
    print(f"  甲 绝对并发[8,16]+寿命≥30        : A {ka}/{n}   ({ka/max(1,n)*100:.0f}%)")
    print(f"  乙 保真率[0.80,1.25]+寿命≥30    : "
          f"A {kba}/{n} ({kba/max(1,n)*100:.0f}%)   B {kb}/{n} ({kb/max(1,n)*100:.0f}%)")
    print(f"  保真率 中位  A {statistics.median([r['a']['fidelity'] for r in rows]):.3f}"
          f"   B {statistics.median([r['b']['fidelity'] for r in rows]):.3f}")
    print(f"  并发中位     A {statistics.median([r['a']['conc'] for r in rows]):.1f}"
          f"   B {statistics.median([r['b']['conc'] for r in rows]):.1f}")
    print(f"  输入框中位   A {statistics.median([r['a']['input'] for r in rows]):.1f}"
          f"   B {statistics.median([r['b']['input'] for r in rows]):.1f}")
    print(f"  寿命比中位   A {statistics.median([r['a']['life_ratio'] for r in rows]):.2f}"
          f"   B {statistics.median([r['b']['life_ratio'] for r in rows]):.2f}")

    # 只挑「甲口径下 A 失败」的段看 B 救回没有 —— 这是本 A/B 要回答的唯一问题
    resc = [r for r in rows if not r["a"]["gate_abs"] and r["b"]["gate_abs"]]
    broke = [r for r in rows if r["a"]["gate_abs"] and not r["b"]["gate_abs"]]
    print(f"\n甲口径下 A 失败、B 通过(救回) {len(resc)} 段: {[r['seg'] for r in resc]}")
    print(f"甲口径下 A 通过、B 失败(搞坏) {len(broke)} 段: {[r['seg'] for r in broke]}")
    print("（判据：甲=并发∈[8,16] 且 中位寿命≥30）")


if __name__ == "__main__":
    main()
