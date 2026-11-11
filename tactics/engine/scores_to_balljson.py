#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scores_to_balljson.py — 头打分 scores → ball_possession 外置球 JSON（每帧 top-1 prob≥th）。

用法:
  python engine/scores_to_balljson.py --scores action_work/validate/ball_cand_scores_multiscale_sas_lal_joint.json \
      --clip sas_lal --th 0.8 --out action_work/validate/sas_lal_ball_multiscale_th08.json
输出格式（ball_possession.py --ball-json 契约）: {"fNNNNN.jpg": [{"bbox":[...], "conf": prob}]}
每帧只取 prob 最高的一个候选（top-1），prob 作为 conf。无达标候选的帧不出现在输出里。
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True)
    ap.add_argument("--clip", required=True)
    ap.add_argument("--th", type=float, default=0.8)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    scores = json.loads(Path(a.scores).read_text())[a.clip]
    out = {}
    for fn, row in scores.items():
        if not row:
            continue
        top = max(row, key=lambda c: c["prob"])
        if top["prob"] >= a.th:
            out[fn] = [{"bbox": [float(v) for v in top["bbox"]], "conf": round(float(top["prob"]), 4)}]
    Path(a.out).write_text(json.dumps(out))
    n = len(out)
    print(f"[balljson] {a.out}  th={a.th}  命中帧 {n}/{len(scores)} ({100*n/len(scores):.1f}%)")


if __name__ == "__main__":
    main()
