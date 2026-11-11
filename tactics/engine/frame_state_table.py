#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frame_state_table (T2) —— sas_det 逐帧状态表：比赛钟 × PBP 对齐。

输入:
  action_work/validate/sas_det_scorebug.json  (A4.27 T1 产出, 400 帧比赛钟读数)
  public.play_by_play  gameid='22400802'  period=1  (501 行, 只读)

方法:
  1) 帧→比赛时间: t(f)=60.04+(f-1)*0.1 (f00001=视频60.04s, DELTA=1 铁律), 
     remaining(f)=C−t(f); C 由 T1 的 37 个变点做区间交拟合(报告可行域宽度)。
     NBA PBP 口径: 事件 clock_seconds=v ⇒ 事件发生在「钟显示 v」的那一秒内,
     与帧 display floor 同一口径 ⇒ 事件 cs=v ↔ 显示 v 的 10 帧窗口(秒内歧义)。
  2) 逐帧状态: confirmed_events(cs>=display+1, 确定已发生) / pending_events(cs==display,
     秒内歧义) 分列; possession=最后确认事件 current_team; score=h_pts/a_pts 前向填充。
  3) 活/死球状态机: 哨响事件(Foul/Violation/Timeout/Instant Replay/Jump Ball)开死球,
     至下一活球动作(Made/Missed Shot/Rebound/Turnover)恢复; 显示冻结>=2s 为独立佐证。

验收(独立于状态机):
  A) PBP 事件 cs 全部落入其 display 秒的解码帧窗口(37 变点约束);
  B) 关键落点视觉抽查: Fox 抢断/三分不中/Duren 篮板/犯规罚球 4 处渲染目视;
  C) 比分单调 + 本段终态 0-2(Harris 两罚全中) 与 PBP 自洽。

产出: action_work/validate/sas_det_frame_states.json (只读 DB, 零写)
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

import numpy as np

from common.nba_paths import repo_file, tactics_data_file

sys.path.insert(0, str(repo_file("backend")))
import psycopg2
from core.config import DB_CONFIG

ROOT = Path(str(tactics_data_file("")))
SCOREBUG = ROOT / "action_work" / "validate" / "sas_det_scorebug.json"
OUT = ROOT / "action_work" / "validate" / "sas_det_frame_states.json"
FR = ROOT / "action_work" / "sas_det"
GAMEID = "22400802"
T0, FPS = 60.04, 10.0                 # f00001 视频秒; 10fps
N_FRAMES = 400
# 哨响(开死球) / 活球动作(恢复) 事件类型(本库 event_type 词表, 已实测)
# v1 简化: Jump Ball 视为活球开始(tip 后立即活, 实证 f1-f5 比赛进行中);
#          Instant Replay 本窗未出现, 暂列 whistle。
WHISTLE = {"Foul", "Violation", "Timeout", "Instant Replay"}
LIVE_ACTION = {"Made Shot", "Missed Shot", "Rebound", "Turnover", "Jump Ball"}


def load_clock():
    data = json.loads(SCOREBUG.read_text())
    rows = data["rows"]
    assert len(rows) == N_FRAMES
    return rows


def load_pbp():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT eventnum, clock, clock_seconds, event_type, team, player1_name, player2_name,
               h_pts, a_pts, current_team, description
        FROM public.play_by_play WHERE gameid=%s AND period=1 ORDER BY eventnum
    """, (GAMEID,))
    evs = [dict(zip("eventnum clock cs etype team p1 p2 h_pts a_pts cur desc".split(), r))
           for r in cur.fetchall()]
    conn.close()
    return evs


def fit_C(changes, t_of):
    """稳健拟合 remaining=C−t 的常数 C。
    每个变点 (f,v) 给区间 C ∈ [max(660+v+t(f), 661+v+t(f−1)), min(661+v+t(f), 662+v+t(f−1)))。
    台标显示端存在偶发 1-tick 更新延迟(实测 f127/f217 晚 1 帧) ⇒ 少数变点区间右移 0.1s,
    全体会交为空。稳健处理: C 取「变点区间 lo 的中位 .. hi 的中位」中点,
    报告支持率(区间含 C 的变点数)与抖动变点清单。"""
    ivs = []
    for f, v in changes:
        l = max(660 + v + t_of[f], 661 + v + t_of[f - 1])
        h = min(661 + v + t_of[f], 662 + v + t_of[f - 1])
        ivs.append((f, v, l, h))
    los = sorted(x[2] for x in ivs)
    his = sorted(x[3] for x in ivs)
    n = len(ivs)
    med_lo, med_hi = los[n // 2], his[n // 2]
    C = (med_lo + med_hi) / 2
    support = [(f, v) for f, v, l, h in ivs if l <= C < h]
    jitter = [(f, v) for f, v, l, h in ivs if not (l <= C < h)]
    return C, med_lo, med_hi, support, jitter


def main():
    clock_rows = load_clock()
    t_of = {r["fid"]: T0 + (r["fid"] - 1) / FPS for r in clock_rows}
    display_of = {r["fid"]: 660 + r["clock"]["ss_total"] for r in clock_rows}

    # 变点表(与 T1 复算一致)
    changes = []
    for i in range(1, N_FRAMES):
        a, b = display_of[i], display_of[i + 1]
        if b != a:
            assert b == a - 1, f"变点非±1: f{i}:{a}->{b}"
            changes.append((i + 1, b - 660))     # SS 秒数(fit_C 内部再加 660)
    C, med_lo, med_hi, support, jitter = fit_C(changes, t_of)
    print(f"[fit] C={C:.3f} (多数派区间 [{med_lo:.3f},{med_hi:.3f})), "
          f"支持 {len(support)}/{len(changes)} 变点, 显示抖动变点: {jitter}")
    print(f"      即 Q1 开球(720s)在视频 t={C-720:.2f}s")
    # 显示抖动帧(逐帧级): est=floor(C−t) 与解码 display 不一致的帧
    jitter_frames = []
    for r in clock_rows:
        fk = r["fid"]
        est = int(np.floor(C - t_of[fk]))
        if est != display_of[fk]:
            jitter_frames.append({"fid": fk, "decoded": display_of[fk], "est": est})
    print(f"      逐帧 est vs 解码不一致: {len(jitter_frames)}/{N_FRAMES} 帧 "
          f"{[(j['fid'], j['decoded'], j['est']) for j in jitter_frames][:8]}")

    evs = load_pbp()
    print(f"[pbp] Q1 事件 {len(evs)} 条")

    # ---- 逐帧状态 ----
    # 显示窗口宽度: 同一 display 值连续帧数。走表期正常 ~10 帧(1s@10fps)。
    # 🔴 抖动 vs 冻结判据(物理: 走表速率守恒): 显示端 1-tick 抖动会把一窗拉长 1 帧
    #    (w=11) 而相邻窗短 1 帧(w=9) — 总量守恒; 真死球窗无互补亏损。
    #    frozen ⟺ excess=w−10 > 相邻窗亏损之和 (10−prev_w) + (10−next_w)。
    win_width, win_span = {}, {}
    fids_sorted = sorted(display_of)
    s = fids_sorted[0]
    spans = []
    for a, b in zip(fids_sorted, fids_sorted[1:] + [None]):
        if b is None or display_of[b] != display_of[a]:
            spans.append((s, a, a - s + 1))
            s = b
    for i, (s0, e0, w0) in enumerate(spans):
        for fk in range(s0, e0 + 1):
            win_width[fk] = w0
            win_span[fk] = i
    rows = []
    for r in clock_rows:
        fk = r["fid"]
        disp = display_of[fk]
        rem = C - t_of[fk]
        confirmed = [e for e in evs if e["cs"] is not None and e["cs"] >= disp + 1]
        pending = [e for e in evs if e["cs"] is not None and e["cs"] == disp]
        last = confirmed[-1] if confirmed else None
        # 证据链 1: 状态机(从最后确认事件向后看哨响)
        machine_dead, machine_note = False, ""
        if last is not None:
            idx = evs.index(last)
            for k in range(idx, len(evs)):
                e = evs[k]
                if e["cs"] is None or e["cs"] < disp + 1:
                    break
                if e["etype"] in WHISTLE:
                    machine_dead, machine_note = True, f"whistle@#{e['eventnum']}({e['etype']})"
                    break
                if e["etype"] in LIVE_ACTION:
                    break
        # 证据链 2: 窗口宽 excess vs 邻窗亏损(独立于 PBP 的物理证据)
        i = win_span[fk]
        s0, e0, w = spans[i]
        excess = w - 10
        deficit = 0
        if i > 0:
            deficit += max(0, 10 - spans[i - 1][2])
        if i < len(spans) - 1:
            deficit += max(0, 10 - spans[i + 1][2])
        frozen = excess > deficit and excess > 0
        pending_whistle = [e for e in pending if e["etype"] in WHISTLE]
        if frozen:
            state = "dead"
            state_note = (f"clock frozen: window {w} frames (excess {excess} > deficit {deficit})"
                          + (f"; machine: {machine_note}" if machine_dead else ""))
        elif machine_dead:
            state = "dead"
            state_note = machine_note
        else:
            state = "live"
            state_note = ("whistle pending in-second" if pending_whistle else "")
        # possession / score(只取确认事件; pending 得分秒内歧义如实标注)
        poss = last["cur"] if last else None
        h = a = 0.0
        for e in evs:
            if e["cs"] is None or (last and e["eventnum"] > last["eventnum"]):
                break
            if e["h_pts"] is not None:
                h = e["h_pts"]
            if e["a_pts"] is not None:
                a = e["a_pts"]
        pend_desc = "; ".join(f"#{e['eventnum']} {e['etype'] or 'Info'}({e['team']}) {e['desc']}"
                              for e in pending)
        rows.append({
            "fid": fk, "frame": r["frame"], "display_clock": f"{disp//60}:{disp%60:02d}",
            "display_sec": disp, "remaining_est": round(rem, 2),
            "display_window_frames": w,
            "live_state": state, "state_note": state_note,
            "possession": poss,
            "pending_events": pend_desc,
            "last_confirmed": (f"#{last['eventnum']} {last['etype']}({last['team']}) {last['desc']}"
                               if last else None),
            "score_confirmed": f"{int(a)}-{int(h)} (DET-SAS)",
        })

    # ---- 验收 A: 每个窗口内事件的 cs 落点 ----
    disp_frames = {}
    for fk, d in display_of.items():
        disp_frames.setdefault(d, []).append(fk)
    in_window_events = [e for e in evs if e["cs"] is not None and 664 <= e["cs"] <= 701]
    align = []
    for e in in_window_events:
        v = int(e["cs"])
        win = disp_frames.get(v, [])
        align.append({"event": f"#{e['eventnum']} {e['etype']} {e['desc']}", "cs": v,
                      "display_frames": f"{min(win)}-{max(win)}" if win else "无",
                      "ok": bool(win)})
    # ---- 验收 C: 比分自洽(确认口径) ----
    scores = [(r["fid"], r["score_confirmed"]) for r in rows]
    score_changes = [(scores[i][0], scores[i - 1][1], scores[i][1])
                     for i in range(1, len(scores)) if scores[i][1] != scores[i - 1][1]]

    out = {"rows": rows,
           "meta": {"gameid": GAMEID, "C_used": round(C, 3), "C_majority_interval": [round(med_lo, 3), round(med_hi, 3)],
                    "C_support": f"{len(support)}/{len(changes)}", "C_jitter_changes": jitter,
                    "display_jitter_frames": jitter_frames,
                    "t0": T0, "fps": FPS,
                    "whistle_types": sorted(WHISTLE), "live_action_types": sorted(LIVE_ACTION)},
           "acceptance": {
               "A_event_alignment": align,
               "A_all_ok": all(x["ok"] for x in align),
               "C_score_changes": score_changes,
               "n_rows": len(rows)}}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))

    print("\n=== T2 验收 ===")
    print("A) 事件↔显示窗口对齐:")
    for x in align:
        print(f"   {'OK ' if x['ok'] else 'BAD'} cs={x['cs']} ({x['cs']//60}:{x['cs']%60:02d}) "
              f"帧窗 {x['display_frames']} — {x['event']}")
    print(f"C) 比分变化点: {score_changes}")
    live_cnt = sum(1 for r in rows if r["live_state"] == "live")
    print(f"状态分布: live {live_cnt} / dead {len(rows)-live_cnt}")
    # 状态转折点
    prev = None
    for r in rows:
        if r["live_state"] != prev:
            print(f"   f{r['fid']:05d} [{r['display_clock']}] -> {r['live_state']} "
                  f"({r['state_note'] or r['pending_events'][:60]})")
            prev = r["live_state"]
    print(f"[out] {OUT}")


if __name__ == "__main__":
    main()
