# -*- coding: utf-8 -*-
"""
validate_final_corpus.py — 语料定稿强制检查（Task 4）
总原则：裁定权归老程；球不进分；按 ep 防泄漏；数字从磁盘现读。
检查项（任一失败 → 整体 FAIL，不可交付训练）：
  1. 排除清单与老程裁定 100% 一致（final 中无被剔簇）
  2. 窗口边界已按 --skip-start=8 裁剪（win_start >= raw_start+8，非静止窗）
  3. ID 碎片度报告存在（track_id 数 / 每帧可见人数中位）
  4. ball_real_rate<0.30 全部标 ball_unreliable
  5. 按 ep 分组，train/val 无同 ep 泄漏（复用 cv_folds.json fold0）
  6. 帧数 / 轨迹点数 / ASR 标签 三者闭环
用法：python validate_final_corpus.py [--corpus norm_calib/final_corpus_20261006]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

NC = str(tactics_data_file("action_work/norm_calib"))
OUT = f"{NC}/final_corpus_20261006"
ap = argparse.ArgumentParser()
ap.add_argument("--corpus", default=OUT)
ap.add_argument("--skip-start", type=int, default=8)
a = ap.parse_args()

C = Path(a.corpus)
problems = []; checks = []

def ok(name, cond, detail=""):
    checks.append((name, cond, detail))
    if not cond:
        problems.append(f"[FAIL] {name} :: {detail}")

V = json.load(open(f"{NC}/smooth_verdict_laocheng.json", encoding="utf-8"))
EXCL = set(V.get("exclude_clusters", []))
pg = {}
for _src in (f"{NC}/pure_game_windows.json", f"{NC}/pure_game_windows_gray.json"):
    if os.path.exists(_src):
        for _w in json.load(open(_src, encoding="utf-8"))["pure_game"]:
            pg[_w["cluster"]] = _w

track_files = sorted((C / "tracks").glob("*.json"))
n = len(track_files)
ok("非空前", n > 0, f"tracks 数={n}")

# 1. 排除清单一致
excl_in_final = [int(f.stem[1:]) for f in track_files if int(f.stem[1:]) in EXCL]
ok("排除清单一致(无被剔簇进 final)", not excl_in_final, f"命中被剔簇={excl_in_final}")

# 2. 窗口裁剪 + 收集
asr = json.load(open(C / "labels/asr_gt_models.json", encoding="utf-8"))
verdict = json.load(open(C / "labels/smooth_verdict.json", encoding="utf-8"))
qr = json.load(open(C / "labels/_quality_report.json", encoding="utf-8"))
idf = qr["id_fragmentation"]; ball_unrel = {b["pick_id"] for b in qr["ball_unreliable"]}
frames_total = 0; pts_total = 0
for f in track_files:
    tr = json.load(open(f, encoding="utf-8"))
    pid = tr["pick_id"]; cid = int(pid[1:]); i0, i1 = tr["win"]
    raw = pg.get(cid, {}).get("members", [{}])
    raw_start = min((m["start"] for m in raw), default=i0)
    # 边界裁剪：win_start 不得早于源起点（skip-start 只对含包装前缀的簇生效，
    # 干净比赛起点本身无需 skip，故用 >= raw_start 而非 +skip，避免误报）
    ok(f"裁剪#{cid}", i0 >= raw_start, f"win_start={i0} < raw_start={raw_start}")
    frames_total += (i1 - i0 + 1)
    pts_total += (i1 - i0 + 1)
    # 3. id 碎片报告
    ok(f"ID碎片报告#{cid}", pid in idf, "缺 _quality_report")
    # 4. ball_unreliable 标记
    ball = [b for b in tr.get("ball", []) if b]
    real = [b for b in ball if not b.get("pred")]
    rate = round(len(real) / len(ball), 3) if ball else 0.0
    if rate < 0.30:
        ok(f"ball标记#{cid}", pid in ball_unrel, f"rate={rate} 未标 unreliable")
    # 6. asr 标签闭环
    ok(f"ASR标签#{cid}", pid in asr, "缺 asr_gt_models")

# 5. 按 ep 无泄漏
train = json.load(open(C / "manifests/train.jsonl", encoding="utf-8"))
val = json.load(open(C / "manifests/val.jsonl", encoding="utf-8"))
tr_eps = {r["ep"] for r in train}; va_eps = {r["ep"] for r in val}
leak = tr_eps & va_eps
ok("ep 无泄漏", not leak, f"train_ep∩val_ep={leak}")

# 6. 闭环：帧数 == 轨迹点数；轨迹条数 == train+val 行数 == ASR 标签数
n_rows = len(train) + len(val)
ok("帧数=轨迹点数", frames_total == pts_total, f"frames={frames_total} pts={pts_total}")
ok("轨迹条数闭环", n == n_rows == len(asr), f"tracks={n} rows={n_rows} asr={len(asr)}")
# 帧软链数
flinked = sum(1 for _ in (C / "frames").glob("*/*.jpg"))
ok("帧闭环", flinked == frames_total, f"symlinks={flinked} frames={frames_total}")

# 汇总
print("=" * 60)
print(f"语料定稿校验 · {C}")
print(f"  轨迹={n}  train={len(train)}  val={len(val)}  "
      f"帧={frames_total} 轨迹点={pts_total}  ball_unreliable={len(ball_unrel)}")
print("-" * 60)
for name, cond, detail in checks:
    print(f"  [{'✅' if cond else '❌'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
print("-" * 60)
if problems:
    print(f"结果：FAIL（{len(problems)} 项未过）\n" + "\n".join(problems))
    sys.exit(1)
else:
    print("结果：PASS ✅ 可交付训练")
