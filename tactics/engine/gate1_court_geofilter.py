#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.12 按老程的正确顺序实测：门1=场内/场外(几何) → 门2=移动 → 门3=球锚点。

老程原话：
  「首先，场内的，场外的这能直接过滤很多干扰，其次才是移动，
    有人发界外球肯定不会大幅移动，但是球又成了根据」

对已有老程裁定的两帧逐框核对：
  ep24_s1 f70 : 31 检测，Top13(绿)=9 球员+4 观众(#3/#8/#9/#13)，被丢的球员=#22
  ep19_s0 f77 : 12 检测（<K=13，Top-K 未触发），裁判=#4/#12，1 名球员未检出
问：门1(场内/场外) 单独能不能砍掉那 4 个观众？会不会误杀 #22？

用法: gate1_court_geofilter.py --seg ep24_s1 --idx 70 [--dump cases.json]
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
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
from court_filter import _foot, court_mask  # noqa: E402

# 老程裁定：{seg_idx: {编号: 判定}}
VERDICT = {
    ("ep24_s1", 70): {3: "观众", 8: "观众", 9: "观众", 13: "观众", 22: "★球员(被丢)"},
    ("ep19_s0", 77): {4: "裁判", 12: "裁判"},
}


def foot_on_mask(m, box):
    fx, fy = _foot(box)
    if not (0 <= fx < m.shape[1] and 0 <= fy < m.shape[0]):
        return False
    return m[fy, fx] > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", required=True)
    ap.add_argument("--idx", type=int, required=True)
    a = ap.parse_args()

    items = json.load(open(OUT / f"{a.seg}_f{a.idx}.json"))
    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    # 整段复用掩膜（镜头基本静止），先用该帧自算再看能否拿到
    imi = cv2.imread(str(files[a.idx]))
    r = court_mask(imi)
    if r is None or r[0] is None:
        print(f"❌ {a.seg} f{a.idx}: court_mask 不可用(None) — 门1 在该帧失效")
        return
    m, mode = r[0], (r[1] if len(r) > 1 else "?")
    print(f"✅ {a.seg} f{a.idx}: court_mask mode={mode}  掩膜占画面 {m.mean()/255:.2f}")

    if not OUT.exists():
        OUT.mkdir(parents=True)
    vis = cv2.imread(str(files[a.idx]))
    ov = vis.copy()
    ov[m > 0] = (0.45 * ov[m > 0] + 0.55 * np.array([30, 190, 40])).astype(np.uint8)
    vis = cv2.addWeighted(ov, 0.55, vis, 0.45, 0)

    verdicts = VERDICT.get((a.seg, a.idx), {})
    print(f"\n{'#':>3}{'留/丢':>5}{'运动量':>7}{'脚在场内':>9}{'老程裁定':>12}")
    keep, drop = [], []
    for it in items:
        on = foot_on_mask(m, it["box"])
        x1, y1, x2, y2 = [int(v) for v in it["box"]]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 220, 0) if on else (0, 0, 225), 3 if on else 2)
        cv2.circle(vis, (int(it["cx"]), int(it["foot_y"])), 5, (255, 0, 255), -1)
        cv2.putText(vis, f"#{it['no']}", (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 4)
        cv2.putText(vis, f"#{it['no']}", (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0) if on else (0, 0, 220), 2)
        (keep if on else drop).append(it["no"])
        vv = verdicts.get(it["no"], "")
        if vv:
            print(f"{it['no']:>3}{'留' if it['topk'] else '丢':>5}{it['m']:>7.2f}"
                  f"{'是' if on else '否':>9}{vv:>12}")
    n_on = len(keep)
    print(f"\n门1(场内/场外) 结果：保留 {n_on} / 丢弃 {len(drop)}（共 {len(items)}）")
    if verdicts:
        spec = [n for n, v in verdicts.items() if v.startswith("观众")]
        pla = [n for n, v in verdicts.items() if v.startswith("★")]
        ok_s = [n for n in spec if n in drop]
        ok_p = [n for n in pla if n in keep]
        print(f"  观众 {spec} → 被门1 砍掉 {ok_s}（{len(ok_s)}/{len(spec)}）")
        print(f"  球员 {pla} → 被门1 保住 {ok_p}（{len(ok_p)}/{len(pla)}）"
              + ("  ❌ 门1 误杀了球员" if len(ok_p) < len(pla) else "  ✅ 无误杀"))
    op = OUT / f"{a.seg}_f{a.idx}_gate1.png"
    cv2.imwrite(str(op), vis)
    print(f"\n-> {op}")


if __name__ == "__main__":
    main()
