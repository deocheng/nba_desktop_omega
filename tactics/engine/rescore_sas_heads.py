#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rescore_sas_heads —— 修复 ball_head_sas.py 打分错位 bug 后，对全 1592 候选重建特征并重打分。

特征只建一次，同时喂 HUMAN 头与 AI-self 头（同候选云、同 build_all）。
产出（覆盖）:
  action_work/validate/ball_cand_scores_sas_human.json
  action_work/validate/ball_cand_scores_sas.json        (AI-self, 供 A4.24 修订)
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
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

cands = json.loads((AW / "validate" / "sas_det_cands.json").read_text())["sas_det"]
idx = {"sas_det": B.build_det_index(cands)}
n_c = sum(len(v) for v in cands.values())
print(f"候选云 sas_det: {len(cands)} 帧 {n_c} 候选", flush=True)

all_rows = []
for f, cs in cands.items():
    for c in cs:
        all_rows.append({"window": "sas_det", "frame": f, "bbox": c["bbox"],
                         "conf1": c.get("conf1", 0.0), "conf2": c.get("conf2", 0.0)})
print("重建全候选特征 ...", flush=True)
Xa = B.build_all(all_rows, idx, dev="cpu", progress=True)
print(f"特征 {Xa.shape}", flush=True)

for head_path, out_path in ((MS / "ball_head_sas_human.joblib", AW / "validate" / "ball_cand_scores_sas_human.json"),
                            (MS / "ball_head_sas.joblib", AW / "validate" / "ball_cand_scores_sas.json")):
    m = joblib.load(head_path)
    pp = m["pipe"].predict_proba(Xa)[:, 1]
    out, k = {}, 0
    for f, cs in cands.items():
        row = []
        for c in cs:  # 按候选递增（与 all_rows 对齐）
            row.append({"bbox": c["bbox"], "prob": float(pp[k]), "conf1": c.get("conf1", 0.0)})
            k += 1
    # k 已在候选循环内递增
        out[f] = row
    assert k == len(pp), f"对齐失败 k={k} != {len(pp)}"
    Path(out_path).write_text(json.dumps(out))
    print(f"[out] {out_path}", flush=True)
