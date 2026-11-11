#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 步语料落地：13 簇 ASR 战术名 → 训练/分析语料 manifest。
每条样本 = 一个战术片段簇，标签 = 对应原视频人声讲解真值(gt_models)，
检测原语仅作佐证字段。**逐帧 os.path.exists 实测帧完整率**（不假完整）。
输出：norm_calib/tactical_corpus.jsonl（每行一样本）+ tactical_corpus_summary.json + 摘要。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import glob
import json
import os

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
BASE = f"{ROOT}/action_work"
SEG_ROOT = f"{BASE}/tactic_notes_batch_full/segments"

# 载入
anch = json.load(open(f"{BASE}/norm_calib/orient_anchors.json", encoding="utf-8"))
PAN = anch["pan_deg"]; ANCH = anch["anchors"]
named = json.load(open(f"{BASE}/norm_calib/a_step_named.json", encoding="utf-8"))["clusters"]
tm = json.load(open(f"{BASE}/tactic_models.json", encoding="utf-8"))
def cn(s):
    for n in s:
        if any('\u4e00' <= c <= '\u9fff' for c in n): return n
    return s[0]
id2name = {m["id"]: cn(m["names"]) for m in tm["models"]}
alias2id = tm.get("alias_index", {})

def resolve(mid):
    if mid in id2name: return id2name[mid]
    t = alias2id.get(mid)
    return id2name.get(t, mid)

samples = []
for cid_s in sorted(ANCH, key=lambda x: int(x)):
    a = ANCH[cid_s]; seg = a["seg"]; s0, s1 = a["start"], a["end"]; ep = seg.split("_")[0]
    # 帧索引→jpg 路径（frames.json 权威）
    fj = json.load(open(f"{SEG_ROOT}/{seg}/frames.json", encoding="utf-8"))
    idx2path = {r["idx"]: r["path"] for r in fj}
    idxs = [i for i in range(s0, s1 + 1) if i in idx2path]
    jpgs, present, missing = [], 0, 0
    for i in idxs:
        ap = os.path.join(ROOT, idx2path[i])
        if os.path.exists(ap): present += 1; jpgs.append(ap)
        else: missing += 1
    nc = named.get(cid_s, {})
    label_zh = [g["name"] for g in nc.get("asr_tactic_names", [])]
    label_models = [g["model"] for g in nc.get("asr_tactic_names", [])]
    samples.append({
        "sample_id": f"c{cid_s}",
        "cluster_id": int(cid_s),
        "ep": ep, "seg": seg,
        "start_idx": s0, "end_idx": s1,
        "n_frames_expected": s1 - s0 + 1,
        "n_frames_present": present, "n_missing": missing,
        "frames_complete": (missing == 0 and present == s1 - s0 + 1),
        "label_zh": label_zh, "label_models": label_models,
        "label_source": "ASR_gt_models(原视频人声讲解)",
        "detected_primitives_zaozheng": nc.get("detected_primitives", {}),
        "cut_noise": nc.get("cut_noise", False),
        "n_jpg": len(jpgs),
        "frames_dir": f"{SEG_ROOT}/{seg}/frames",
        "frames_list": jpgs,                    # 逐帧绝对路径（供训练直读）
        "tracks_json": f"{SEG_ROOT}/{seg}/tracks.json",
        "ball_tracks_json": f"{SEG_ROOT}/{seg}/ball_tracks.json",
        "pan_deg": PAN,
    })

out_jsonl = f"{BASE}/norm_calib/tactical_corpus.jsonl"
with open(out_jsonl, "w", encoding="utf-8") as f:
    for s in samples:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

# ---- 汇总 ----
from collections import Counter, defaultdict

label_frames = defaultdict(int); label_clusters = defaultdict(list)
for s in samples:
    key = "+".join(s["label_zh"]) or "(无)"
    label_frames[key] += s["n_frames_present"]; label_clusters[key].append(s["cluster_id"])
tot_present = sum(s["n_frames_present"] for s in samples)
tot_expected = sum(s["n_frames_expected"] for s in samples)
complete = sum(1 for s in samples if s["frames_complete"])
ep_set = {s["ep"] for s in samples}

summary = {
    "pan_deg": PAN, "n_clusters": len(samples),
    "total_frames_expected": tot_expected, "total_frames_present": tot_present,
    "global_frame_completeness_pct": round(100.0 * tot_present / tot_expected, 2) if tot_expected else 0,
    "clusters_fully_complete": complete,
    "n_eps": len(ep_set), "eps": sorted(ep_set),
    "label_distribution_frames": dict(label_frames),
    "label_distribution_clusters": {k: label_clusters[k] for k in label_clusters},
    "label_source": "ASR_gt_models(原视频人声讲解)",
    "note": "命名=ASR真值权威；检测原语仅佐证。帧完整率逐帧 os.path.exists 实测。",
}
json.dump(summary, open(f"{BASE}/norm_calib/tactical_corpus_summary.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# ---- 摘要 ----
print(f"pan={PAN}  13 簇 → 训练/分析语料 manifest\n")
print(f"{'簇':<4}{'段':<10}{'标签(ASR)':<22}{'帧(在/应有)':<12}{'完整':<5}原语佐证")
for s in samples:
    lab = "+".join(s["label_zh"]) or "(无)"
    ok = "✓" if s["frames_complete"] else "✗"
    fr = f"{s['n_frames_present']}/{s['n_frames_expected']}"
    prims = " ".join(f"{k}×{v}" for k, v in sorted(s["detected_primitives_zaozheng"].items())) or "无"
    print(f"#{s['cluster_id']:<3}{s['seg']:<10}{lab:<22}{fr:<12}{ok:<5}{prims}")
print(f"\n总簇={len(samples)}  总帧(在/应有)={tot_present}/{tot_expected} "
      f"({summary['global_frame_completeness_pct']}%)  全完整簇={complete}/{len(samples)}")
print("涉及 ep:", ",".join(sorted(ep_set)))
print("\n标签分布(按帧):")
for k, v in sorted(label_frames.items(), key=lambda x: -x[1]):
    print(f"  {k:<24}{v:>4}帧  簇={label_clusters[k]}")
print(f"\n[产物] {out_jsonl}")
print(f"[产物] {BASE}/norm_calib/tactical_corpus_summary.json")
