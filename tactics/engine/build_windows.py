#!/usr/bin/env python3
"""扩样本窗口构建：把「影片时间 ↔ 比赛读秒」映射与 PBP 事件物化成 pose_motion 的输入契约。

🔴 方法学（2026-09-23 里程碑 03 教训的直接产物）
  1. **事件时刻绝不允许手写**。本脚本只做两件事：
     ① 把「目视读秒 + 1:1 运行段验证」得到的锚点对写成 clock_table；
     ② 从权威 PBP（pbp_validation.json，gameid 22500843 period 4 全 155 事件）
        按 clock 区间筛事件、**按 clock 去重**（同一秒的 shot+rebound/block 是同一时刻）。
  2. **1:1 假设必须有证据**：每个窗口的映射都由 ≥2 个直读端点 + ≥2 个独立中段锚点
     交叉验证（见 WINDOW_DEFS 内的 `evidence` 字段）。不满足的窗口不进分析。
  3. **冻结段显式截断**：时钟 ROI 冻结检测（clip_feb25/clock_freeze.json）发现
     W3 尾部 172–175.5s、W4 尾部 199–204.5s 时钟停走 → 窗口截到冻结起点为止，
     冻结区间不假设 1:1（截断比硬拟合诚实）。

输出（每窗口）：
  <dir>/clock_table.json   {"frames":[{"frame":N,"clock_sec":X}]}   frame 与该窗口 frames.json 的 idx 对齐（frame = idx+1）
  <dir>/pbp_actions.json   {"pbp_actions":[{n,eventnum,clock,team,player,kind,detail}]}
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os

from common.nba_paths import tactics_data_file, workspace_file

PBP = str(tactics_data_file("reports/milestone_02/pbp/pbp_validation.json"))
AW = str(tactics_data_file("action_work"))

# 每窗口：影片时间区间、经交叉验证的 (t, clock) 锚点对、证据说明。
# 锚点来源：clip_feb25/sheet_*.png 目视读数 + 窗口端点直读（10fps 首末帧）。
WINDOW_DEFS = {
    "w2": {
        "t_range": (46.5, 79.9),
        "pairs": [(46.5, 255.0), (50.0, 251.0), (60.0, 241.0),
                  (70.0, 231.0), (79.9, 221.0)],
        "evidence": "端点直读 4:15/3:41；中段锚点 t=50/60/70 读 4:11/4:01/3:51，"
                    "四点均 1:1（每 10s 视频走 10s 时钟）",
    },
    "w3": {
        "t_range": (97.0, 171.0),
        "pairs": [(97.0, 182.0), (100.0, 180.0), (110.0, 170.0), (120.0, 160.0),
                  (130.0, 150.0), (140.0, 140.0), (150.0, 130.0), (160.0, 120.0),
                  (170.0, 110.0), (171.0, 109.0)],
        "evidence": "端点直读 3:02/1:48(=108,但 172s 起冻结 → 截到 171s)；"
                    "锚点 t=100..170 八点全 1:1；172–175.5s 时钟冻结已截断",
    },
    "w4": {
        "t_range": (177.0, 199.0),
        "pairs": [(177.0, 106.0), (180.0, 103.0), (190.0, 93.0), (199.0, 84.0)],
        "evidence": "端点直读 1:46/1:24；锚点 t=180/190/200 读 1:43/1:33/1:24；"
                    "199–204.5s 时钟冻结（1:24 停走）→ 截到 199s",
    },
    "w1": {
        "t_range": (204.5, 247.9),
        "pairs": None,   # 用已有 87 帧 clock_table（0.5s 分辨率）换算到 10fps 帧号
        "evidence": "已有 clock_table.json（87 帧 @2fps，里程碑 02 目视读数）",
        "src_clock_table": (str(tactics_data_file("reports/")) + "/"
                            + "milestone_02/pbp/clock_table.json"),
        "src_frames": str(workspace_file("action_work/seg_hi/frames.json")),
    },
}

# 计入场上的动作类型（Substitution/Timeout/period/Instant Replay 不算court action）
ACTION_KINDS = {"Made Shot", "Missed Shot", "Rebound", "Turnover",
                "Foul", "Violation", "Free Throw", "Jump Ball", "Block"}


def load_pbp():
    d = json.load(open(PBP))
    return d["events"]


def build_events_for_window(c_lo, c_hi, all_events):
    """取 clock∈[c_lo,c_hi] 的场上动作，按 clock 去重（同一秒=同一时刻）。"""
    sub = [e for e in all_events
           if c_lo - 0.01 <= e["clock_sec"] <= c_hi + 0.01
           and e["event_type"] in ACTION_KINDS]
    sub.sort(key=lambda e: (-e["clock_sec"], e["eventnum"]))
    out, seen = [], set()
    for e in sub:
        key = round(e["clock_sec"], 1)
        if key in seen:
            # 同一秒的并发事件（如 Missed Shot + Block）合并进 detail，不重复计时刻
            for prev in out:
                if round(prev["clock"], 1) == key:
                    prev["detail"] += f" | {e['player']} {e['event_type']}".strip()
                    break
            continue
        seen.add(key)
        kind = e["event_type"]
        if kind == "Block":
            kind = "Block"
        out.append({"n": f"e{e['eventnum']}", "eventnum": e["eventnum"],
                    "clock": round(e["clock_sec"], 1), "team": "",
                    "player": e["player"], "kind": kind,
                    "detail": e["main"]})
    return out


def main() -> int:
    all_events = load_pbp()
    summary = {}
    for name, wd in WINDOW_DEFS.items():
        t0, t1 = wd["t_range"]
        dt = 0.1
        # clock_table：frame = idx+1，t = t0 + idx*dt → frame = 1 + (t-t0)/dt
        if wd["pairs"]:
            pairs = wd["pairs"]
        else:  # w1：把 2fps 的 87 帧表换算到 10fps 帧号
            ct = json.load(open(wd["src_clock_table"]))
            pairs = [(round(t0 + (f["frame"] - 1) * 0.5, 3), float(f["clock_sec"]))
                     for f in ct["frames"] if "clock_sec" in f]
        frames = [{"frame": int(round(1 + (t - t0) / dt)), "clock_sec": c}
                  for t, c in pairs]
        os.makedirs(f"{AW}/{name}", exist_ok=True)
        json.dump({"note": wd["evidence"], "t0": t0, "dt": dt, "frames": frames},
                  open(f"{AW}/{name}/clock_table.json", "w"),
                  ensure_ascii=False, indent=1)
        # 事件：窗口映射覆盖的 clock 区间
        clocks = [c for _, c in pairs]
        c_hi, c_lo = max(clocks), min(clocks)
        evs = build_events_for_window(c_lo, c_hi, all_events)
        json.dump({"window": name, "t_range": [t0, t1],
                   "clock_range": [c_lo, c_hi], "pbp_actions": evs},
                  open(f"{AW}/{name}/pbp_actions.json", "w"),
                  ensure_ascii=False, indent=1)
        summary[name] = {"t_range": [t0, t1], "clock_range": [round(c_lo, 1), round(c_hi, 1)],
                         "n_events": len(evs),
                         "event_clocks": [e["clock"] for e in evs]}
        print(f"[{name}] t {t0}..{t1}  clock {c_lo:.1f}..{c_hi:.1f}  事件 {len(evs)} 个")
        for e in evs:
            print(f"    clock={e['clock']:>6.1f}  {e['player']:<16} {e['kind']:<14} {e['detail'][:46]}")
    tot = sum(v["n_events"] for v in summary.values())
    print(f"\n=== 四窗口合计 {tot} 个去重后场上动作时刻 ===")
    json.dump(summary, open(f"{AW}/windows_summary.json", "w"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
