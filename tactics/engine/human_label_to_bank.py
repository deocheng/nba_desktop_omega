#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""human_label_to_bank —— 把人工标注 JSON 转成高可靠性 sas_det 标签库。

与 AI 自标 bank 的区别：
  - annotator = human(老程)，可靠性高（不覆盖 74.4% 门禁，这是合规路线）；
  - 判定口径：每帧 ball_idx 列出的候选 = TP，其余候选 = FP；
    标 none(置信无球) 的帧所有候选 = FP；标 skip(不确定) 的帧 = 剔除(不进训练)。

用法:
  python engine/human_label_to_bank.py \
      --labels action_work/validate/sas_det_sheets/human_labels.json \
      --manifest action_work/validate/sas_det_sheets/manifest.json \
      --bank action_work/validate/sas_det_label_bank_human.json
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--labels", required=True)
ap.add_argument("--manifest", default=str(Path("action_work/validate/sas_det_sheets/manifest.json")))
ap.add_argument("--bank", required=True)
ap.add_argument("--clip", default="sas_det")
ap.add_argument("--shot-types", default=None,
                help="shot_types.json：给每个候选打镜头类型（close 帧可按需排除出训练池）")
ap.add_argument("--miss-frames", default="", help="有球但候选云漏检的帧号，逗号分隔（只进 meta 召回分母）")
ap.add_argument("--occ-frames", default="", help="球被遮挡的帧号，逗号分隔（同上）")
a = ap.parse_args()
CLIP = a.clip
SHOT = {}
if a.shot_types:
    SHOT = json.loads(Path(a.shot_types).read_text())["frames"]
MISS = [int(x) for x in a.miss_frames.replace(" ", "").split(",") if x]
OCC = [int(x) for x in a.occ_frames.replace(" ", "").split(",") if x]

manifest = json.loads(Path(a.manifest).read_text())
labels = json.loads(Path(a.labels).read_text())

META = {
    "annotator": "human (老程)",
    "protocol": "v2-3panel (full-frame context + 5x zoom; shape->texture->context-veto)",
    "gate": "compliant: human-labeled (reliable). NOT AI-self. Authorized as the gate-passing "
            "self-label route 2026-09-26. Eligible for head retraining (no gate override needed).",
    "clip": CLIP,
    "built_at": datetime.now().isoformat(timespec="seconds"),
}

tp = fp = unc = skip = 0
out = []
for j in labels:
    fr = j["frame"]
    if fr not in manifest:
        print(f"SKIP {fr}: not in manifest", file=sys.stderr); continue
    cands = manifest[fr]
    if j.get("skip"):
        skip += 1
        continue
    ball = j.get("ball_idx", []) or []
    for i in ball:
        if i < 0 or i >= len(cands):
            print(f"WARN {fr}: ball_idx {i} 越界(本帧{len(cands)}候选), 跳过", file=sys.stderr); continue
    ball_set = set(i for i in ball if 0 <= i < len(cands))
    for i, c in enumerate(cands):
        entry = {"clip": CLIP, "frame": fr, "idx": i,
                 "bbox": c["bbox"], "conf1": c.get("conf1"), "conf2": c.get("conf2"),
                 "shot_type": SHOT.get(fr, {}).get("type")}
        if i in ball_set:
            entry["label"] = "TP"; tp += 1
        else:
            entry["label"] = "FP"; fp += 1
        out.append(entry)

Path(a.bank).write_text(json.dumps({"meta": META, "labels": out}, indent=1, ensure_ascii=False))
for k, v in (("recall_miss_frames", MISS), ("occluded_frames", OCC)):
    if v: META[k] = v
if SHOT:
    nclose = sum(1 for e in out if e.get("shot_type") == "close")
    META["shot_type_counts"] = {"close_cands": nclose, "nonclose_cands": len(out) - nclose}
n_frames = len({e["frame"] for e in out})
print(f"[bank] {a.bank}")
print(f"  帧(有效)={n_frames}  跳过(不确定)={skip}")
print(f"  TP={tp}  FP={fp}  合计={len(out)}")
print(f"  含球帧={sum(1 for j in labels if not j.get('skip') and j.get('ball_idx'))}")
