# -*- coding: utf-8 -*-
"""
update_smooth_verdict.py — 老程裁定更新 + 一键重跑（Task 2）
总原则：裁定权归老程；smooth_verdict_laocheng.json 是「顺畅进攻语料」的唯一权威来源；
        机器打分只排序/推荐，最终以本文件为准（裁定 > 打分）。

用法：
  # 方式A：把老程口头裁定写进一个 json 文件，再跑
  python update_smooth_verdict.py --verdicts my_verdicts.json --rerun
  # 方式B：命令行内联
  python update_smooth_verdict.py --set "11:EXCLUDE,22:EXCLUDE,17:KEEP" --rerun
  # 方式C：只更新裁定文件、不重跑（--dry-run 默认）
  python update_smooth_verdict.py --set "17:KEEP"

verdicts.json 示例: {"11":"EXCLUDE","22":"EXCLUDE","17":"KEEP"}
  verdict 取值: KEEP | EXCLUDE | DISREGARD | pending

行为：
  1. 载入 smooth_verdict_laocheng.json（若不存在则建基线，排除清单=[2,12,19,21,27,31,33]）
  2. 合并新裁定 -> reviews + 重算 exclude_clusters（基线 ∪ 新 EXCLUDE/DISREGARD；KEEP 移除）
  3. 写回 smooth_verdict_laocheng.json（单一权威源）
  4. --rerun: 调 pick_smooth_offense_ext.py --out-suffix v2 + gen_smooth_review.py 生成 v2 轨迹与复核页

版本号：v2 轨迹落在 norm_calib/smooth_tracks_game20_v2/，复核页 smooth_review_game20_v2.html
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import subprocess
import sys

from common.nba_paths import tactics_data_file

NC = str(tactics_data_file("action_work/norm_calib"))
VF = f"{NC}/smooth_verdict_laocheng.json"
BASELINE_EXCLUDE = [2, 12, 19, 21, 27, 31, 33]

ap = argparse.ArgumentParser()
ap.add_argument("--verdicts", help="裁定 json 文件: {cluster: verdict}")
ap.add_argument("--set", help="内联裁定: '11:EXCLUDE,22:EXCLUDE,17:KEEP'")
ap.add_argument("--rerun", action="store_true", help="更新后一键重跑导出 v2")
ap.add_argument("--suffix", default="_v2", help="重跑导出后缀(默认 _v2)")
ap.add_argument("--pool", default="game20")
ap.add_argument("--skip-start", type=int, default=8)
a = ap.parse_args()

# ---- 1. 载入/建基线 ----
if os.path.exists(VF):
    V = json.load(open(VF, encoding="utf-8"))
else:
    V = {"_source": "基线（待老程目视裁定）", "_authority": "老程目视裁定 > 机器打分",
         "reviews": {}, "_lesson": "", "exclude_clusters": list(BASELINE_EXCLUDE),
         "_exclude_reason": {}}

def parse_new():
    d = {}
    if a.verdicts:
        d.update({int(k): v for k, v in json.load(open(a.verdicts, encoding="utf-8")).items()})
    if a.set:
        for part in a.set.split(","):
            part = part.strip()
            if not part:
                continue
            cid, vd = part.split(":", 1)
            d[int(cid)] = vd.strip().upper()
    return d

new = parse_new()
if not new:
    print("[warn] 无新裁定输入（用 --verdicts 或 --set）。仅展示当前状态。")
else:
    print(f"[合并] 新裁定 {len(new)} 条：{new}")

reviews = V.setdefault("reviews", {})
changed = []
for cid, vd in new.items():
    cid = int(cid); vd = vd.upper()
    rec = reviews.get(str(cid), {})
    rec["verdict"] = vd
    if vd == "KEEP":
        rec["confirm"] = rec.get("confirm") or "老程裁定 KEEP（保留为顺畅候选）"
    elif vd in ("EXCLUDE", "DISREGARD"):
        rec["confirm"] = rec.get("confirm") or "老程裁定剔出（不进顺畅语料）"
    reviews[str(cid)] = rec
    changed.append((cid, vd))

# ---- 2. 重算 exclude_clusters（裁定 > 打分）----
exclude = set(BASELINE_EXCLUDE)
for cid, rec in reviews.items():
    if rec.get("verdict") in ("EXCLUDE", "DISREGARD"):
        exclude.add(int(cid))
    elif rec.get("verdict") == "KEEP":
        exclude.discard(int(cid))
V["exclude_clusters"] = sorted(exclude)
# 同步 _exclude_reason
er = V.setdefault("_exclude_reason", {})
for cid, rec in reviews.items():
    if rec.get("verdict") in ("EXCLUDE", "DISREGARD"):
        er.setdefault(str(cid), rec.get("issue") or rec.get("confirm") or "老程裁定剔出")
    else:
        er.pop(str(cid), None)
V["_exclude_reason"] = er
V["_authority"] = "老程目视裁定 > 机器打分"
V["_note_exclude"] = ("老程目视裁定优先于机器分：上列簇即使机器分高也一律不进顺畅进攻语料。"
                      "KEEP 的簇从排除清单移除。")

# ---- 3. 写回 ----
json.dump(V, open(VF, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"[写入] {VF}")
print(f"  exclude_clusters = {V['exclude_clusters']}")
if changed:
    print(f"  本次变更: {changed}")

# ---- 4. 一键重跑 ----
if a.rerun:
    py = sys.executable
    print(f"\n[重跑] pick_smooth_offense_ext.py --pool {a.pool} --skip-start {a.skip_start} --out-suffix {a.suffix}")
    rc = subprocess.run([py, "pick_smooth_offense_ext.py", "--pool", a.pool,
                         "--skip-start", str(a.skip_start), "--out-suffix", a.suffix],
                        cwd=os.path.dirname(os.path.abspath(__file__)))
    if rc.returncode != 0:
        raise SystemExit(f"pick 失败 rc={rc.returncode}")
    picks_v2 = f"{NC}/smooth_picks_{a.pool}{a.suffix}.json"
    out_v2 = f"{NC}/smooth_review_{a.pool}{a.suffix}.html"
    print(f"[重跑] gen_smooth_review.py --picks {picks_v2} --out {out_v2}")
    rc = subprocess.run([py, "gen_smooth_review.py", "--picks", picks_v2, "--out", out_v2],
                        cwd=os.path.dirname(os.path.abspath(__file__)))
    if rc.returncode != 0:
        raise SystemExit(f"review 失败 rc={rc.returncode}")
    print(f"\n[完成] v2 轨迹 → {NC}/smooth_tracks_{a.pool}{a.suffix}/  · 复核页 → {out_v2}")
else:
    print("\n[提示] 未带 --rerun，仅更新裁定文件。加 --rerun 可一键导出 v2。")
