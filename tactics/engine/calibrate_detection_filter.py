#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calibrate_detection_filter —— 给 ep*_sX 的**未过滤原始检测**标定净化门阈值。

背景：sas_* 的源 `*_poss_tile` 是过滤过的（10~13 框），但 ep*_sX 段的段内
      `ball_tracks.json` 是**原始检测**：conf 中位 0.41、33% 框高<60px（远景/观众）。
      直接喂给 stabilize ⇒ 每帧 25~27 个框、并发 27 ⇒ 撞死「并发∈[8,16]」硬门。

物理约束（可证伪，不是拍数）：半场转播画面里同时最多 10 名球员（+2 裁判）。
      ⇒ 好的过滤应使「每帧人数中位数」落在 8~13，且尽量少出现 <6 的帧。

本脚本只读原始 json 做统计，不跑 stabilize（快），扫 conf/h 的二维网格。

用法:
  python3 calibrate_detection_filter.py --seg ep10_s0 --seg ep10_s1 ...
  python3 calibrate_detection_filter.py --all --sample 20
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

SEGBASE = Path(str(tactics_data_file("action_work/tactic_notes_batch_full/segments")))


def segs_of():
    return sorted(d.name for d in SEGBASE.iterdir() if d.is_dir())


def stats(seg, conf_min, h_min, topn=0):
    """口径与 stabilize_tracks_v2.py 的 --conf-min/--h-min/--topn 完全一致。

    ⚠️ topn 是**景别无关**的过滤：每帧取 conf 达标里框最高的 topn 个。
    h_min（绝对像素高度）对宽景/特写镜头不鲁棒，实测会把宽景里的真球员砍光，
    故最终口径 = conf_min + topn（见 run_stabilize_batch.py 的 G3）。
    """
    d = json.loads((SEGBASE / seg / "ball_tracks.json").read_text(encoding="utf-8"))
    cnt = []
    for r in d:
        ps = [p for p in (r.get("players") or [])
              if (conf_min <= 0 or (p.get("conf") or 0.0) >= conf_min)
              and (h_min <= 0 or ((p.get("bbox") or [0, 0, 0, 0])[3]
                                  - (p.get("bbox") or [0, 0, 0, 0])[1]) >= h_min)]
        if topn and len(ps) > topn:
            ps = sorted(ps, key=lambda p: -((p["bbox"][3] - p["bbox"][1])))[:topn]
        cnt.append(len(ps))
    cnt = np.array(cnt)
    return {
        "median": float(np.median(cnt)),
        "p10": float(np.percentile(cnt, 10)),
        "p90": float(np.percentile(cnt, 90)),
        "max": int(cnt.max()),
        "frac_lt6": float((cnt < 6).mean()),
        "frac_gt14": float((cnt > 14).mean()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--conf-grid", default="0.30,0.40,0.50,0.55,0.60")
    ap.add_argument("--h-grid", default="0,80")
    ap.add_argument("--topn-grid", default="0,12")
    ap.add_argument("--dump-perseg", default="")
    a = ap.parse_args()

    # --all 表示全量；--sample N（显式给值）才抽样。踩过：默认 sample=20 把 --all 吃掉
    segs = a.seg or (segs_of()[: a.sample] if (not a.all) and a.sample > 0 else segs_of())
    confs = [float(x) for x in a.conf_grid.split(",")]
    hs = [float(x) for x in a.h_grid.split(",")]
    tns = [int(x) for x in a.topn_grid.split(",")]

    print(f"样本段数={len(segs)}")
    print(f"{'conf':>5}{'h_min':>7}{'topn':>6}{'人数中位':>9}{'p10':>6}{'p90':>6}{'max':>5}"
          f"{'<6帧%':>8}{'>14帧%':>8}{'段达标':>7}  合格")
    print("-" * 90)
    for cm in confs:
        for tn in tns:
            for hm in hs:
                rows = [stats(s, cm, hm, tn) for s in segs]
            med = float(np.median([r["median"] for r in rows]))
            f6 = float(np.mean([r["frac_lt6"] for r in rows]))
            f14 = float(np.mean([r["frac_gt14"] for r in rows]))
            # 逐段看：这一段自己的每帧人数中位数是否落在物理区间 [8,13]
            nseg = sum(1 for r in rows if 8.0 <= r["median"] <= 13.0)
            ok = 8.0 <= med <= 13.0 and f6 < 0.20
            print(f"{cm:>5.2f}{hm:>7.0f}{tn:>6d}{med:>9.1f}"
                  f"{np.median([r['p10'] for r in rows]):>6.0f}"
                  f"{np.median([r['p90'] for r in rows]):>6.0f}{max(r['max'] for r in rows):>5d}"
                  f"{f6*100:>7.1f}%{f14*100:>7.1f}%{nseg:>6d}/{len(rows)}  {'✅' if ok else ''}")
        print()

    if a.dump_perseg:
        out = {}
        for s in segs:
            per = {}
            for cm in confs:
                for tn in tns:
                    for hm in hs:
                        per[f"{cm}|{tn}|{hm}"] = stats(s, cm, hm, tn)["median"]
            out[s] = per
        Path(a.dump_perseg).write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[dump] 逐段中位数 -> {a.dump_perseg}")


if __name__ == "__main__":
    main()
