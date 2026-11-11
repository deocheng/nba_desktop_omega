#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_rel_confound.py — 决定性判别：关系模型的 holding / defending 到底**看懂了语义**，
还是只是**复现几何**？

背景（必须问这个问题）
----------------------
`poss_track_id` 的定义 = 「距球框矩形最近的球员」= **纯几何**。
而 rel_handler_validate 得到 H1: holding→BALL 的 top-1 在「有边」时 46/46 = 100% 命中 poss，
**零分歧**。100% 一致有两种互斥解释：
  (a) 模型真看懂了「谁拿着球」⇒ 关系层携带语义，值得做阈值扫描/时序稳定（item 2/3）
  (b) 模型只是对「区域邻近」敏感 ⇒ 它就是几何的复述，不带来任何新信息

判别判据
--------
1. **分数-距离相关性**：若 holding 分数只是「球到该球员距离」的函数 ⇒ (b)。
   取每帧 holding→BALL 的**所有**候选边，看 score 与 d(球, sub) 的 Spearman 相关。
2. **次近对照**：在「最近 vs 次近」差距很小的模糊帧上，模型是否仍 100% 选最近？
   若永远选最近 ⇒ (b)。
3. **defending 边的空间合理性**：defending 边两端球员的框距 vs 随机球员对的框距。
   若 defending 边只是随机配对 ⇒ 不携带对位信息。
4. **defending 边是否倾向「一前一后」**：对位应是防守者挡在持球人身前。

用法
----
  python engine/_rel_confound.py [--suffix _poss_tile_fp]
（读 action_work/validate/rel_handler_validate.json + <clip><suffix>/ball_tracks.json）
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"


def rect_dist(bx, by, b):
    dx = max(b[0] - bx, 0.0, bx - b[2])
    dy = max(b[1] - by, 0.0, by - b[3])
    return math.hypot(dx, dy)


def center_dist(a, b):
    ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return math.hypot(ax - bx, ay - by)


def spearman(x, y):
    if len(x) < 3:
        return None
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[s[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default="_poss_tile_fp")
    a = ap.parse_args()

    rep = json.loads((AW / "validate" / "rel_handler_validate.json").read_text())
    all_hold, all_dist, all_defd, all_rand = [], [], [], []
    margins = []
    print(f"{'片段':8} {'帧':>4} | {'hold边的Spearman(score,dist)':>28} | "
          f"{'模糊帧(次近-最近<40px)':>24} | {'defend框距中位':>14} {'随机对中位':>10}")
    print("-" * 108)

    for clip, blk in rep["clips"].items():
        bt = json.loads((AW / f"{clip}{a.suffix}" / "ball_tracks.json").read_text())
        fmap = {int(f["frame"]): f for f in bt}
        hs, ds = [], []
        rand_pool = []
        amb = amb_hit = 0
        for r in blk["records"]:
            fr = fmap.get(r["idx"])
            if fr is None:
                continue
            pm = {int(p["track_id"]): p["bbox"] for p in fr["players"]}
            ball = fr["ball"]["bbox"]
            bx, by = (ball[0] + ball[2]) / 2, (ball[1] + ball[3]) / 2
            # 1) holding 边：score vs d(球, sub)
            if r["e35"]:
                sub = int(r["e35"]["sub"])
                if sub in pm:
                    hs.append(r["e35"]["score"])
                    ds.append(rect_dist(bx, by, pm[sub]))
            # 2) 次近 margin
            dsort = sorted((rect_dist(bx, by, b), tid) for tid, b in pm.items())
            if len(dsort) >= 2:
                margin = dsort[1][0] - dsort[0][0]
                margins.append(margin)
                if margin < 40 and r["e35"]:
                    amb += 1
                    if int(r["e35"]["sub"]) == dsort[0][1]:
                        amb_hit += 1
            # 3) defending 边两端框距 + 随机对照
            for e in r["def_edges"]:
                s, o = e["s"], e["o"]
                if s in ("BALL",) or o in ("BALL",):
                    continue
                if int(s) in pm and int(o) in pm:
                    all_defd.append(center_dist(pm[int(s)], pm[int(o)]))
            ids = [t for t in pm]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    rand_pool.append(center_dist(pm[ids[i]], pm[ids[j]]))
        all_hold += hs
        all_dist += ds
        all_rand += rand_pool
        sp = spearman(hs, ds)
        md = sorted(all_defd)[len(all_defd) // 2] if all_defd else None
        mr = sorted(rand_pool)[len(rand_pool) // 2] if rand_pool else None
        print(f"{clip:8} {blk['summary']['n_frames']:>4} | "
              f"{('ρ=%+.3f (n=%d)' % (sp, len(hs))) if sp is not None else 'n/a':>28} | "
              f"{f'{amb_hit}/{amb} 选最近' if amb else '无模糊帧':>24} | "
              f"{f'{md:.0f}px' if md else '—':>14} {f'{mr:.0f}px' if mr else '—':>10}")

    print()
    print("=== 汇总（三段合并）===")
    sp_all = spearman(all_hold, all_dist)
    print(f"holding 边样本数 {len(all_hold)}；defending 边 {len(all_defd)}；随机球员对 {len(all_rand)}")
    print(f"[判据1] holding 分数 vs 球到该球员距离  Spearman ρ = "
          f"{sp_all:+.3f}" if sp_all is not None else "n/a")
    if all_defd and all_rand:
        md = sorted(all_defd)[len(all_defd) // 2]
        mr = sorted(all_rand)[len(all_rand) // 2]
        print(f"defending 边两端框距中位 = {md:.0f}px ；随机球员对中位 = {mr:.0f}px "
              f"⇒ 比值 {md/max(1,mr):.2f}（≈1 表示 defending 边就是随机配对）")
    m_sorted = sorted(margins)
    print(f"几何 margin（次近-最近）中位 = {m_sorted[len(m_sorted)//2]:.1f}px")


if __name__ == "__main__":
    main()
