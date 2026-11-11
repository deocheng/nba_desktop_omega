#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
screen_specificity_probe.py — 掩护特异性是否**可解**的关键诊断实验（A4.61）
==========================================================================
A4.60 结论: 掩护原语(SCREEN.CROSS)在**任何**片段都大量检出(13–26/20s), 且收紧站定门
**只等比缩小不分离** → 匹配层被证伪。老程授权攻「掩护特异性」。

本脚本**不训练、不调排序**，只做一件事: 对同一批《战术笔记》实战片段，把多种
「掩护判据变体」的检出**数量**并排列出，回答一个二值问题:

  ❓ 是否存在某个纯几何/运动学判据, 使「真·横掩护片段(ep24)」的检出显著区别于
     无关片段(ep5 backdoor / ep27 drop)?

若**任何**变体都不能把 ep24 拉出人群 → 结论=几何+运动学**无法**特异性识别掩护 →
转 A4.53 占有权约束路径(有球半场进攻)+ 必须引入防守人(配准)。

判据变体(逐级加严):
  V0 现行(:  _mk_screen 原逻辑, hold_max=3·disp_med, move_min=0.5·disp_med·(run-1), hi≥2·lo, hi≥0.25·diag)
  V1 绝对站定量: min_disp ≤ K·med_diag (K=0.5)      —— 尺度无关, 相对体长
  V2 更严站定:  min_disp ≤ K·med_diag (K=0.2)
  V3 =V1 + 穿过判据: 段内两人距离 先减后增(极小于两端, 余量 0.15·diag)
  V4 =V1 + 侧翻判据: 通行者相对掩护者的横向偏移 o_x 在段首尾**变号**(真从一侧穿到另一侧)
  V5 =V1 + V3 + V4 + 横移主导(|dx|≥2|dy|)  ← 最严, 目标=「真横掩护」唯一化
每变体另外要求: 通行者位移 ≥ 0.5·med_diag(确实走动)。

诚实边界: 段级真值仍缺(期级不够) → 本实验只检验**可分性**, 不产出战术认定; 数字全部现读。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import statistics as st
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"

D_SCREEN_FRAC = 0.5   # 两人中心 < 0.5·体长 ≈ 贴身(与 tactic_match_real.derive_thresholds 一致)


def _ctr(bb):
    return ((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def load_seg(seg_dir: Path):
    """读 ball_tracks(_team).json(契约) → frames=[{t, players:{tid:(x,y)}, bbox:{tid:bb},
    team:{tid:0/1}, ball:(cx,cy)|None, handler:tid|None}] + 阈值。

    team 字段来自 A4.61 解锁路径①(assign_team 逐帧队色); handler=球最近球员(占有权弱代理,
    与 segment_detect_track.assign_ball_handler 同口径: dist(球心,脚点)/框高 最近者)。
    """
    tp = seg_dir / "ball_tracks_team.json"
    raw = json.load(open(tp if tp.exists() else seg_dir / "ball_tracks.json", encoding="utf-8"))
    frames = []
    diags, disps = [], []
    for i, fr in enumerate(raw):
        players, bbox, team = {}, {}, {}
        for p in fr.get("players", []):
            tid = int(p["track_id"])
            players[tid] = _ctr(p["bbox"])
            bbox[tid] = p["bbox"]
            team[tid] = p.get("team")
            bb = p["bbox"]
            diags.append(((bb[2] - bb[0]) ** 2 + (bb[3] - bb[1]) ** 2) ** 0.5)
        if i > 0:
            for tid, c in players.items():
                c0 = frames[-1]["players"].get(tid)
                if c0:
                    disps.append(abs(c[0] - c0[0]) + abs(c[1] - c0[1]))
        ball = fr.get("ball") or {}
        bb = ball.get("bbox")
        bc = ((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0) if bb else None
        handler = None
        if bc is not None and players:
            best, bd = None, 1e18
            for tid, box in bbox.items():
                fx, fy = (box[0] + box[2]) / 2.0, box[3]
                h = max(box[3] - box[1], 1.0)
                d = math.hypot(bc[0] - fx, bc[1] - fy) / h
                if d < bd:
                    bd, best = d, tid
            handler = best
        frames.append({"t": i, "players": players, "bbox": bbox, "team": team,
                       "ball": bc, "handler": handler})
    med_diag = st.median(diags) if diags else 1.0
    med_disp = st.median(disps) if disps else 1.0
    return frames, med_diag, med_disp


def _runs_for_pair(frames, a, b, d_screen, min_run=3):
    """返回 [(i0,i1)] 连续 min_run 帧 dist(a,b)<d_screen 的区间。"""
    out, run = [], []
    for i, f in enumerate(frames):
        pa, pb = f["players"].get(a), f["players"].get(b)
        if pa and pb and _dist(pa, pb) < d_screen:
            run.append(i)
        else:
            if len(run) >= min_run:
                out.append((run[0], run[-1]))
            run = []
    if len(run) >= min_run:
        out.append((run[0], run[-1]))
    return out


def _iou(b1, b2):
    x1, y1 = max(b1[0], b2[0]), max(b1[1], b2[1])
    x2, y2 = min(b1[2], b2[2]), min(b1[3], b2[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    u = a1 + a2 - inter
    return inter / u if u > 0 else 0.0


def features(frames, a, b, i0, i1):
    """一个候选(对对 a,b, 区间 i0..i1)的运动学特征。"""
    def traj(tid):
        return [frames[i]["players"][tid] for i in range(i0, i1 + 1) if tid in frames[i]["players"]]
    ta, tb = traj(a), traj(b)
    if len(ta) < 3 or len(tb) < 3:
        return None
    def net(t):
        return (t[-1][0] - t[0][0], t[-1][1] - t[0][1])
    def pathlen(t):
        return sum(_dist(t[k - 1], t[k]) for k in range(1, len(t)))
    disp_a = math.hypot(*net(ta))
    disp_b = math.hypot(*net(tb))
    # 距离剖面(逐帧, 取两轨同时存在帧)
    dprof, offx = [], []
    for i in range(i0, i1 + 1):
        pa, pb = frames[i]["players"].get(a), frames[i]["players"].get(b)
        if pa and pb:
            dprof.append(_dist(pa, pb))
            offx.append(pb[0] - pa[0])   # 相对横向偏移(方向: a->b)
    if len(dprof) < 3:
        return None
    dmin = min(dprof)
    i_min = dprof.index(dmin)
    trav = a if disp_a >= disp_b else b      # 通行者=位移大者; 掩护者=另一个
    scr = b if trav == a else a
    trav_disp = disp_a if trav == a else disp_b
    scr_disp = disp_b if trav == a else disp_a
    trav_net = net(ta if trav == a else tb)
    scr_net = net(tb if trav == a else ta)
    scr_path = pathlen(tb if trav == a else ta)
    sign_flip = (offx[0] * offx[-1] < 0)
    # 同人碎片检测: 整段两框最大 IoU(高=同一人的两截轨迹被当两人)
    max_iou = 0.0
    for i in range(i0, i1 + 1):
        bb1 = frames[i]["bbox"].get(a)
        bb2 = frames[i]["bbox"].get(b)
        if bb1 and bb2:
            max_iou = max(max_iou, _iou(bb1, bb2))
    return {
        "a": a, "b": b, "i0": i0, "i1": i1, "dur": i1 - i0 + 1,
        "trav": trav, "scr": scr,
        "trav_disp": trav_disp, "scr_disp": scr_disp, "scr_path": scr_path,
        "dmin": dmin, "d_first": dprof[0], "d_last": dprof[-1],
        "i_min_rel": i_min, "interior": 0 < i_min < len(dprof) - 1,
        "dprof": dprof, "trav_net": trav_net, "max_iou": max_iou,
    }


def classify(f, med_diag, med_disp, d_screen):
    """返回该特征在各变体下是否命中 {V0..V5}。"""
    hi = f["trav_disp"]; lo = f["scr_disp"]
    res = {}
    # V0 现行 _mk_screen (近似复刻)
    hold_max = 3.0 * med_disp
    move_min = 0.5 * med_disp * max(1, f["dur"] - 1)
    res["V0"] = (lo <= hold_max and hi >= 2.0 * max(lo, 1.0) and hi >= move_min
                 and hi >= 0.25 * med_diag)
    # V1 绝对站定 K=0.5
    res["V1"] = (lo <= 0.5 * med_diag and hi >= 0.5 * med_diag)
    # V2 绝对站定 K=0.2
    res["V2"] = (lo <= 0.2 * med_diag and hi >= 0.5 * med_diag)
    # 穿过: 距离先减后增(余量 0.15·diag), 极小于段内
    thru = (f["d_first"] - f["dmin"] >= 0.15 * med_diag
            and f["d_last"] - f["dmin"] >= 0.15 * med_diag)
    # 侧翻: 横向偏移变号 且 极小的 |offx| 在段内
    res["V3"] = res["V1"] and thru
    res["V4"] = res["V1"] and f.get("_side_flip", False)
    dx, dy = f["trav_net"]
    cross_dir = abs(dx) >= 2.0 * abs(dy)
    res["V5"] = res["V1"] and thru and f.get("_side_flip", False) and cross_dir
    # V6 = V5 + **异人门**: 排除同一人的两截碎片轨迹(整段两框 IoU ≥ 0.2 → 同一人 → 非掩护)
    res["V6"] = res["V5"] and f.get("max_iou", 0.0) < 0.2
    # 对照: V5 中被判「同人碎片」的数量(IoU ≥ 0.2)
    res["V5_same"] = res["V5"] and f.get("max_iou", 0.0) >= 0.2
    f["thru"] = thru
    f["cross_dir"] = cross_dir
    return res


def _modal_team(frames, tid, i0, i1):
    """窗口内该 tid 的众数队色; 全 None → None。"""
    from collections import Counter
    c = Counter(frames[i]["team"].get(tid) for i in range(i0, i1 + 1)
                if tid in frames[i]["team"] and frames[i]["team"].get(tid) is not None)
    return c.most_common(1)[0][0] if c else None


def _modal_handler(frames, i0, i1):
    """窗口内众数持球人(球最近球员); 无球帧则 None。"""
    from collections import Counter
    c = Counter(frames[i]["handler"] for i in range(i0, i1 + 1)
                if frames[i].get("handler") is not None)
    return c.most_common(1)[0][0] if c else None


def probe(seg_dirs, min_run=3):
    """对每个 segment 统计各变体命中数。

    V7 家族(A4.61 解锁路径①+② 的可分性检验, 全部基于逐帧队色+球最近人弱代理):
      V1_xteam = V1 + 接触对两人异队(攻防对位; A4.61 已证 4/5 V5 命中即此类)
      V7       = V1_xteam + 众数持球人 H 存在且 H∉{a,b} 且 team[H]==team[掩护者]
                 —— 语义: 站定者是与持球人同队的进攻掩护者, 接触对象是防守人
      V7_def   = V1_xteam + 众数持球人 ∈ {a,b}
                 —— 语义: 接触对里就有持球人 = 贴身防守对位(A4.61 证伪类, 应被 V7 排除)
    """
    rows = []
    for sd in seg_dirs:
        frames, med_diag, med_disp = load_seg(sd)
        d_screen = D_SCREEN_FRAC * med_diag
        # 候选池净化(A4.62 第一步): 只对被 assign_team 赋了真实队色(非 None)的 tid 配对,
        # 把 bench/audience/静态观众多掉的 tid 直接排除出两两候选池(几何+语义判据都干净)。
        tids = sorted({t for f in frames for t in f["team"] if f["team"].get(t) is not None})
        feats = []
        for ia, a in enumerate(tids):
            for b in tids[ia + 1:]:
                for (i0, i1) in _runs_for_pair(frames, a, b, d_screen, min_run):
                    f = features(frames, a, b, i0, i1)
                    if f:
                        # 侧翻: 用相对横向偏移变号(取两轨同时存在帧)
                        offx = []
                        for i in range(i0, i1 + 1):
                            pa, pb = frames[i]["players"].get(a), frames[i]["players"].get(b)
                            if pa and pb:
                                offx.append(pb[0] - pa[0])
                        f["_side_flip"] = (len(offx) >= 3 and offx[0] * offx[-1] < 0)
                        feats.append(f)
        cnts = {k: 0 for k in ["V0", "V1", "V2", "V3", "V4", "V5", "V6", "V5_same",
                               "V1_xteam", "V7", "V7_def", "V8"]}
        v7_hits = []
        for f in feats:
            res = classify(f, med_diag, med_disp, d_screen)
            for k, hit in res.items():
                if hit:
                    cnts[k] += 1
            # V7 家族(需要窗口上下文: 队色 + 持球人)
            t_scr = _modal_team(frames, f["scr"], f["i0"], f["i1"])
            t_trav = _modal_team(frames, f["trav"], f["i0"], f["i1"])
            H = _modal_handler(frames, f["i0"], f["i1"])
            cross = (t_scr is not None and t_trav is not None and t_scr != t_trav)
            f["t_scr"], f["t_trav"], f["H"] = t_scr, t_trav, H
            if res["V1"] and cross:
                cnts["V1_xteam"] += 1
                if H is not None and H in (f["a"], f["b"]):
                    cnts["V7_def"] += 1
                elif H is not None and _modal_team(frames, H, f["i0"], f["i1"]) == t_scr:
                    cnts["V7"] += 1
                    # V8 = V7 + 异人门(A4.61 V6: IoU<0.2 排同人碎片) + 持球人邻近门
                    # (掩护为持球人而做: H 必须在接触对附近; 尺度取 3·med_diag, 与 V1 同为体长相对量)
                    hbb = None
                    hprox = None
                    if H is not None:
                        hbb = next((frames[i]["bbox"].get(H) for i in range(f["i0"], f["i1"] + 1)
                                    if frames[i]["bbox"].get(H)), None)
                    if hbb is not None:
                        hctr = _ctr(hbb)
                        dmin_H = None
                        for i in range(f["i0"], f["i1"] + 1):
                            for t in (f["scr"], f["trav"]):
                                c = frames[i]["players"].get(t)
                                if c is not None:
                                    d = _dist(hctr, c)
                                    if dmin_H is None or d < dmin_H:
                                        dmin_H = d
                        hprox = dmin_H
                    f["H_dist"] = round(hprox, 1) if hprox is not None else None
                    v8 = (f.get("max_iou", 0.0) < 0.2
                          and hprox is not None and hprox <= 3.0 * med_diag)
                    if v8:
                        cnts["V8"] += 1
                    v7_hits.append({"a": f["a"], "b": f["b"], "i0": f["i0"], "i1": f["i1"],
                                    "scr": f["scr"], "trav": f["trav"],
                                    "t_scr": t_scr, "t_trav": t_trav, "H": H,
                                    "H_dist": f["H_dist"],
                                    "dmin": round(f["dmin"], 1), "max_iou": round(f["max_iou"], 3),
                                    "V8": bool(v8)})
        rows.append({
            "seg": sd.name,
            "n_frames": len(frames),
            "n_tids": len(tids),
            "n_ball_frames": sum(1 for f in frames if f["ball"] is not None),
            "med_diag": round(med_diag, 1),
            "med_disp": round(med_disp, 2),
            "n_close_runs": len(feats),
            **cnts,
            "V7_hits": v7_hits,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(AW / "tactic_notes_batch_pilot_cf" / "segments"),
                    help="包含 <ep>_sN 子目录的目录")
    ap.add_argument("--eps", default="24,5,27,2,15,16,19,20,25,26,53,70,1,31",
                    help="期号列表(取 *_s0/_s1)")
    ap.add_argument("--segs", default="", help="逗号分隔的具体段目录名(优先)")
    ap.add_argument("--out", default=str(AW / "screen_specificity_probe.json"))
    a = ap.parse_args()
    base = Path(a.base)
    if a.segs:
        segs = [base / x.strip() for x in a.segs.split(",") if x.strip()]
    else:
        eps = [x.strip() for x in a.eps.split(",") if x.strip()]
        segs = []
        for ep in eps:
            for s in sorted(base.glob(f"ep{ep}_s*")):
                segs.append(s)
    segs = [s for s in segs if (s / "ball_tracks.json").exists()]
    print(f"[probe] {len(segs)} 个片段 @ {base}")
    rows = probe(segs)
    hdr = ["seg", "n_frames", "n_ball_frames", "n_tids", "med_diag", "med_disp", "n_close_runs",
           "V0", "V1", "V2", "V3", "V4", "V5", "V6", "V5_same", "V1_xteam", "V7", "V7_def", "V8"]
    print("  " + "  ".join(f"{h:>10s}" for h in hdr))
    for r in rows:
        print("  " + "  ".join(f"{r[h]:>10}" for h in hdr))
    # V7 命中明细(供视觉自证)
    tot7 = sum(r["V7"] for r in rows)
    tot8 = sum(r["V8"] for r in rows)
    print(f"\n[V7] 全部片段命中合计 {tot7}  [V8=V7+异人门+持球人邻近门] {tot8}")
    for r in rows:
        for h in r["V7_hits"]:
            tag = "V8✓" if h.get("V8") else "V8✗"
            print(f"  {r['seg']:10s} [{tag}] scr={h['scr']}(t{h['t_scr']}) trav={h['trav']}(t{h['t_trav']}) "
                  f"H={h['H']}(d={h.get('H_dist')}) i0={h['i0']} i1={h['i1']} dmin={h['dmin']} iou={h['max_iou']}")
    json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[写出] {a.out}")


if __name__ == "__main__":
    main()
