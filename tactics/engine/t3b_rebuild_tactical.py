#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t3b_rebuild_tactical (T3b) —— 用 HUMAN 头重建 sas_det 球轨迹并重跑战术事件层 + teamID。

背景（A4.23 遗留）:
  - 旧 sas_det 球信号来自稀疏 poss_tile 源（覆盖 3.5%, A4.23 判「指标不可用」）;
  - 战术事件层 PnR 标注为「探索性: 无 team ID」。
本脚本（DB 零写, 全部内存计算）:
  1) ball 轨迹重建: HUMAN 头打分(th=0.30, diag<60)逐帧 top1 → ball{bbox,conf}（不插值,
     无拾取=null; 拾取缺失=头弃权, 属预期语义——见 T3a）。
  2) players 沿用生产稳定轨迹 stabilize_tracks_v2 v1(bbox-top, 85 ID, A4.43); 旧 sas_det_poss_tile 为未稳定 260 ID。
  3) possession: 球心最近球员(框内优先, radius=0.04 对角线) → 逐帧 tid → RLE 段。
  4) 战术事件: 直接调 tactical_events.detect()（PASS/DRIVE/PnR + N-of-M 稳定）。
  5) teamID: 每 track_id 球衣亮度(bbox 内 HSV V 中值)二分 → 白队(SAS)/深队(DET);
     🔴 独立验证 = 活球帧「持球者队伍 vs T2 状态表 PBP possession」一致率
     （颜色聚类与 PBP 两条独立证据链, 一致率即交叉验证, 不一致率如实报告）。
  6) frame_annotations 接入: 每事件附 live_state/dead_ball_veto/occluded 标注。

产出: action_work/validate/sas_det_t3b_tactical.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
import tactical_events as te  # noqa: E402

# A4.50 起 SCORES/OLD_TRACKS/STATES/FR/OUT 全部由 --clip 在 main() 内派生, 不再模块级硬编码。
TH = 0.30
DIAG_MAX = 60
POSS_RADIUS = 0.04
N_FRAMES = 400
# PBP 口径: SAS=主场(白) / DET=客场(深)。帧为 1080p。
# 球衣亮度二分阈值由 tid 特征分布 Otsu 自适应, 不手写常数。


def top1(cands):
    best = None
    for c in cands:
        diag = max(c["bbox"][2] - c["bbox"][0], c["bbox"][3] - c["bbox"][1])
        if c["prob"] >= TH and diag < DIAG_MAX:
            if best is None or c["prob"] > best["prob"]:
                best = c
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", default=None,
                   help="覆盖 players 轨迹源(默认 <clip>_poss_tile_stab/ball_tracks.json, 生产稳定轨迹)")
    ap.add_argument("--scores", default=None,
                   help="覆盖 ball 候选分数源(默认 ball_cand_scores_dense_a442_<clip>_joint.json, A4.42 生产头)")
    ap.add_argument("--out", default=None,
                   help="覆盖输出路径(默认 validate/<clip>_t3b_tactical.json)")
    # A4.50: clip 参数化(sas_det 为默认 canonical)。T2/T3a 前置产物不存在时报错提示,
    # 而非静默用错 clip 的真值源。
    ap.add_argument("--clip", default="sas_det",
                   help="片段名(默认 sas_det); 派生帧目录/前置产物路径")
    # A4.48/49 老程目视裁定(2026-09-28, 裁定图 a4_48_teamcolor_adjudication.png):
    # sas_det tid=31/33/38/64 = 裁判(31: f00130/160/190; 33/38/64: 追加裁定);
    # sas_lal tid=7/8/38 = 裁判(A4.50 预筛图, 2026-09-28 老程逐帧裁定; 注意两 clip 的
    # tid=38 互不相干)。裁判不可能持球且触球只在死球段(战术层不消费), 剔除零信息损失;
    # 剔除同时移出 Otsu 队色分布(其 V 中值不属于任何一队)。
    # A4.53 老程裁定(2026-09-29, f197 接触表): sas_det tid=44 = 场边观众(非球员) → 同法理剔除。
    ap.add_argument("--exclude-tids", default=None,
                   help="非球员 track_id(逗号分隔)。默认按 clip 取 A4.48/49/50/53 老程裁定: "
                        "sas_det=31,33,38,44,64(44=场边观众); sas_lal=7,8,38。传空串则不剔除")
    a = ap.parse_args()
    CLIP = a.clip
    ADJUDGED_REFEREES = {"sas_det": "31,33,38,44,64", "sas_lal": "7,8,38"}
    if a.exclude_tids is None:
        a.exclude_tids = ADJUDGED_REFEREES.get(CLIP, "")
    EXCL = {int(t) for t in a.exclude_tids.split(",") if t.strip()}
    SCORES = AW / "validate" / f"ball_cand_scores_dense_a442_{CLIP}_joint.json"
    OLD_TRACKS = AW / f"{CLIP}_poss_tile_stab" / "ball_tracks.json"
    STATES = AW / "validate" / f"{CLIP}_frame_states.json"
    FR = AW / CLIP
    if a.out is None:
        a.out = str(AW / "validate" / f"{CLIP}_t3b_tactical.json")
    T3A = AW / "validate" / f"{CLIP}_t3a_semantic.json"
    for need in (SCORES, OLD_TRACKS, STATES, T3A):
        if not Path(need).exists():
            sys.exit(f"[err] 缺前置产物 {need} — 该 clip 的上游链路(T2 状态表等)未建, "
                     f"不可用其他 clip 的真值源替代")
    if a.scores is None:
        a.scores = str(SCORES)
    if a.tracks is None:
        a.tracks = str(OLD_TRACKS)
    scores = json.loads(Path(a.scores).read_text())
    fr_scores = scores[CLIP] if CLIP in scores else scores
    old = json.loads(Path(a.tracks).read_text())
    states = json.loads(STATES.read_text())
    live_of = {r["fid"]: r["live_state"] for r in states["rows"]}
    poss_of = {r["fid"]: r["possession"] for r in states["rows"]}
    annot = states  # frame_annotations 在 t3a json 里
    t3a = json.loads(T3A.read_text())
    sem_of = {int(k): v["semantic"] for k, v in t3a["frame_annotations"].items()}

    # ---- 1+2: 重建 frames（与 tactical_events.load_clip 同构, 索引 gi=fid-1）----
    frames = []
    n_ball = 0
    for i, oldfr in enumerate(old[:N_FRAMES]):
        fk = i + 1
        t = top1(fr_scores.get(f"f{fk:05d}.jpg", []))
        ball = None
        if t is not None:
            b = t["bbox"]
            ball = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)   # te.detect 期望中心点
            n_ball += 1
        players = [{"tid": pl.get("track_id"), "c": te.ctr(pl["bbox"]), "bbox": pl["bbox"]}
                   for pl in oldfr.get("players", []) if pl.get("bbox")
                   and pl.get("track_id") not in EXCL]
        frames.append({"frame": oldfr.get("frame", f"f{fk:05d}.jpg"),
                       "file": oldfr.get("file"), "ball": ball, "interp": False,
                       "players": players})
    print(f"[rebuild] ball 覆盖: {n_ball}/{N_FRAMES} ({n_ball/N_FRAMES*100:.1f}%) "
          f"(旧 poss_tile 源: 3.5%)")

    # ---- 3: possession（球心在框内优先, 否则最近球员中心距 ≤ radius*对角线）----
    diag = math.hypot(1920, 1080)
    rad = POSS_RADIUS * diag
    taf = [None] * N_FRAMES
    for gi, fr in enumerate(frames):
        if fr["ball"] is None:
            continue
        bcx, bcy = fr["ball"]                                # ball 已是中心点
        inside, nearest, nd = None, None, 1e18
        for p in fr["players"]:
            pb = p["bbox"]
            if pb[0] <= bcx <= pb[2] and pb[1] <= bcy <= pb[3]:
                if inside is None:
                    inside = p["tid"]
            d = math.hypot(p["c"][0] - bcx, p["c"][1] - bcy)
            if d < nd:
                nd, nearest = d, p["tid"]
        taf[gi] = inside if inside is not None else (nearest if nd <= rad else None)
    segs = te.smoothed_segments(taf)
    print(f"[poss] 逐帧 tid 帧数: {sum(1 for t in taf if t is not None)}, "
          f"RLE 段: {len(segs)} (旧: 11 段全 1 帧碎片)")

    # ---- 4: 战术事件 ----
    res = te.detect(frames, segs)
    print(f"[events] raw_seg={res['n_raw_segments']} sm_seg={res['n_smoothed_segments']} "
          f"passes={res['confirmed_passes']} drives={res['n_drive_total']} "
          f"pnr={res['n_pnr_exploratory']}")

    # ---- 5: teamID（球衣亮度 Otsu 二分 ⊥ PBP 交叉验证）----
    # 每 tid 的 bbox 内 HSV V 中值（采样活球帧, 每帧每 tid 一次）
    tid_vals = {}
    for gi, fr in enumerate(frames):
        fk = gi + 1
        if live_of.get(fk) != "live":
            continue
        img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        for p in fr["players"]:
            b = [int(round(v)) for v in p["bbox"]]
            x0, y0, x1, y1 = max(0, b[0]), max(0, b[1]), min(1920, b[2]), min(1080, b[3])
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            v = float(np.median(hsv[y0:y1, x0:x1, 2]))
            tid_vals.setdefault(p["tid"], []).append(v)
    tid_med = {tid: float(np.median(vs)) for tid, vs in tid_vals.items() if len(vs) >= 10}
    vals = np.array(sorted(tid_med.values()), np.float32)
    # 一维 Otsu（OpenCV 5.0 threshold 不收 float32 一维）
    hist, edges = np.histogram(vals, bins=64, range=(vals.min(), vals.max() + 1e-6))
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist); w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centers); s1 = s0[-1] - s0
    valid = (w0 > 0) & (w1 > 0)
    mu0 = np.where(valid, s0 / np.maximum(w0, 1), 0)
    mu1 = np.where(valid, s1 / np.maximum(w1, 1), 0)
    between = np.where(valid, w0 * w1 * (mu0 - mu1) ** 2, -1)
    thr = float(centers[int(np.argmax(between))])
    tid_team = {tid: ("SAS(white)" if v >= thr else "DET(dark)") for tid, v in tid_med.items()}
    print(f"[team] Otsu 阈值 V={thr:.1f}, tid 分布: "
          f"{sum(1 for v in tid_med.values() if v >= thr)} 白 / {sum(1 for v in tid_med.values() if v < thr)} 深")

    # 交叉验证: 持球者队伍 vs T2 possession —— 双口径
    # 口径1 全部可判帧; 口径2 仅「球在手中」帧(球速<250px/s, 排除球飞行段 nearest 误配)。
    HOLD_MAX = 250.0
    spd = [None] * N_FRAMES
    for gi in range(1, N_FRAMES):
        fa, fb = frames[gi - 1], frames[gi]
        if fa["ball"] and fb["ball"]:
            spd[gi] = math.hypot(fb["ball"][0] - fa["ball"][0], fb["ball"][1] - fa["ball"][1]) * 10
    a1 = d1 = a2 = d2 = na = 0
    for gi, fr in enumerate(frames):
        fk = gi + 1
        if live_of.get(fk) != "live":
            continue
        tid = taf[gi]
        pbp = poss_of.get(fk)
        if tid is None or pbp not in ("SAS", "DET"):
            na += 1
            continue
        team = tid_team.get(tid)
        if team is None:
            na += 1
            continue
        ok = team.startswith(pbp)
        if ok:
            a1 += 1
        else:
            d1 += 1
        s = spd[gi]
        if s is not None and s < HOLD_MAX:
            if ok:
                a2 += 1
            else:
                d2 += 1
    tot1, tot2 = a1 + d1, a2 + d2
    r1 = a1 / tot1 * 100 if tot1 else float("nan")
    r2 = a2 / tot2 * 100 if tot2 else float("nan")
    print(f"[xval] 口径1 全部可判帧: 一致 {a1}/{tot1} = {r1:.1f}%")
    print(f"[xval] 口径2 球在手中:  一致 {a2}/{tot2} = {r2:.1f}%")
    if tot2 and r2 >= 90.0:
        verdict = (f"QUALIFIED: 球在手中一致率≥90%; 非球员轨迹(A4.48/49/50 老程目视裁定: {CLIP} "
                   f"tid={','.join(map(str, sorted(EXCL)))}=裁判) 已从持球候选/队色分布剔除。"
                   "⚠️ 单片段裁定, 换转播须重裁该转播的非球员轨迹")
        print(f"[xval] ✅ {verdict}")
    else:
        verdict = ("NOT_QUALIFIED: 一致率<90%(当前方案上限≈86.5%); 根因=头判别力天花板(A4.35/36) "
                   "+ 残余 tid/team 歧义(外观 A4.44 证非杠杆) + 占有权先验辅助球追踪 A4.46 证伪; "
                   "不引入新模型已到头, teamID 保持 NOT_QUALIFIED, 战术层转用不依赖 teamID 模块")
        print(f"[xval] 🔴 {verdict}")

    # ---- 6: 事件叠 teamID + frame_annotations ----
    events_out = []
    for ev in res["events"]:
        gi = ev.get("at", ev.get("start"))
        fk = gi + 1
        e = dict(ev)
        e["frame_fid"] = fk
        e["live_state"] = live_of.get(fk)
        e["semantic"] = sem_of.get(fk)
        if e["semantic"] == "dead_ball_veto":
            e["veto"] = True
        if e["type"] in ("DRIVE", "PnR"):
            e["team"] = tid_team.get(ev["tid"])
            if "screen_setter" in ev:
                e["team_screen_setter"] = tid_team.get(ev["screen_setter"])
                e["team_screen_defender"] = tid_team.get(ev["screen_defender"])
        elif e["type"] == "PASS":
            e["team_from"] = tid_team.get(ev["from"])
            e["team_to"] = tid_team.get(ev["to"])
            e["cross_team"] = (e["team_from"] != e["team_to"]) if (e["team_from"] and e["team_to"]) else None
        events_out.append(e)

    n_veto = sum(1 for e in events_out if e.get("veto"))
    pnr_with_team = [e for e in events_out if e["type"] == "PnR" and e.get("team")]
    print(f"\n[out] 事件 {len(events_out)} 个, 其中死球段 veto {n_veto} 个; "
          f"PnR 带 team: {len(pnr_with_team)}")
    for e in events_out:
        tag = f"team={e.get('team')}" if e.get("team") else ""
        print(f"   {e['type']:5s} f{e['frame_fid']:03d} [{e['live_state']}/{e['semantic']}] "
              f"{tag} {'VETO' if e.get('veto') else ''}")

    out = {"meta": {"ball_source": f"{Path(a.scores).stem} th={TH} top1 (no interp)",
                    "ball_coverage_pct": round(n_ball / N_FRAMES * 100, 1),
                    "poss_radius": POSS_RADIUS, "n_frames": N_FRAMES,
                    "team_method": "per-tid HSV-V median + Otsu binary",
                    "otsu_thr_V": round(thr, 1),
                    "excluded_tids": sorted(EXCL),
                    "exclusion_basis": f"A4.48/49/50 老程目视裁定(2026-09-28): {CLIP} 裁判 tid="
                                       f"{','.join(map(str, sorted(EXCL)))}"
                                       "(sas_det 见 a4_48_teamcolor_adjudication.png; sas_lal 见 "
                                       "a4_50_sas_lal_referee_prescreen.png); "
                                       "裁判触球只在死球段, 战术层不消费死球, 剔除零信息损失"},
           "xval_possession": {"all_frames": {"agree": a1, "disagree": d1, "na": na,
                                              "agree_rate_pct": round(r1, 1) if tot1 else None},
                               "ball_in_hand": {"agree": a2, "disagree": d2,
                                                "agree_rate_pct": round(r2, 1) if tot2 else None},
                               "verdict": verdict},
           "summary": {"n_raw_segments": res["n_raw_segments"],
                       "n_smoothed_segments": res["n_smoothed_segments"],
                       "confirmed_passes": res["confirmed_passes"],
                       "n_drive": res["n_drive"],
                       "n_pnr": res["n_pnr_exploratory"],
                       "n_vetoed": n_veto},
           "events": events_out}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"[out] {a.out}")


if __name__ == "__main__":
    main()
