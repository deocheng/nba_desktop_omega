#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.11 老程逐帧裁定落盘 + 帧级指标核算（2026-10-01）。

老程裁定（原文）：
  ep24 : 「0.65，0.40，0.48，0.49都是观众啊，不可能有大幅移动，场上10个球员，有一个是红框」
  ep19 : 「0.69是场边裁判，0.00也是，黑裤子灰背心很明显，0.00周围都是观众明显在场外，
         场上有9个球员，有一个没被框选在0.38后方」

反推（人数自洽校验）：
  ep24 场上球员 10 个、9 个进 Top13 ⇒ Top13(13) = 9 球员 + 4 观众。
      4 个观众 ⟺ 老程列的 4 个数值：0.65 / 0.40 / 0.48 / 0.49
      ⇒ 两个 0.65 里只有 1 个是观众（#3 坐看台），另一个 #4 是球员。
      被丢的球员 = 红框里那个 1 个。
  ep19 检测数 12 ≤ K=13 ⇒ **Top-K 未触发**，一个都没丢；
      场上 9 球员里 1 个**检测器漏检**（不在任何框里）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
NUM = ROOT / "action_work" / "track_judge" / "num"

V = {
    "ep24_s1": {
        "idx": 70, "k": 13,
        "n_det": 31,
        "spectator_topk_nos": [3, 13, 9, 8],   # 0.65 / 0.40 / 0.48 / 0.49
        "spectator_note": "4 个数值对应 4 个观众框；两个 0.65 里 #3 是坐看台的观众，#4 据人数自洽反推为球员",
        "player_missed_in_dropped_no": 22,      # 红框里的场上球员
        "player_missed_note": "持球太阳球员，105x166px，m=0.21 被丢",
        "on_court_players": 10,
        "players_in_topk": 9,
    },
    "ep19_s0": {
        "idx": 77, "k": 13,
        "n_det": 12,
        "referee_topk_nos": [4, 12],            # 0.69 / 0.00
        "referee_note": "黑裤子灰背心；#12(0.00) 周围都是观众、明显在场外",
        "player_missed_no_box": True,
        "player_missed_anchor_no": 9,           # 在 0.38(#9) 后方
        "on_court_players": 9,
        "players_detected": 8,
    },
}


def metrics(seg):
    v = V[seg]
    items = json.load(open(NUM / f"{seg}_f{v['idx']}.json"))
    n = len(items)
    topk = [it for it in items if it["topk"]]
    if seg == "ep24_s1":
        fp = len(v["spectator_topk_nos"])
        tp = len(topk) - fp
        fn = 1                                   # 红框里 1 个球员
        prec = tp / len(topk)
        rec = v["players_in_topk"] / v["on_court_players"]
        return dict(seg=seg, idx=v["idx"], n_det=n, n_topk=len(topk),
                    topk_tp=tp, topk_fp=fp, topk_fn=fn,
                    precision=round(prec, 4), recall=round(rec, 4),
                    note="Top-K 触发；排序把 4 个观众排进前 13，把持球人挤出")
    # ep19：Top-K 未触发
    nref = len(v["referee_topk_nos"])
    tp = v["players_detected"]
    return dict(seg=seg, idx=v["idx"], n_det=n, n_topk=len(topk),
                topk_triggered=False, topk_tp=tp, topk_fp=nref,
                topk_fn=v["on_court_players"] - v["players_detected"],
                precision=round(tp / len(topk), 4),
                recall=round(v["players_detected"] / v["on_court_players"], 4),
                note="K=13 未触发（检测数≤K）；瓶颈在检测器召回，不在 Top-K")


out = {"verdicts": V, "metrics": [metrics("ep24_s1"), metrics("ep19_s0")]}
p = ROOT / "action_work" / "track_judge" / "verdicts_frames_a511.json"
json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)

for m in out["metrics"]:
    print(f"\n== {m['seg']} f{m['idx']} ==")
    print(f"  检测 {m['n_det']}  TopK 触发={m.get('topk_triggered', True)}  进池 {m['n_topk']}")
    print(f"  TopK 内: 真目标 {m['topk_tp']} / 误报 {m['topk_fp']} ；漏 {m['topk_fn']}")
    print(f"  精确率 {m['precision']:.1%}  召回 {m['recall']:.1%}")
    print(f"  {m['note']}")
print(f"\n-> {p}")
