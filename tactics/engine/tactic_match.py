#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tactic_match.py — 战术匹配引擎（抽象层 -> 素材发掘）
=====================================================
读 action_work/tactic_models.json（抽象战术模型）+ 一段球员/球轨道，
① 区域映射 ② 原语检测 ③ 与各模型 sequence/signature 对齐打分 ④ 输出候选战术（老程裁定）。

契约（输入轨道，球场坐标）：
  frames = [ {"t": i, "ball": (x,y)|None, "players": {tid:(x,y)}} , ... ]
  x ∈ [-250,250]（左右边线）, y ∈ [0,940]（底线->底线, 0 端为进攻篮筐侧）

真实素材接入：需 稳定化球员轨迹 + 球轨迹 + **球场配准**（把像素映射到上述坐标）。
本文件自带 --demo，用**合成轨道**跑通机制（证明匹配逻辑，不代表真实素材结果）。
纪律：只出候选+分，不盖章；signature 只用可观察量。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
import sys

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
MODELS = os.path.join(ROOT, "action_work", "tactic_models.json")

# 阈值（像素=球场单位；真实接入时应按球场配准标定，这里为骨架默认值）
D_SCREEN = 70.0     # 两人距离 < 视为掩护接触
D_HANDOFF = 70.0    # 球到持球/接手人距离 < 视为手递手
V_CUT = 10.0        # 单位/帧 速度阈值（切入；10fps 下 ≈100 单位/秒）
V_DRIVE = 15.0
CUT_NET_MIN = 80.0  # 🔧 2026-10-06 临时门（Task 5②）：CUT 须净位移≥80px 且朝筐投影严格>0，
                    # 否则把普通重定位降级为 RELOCATE（不进战术匹配）。
MIN_RUN = 3         # 事件最短持续帧


def zone_of(x, y, hoop_y=57.0):
    """粗分区（进攻半场，篮筐在 y≈57）。"""
    if math.hypot(x, y - hoop_y) < 60:
        return "RIM"
    if abs(x) < 80 and y < 190:
        return "PAINT"
    if abs(x) > 200 and y < 90:
        return "CORNER_L" if x < 0 else "CORNER_R"
    if abs(x) > 120 and 120 <= y < 300:
        return "WING_L" if x < 0 else "WING_R"
    if 190 <= y < 260:
        if -120 <= x <= -30:
            return "ELBOW_L"
        if 30 <= x <= 120:
            return "ELBOW_R"
    if y < 120:
        if -120 <= x < -30:
            return "BLOCK_L"
        if 30 < x <= 120:
            return "BLOCK_R"
    if y >= 300 and abs(x) < 120:
        return "TOP"
    return "PERIMETER" if y >= 300 else "MID"


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------------- ① 原语检测 ----------------
def detect_primitives(frames, d_screen=D_SCREEN, d_handoff=D_HANDOFF, v_cut=V_CUT, min_run=MIN_RUN,
                      disp_med=None, med_diag=None, orient=None):
    """orient: 广播像素空间的「朝筐」单位向量 (bx,by)，来自老程逐簇角点标注的朝向锚。
    为 None 时回退俯视系默认 (0,-1) = y 减小朝筐（向后兼容 --demo）。
    🔧 2026-10-04 广播像素原生修正（A3.1）：原代码硬 assumef 俯视 y 轴，在横屏广播像素下
    把「沿篮筐的掩护(DOWN)」误标成 CROSS（因侧翼视角下沿篮筐位移在像素里偏横）。
    改为把位移投影到 (朝筐 bw, 侧向 lat) 两轴再判 CROSS/DOWN 与「朝筐加速」。"""
    if orient is None:
        bw = (0.0, -1.0)
    else:
        bw = (float(orient[0]), float(orient[1]))
        nrm = math.hypot(*bw) or 1.0
        bw = (bw[0] / nrm, bw[1] / nrm)
    lat = (-bw[1], bw[0])   # 垂直(侧向)单位向量
    """阈值可注入：真实素材(像素空间)应按实测分布标定后传入，不沿用骨架默认值。
    disp_med: 单帧中位位移(像素)。给出时启用**掩护站定门**（spec 的实质判据 = 一者近零位移、
    另一者贴身通过），否则沿用旧的「仅邻近」判据（会大量误报，仅骨架 demo 用）。
    med_diag: 中位球员体长(像素)。给出时叠加**通行距离门**（通行者必须真的走过 ≥1/4 体长），
    以免「两人相邻漂移」被当成掩护。"""
    ev = []  # {"type","sub","f0","f1","who","zone","note"}
    n = len(frames)
    # 掩护：任意两人连续 min_run 帧距离 < d_screen
    for tid_a in {t for f in frames for t in f["players"]}:
        for tid_b in {t for f in frames for t in f["players"]}:
            if tid_a >= tid_b:
                continue
            run = []
            for i, f in enumerate(frames):
                pa, pb = f["players"].get(tid_a), f["players"].get(tid_b)
                if pa and pb and _dist(pa, pb) < d_screen:
                    run.append(i)
                else:
                    if len(run) >= min_run:
                        e = _mk_screen(frames, tid_a, tid_b, run, disp_med, med_diag, bw, orient)
                        if e:
                            ev.append(e)
                    run = []
            if len(run) >= min_run:
                e = _mk_screen(frames, tid_a, tid_b, run, disp_med, med_diag, bw, orient)
                if e:
                    ev.append(e)
    # 手递手：球同时贴近两名球员
    run = []
    for i, f in enumerate(frames):
        b = f["ball"]
        near = [t for t, p in f["players"].items() if b and _dist(b, p) < d_handoff]
        if b and len(near) >= 2:
            run.append((i, tuple(sorted(near[:2]))))
        else:
            if len(run) >= min_run:
                ev.append({"type": "HANDOFF", "sub": None, "f0": run[0][0], "f1": run[-1][0],
                           "who": list(run[0][1]), "zone": _zone_at(frames, run[0][1][0]),
                           "note": "球在两球员间近距离交接"})
            run = []
    if len(run) >= min_run:   # 循环末冲刷
        ev.append({"type": "HANDOFF", "sub": None, "f0": run[0][0], "f1": run[-1][0],
                   "who": list(run[0][1]), "zone": _zone_at(frames, run[0][1][0]),
                   "note": "球在两球员间近距离交接"})
    # 切入 / 突破：单人速度 > 阈值且朝篮筐（投影到朝筐轴）
    # 🔧 2026-10-04 CUT 通行距离门 + 净朝筐门：
    #   旧逻辑只判「瞬时帧间速度>V_CUT 且朝筐、连续≥3帧」→ 跟踪抖动(3-5帧小幅晃)被记成 CUT，
    #   半场进攻里出现 41 次切(≈0.5/帧)明显失真。加与掩护一致的通行距离门：run 的**净位移**
    #   (起点→终点) 必须 ≥ 0.5×med_diag(真实素材) 或 ≥30px(demo)，且净位移·朝筐轴 ≥ 0.35×净位移
    #   (净方向确实朝筐)。抖动净≈0 → 剔除。med_diag=None(纯 demo) 时回落旧行为保向后兼容。
    for tid in {t for f in frames for t in f["players"]}:
        run = []
        run_start_i = None
        for i in range(1, n):
            p0, p1 = frames[i - 1]["players"].get(tid), frames[i]["players"].get(tid)
            fast = False
            if p0 and p1:
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                d = math.hypot(dx, dy)
                toward = (dx * bw[0] + dy * bw[1]) > 0  # 位移·朝筐轴 > 0 = 朝篮筐
                # 🔧 2026-10-06：累积只看「快速」(不管方向)，冲洗时再分 CUT(朝筐)/RELOCATE(非朝筐)
                fast = d > v_cut
                if fast:
                    if run_start_i is None:
                        run_start_i = i - 1
                    run.append(i)
            if not fast:
                if len(run) >= min_run and run_start_i is not None:
                    ps = frames[run_start_i]["players"].get(tid)
                    pe = frames[run[-1]]["players"].get(tid)
                    is_cut = False; relocated = False; net = 0.0; toward = False
                    if ps and pe:
                        nx, ny = pe[0] - ps[0], pe[1] - ps[1]
                        net = math.hypot(nx, ny)
                        toward = (nx * bw[0] + ny * bw[1]) > 0
                        # 🔧 2026-10-06 临时门(Task 5②)：CUT 须净位移≥80px 且朝筐投影严格>0
                        is_cut = net >= CUT_NET_MIN and toward
                        # 快速但方向不朝筐 / 位移不足 → 普通重定位，降级 RELOCATE（不进战术匹配）
                        relocated = (not is_cut) and (net >= CUT_NET_MIN or toward)
                    if is_cut:
                        ev.append({"type": "CUT", "sub": None, "f0": run[0], "f1": run[-1],
                                   "who": [tid], "zone": _zone_at(frames, tid),
                                   "note": f"朝篮筐加速 净位移={net:.0f}px"})
                    elif relocated:
                        ev.append({"type": "RELOCATE", "sub": None, "f0": run[0], "f1": run[-1],
                                   "who": [tid], "zone": _zone_at(frames, tid),
                                   "note": f"快速重定位(非朝筐切) 净位移={net:.0f}px, 朝筐={toward}"})
                run = []
                run_start_i = None
        # 循环末冲刷
        if len(run) >= min_run and run_start_i is not None:
            ps = frames[run_start_i]["players"].get(tid)
            pe = frames[run[-1]]["players"].get(tid)
            is_cut = False; relocated = False; net = 0.0; toward = False
            if ps and pe:
                nx, ny = pe[0] - ps[0], pe[1] - ps[1]
                net = math.hypot(nx, ny)
                toward = (nx * bw[0] + ny * bw[1]) > 0
                is_cut = net >= CUT_NET_MIN and toward
                relocated = (not is_cut) and (net >= CUT_NET_MIN or toward)
            if is_cut:
                ev.append({"type": "CUT", "sub": None, "f0": run[0], "f1": run[-1],
                           "who": [tid], "zone": _zone_at(frames, tid),
                           "note": f"朝篮筐加速 净位移={net:.0f}px"})
            elif relocated:
                ev.append({"type": "RELOCATE", "sub": None, "f0": run[0], "f1": run[-1],
                           "who": [tid], "zone": _zone_at(frames, tid),
                           "note": f"快速重定位(非朝筐切) 净位移={net:.0f}px, 朝筐={toward}"})
    ev.sort(key=lambda e: e["f0"])
    return ev


def _screen_sub(dx, dy, bw=(0.0, -1.0)):
    """掩护子类 = **方向主导轴**(尺度无关), 投影到朝筐(bw)/侧向(lat)两轴:
       |along| >= 2|lat| → DOWN(沿篮筐/下掩护);  |lat| >= 2|along| → CROSS(横掩护);
       否则方向不明 → None(通用 SCREEN, 下游只作 0.5 弱命中)。
    🔧 广播像素原生：along = 位移·朝筐轴, lat = 位移·侧向轴。俯视默认 bw=(0,-1) 时退化为旧 |dy|/|dx| 规则。"""
    lat = (-bw[1], bw[0])
    along = dx * bw[0] + dy * bw[1]
    latv = dx * lat[0] + dy * lat[1]
    a, l = abs(along), abs(latv)
    if a >= 2.0 * l:
        return "DOWN"
    if l >= 2.0 * a:
        return "CROSS"
    return None


def _mk_screen(frames, a, b, run, disp_med=None, med_diag=None, bw=(0.0, -1.0), orient=None):
    """掩护判据。disp_med 给出时启用**站定门**(spec 实质: 一者近零位移、另一者贴身通过):
       hold_max = 3x 单帧中位位移  → 掩护人整段几乎停在原地
       move_min = 0.5x 单帧中位位移 x (run-1) → 通过者确实走了
       hi >= 2 x lo → 两人位移量级可比时判为「并行跑动」而非掩护, 丢弃。
    med_diag 给出时叠加**通行距离门**: 通行者总位移 hi 必须 ≥ 1/4 体长, 否则只是「两人相邻漂移」。
    🔴 局限: 站定门只认「站定型掩护」(掩护人近零位移); 横向穿场的 cross screen 由 _screen_sub
    按**方向主导轴**识别(横移占优即 CROSS), 不再依赖被掩护人是否站定。"""
    disp = []
    for tid in (a, b):
        p0 = frames[run[0]]["players"][tid]
        p1 = frames[run[-1]]["players"][tid]
        disp.append((tid, p1[0] - p0[0], p1[1] - p0[1]))
    mags = {tid: math.hypot(dx, dy) for tid, dx, dy in disp}
    tid, dx, dy = max(disp, key=lambda t: abs(t[1]) + abs(t[2]))
    hi = mags[tid]
    sub = _screen_sub(dx, dy, bw)
    zone = "PX" if orient is not None else _zone_at(frames, tid)
    if disp_med is not None:
        hold_max = 3.0 * disp_med
        move_min = 0.5 * disp_med * max(1, len(run) - 1)
        lo = min(mags.values())
        if not (lo <= hold_max and hi >= 2.0 * max(lo, 1.0) and hi >= move_min):
            return None
        if med_diag is not None and hi < 0.25 * med_diag:
            return None
        return {"type": "SCREEN", "sub": sub, "f0": run[0], "f1": run[-1], "who": [a, b],
                "zone": zone,
                "note": f"traveler={tid} dt=({dx:.0f},{dy:.0f}) travel={hi:.0f} lo={lo:.0f} hold_max={hold_max:.0f}"}
    return {"type": "SCREEN", "sub": sub, "f0": run[0], "f1": run[-1],
            "who": [a, b], "zone": zone, "note": f"screener={tid} dt=({dx:.0f},{dy:.0f})"}


def _zone_at(frames, tid):
    for fr in frames:
        if tid in fr["players"]:
            return zone_of(*fr["players"][tid])
    return "?"


# ---------------- ③ 匹配打分 ----------------
def _prim_name(p):
    return p["type"] + ("." + p["sub"] if p.get("sub") else "")


def match(events, models, min_cov=0.5, top=None, signature_evaluated=False, min_evidence=2):
    """打分 = 绝对命中分（hit=1.0 / 同类弱命中=0.5）；覆盖率 = 命中分 / max(len(need), min_evidence)。
    两条**防造假门**(否则多原语复合模型靠计数灌分霸榜):
      ① **判别原语门(key_primitive)**: 模型的判别原语(其 discriminative 直指的原语)若缺失,
         该模型**直接出局**。例: eog 判别量是 STS(先掩护后受掩护) → 检不到 STS 就不成立,
         不能靠 CROSS+3×DOWN 的计数堆上去。
      ② **时序依赖降级(seq_dependent)**: 判别量是**次序/重复/反转**类(连续两个/重复/先…后)的模型,
         在 signature 未评估时降级(rank 下沉), 因当前匹配只看原语集合、验不了次序。
    🔴 **复杂度先验(min_evidence, 2026-10-03 A类修复)**: 分母用 `max(len(need), min_evidence)`。
       动机：need=1 的泛用模型(cross_screen/cut_family/handoff)只要那一个原语出现就拿 cov=1.0
       满分，结构上压过任何 cov<1.0 的多原语真值 ⇒ 实测 top1 恒被单原语泛型霸榜。
       min_evidence=2 时「靠单个原语满足」只算 cov=0.5，多原语模型满命中(cov=1.0)才压得住。
       **可证伪/可回退**：min_evidence=1 即完全退回旧公式(便于 A/B 对照)。
    Rank: (已验证优先, 覆盖率, 复杂度先验后的绝对分) 降序 —— 覆盖率优先避免「多原语=高分」的偏差。
    返回 (score, cov, mid, detail, unverified) 元组，unverified=True 表示判别量未验证而降级。"""
    hits = []
    prims = [_prim_name(e) for e in events]
    prim_set = set(prims)
    for m in models:
        need = m.get("primitives", [])
        if not need:
            continue
        key = m.get("key_primitive")
        if key and key not in prim_set:      # ① 判别原语门 (精确命中, 不许弱顶)
            continue
        pool = list(prims)       # 每个事件只能被消费一次，避免重复计分
        hit = 0.0
        detail = []
        for pr in need:
            if pr in pool:
                pool.remove(pr); hit += 1.0; detail.append(("hit", pr))
            else:
                base = pr.split(".")[0]
                # 弱命中: 只允许**未细分**的事件(base 无子类)去满足某个具体子类需求。
                # 例: 未细分 SCREEN 可弱满足 SCREEN.DOWN；但 SCREEN.CROSS **不能**顶 SCREEN.DOWN
                # (否则「任意掩护」会满足所有掩护类战术, 造成 eog/stagger 类虚假榜首)。
                wk = [p for p in pool if "." not in p and p == base]
                if wk:
                    pool.remove(wk[0]); hit += 0.5; detail.append(("weak", pr))
        # 复杂度先验: 分母取 max(len(need), min_evidence)，让单原语泛型模型拿不到满分
        cov = hit / max(len(need), int(min_evidence))
        if cov >= min_cov and hit > 0:
            unverified = bool(m.get("seq_dependent")) and not signature_evaluated   # ② 时序依赖降级
            hits.append((round(hit, 2), round(cov, 3), m["id"], detail, unverified))
    # 同覆盖率时，need 越长的模型（证据越复杂）优先——用绝对 hit 做次级 tiebreak 已足够，
    # 因为复杂度先验已把单原语模型的 cov 压到 0.5。
    hits.sort(key=lambda x: (x[4], -x[1], -x[0]))   # 已验证优先 → 覆盖率 → 绝对分
    return hits[:top] if top else hits


def match_windowed(events, models, win=60, step=None, min_cov=0.5, min_events=2, top_per_win=3,
                   signature_evaluated=False, min_evidence=2):
    """🔴 战术是**局部有序序列** —— 必须按时间窗匹配, 不能拿全片事件池聚合
    (否则「f20 的一个掩护 + f300 的一个手递手」会被拼成假候选)。
    滑窗(默认 60 帧=6s)内跑 match, 返回 [{t0,t1,score,coverage,model,detail,unverified}]。
    min_evidence 透传给 match()（复杂度先验，=1 退回旧公式）。"""
    if not events:
        return []
    step = step or max(1, win // 2)
    f0 = min(e["f0"] for e in events)
    f1 = max(e["f1"] for e in events)
    out = []
    t = f0
    while t <= f1:
        ev = [e for e in events if t <= e["f0"] < t + win]
        if len(ev) >= min_events:
            for sc, cov, mid, detail, unv in match(ev, models, min_cov=min_cov,
                                                   top=top_per_win, signature_evaluated=signature_evaluated,
                                                   min_evidence=min_evidence):
                out.append({"t0": t, "t1": t + win, "score": sc, "coverage": cov,
                            "model": mid, "detail": detail, "unverified": unv})
        t += step
    out.sort(key=lambda x: (x["unverified"], -x["coverage"], -x["score"]))
    return out


# ---------------- demo：合成轨道（证明匹配机制，非真实素材结论）----------------
def synth(seq):
    """合成一段球员/球轨道（球场坐标）。仅用于验证匹配机制。"""
    F = []
    n = 40
    for i in range(n):
        players = {"1": (0.0, 360.0),   # ball_handler 弧顶
                   "2": (-70.0, 225.0),  # big1 左肘
                   "3": (70.0, 225.0),   # big2 右肘
                   "4": (-210.0, 70.0),  # 左底角
                   "5": (210.0, 70.0)}   # 右底角
        ball = players["1"]
        if seq == "horns_backdoor":
            # 帧 12-22: 3号从右肘横向穿场到左侧(横掩护: dx 大, dy≈0)
            if 12 <= i <= 22:
                t = (i - 12) / 10.0
                players["3"] = (70.0 - 220.0 * t, 225.0)
            elif i > 22:
                players["3"] = (-150.0, 225.0)
            # 帧 24-32: 2号后门切篮(y 减小, 快速)
            if i >= 24:
                t = min(1.0, (i - 24) / 8.0)
                players["2"] = (-70.0 + 40.0 * t, 225.0 - 150.0 * t)
        elif seq == "handoff":
            # 球落在 1、2 两人之间(D_HANDOFF 内) -> 手递手
            players = {"1": (0.0, 360.0), "2": (-60.0, 250.0), "4": (-210.0, 70.0)}
            ball = (-30.0, 305.0)
        F.append({"t": i, "ball": ball, "players": players})
    return F


def coverage_report():
    """自证：库条目(61) 是否全部映射到存在的模型。"""
    d = json.load(open(MODELS, encoding="utf-8"))
    ids = {m["id"] for m in d["models"]}
    alias = d.get("alias_index", {})
    bad = {k: v for k, v in alias.items() if v not in ids}
    print(f"[coverage] 模型 {len(d['models'])} 个; 库条目 {len(alias)} 个; 指向不存在的模型: {bad or '无'}")
    return not bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", choices=["horns_backdoor", "handoff"], default="horns_backdoor")
    ap.add_argument("--prims-only", action="store_true")
    ap.add_argument("--coverage", action="store_true", help="只校验库->模型覆盖")
    ap.add_argument("--min-coverage", type=float, default=0.5)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    if a.coverage:
        ok = coverage_report()
        sys.exit(0 if ok else 1)
    models = json.load(open(MODELS, encoding="utf-8"))["models"]
    frames = synth(a.demo)
    ev = detect_primitives(frames)
    print(f"[demo={a.demo}] 检测到原语事件 {len(ev)}:")
    from collections import Counter
    print("  ", dict(Counter(_prim_name(e) for e in ev)))
    if a.prims_only:
        return
    print(f"[match] 候选战术 (绝对分/覆盖率, 最少覆盖率={a.min_coverage}, top={a.top}):")
    for sc, cov, mid, detail, unv in match(ev, models, min_cov=a.min_coverage, top=a.top):
        flag = "  [seq-unverified ⤵]" if unv else ""
        print(f"  {sc:>4.2f}  cov={cov:.2f}  {mid:20s} {detail}{flag}")


if __name__ == "__main__":
    main()
