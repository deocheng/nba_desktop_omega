#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rescore_clip_heads.py — 对任意 clip 的候选池用 sas HUMAN 头重打分（rescore_sas_heads 泛化版）。

用法:
  python engine/rescore_clip_heads.py --clip sas_lal \
      [--cands action_work/validate/sas_lal_cands.json]
产出:
  action_work/validate/ball_cand_scores_<clip>_human.json   ({"<clip>": {fn: [{bbox,prob,conf1,conf2}]}})
  （run_ball_events --scores 直读此文件）
⚠️ A4.25 教训：候选逐个递增打分（k+=1 每帧候选循环内），打分后 assert 对齐。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import joblib

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
MS = ROOT / "reports/milestone_05/measure"
sys.path.insert(0, str(ROOT / "engine"))
import ball_feats_all as B  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--cands", default=None)
    ap.add_argument("--out", default=None, help="默认 ball_cand_scores_<clip>_human.json")
    ap.add_argument("--head", default=str(MS / "ball_head_dense_a442.joblib"),
                    help="头 joblib 路径；A4.42 转正默认 dense 头(ball_head_dense_a442)；"
                         "旧池(top-4)官方头=ball_head_joint.joblib(final351)，须显式 --head 指定")
    ap.add_argument("--device", default="cpu",
                    help="build_all 特征设备；multiscale 密集池(~4.6万候选/片段)用 mps 提速约10倍")
    a = ap.parse_args()
    cands_path = Path(a.cands) if a.cands else AW / "validate" / f"{a.clip}_cands.json"
    cands = json.loads(cands_path.read_text())[a.clip]
    n_c = sum(len(v) for v in cands.values())
    print(f"候选云 {a.clip}: {len(cands)} 帧 {n_c} 候选", flush=True)

    idx = {a.clip: B.build_det_index(cands)}
    all_rows = []
    for f, cs in cands.items():
        for c in cs:
            all_rows.append({"window": a.clip, "frame": f, "bbox": c["bbox"],
                             "conf1": c.get("conf1", 0.0), "conf2": c.get("conf2", 0.0)})
    print("重建全候选特征 ...", flush=True)
    Xa = B.build_all(all_rows, idx, dev=a.device, progress=True)
    print(f"特征 {Xa.shape}", flush=True)

    head = joblib.load(a.head)
    pp = head["pipe"].predict_proba(Xa)[:, 1]
    out, k = {}, 0
    for f, cs in cands.items():
        row = []
        for c in cs:
            row.append({"bbox": c["bbox"], "prob": float(pp[k]),
                        "conf1": c.get("conf1", 0.0), "conf2": c.get("conf2", 0.0)})
            k += 1
        out[f] = row
    assert k == len(pp), f"对齐失败 k={k} != {len(pp)}"
    out_path = (Path(a.out) if a.out
                else AW / "validate" / f"ball_cand_scores_{a.clip}_human.json")
    out_path.write_text(json.dumps({a.clip: out}))
    print(f"[out] {out_path}", flush=True)
    hi = sum(1 for cs in out.values() if any(r["prob"] >= 0.8 for r in cs))
    print(f"th=0.80 命中帧 {hi}/{len(out)} ({hi/len(out)*100:.1f}%)")


if __name__ == "__main__":
    main()
