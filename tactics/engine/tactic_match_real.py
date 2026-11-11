#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tactic_match_real.py — 把「真实素材」接进战术匹配引擎（L3 端到端）
====================================================================
输入(真实产物):
  · 稳定化球员轨迹  action_work/<clip>_poss_tile_stab/ball_tracks.json  (A4.43, bbox 像素)
  · 球轨迹(遮挡补全) action_work/validate/<clip>_ball_track_occluded.json (A4.54, 像素)
  · 非球员 tid 裁定  复用 t3b_rebuild_tactical.py 的 ADJUDGED_REFEREES(裁判/场边观众)

流程: 载入 -> 剔除非球员 -> 组成轨道契约(图像像素空间) -> 原语检测 -> 匹配 -> 候选
       + 视觉自证(把检测到的原语事件画回原帧)

🔴 诚实边界(必读, 输出里也会写)
  1. **球场配准缺失**: 本素材无 pixel→court 单应(court_fit 在 w1 上失败 F≈8-9/R≈19, A2 已记录)。
     故本脚本在**图像像素空间**运行: 距离/速度阈值为像素。
     → 依赖 Zone 的 signature(如 CORNER/WING/BLOCK 判定) **未解**;
     → CUT/DRIVE 的「朝篮筐」方向是**假设**(--rim-dir, 默认 up, 不可靠)。
  2. 本脚本只证「真实素材 → 原语 → 候选」链路可跑; **不代表**该片段含某战术(裁定归老程)。
  3. 阈值不手写: d_screen/d_handoff/v_cut 由本片段**实测分布**导出(见输出 thresholds)。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

import cv2

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
import tactic_match as tm  # noqa: E402

# 与 t3b_rebuild_tactical.py 保持一致的老程裁定(非球员轨迹)
ADJUDGED_REFEREES = {"sas_det": "31,33,38,44,64", "sas_lal": "7,8,38"}


def _ctr(bbox):
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _read_json(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def load_ball_source(clip):
    """球位置(fid->像素中心)。优先遮挡补全(A4.54); 否则 dense 头 top1; 否则 tracks 内 ball 字段。"""
    occ = AW / "validate" / f"{clip}_ball_track_occluded.json"
    if occ.exists():
        raw = json.load(open(occ, encoding="utf-8"))
        return {int(r["fid"]): (float(r["ball"][0]), float(r["ball"][1])) if r.get("ball") else None
                for r in raw["frame"]}, "A4.54 occluded(detect+attachment)"
    dense = AW / "validate" / f"{clip}_ball_dense_th03.json"
    if dense.exists():
        raw = json.load(open(dense, encoding="utf-8"))
        out = {}
        for fname, cands in raw.items():
            try:
                fid = int(fname[1:6])
            except ValueError:
                continue
            best = None
            for c in cands or []:
                if best is None or c["conf"] > best["conf"]:
                    best = c
            out[fid] = _ctr(best["bbox"]) if best else None
        return out, "dense_head_th03_top1(partial coverage)"
    return {}, "none"


def _resolve_tracks(clip):
    for cand in (f"{clip}_poss_tile_stab", f"{clip}_poss_stable", f"{clip}_poss_tile", f"{clip}_poss"):
        p = AW / cand / "ball_tracks.json"
        if p.exists():
            return p
    raise FileNotFoundError(f"找不到 {clip} 的稳定球员轨迹 (尝试 *_poss_tile_stab/_stable/_tile/_poss)")


def load_clip(clip, tracks_json=None):
    tracks_p = Path(tracks_json) if tracks_json else _resolve_tracks(clip)
    frames_raw = json.load(open(tracks_p, encoding="utf-8"))
    ball_by_fid, ball_src = load_ball_source(clip)
    if not ball_by_fid:  # 兜底: tracks 内 ball 字段(稀疏)
        for i, fr in enumerate(frames_raw):
            b = fr.get("ball")
            ball_by_fid[i + 1] = _ctr(b["bbox"]) if b else None
        ball_src = "tracks.ball_field(sparse)"
    excl = {int(x) for x in ADJUDGED_REFEREES.get(clip, "").split(",") if x.strip()}
    frames = []
    for i, fr in enumerate(frames_raw):
        fid = i + 1
        players, bboxes, teams = {}, {}, {}
        for p in fr.get("players", []):
            tid = int(p["track_id"])
            if tid in excl:
                continue
            c = _ctr(p["bbox"])
            players[tid] = c
            bboxes[tid] = p["bbox"]
            teams[tid] = p.get("team")
        ball = ball_by_fid.get(fid)
        frames.append({"t": i, "fid": fid, "file": fr.get("file"),
                       "ball": ball, "players": players, "bboxes": bboxes, "teams": teams})
    return frames, excl, ball_src


def derive_thresholds(frames):
    """阈值全部由本片段实测分布导出(不手写常数)。"""
    diags = []
    disps = []
    for i, f in enumerate(frames):
        for tid, bb in f["bboxes"].items():
            diags.append(((bb[2] - bb[0]) ** 2 + (bb[3] - bb[1]) ** 2) ** 0.5)
        if i == 0:
            continue
        for tid, c in f["players"].items():
            c0 = frames[i - 1]["players"].get(tid)
            if c0:
                disps.append(abs(c[0] - c0[0]) + abs(c[1] - c0[1]))
    med_diag = st.median(diags)
    med_disp = st.median(disps)
    # v_cut: 明显快于常态的位移 = p95, 且至少 3x 中位位移(防慢速片段把阈值压得过低)
    disps_sorted = sorted(disps)
    p95 = disps_sorted[min(len(disps_sorted) - 1, int(0.95 * len(disps_sorted)))]
    v_cut = max(p95, 3.0 * med_disp)
    return {
        "median_player_diag_px": round(med_diag, 1),
        "median_frame_disp_px": round(med_disp, 2),
        "d_screen_px": round(0.5 * med_diag, 1),      # 两球员中心 < 半个体长 ≈ 贴身/掩护
        "d_handoff_px": round(0.6 * med_diag, 1),     # 球到人 < 0.6 体长 ≈ 交接
        "v_cut_px": round(v_cut, 2),                  # p95 位移(且 >=3x 中位)
        "min_run": 3,
    }


def render_selfevid(frames, events, out_png, top=6):
    """把检测到的原语事件画回原帧(视觉自证)。取跨时间分布的代表事件, 2x3 拼图。"""
    picks = []
    if events:
        step = max(1, len(events) // top)
        picks = events[::step][:top]
    imgs = []
    for e in picks:
        mid = (e["f0"] + e["f1"]) // 2
        fr = frames[mid]
        path = frames_raw_file(fr["file"])
        img = cv2.imread(str(path))
        if img is None:
            continue
        for tid in e.get("who", []):
            bb = fr["bboxes"].get(tid)
            if not bb:
                continue
            color = (0, 0, 255) if e["type"] == "SCREEN" else (0, 200, 0)
            cv2.rectangle(img, (int(bb[0]), int(bb[1])), (int(bb[2]), int(bb[3])), color, 3)
        lab = f'{e["type"]}{"." + e["sub"] if e.get("sub") else ""} f{e["f0"]}-{e["f1"]}'
        cv2.putText(img, lab, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3)
        h, w = img.shape[:2]
        img = cv2.resize(img, (w // 3, h // 3))
        imgs.append(img)
    if not imgs:
        return False
    while len(imgs) < 6:
        imgs.append(imgs[-1] * 0)
    row1 = cv2.hconcat(imgs[:3])
    row2 = cv2.hconcat(imgs[3:6])
    sheet = cv2.vconcat([row1, row2])
    cv2.imwrite(str(out_png), sheet)
    return True


def frames_raw_file(name):
    # 帧目录: action_work/<clip>/  (调用处注入 clip 目录)
    return Path(render_selfevid.clip_dir) / name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_det")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--min-coverage", type=float, default=0.5)
    ap.add_argument("--win", type=int, default=60, help="时间窗宽(帧, 10fps → 60帧=6s)")
    ap.add_argument("--min-events", type=int, default=2, help="窗口内最少原语事件数")
    ap.add_argument("--only-ids", default=None, help="逗号分隔的模型 id 子集(如 SAS 重点池)")
    ap.add_argument("--sas", action="store_true", help="只跑 priority.sas 模型")
    ap.add_argument("--tracks-json", default=None, help="直接指定球员轨迹 JSON(ball_tracks.json 契约)")
    ap.add_argument("--frames-dir", default=None, help="帧图目录(自证渲染用); 默认 action_work/<clip>")
    ap.add_argument("--out-suffix", default="", help="输出文件名后缀(避免覆盖)")
    ap.add_argument("--rim-dir", choices=["up", "down"], default="up",
                    help="假设的进攻篮筐方向(图像 y)。配准缺失 → 不可靠, 见输出 caveats")
    a = ap.parse_args()

    frames, excl, ball_src = load_clip(a.clip, a.tracks_json)
    frames_dir_path = Path(a.frames_dir) if a.frames_dir else AW / a.clip
    render_selfevid.clip_dir = frames_dir_path
    th = derive_thresholds(frames)
    mj = json.load(open(AW / "tactic_models.json", encoding="utf-8"))
    models = mj["models"]
    sel = None
    if a.sas:
        sel = set(mj.get("priority", {}).get("sas", []))
    if a.only_ids:
        sel = set(x.strip() for x in a.only_ids.split(",") if x.strip()) if sel is None else (sel & set(a.only_ids.split(",")))
    if sel is not None:
        models = [m for m in models if m["id"] in sel]
        print(f"[模型池] {len(models)} 个: {sorted(m['id'] for m in models)}")
    tier_by_id = {m["id"]: m.get("tier", "?") for m in mj["models"]}

    events = tm.detect_primitives(frames, d_screen=th["d_screen_px"],
                                  d_handoff=th["d_handoff_px"],
                                  v_cut=th["v_cut_px"], min_run=th["min_run"],
                                  disp_med=th["median_frame_disp_px"],
                                  med_diag=th["median_player_diag_px"])
    # 🔴 按时间窗匹配(战术=局部序列)，不跨全片聚合; signature 未评估 → 时序依赖模型降级
    wins = tm.match_windowed(events, models, win=a.win, min_cov=a.min_coverage,
                             min_events=a.min_events, top_per_win=3, signature_evaluated=False)

    primcount = dict(Counter((e["type"] + ("." + e["sub"] if e.get("sub") else "")) for e in events))
    print(f"[clip={a.clip}] 帧={len(frames)} 球源={ball_src} 剔除非球员 tid={sorted(excl) or '无'}")
    print(f"[thresholds] {th}")
    print(f"[原语] {len(events)} 个: {primcount}")
    ep_meta = _read_json(Path(a.tracks_json).parent / "meta.json") if a.tracks_json else None
    if ep_meta:
        tn = ep_meta.get("tactic_name_from_title", "")
        print(f"ℹ️ 片段来自《战术笔记》(实战片段, 当期讲解={tn!r} 为对照真值); 下列为原语驱动的 window 候选, 待与讲解对照。")
    else:
        print("⚠️ 该片段经老程裁定=**简单配合**(非战术); 下列为原语驱动的**window 候选**, 非战术认定。")
    print(f"[窗口候选] 窗宽={a.win}帧 最少事件={a.min_events} 最少覆盖率={a.min_coverage}; 候选窗口 {len(wins)} 个:")
    print("  (rank: 判别量已验证优先 → 覆盖率 → 绝对分; [seq-unverified]=判别量=次序/重复, 当前验不了 → 降级)")
    for w in wins[:a.top]:
        t = tier_by_id.get(w["model"], "?")
        tb = "〔简单配合〕" if t == "basic" else "〔战术(草案)〕" if t == "system" else ""
        uv = "  [seq-unverified ⤵]" if w.get("unverified") else ""
        print(f"  f{w['t0']:>3}-{w['t1']:<3} {w['score']:>4.2f} cov={w['coverage']:.2f}  {w['model']:20s}{tb}{uv} {w['detail']}")

    out = {
        "meta": {
            "clip": a.clip,
            "coordinate_space": "image_pixels (源画面分辨率)",
            "tracks_json": a.tracks_json,
            "frames_dir": str(frames_dir_path),
            "episode_meta": ep_meta,
            "registration": "NONE — 无 pixel→court 单应(court_fit 在 w1 失败 F≈8-9/R≈19, A2)",
            "ball_source": ball_src,
            "signature_evaluated": False,
            "signature_note": "匹配当前**只用 primitives**；signature(判别信号)多依赖 Zone/防守人相对位置 → 未计算。",
            "tactic_claim": False,
            "old_cheng_ruling": ("片段=《战术笔记》实战战术(讲解为对照真值); 本输出仅为原语窗口候选, "
                                 "须与当期讲解对照后才可下结论。") if ep_meta else
                                "2026-09-29 老程裁定: 本素材(sas_det/sas_lal 等)呈现的是**简单配合**, 不是战术。故本输出不得作为战术认定。",
            "excluded_tids": sorted(excl),
            "n_frames": len(frames),
            "rim_dir_assumption": a.rim_dir,
        },
        "thresholds": th,
        "primitives": events,
        "primitive_counts": primcount,
        "windows": [{**w, "tier": tier_by_id.get(w["model"], "?")} for w in wins],
        "caveats": [
            "Zone 依赖的 signature(区域判定)未解 —— 配准缺失。",
            f"CUT/DRIVE 的朝筐方向为假设(rim-dir={a.rim_dir})，不可靠。",
            "掩护=站定型(下/背/平)判据；**不收横向穿场的 cross screen**(掩盖人在动)。无防守人相对位置 → 无法判真掩护接触。",
            "候选是**窗口内原语聚合**(局部)，仍非「该窗含该战术」的证明。",
            "本结果仅证链路可跑；不宣称该片段含某战术(裁定归老程)。",
            "sas_det 经老程裁定为「即兴配合且失败」的非战术回合 —— 此处不因此下任何战术结论。",
        ],
    }
    outp = AW / "validate" / f"{a.clip}_tactic_match_real{a.out_suffix}.json"
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[写出] {outp}")

    # 视觉自证
    png = AW / "validate" / f"{a.clip}_tactic_match_real{a.out_suffix}_selfevid.png"
    if render_selfevid(frames, events, png):
        print(f"[自证图] {png}")
    else:
        print("[自证图] 无事件可渲染")


if __name__ == "__main__":
    main()
