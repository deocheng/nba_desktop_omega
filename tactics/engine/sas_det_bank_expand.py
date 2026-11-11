#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 (frame, idx, label) 判定扩展为完整 sas_det 标签 bank 条目（bbox/conf 从 manifest 回填）。
元数据按技能铁律：标注者、协议版本、门禁覆盖声明、时间。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True)
ap.add_argument("--judge", required=True, help="判定 JSON: [{frame, idx, label, note?}]")
ap.add_argument("--bank", required=True)
ap.add_argument("--append", action="store_true")
a = ap.parse_args()

manifest = json.loads(Path(a.manifest).read_text())
judge = json.loads(Path(a.judge).read_text())

META = {
    "annotator": "AI-self (WorkBuddy)",
    "protocol": "v2-3panel (full-frame context + 5x zoom; shape->texture->context-veto)",
    "gate": "OVERRIDE: user authorized 2026-09-26; known annotator accuracy 74.4% "
            "(Wilson CI [59.8%,85.1%]) on wide-view; sas_det dark ball expected LOWER. "
            "ALL sas_det outputs = exploratory only, NOT for conclusions.",
    "clip": "sas_det",
    "built_at": datetime.now().isoformat(timespec="seconds"),
}

out = []
for j in judge:
    fr = j["frame"]
    if fr not in manifest:
        print(f"SKIP {fr}: not in manifest", file=sys.stderr)
        continue
    cands = manifest[fr]
    entry = {
        "clip": "sas_det", "frame": fr, "idx": j["idx"], "label": j["label"],
        "note": j.get("note", ""),
    }
    m = cands[j["idx"]]
    entry.update({"bbox": m["bbox"], "conf1": m["conf1"], "conf2": m["conf2"]})
    out.append(entry)

bank = []
bp = Path(a.bank)
if a.append and bp.exists():
    loaded = json.loads(bp.read_text())
    bank = loaded["labels"] if isinstance(loaded, dict) else loaded
bank.extend(out)
bp.write_text(json.dumps({"meta": META, "labels": bank}, indent=1, ensure_ascii=False))
print(f"bank now {len(bank)} labels -> {a.bank}")
