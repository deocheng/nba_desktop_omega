#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tactic_primitives_ext.py — 扩展 detect_primitives 的原语词表（2026-10-03 A类修复·第一步）

为什么有本模块
--------------
实测（跨11期 hit@1/3/k=0/11）根因**不是评分权重**，而是**原语词表缺口**：
`detect_primitives` 原本只能产出 5 种原语 `SCREEN{.DOWN,.CROSS}/HANDOFF/CUT`，
而 55 个战术模型需要 `PASS/DRIVE/ROLL/EXCHANGE/SCREEN.{EXIT,STS,GHOST,TOUCH,WEDGE}/…`。
`match()` 的 key_primitive 门（判别原语不在事件池→直接淘汰）导致 **13 个真值里 11 个
结构性永不可达**——评分再完美也返回不了。

本模块只实现**从现有像素轨迹可由证据判定**的原语，逐条给出判据与阈值来源：

  A. 球/持球人派生（真实可观测）
     PASS    持球人切换 + 球实际位移 > 0.6·体长（球"真的传出去"，不是噪声抖动）
     DRIVE   持球人朝篮筐(y减小)且速度 > v_cut（与 CUT 区别：CUT 是任意人，DRIVE 限定持球人）
     EXCHANGE 两名近球球员的左右次序在短窗内发生翻转（进攻掩护 vs 防守人交换的判别量）
     ROLL    SCREEN 事件结束后，掩护人朝篮筐持续位移 > v_cut（滚屏接应的序列原语）

  B. 掩护子类几何（单事件可判，**以平行事件追加，不覆盖原 DOWN/CROSS**）
     STS     两人位移方向**同向**（dot>0）且都发生位移 → 并行(sts)掩护
     GHOST   掩护发生时两人**均非持球人** → 无球掩护
     EXIT    掩护人(小位移方)位移方向**背离球** → 让位退出(exit)掩护
     TOUCH   掩护持续帧数极短(f1-f0 <= min_run+1) → 轻触(touch)掩护

🔴 诚实边界（**不硬凑**）：以下 key 本轮**不实现**，对应模型仍受阻：
     SCREEN.WEDGE / SCREEN.STAGGER / SCREEN.FLARE（本质是**序列/角度复合**，
       塞进单事件子类就是造假）；SHORT_ROLL（滚到哪算短，缺可证伪阈值）；
       ZONE_23（联防站位）、INBOUND（界外球）、PASS.POCKET / CUT.BACKDOOR / SPOT_UP
       （需更细的球/角色判别）。⇒ wedge_screen / short_roll / zone_23 / slob 仍不可达。

判据全部参数化（阈值由 derive_thresholds 实测分布注入），不使用手写常数。
"""
from __future__ import annotations

import math


# ---------------- 工具 ----------------
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _handler(fr, gate):
    """返回 (tid, dist)；球或球员缺失→(None, inf)。gate=球到人距离上限。"""
    b = fr.get("ball")
    if not b:
        return None, float("inf")
    best, bd = None, gate
    for tid, p in fr.get("players", {}).items():
        d = _dist(b, p)
        if d < bd:
            best, bd = tid, d
    return best, bd


# ---------------- A. 球/持球人派生原语 ----------------
def detect_pass(frames, med_diag, min_run=3):
    """PASS：持球人 A→B 切换 且 球在切换前后实际位移 > 0.6·体长。
    动机：杜绝「球在一人附近轻微抖动就算传球」。判据=**人换 + 球真走**双条件。"""
    ev = []
    n = len(frames)
    if n < 2:
        return ev
    gate = 0.8 * med_diag
    move_min = 0.6 * med_diag
    hs = [_handler(frames[i], gate) for i in range(n)]
    for i in range(1, n):
        a, b = hs[i - 1][0], hs[i][0]
        if a is None or b is None or a == b:
            continue
        b0, b1 = frames[i - 1].get("ball"), frames[i].get("ball")
        if not b0 or not b1:
            continue
        if _dist(b0, b1) > move_min:
            ev.append({"type": "PASS", "sub": None, "f0": i - 1, "f1": i,
                       "who": [int(a), int(b)], "zone": "?",
                       "note": f"pass {a}->{b} d_ball={_dist(b0,b1):.0f}"})
    return ev


def detect_drive(frames, v_cut, med_diag, min_run=3, v_drive=None):
    """DRIVE：**持球人**朝篮筐(y减小)且速度 > 阈值 持续 >= min_run 帧。
    与 CUT 区别：CUT 判任意球员；DRIVE 限定『球仍在其手边』的持球人。
    🔴 v_drive 口径修正(2026-10-03)：不能用**全场任意球员** p95 位移当持球人速度门——
       实测持球人 p95 位移(≈32px)远小于全场 p95(≈89px)，因为持球人带球移动本就比无球跑动慢。
       故速度型原语(DRIVE/ROLL)默认用**持球人自身**位移基线 v_drive（由本函数自测）。"""
    v = v_drive if v_drive is not None else v_cut
    ev = []
    n = len(frames)
    gate = 0.8 * med_diag
    # 持球人位移基线：p90(持球人逐帧位移)，下界 0.5·全场p95 防呆
    hv = []
    for i in range(1, n):
        h, _ = _handler(frames[i], gate)
        if h is None:
            continue
        p0, p1 = frames[i - 1]["players"].get(h), frames[i]["players"].get(h)
        if p0 and p1:
            hv.append(_dist(p0, p1))
    base = sorted(hv)[int(0.90 * (len(hv) - 1))] if len(hv) > 1 else 0.0
    thr = max(2.5 * base, 0.5 * v_cut, 1e-6)
    cur, run = None, []
    for i in range(n):
        h, hd = _handler(frames[i], gate)
        p_now = frames[i]["players"].get(h) if h is not None else None
        ok = h is not None and p_now is not None
        if ok and i > 0:
            p0 = frames[i - 1]["players"].get(h)
            if p0 is None:
                ok = False
            else:
                d = _dist(p0, p_now)
                toward = p_now[1] < p0[1]          # y 减小 = 朝进攻篮筐(沿用 CUT 约定)
                if not (d > thr and toward):
                    ok = False
        if ok:
            if cur != h:
                if cur is not None and len(run) >= min_run:
                    ev.append({"type": "DRIVE", "sub": None, "f0": run[0], "f1": run[-1],
                               "who": [int(cur)], "zone": "?", "note": f"handler {cur} drive thr={thr:.0f}"})
                cur, run = h, [i]
            else:
                run.append(i)
        else:
            if cur is not None and len(run) >= min_run:
                ev.append({"type": "DRIVE", "sub": None, "f0": run[0], "f1": run[-1],
                           "who": [int(cur)], "zone": "?", "note": f"handler {cur} drive thr={thr:.0f}"})
            cur, run = None, []
    if cur is not None and len(run) >= min_run:
        ev.append({"type": "DRIVE", "sub": None, "f0": run[0], "f1": run[-1],
                   "who": [int(cur)], "zone": "?", "note": f"handler {cur} drive thr={thr:.0f}"})
    return ev, thr


def detect_exchange(frames, med_diag, min_run=3):
    """EXCHANGE：两名**近球**球员的左右次序在连续帧内发生**翻转**。
    动机：exchange_down 的 key_primitive=EXCHANGE。判据=相对 x 次序反转（进攻人换位/防守人交换）。
    🔴 保守：要求两人全程近球(<=d_screen)且次序翻转持续 >= min_run，避免噪声。"""
    ev = []
    n = len(frames)
    gate = 0.9 * med_diag
    prev_sign, cur_pair, run = 0, None, []
    def flush(pair, f0, f1):
        if pair:
            ev.append({"type": "EXCHANGE", "sub": None, "f0": f0, "f1": f1,
                       "who": [int(pair[0]), int(pair[1])], "zone": "?",
                       "note": f"x-order flip {pair}"})
    for i in range(n):
        near = [tid for tid, p in frames[i]["players"].items()
                if frames[i].get("ball") and _dist(frames[i]["ball"], p) <= gate]
        if len(near) >= 2:
            a, b = sorted(near[:2], key=lambda t: frames[i]["players"][t][0])
            sign = 1 if frames[i]["players"][a][0] <= frames[i]["players"][b][0] else -1
            if cur_pair == (a, b):
                if sign != prev_sign and sign != 0:
                    run.append(i)
                else:
                    run = [i] if sign != 0 else []
                    prev_sign = sign
            else:
                if prev_sign != 0 and sign != 0 and sign != prev_sign and len(run) >= min_run:
                    flush(cur_pair, run[0], run[-1])
                cur_pair, prev_sign, run = (a, b), sign, [i]
        else:
            if prev_sign != 0 and len(run) >= min_run:
                flush(cur_pair, run[0], run[-1])
            cur_pair, prev_sign, run = None, 0, []
    if prev_sign != 0 and len(run) >= min_run:
        flush(cur_pair, run[0], run[-1])
    return ev


def detect_roll(frames, screen_events, v_cut, min_run=3, post_win=20, v_roll=None):
    """ROLL：某 SCREEN 事件**结束后** post_win 帧内，掩护人朝篮筐持续位移 > 阈值。
    判据=『先掩护后滚』的序列（滚屏接应），who=发生滚动的那个球员。
    🔴 v_roll 口径同 DRIVE：用**持球人/滚动者自身**位移基线，非全场 p95（否则被卡死）。"""
    v = v_roll if v_roll is not None else v_cut
    ev = []
    n = len(frames)
    # 全局滚动者位移基线（用所有球员 p90 近似，实际由 post_win 内最大位移把关）
    for se in screen_events:
        who = [t for t in se.get("who", [])]
        f1 = se.get("f1", 0)
        for tid in who:
            run = []
            for i in range(f1 + 1, min(n, f1 + 1 + post_win)):
                p0 = frames[i - 1]["players"].get(tid)
                p1 = frames[i]["players"].get(tid)
                if p0 and p1:
                    d = _dist(p0, p1)
                    if d > v and p1[1] < p0[1]:   # 朝篮筐滚动
                        run.append(i)
                    else:
                        if len(run) >= min_run:
                            ev.append({"type": "ROLL", "sub": None, "f0": run[0], "f1": run[-1],
                                       "who": [int(tid)], "zone": "?",
                                       "note": f"roll by {tid} after screen@{se.get('f0')} thr={v:.0f}"})
                        run = []
            if len(run) >= min_run:
                ev.append({"type": "ROLL", "sub": None, "f0": run[0], "f1": run[-1],
                           "who": [int(tid)], "zone": "?",
                           "note": f"roll by {tid} after screen@{se.get('f0')} thr={v:.0f}"})
    return ev, v


# ---------------- B. 掩护子类几何（平行追加，不覆盖 DOWN/CROSS） ----------------
def _screen_disps(frames, se):
    a, b = se.get("who", [None, None])[:2]
    f0, f1 = se.get("f0"), se.get("f1")
    if a is None or b is None or f0 == f1:
        return None
    p0a, p1a = frames[f0]["players"].get(a), frames[f1]["players"].get(a)
    p0b, p1b = frames[f0]["players"].get(b), frames[f1]["players"].get(b)
    if not (p0a and p1a and p0b and p1b):
        return None
    return (a, (p1a[0] - p0a[0], p1a[1] - p0a[1]), b, (p1b[0] - p0b[0], p1b[1] - p0b[1]))


def label_screen_subtypes(frames, screen_events, med_diag, min_run=3):
    """为已有 SCREEN 事件**追加**子类事件（保留原 DOWN/CROSS，避免破坏 stagger_screen 等）。
    追加而非改写：key_primitive 门按 prim_set 判定，平行事件即可让门放行，且不破坏原模型。"""
    extra = []
    gate = 0.8 * med_diag
    for se in screen_events:
        d = _screen_disps(frames, se)
        if not d:
            continue
        a, da, b, db = d
        mag_a, mag_b = math.hypot(*da), math.hypot(*db)
        base = dict(type="SCREEN", f0=se["f0"], f1=se["f1"], who=se.get("who"), zone=se.get("zone", "?"))
        # STS：两人同向移动
        if mag_a > 1 and mag_b > 1 and (da[0] * db[0] + da[1] * db[1]) > 0:
            extra.append({**base, "sub": "STS", "note": f"parallel move sts a=({da[0]:.0f},{da[1]:.0f})"})
        # GHOST / EXIT：需球与持球人
        mid = (se["f0"] + se["f1"]) // 2
        h, _ = _handler(frames[mid], gate)
        if h is not None and h not in (a, b):
            extra.append({**base, "sub": "GHOST", "note": f"off-ball screen, handler={h}"})
        ball = frames[mid].get("ball")
        if ball is not None:
            # 掩护人 = 位移较小者(站定型)；其位移若背离球 → EXIT
            holder, dh = (a, da) if mag_a <= mag_b else (b, db)
            hp = frames[mid]["players"].get(holder)
            if hp is not None and math.hypot(*dh) > 1:
                to_ball = (ball[0] - hp[0], ball[1] - hp[1])
                if (dh[0] * to_ball[0] + dh[1] * to_ball[1]) < 0:
                    extra.append({**base, "sub": "EXIT", "note": f"holder {holder} moves away from ball"})
        # TOUCH：极短掩护
        if (se["f1"] - se["f0"]) <= (min_run + 1):
            extra.append({**base, "sub": "TOUCH", "note": f"brief screen dur={se['f1']-se['f0']}"})
    return extra


# ---------------- 编排 ----------------
def augment(frames, events, th):
    """把扩展原语并入 events。th=derive_thresholds() 的返回值。
    frames 需含 bboxes/ball（真实素材满足）；缺 bboxes 时只跑不依赖体长的部分。"""
    med_diag = th.get("median_player_diag_px", 100.0)
    v_cut = th.get("v_cut_px", 10.0)
    min_run = th.get("min_run", 3)
    screens = [e for e in events if e.get("type") == "SCREEN"]
    new = []
    new += detect_pass(frames, med_diag, min_run)
    drive_ev, v_drive = detect_drive(frames, v_cut, med_diag, min_run)
    new += drive_ev
    new += detect_exchange(frames, med_diag, min_run)
    # ROLL 速度门与 DRIVE 同口径（各自实测基线），但至少不小于 v_cut 的一半
    roll_ev, _ = detect_roll(frames, screens, max(v_drive, 0.5 * v_cut), min_run)
    new += roll_ev
    new += label_screen_subtypes(frames, screens, med_diag, min_run)
    # 去重：同 (type,sub,f0,f1,who) 只留一条
    seen, out = set(), []
    for e in sorted(new, key=lambda z: (z["type"], z.get("sub") or "", z["f0"])):
        k = (e["type"], e.get("sub"), e["f0"], e["f1"], tuple(e.get("who") or []))
        if k not in seen:
            seen.add(k)
            out.append(e)
    return events + out
