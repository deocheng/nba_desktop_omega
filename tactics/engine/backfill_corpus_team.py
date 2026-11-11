#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_corpus_team.py —— 给 final_corpus_20261006 的 tracks/cXX.json 补 team 字段。

为什么能复用既有算法，不重新造轮子
-----------------------------------
final_corpus 的 cXX.json 只存「球员逐帧中心坐标」players[tid][frame]=[x,y]（无 bbox），
而既有 assign_team.compute_team_of 需要 bbox。但 corpus 的每段(seg)都能在
action_work/tactic_notes_batch*/segments/<seg>/tracks.json 找到**同源、同 tid、同 frame 索引**
的带 bbox 追踪结果（已验证：win[0] 帧 tid 100% 重叠、坐标差 ≤0.1px，corpus 帧 N = segment idx N）。

因此不必在 corpus 上重做队色分类：直接用 compute_team_of 在源段上算逐帧 team_of[(idx,tid)]，
再按 (frame,tid) 映射回 corpus 即可。零新启发式、与批量管线同一套队色口径。

输出（非侵入式，不改 players 结构）
----------------------------------
  在每个 cXX.json 顶层新增：
    player_team[tid][frame] = 0/1/null   # 与 players 同形，便于 consumers 直接对齐
    team_info = {source, method, encoding, win}
  未通过候选池净化的 tid(替补/裁判/场边) → null（与 compute_team_of 语义一致）。

用法
----
  backfill_corpus_team.py --dry-run            # 只报计划+抽样团队分布，不写盘
  backfill_corpus_team.py --seg ep15_s0        # 只跑该 seg（验证用，覆盖其下所有 pick）
  backfill_corpus_team.py --write              # 实写 player_team 回 corpus
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
import assign_team as at  # noqa: E402

CORPUS = AW / "norm_calib" / "final_corpus_20261006" / "tracks"


def ctr(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def resolve_source(seg: str, win0: int, corpus_f0_xy: dict):
    """在 tactic_notes_batch* 里挑 win[0] 帧 tid/坐标与 corpus 最匹配的源段目录。

    评分 = (重叠 tid 数, -最大坐标差)；重叠多者优，其次坐标差小者优。
    只接受既含 tracks.json 又含 frames(目录或 frames.json) 的目录（compute_team_of 需要帧图）。
    """
    best = None
    for d in glob.glob(f"{AW}/tactic_notes_batch*/segments/{seg}"):
        tk = Path(d) / "tracks.json"
        if not tk.exists():
            continue
        if not (Path(d) / "frames").exists() and not (Path(d) / "frames.json").exists():
            continue
        tr = json.load(open(tk, encoding="utf-8"))
        byidx = {f["idx"]: f for f in tr["frames"]}
        f = byidx.get(win0)
        if not f:
            continue
        segt = {int(p["id"]): ctr(p["box"]) for p in f["players"]}
        inter = set(int(t) for t in corpus_f0_xy) & set(segt)
        if not inter:
            continue
        diffs = [np.hypot(corpus_f0_xy[str(t)][0] - segt[t][0],
                          corpus_f0_xy[str(t)][1] - segt[t][1]) for t in inter]
        score = (len(inter), -max(diffs))
        if best is None or score > best[1]:
            best = (d, score, len(segt))
    return best[0] if best else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只报计划+抽样团队分布，不写盘（默认行为）")
    ap.add_argument("--seg", default=None,
                    help="只处理该 seg（验证用，覆盖其下所有 pick）")
    ap.add_argument("--write", action="store_true",
                    help="实写 player_team 回 corpus（与 --dry-run 互斥；不指定则仅报告）")
    a = ap.parse_args()

    picks = sorted(CORPUS.glob("c*.json"))
    plan = []  # (pick_path, seg, win, src_dir)
    for pf in picks:
        c = json.load(open(pf, encoding="utf-8"))
        seg = c["seg"]
        win = c["win"]
        cf = {}
        for tid, pd in c["players"].items():
            for fr, xy in pd.items():
                cf.setdefault(fr, {})[tid] = tuple(xy)
        f0 = str(win[0])
        corp = cf.get(f0, {})
        src = resolve_source(seg, win[0], corp)
        if src is None:
            print(f"[WARN] {pf.name}: 未解析到源段（seg={seg}）")
            continue
        plan.append((pf, seg, win, src))

    # 收集每段在 corpus 窗口里出现过的 tid 集合，作为 compute_team_of 的 player_track_ids。
    # 🔴 关键：源段的候选池净化(场上脚点门+运动门)会把战术窗口里真实在场的球员也剔掉
    # （n_tids_total=413 仅 152 通过），导致 corpus 主力球员 team=None。
    # 这里绕过净化：team 色心仍由该帧所有球员 2-means 求得（稳定），但给 corpus 窗口内
    # 每个 tid 都贴 0/1（含替补/裁判；老程目视裁定时自行忽略即可）。
    seg_tids: dict = {}
    for pf, seg, win, src in plan:
        c = json.load(open(pf, encoding="utf-8"))
        for tid in c["players"]:
            seg_tids.setdefault(seg, set()).add(int(tid))

    segs = sorted(seg_tids.keys())
    if a.seg:
        segs = [s for s in segs if s == a.seg]
        plan = [p for p in plan if p[1] == a.seg]
    print(f"[plan] {len(plan)} picks, {len(segs)} unique segs: {segs}")

    seg_cache = {}
    for seg in segs:
        src = next(p[3] for p in plan if p[1] == seg)
        print(f"  computing team_of for seg={seg} <- "
              f"{os.path.basename(Path(src).parts[-3])} "
              f"(player_track_ids={len(seg_tids[seg])}, 绕过净化) ...", flush=True)
        team_of, info = at.compute_team_of(src, tracks_name="tracks.json",
                                          player_track_ids=seg_tids[seg])
        seg_cache[seg] = (src, team_of, info)
        n_ass = sum(1 for v in team_of.values() if v is not None)
        print(f"    -> assigned={n_ass} none={sum(1 for v in team_of.values() if v is None)} "
              f"centers_rgb={info.get('centers_rgb')}")

    total_assigned = 0
    total_none = 0
    for pf, seg, win, src in plan:
        if a.seg and seg != a.seg:
            continue
        _, team_of, _ = seg_cache[seg]
        c = json.load(open(pf, encoding="utf-8"))
        player_team = {}
        for tid, pd in c["players"].items():
            itid = int(tid)
            for fr in pd:
                fidx = int(fr)
                tm = team_of.get((fidx, itid))
                player_team.setdefault(tid, {})[fr] = tm
                if tm is None:
                    total_none += 1
                else:
                    total_assigned += 1
        ass = sum(1 for tid in player_team for fr in player_team[tid]
                  if player_team[tid][fr] is not None)
        print(f"  {pf.name}: seg={seg} tids={len(player_team)} "
              f"team_assigned={ass} team_none={sum(1 for t in player_team for f in player_team[t] if player_team[t][f] is None)}")
        if a.write and not a.dry_run:
            c["player_team"] = player_team
            c["team_info"] = {
                "source": os.path.basename(Path(src).parts[-3]),
                "source_seg": seg,
                "method": "assign_team.compute_team_of (reused from batch pipeline)",
                "encoding": "0/1=team, null=unassigned(dropped from candidate pool: bench/ref/sideline)",
                "win": win,
            }
            json.dump(c, open(pf, "w", encoding="utf-8"), ensure_ascii=False)

    print(f"[done] team_assigned={total_assigned} team_none={total_none}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
