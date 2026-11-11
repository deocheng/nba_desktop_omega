#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 步语料切分：按 ep 分组切 train/val（防同 ep 泄漏）+ by-ep GroupKFold 5折(小样本CV)。
铁律：分组键 = ep（同一 ep 的所有簇必须同集，防画面/来源泄漏）；
     切分后实测 train_ep ∩ val_ep == ∅ 作为可证伪门。
输出：tactical_corpus_split.jsonl(带split字段) + split_train.jsonl + split_val.jsonl
     + cv_folds.json + split_summary.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
from collections import defaultdict

from common.nba_paths import tactics_data_file

BASE = str(tactics_data_file("action_work"))
NC = f"{BASE}/norm_calib"

ap = argparse.ArgumentParser()
ap.add_argument("--val-ratio", type=float, default=0.25)
ap.add_argument("--folds", type=int, default=5)
a = ap.parse_args()

samples = [json.loads(l) for l in open(f"{NC}/tactical_corpus.jsonl", encoding="utf-8") if l.strip()]

# 聚合 ep
ep2 = defaultdict(lambda: {"frames": 0, "clusters": [], "labels": set()})
for s in samples:
    e = ep2[s["ep"]]
    e["frames"] += s["n_frames_present"]
    e["clusters"].append(s["cluster_id"])
    for l in s["label_zh"]: e["labels"].add(l)
total = sum(s["n_frames_present"] for s in samples)
target = a.val_ratio * total

# 贪心：ep 帧数降序；放 val 后不超 target*1.2 且(标签新增 或 val空) → 放 val
eps = sorted(ep2.items(), key=lambda kv: -kv[1]["frames"])
val_eps, train_eps = [], []
val_frames, val_labels = 0, set()
for ep, e in eps:
    mainlab = max(e["labels"], key=lambda l: 0)  # 取任一标签做代表
    cand = val_frames + e["frames"]
    newlab = bool(e["labels"] - val_labels)
    if cand <= target * 1.2 and (newlab or val_frames == 0):
        val_eps.append(ep); val_frames = cand; val_labels |= e["labels"]
    else:
        train_eps.append(ep)
# 若 val 为空兜底放最小 ep
if not val_eps:
    ep = min(eps, key=lambda kv: kv[1]["frames"])[0]
    val_eps = [ep]; val_frames = ep2[ep]["frames"]; train_eps = [x for x in ep2 if x != ep]

split_of = {cid: ("val" if ep in val_eps else "train") for ep in (ep2) for cid in ep2[ep]["clusters"]}
for s in samples:
    s["split"] = split_of[s["cluster_id"]]

# 主文件 + train/val
with open(f"{NC}/tactical_corpus_split.jsonl", "w", encoding="utf-8") as f:
    for s in samples: f.write(json.dumps(s, ensure_ascii=False) + "\n")
for sp in ("train", "val"):
    with open(f"{NC}/split_{sp}.jsonl", "w", encoding="utf-8") as f:
        for s in samples:
            if s["split"] == sp: f.write(json.dumps(s, ensure_ascii=False) + "\n")

# by-ep GroupKFold：ep 帧数降序，轮流分配到各折（每 ep 整体进一折）
ep_order = [ep for ep, _ in eps]
folds = defaultdict(list)
for i, ep in enumerate(ep_order):
    folds[i % a.folds].append(ep)
cid2fold = {cid: fi for fi, eps_f in folds.items() for ep in eps_f for cid in ep2[ep]["clusters"]}
cv = [{"fold": fi, "eps": sorted(eps_f), "clusters": sorted(c for c, f in cid2fold.items() if f == fi),
       "frames": sum(s["n_frames_present"] for s in samples if cid2fold[s["cluster_id"]] == fi)}
      for fi, eps_f in sorted(folds.items())]
json.dump(cv, open(f"{NC}/cv_folds.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- 泄漏门 + 统计 ----
train_ep = {s["ep"] for s in samples if s["split"] == "train"}
val_ep = {s["ep"] for s in samples if s["split"] == "val"}
leak = train_ep & val_ep
def stat(sp):
    ss = [s for s in samples if s["split"] == sp]
    lf = defaultdict(int)
    for s in ss:
        lf["+".join(s["label_zh"]) or "(无)"] += s["n_frames_present"]
    return {"n_clusters": len(ss), "frames": sum(s["n_frames_present"] for s in ss),
            "n_ep": len({s["ep"] for s in ss}), "labels": dict(lf)}
summary = {
    "val_ratio_target": a.val_ratio, "total_frames": total,
    "train": stat("train"), "val": stat("val"),
    "train_eps": sorted(train_ep), "val_eps": sorted(val_ep),
    "leak_ep_intersection": sorted(leak), "leak_free": len(leak) == 0,
    "group_key": "ep", "n_folds": a.folds,
    "note": "分组键=ep，同ep不跨集；train_ep∩val_ep=∅已实测。",
}
json.dump(summary, open(f"{NC}/split_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- 摘要 ----
print(f"按 ep 分组切分（防泄漏）  总簇={len(samples)} 总帧={total}\n")
print(f"  TRAIN: {summary['train']['n_clusters']}簇 {summary['train']['frames']}帧 "
      f"{summary['train']['n_ep']}ep  eps={sorted(train_ep)}")
print(f"  VAL  : {summary['val']['n_clusters']}簇 {summary['val']['frames']}帧 "
      f"{summary['val']['n_ep']}ep  eps={sorted(val_ep)}")
print(f"\n  泄漏检查 train_ep ∩ val_ep = {sorted(leak) or '∅(无泄漏✓)'}"
      f"  → {'通过✓' if summary['leak_free'] else '失败✗'}")
print(f"\n  VAL 标签分布: {summary['val']['labels']}")
print(f"  TRAIN 标签分布: {summary['train']['labels']}")
print(f"\n  GroupKFold({a.folds}折, by ep):")
for c in cv:
    print(f"    折{c['fold']}: {c['n_frames'] if 'n_frames' in c else c['frames']}帧 eps={c['eps']} 簇={c['clusters']}")
print("\n[产物] tactical_corpus_split.jsonl / split_train.jsonl / split_val.jsonl / cv_folds.json / split_summary.json")
