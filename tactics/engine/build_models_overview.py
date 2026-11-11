#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_models_overview.py — 由 tactic_models.json 生成人读总表（A4.58b）。
含 tier / key_primitive / seq_dependent / confirm_primitives，数字全从磁盘现读。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
MJ = os.path.join(ROOT, "action_work", "tactic_models.json")
OUT = os.path.join(ROOT, "action_work", "tactic_models_overview.md")

d = json.load(open(MJ, encoding="utf-8"))
models = d["models"]
alias = d.get("alias_index", {})
inv = {}
for k, v in alias.items():
    inv.setdefault(v, []).append(k)

L = []
L.append(f"# 战术抽象模型总表（{len(models)} 模型 / 覆盖 {len(alias)} 库条目）\n")
L.append("> 来源：《NBA战术笔记》人声 ASR（A4.56）。语义来自人声；sequence/signature 为形式化约定"
         "（engine/tactic_abstraction_spec.md）。")
L.append("> signature 仅含**可观察量**；匹配只出候选，裁定归老程。")
L.append("> `tier`: basic=简单配合 / system=战术（**草案**）。`key_primitive`=判别原语（缺失则该模型出局）。"
         "`seq_dependent`=判别量依赖次序/重复，signature 未评估时降级。`confirm`=不可检但可文档化的确认项。\n")

for m in models:
    L.append(f"## {m['id']}")
    L.append(f"- 名称: {' / '.join(m.get('names', []))}")
    if inv.get(m["id"]):
        L.append(f"- 库条目: {' / '.join(inv[m['id']])}")
    if m.get("kind"):
        L.append(f"- 类别: {m['kind']}")
    L.append(f"- tier: {m.get('tier', '?')}")
    if m.get("key_primitive"):
        L.append(f"- 判别原语(key): {m['key_primitive']}")
    if m.get("seq_dependent"):
        L.append("- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）")
    L.append(f"- 目的: {m.get('goal', '')}")
    L.append(f"- 触发: {m.get('trigger', '')}")
    L.append(f"- 原语: {' -> '.join(m.get('primitives', []))}")
    if m.get("confirm_primitives"):
        L.append(f"- 确认项(confirm): {' / '.join(m['confirm_primitives'])}")
    seq = m.get("sequence", [])
    if seq:
        parts = [f"{s.get('role', '?')}:{s.get('action', '?')}" + (f"/{s['screen']}" if s.get("screen") else "")
                 + (f"/{s['cut']}" if s.get("cut") else "") for s in seq]
        L.append(f"- 序列: {' → '.join(parts)}")
    sig = m.get("signature", [])
    if sig:
        L.append(f"- 判别信号: {'; '.join(s['feat'] for s in sig)}")
    L.append(f"- 与最像战术的区别: {m.get('discriminative', '')}")
    src = m.get("source", {})
    if src.get("clip"):
        L.append(f"- 来源: {src['clip']}")
    L.append("")

open(OUT, "w", encoding="utf-8").write("\n".join(L))
print(f"[写出] {OUT}  ({len(models)} 模型)")
