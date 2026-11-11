# -*- coding: utf-8 -*-
"""
build_final_corpus.py — 组装定稿训练语料包（Task 4）
总原则：
  - 语义命名 = ASR gt_models；检测原语仅作结构佐证。
  - 球质量单独报告不进分；ball_real_rate<0.30 标 ball_unreliable。
  - 按 ep 分组防泄漏（复用 cv_folds.json）。
  - 帧用软链(不复制)，保持磁盘轻量、可溯源。
输入：--tracks 默认 norm_calib/smooth_tracks_game20（KEEP 候选集；签核后用 _v2）
输出：norm_calib/final_corpus_20261006/
  frames/  tracks/  labels/{asr_gt_models.json, smooth_verdict.json}
  manifests/{train.jsonl, val.jsonl, cv_folds.json}  README.md
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import shutil
import statistics
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
BASE = f"{ROOT}/action_work"
NC = f"{BASE}/norm_calib"
SEG = f"{BASE}/tactic_notes_batch_full/segments"
OUT = f"{NC}/final_corpus_20261006"

ap = argparse.ArgumentParser()
ap.add_argument("--tracks", default=f"{NC}/smooth_tracks_game20")
ap.add_argument("--verdict", default=f"{NC}/smooth_verdict_laocheng.json")
ap.add_argument("--status", default="PROVISIONAL(待老程逐条签核)")
a = ap.parse_args()

TRACKS = Path(a.tracks)
V = json.load(open(a.verdict, encoding="utf-8"))
named = json.load(open(f"{NC}/a_step_named.json", encoding="utf-8")).get("clusters", {})
cv = json.load(open(f"{NC}/cv_folds.json", encoding="utf-8"))

for d in ("frames", "tracks", "labels", "manifests"):
    os.makedirs(f"{OUT}/{d}", exist_ok=True)

# 清空旧软链/文件/子目录（防陈旧污染，含上一轮 provisional 的 per-pid 子目录）
for d in ("frames", "tracks"):
    dd = Path(f"{OUT}/{d}")
    if dd.exists():
        shutil.rmtree(dd)
    dd.mkdir(parents=True, exist_ok=True)

tracks_files = sorted(TRACKS.glob("*.json"))
print(f"[组装] 源={TRACKS}  轨迹数={len(tracks_files)}")

# 按 ep 分组防泄漏：fold0 簇若仍在本批保留，则其所属 ep 整集进 val（保证同 ep 不跨 train/val）
kept_ids = {int(f.stem.split("_")[0][1:]) for f in tracks_files}
cmap = {}
for _src in (f"{NC}/pure_game_windows.json", f"{NC}/pure_game_windows_gray.json"):
    if os.path.exists(_src):
        for _w in json.load(open(_src, encoding="utf-8"))["pure_game"]:
            for _m in _w["members"]:
                cmap.setdefault(_w["cluster"], _m["seg"].split("_")[0])
fold0 = cv[0].get("clusters", []) if isinstance(cv, list) and cv else []
val_eps = {cmap[c] for c in fold0 if c in kept_ids and cmap.get(c)}
print(f"[防泄漏] fold0 保留簇→val eps = {sorted(val_eps)}  (其余 ep 进 train)")

asr_map = {}; verdict_map = {}; id_frag = {}; ball_unreliable = []
frames_total = 0; points_total = 0
train_rows = []; val_rows = []

for f in tracks_files:
    tr = json.load(open(f, encoding="utf-8"))
    pid = tr["pick_id"]; seg = tr["seg"]; ep = tr["ep"]; cid = int(pid[1:])
    i0, i1 = tr["win"]
    asr_name = tr.get("asr_name", "")
    asr_map[pid] = {"cluster": cid, "seg": seg, "ep": ep, "asr_name": asr_name,
                    "win": [i0, i1]}
    verdict_map[pid] = {"cluster": cid, "verdict": V.get("reviews", {}).get(str(cid), {}).get("verdict", "KEEP"),
                        "in_exclude": cid in set(V.get("exclude_clusters", []))}

    # 软链帧
    fj = json.load(open(f"{SEG}/{seg}/frames.json", encoding="utf-8"))
    fmap = {r["idx"]: r["path"] for r in fj}
    fdir = Path(f"{OUT}/frames/{pid}")
    fdir.mkdir(parents=True, exist_ok=True)
    for k in range(i0, i1 + 1):
        src = fmap.get(k)
        if not src:
            continue
        sp = os.path.join(ROOT, src)
        dp = fdir / f"f{k}.jpg"
        if not dp.exists():
            os.symlink(sp, dp)
        frames_total += 1
    # 轨迹点
    json.dump(tr, open(f"{OUT}/tracks/{pid}.json", "w", encoding="utf-8"), ensure_ascii=False)

    # ID 碎片度：track_id 数 vs 每帧可见人数中位（近似实际人数）
    n_tids = len(tr["players"])
    pfn = [len([1 for tid, pos in tr["players"].items() if str(k) in pos]) for k in range(i0, i1 + 1)]
    med_people = round(statistics.median(pfn), 1) if pfn else 0
    id_frag[pid] = {"n_track_ids": n_tids, "median_people_per_frame": med_people,
                    "fragmentation_x": round(n_tids / med_people, 2) if med_people else None}
    # 球质量
    ball = [b for b in tr.get("ball", []) if b]
    real = [b for b in ball if not b.get("pred")]
    rate = round(len(real) / len(ball), 3) if ball else 0.0
    if rate < 0.30:
        ball_unreliable.append({"pick_id": pid, "ball_real_rate": rate})

    # manifests 行
    row = {"pick_id": pid, "seg": seg, "ep": ep, "cluster": cid,
           "win": [i0, i1], "n_frames": i1 - i0 + 1, "asr_name": asr_name,
           "ball_real_rate": rate, "ball_unreliable": rate < 0.30,
           "id_fragmentation_x": id_frag[pid]["fragmentation_x"]}
    points_total += (i1 - i0 + 1)
    # 按 ep 分组防泄漏：val = 整 ep（fold0 保留簇所属 ep），train = 其余 ep
    split = "val" if ep in val_eps else "train"
    if split == "val":
        val_rows.append(row)
    else:
        train_rows.append(row)

json.dump(asr_map, open(f"{OUT}/labels/asr_gt_models.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(verdict_map, open(f"{OUT}/labels/smooth_verdict.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump({"id_fragmentation": id_frag,
           "ball_unreliable": ball_unreliable},
          open(f"{OUT}/labels/_quality_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(train_rows, open(f"{OUT}/manifests/train.jsonl", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(val_rows, open(f"{OUT}/manifests/val.jsonl", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
# 直接复用现有 cv_folds.json
json.dump(cv, open(f"{OUT}/manifests/cv_folds.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

readme = f"""# 定稿训练语料包 · final_corpus_20261006

- 状态：{a.status}
- 来源轨迹：{TRACKS.name}
- 窗口裁剪：--skip-start=8（剔除开场包装帧）
- 排除清单（老程裁定，最高权威）：{V.get('exclude_clusters')}
- 命名：ASR gt_models（检测原语仅作结构佐证）
- 球质量：单列报告、不进顺畅分；ball_real_rate<0.30 标 ball_unreliable（见 labels/_quality_report.json）
- 按 ep 分组防泄漏：train {len(train_rows)} 条 / val {len(val_rows)} 条（cv_folds.json）

## 结构
frames/<pick_id>/f*.jpg   软链，仅签核通过窗口的帧
tracks/<pick_id>.json     球员逐帧坐标 + 球 xy/conf/pred
labels/asr_gt_models.json 战术名（ASR 真值）
labels/smooth_verdict.json 老程裁定
labels/_quality_report.json ID 碎片化 + 球质量
manifests/train.jsonl | val.jsonl | cv_folds.json

## 已知局限（交付训练前须知）
- ID 碎片化虚高：track_id 数 >> 每帧可见人数（见 _quality_report），所有按 ID 聚合指标带系统性虚高。
- 球检测不可靠：多数学球真检出率<30%，球轨迹仅参考。
- 顺畅分只量球员协同移动，内容级判断靠老程目视。
"""
open(f"{OUT}/README.md", "w", encoding="utf-8").write(readme)
print(f"[完成] {OUT}")
print(f"  轨迹={len(tracks_files)} 帧={frames_total} 轨迹点={points_total} "
      f"train={len(train_rows)} val={len(val_rows)} ball_unreliable={len(ball_unreliable)}")
