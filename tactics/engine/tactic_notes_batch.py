#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tactic_notes_batch.py — 逐个分析《NBA战术笔记》视频（A4.60）
=============================================================
老程指令(2026-09-29):「你可以逐个分析战术笔记里的视频，应该有很大的帮助。」

把 A4.59 的单片段验证扩展成**全量回归**：每个视频自动定位其**实战片段**→追踪→匹配，
再与**当期战术名（来自标题/战术库，作对照真值）**比对，统计「真值战术是否被匹配到」的命中率。

🔴 关键前提（已探明, 全量前先自证）：
  战术笔记视频**混杂** 演播室主持 / 战术板图解(telestration) / 实战画面。
  实测「实战帧」可从**人物统计**干净分离：n_person ≥ N 且 中位框高 < ratio×画面高
  （演播室/特写=人少框大；telestration 帧 YOLO 常检不到真人 → 0 人）。
  阈值 N/ratio 为**几何先验**(宽景球场镜头里人不可能占半屏)，不是拍脑袋常数。

流程（每视频）:
  1 解析期号 + 从 tactic_library.json 取真值战术 → alias_index → 模型 id 集
  2 ffprobe 时长
  3 抽帧(step 秒) 检测 person → 分「实战帧」→ 连续分组 → 段(取最长 ≤max_seg 段, 每段 ≤seg_cap 秒)
  4 每段: ffmpeg 10fps 抽帧 → segment_detect_track → totracks → 匹配(时间窗) → top-k 候选
  5 记录 真值在 top-k 的排名; 汇总 CSV + MD + 命中率

诚实边界: 真值是**期级**(标题战术), 段级未必全部含该战术; 无球场配准/无防守人 → 见 tactic_match_real caveats。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from common.nba_paths import data_file, tactics_data_file, workspace_file

os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")
import numpy as np  # noqa: E402
from ultralytics import YOLO  # noqa: E402

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
ENG = ROOT / "engine"
sys.path.insert(0, str(ENG))
import assign_team as at  # noqa: E402
import court_filter as cf  # noqa: E402
import tactic_match as tm  # noqa: E402
import tactic_match_real as tmr  # noqa: E402
import tactic_notes_totracks as tt  # noqa: E402
import tactic_primitives_ext as ext  # noqa: E402  (A类修复: 原语词表扩展)

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
VID_DIR = Path(str(data_file("NBA战术笔记")))
DEFAULT_W = str(workspace_file("action_work/weights/yolo11n.pt"))


# ---------------- 期号 + 真值 ----------------
def parse_ep(name: str):
    m = re.search(r"第\s*(\d+)\s*期", name)
    if m:
        return f"ep{m.group(1)}"
    m = re.search(r"[Ee][Pp]\s*0*(\d+)", name)
    if m:
        return f"wcep{m.group(1)}"
    return None


def gt_model_ids(video_name, alias_index, clip2tactics):
    tac = clip2tactics.get(video_name, [])
    return sorted({alias_index[t] for t in tac if t in alias_index})


def load_gt_maps():
    lib = json.load(open(AW / "tactic_library.json", encoding="utf-8"))["tactics"]
    alias = json.load(open(AW / "tactic_models.json", encoding="utf-8"))["alias_index"]
    clip2tactics = {}
    for tac, d in lib.items():
        for c in d.get("source_clips", []):
            clip2tactics.setdefault(c, []).append(tac)
    return alias, clip2tactics


# ---------------- 实战片段定位 ----------------
def probe_duration(video: Path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
                         capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def classify_game_frames(video, model, step, n_min, ratio):
    """抽 step 秒/帧 → 返回 [(t, n_person, med_ratio, is_game)]。"""
    td = Path(tempfile.mkdtemp(prefix="tnprobe_"))
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(video),
                    "-vf", f"fps=1/{step},scale=960:-1", str(td / "f%04d.jpg")], check=True)
    files = sorted(td.glob("f*.jpg"))
    rows = []
    for i, fp in enumerate(files):
        r = model.predict(str(fp), classes=[0], conf=0.30, verbose=False, imgsz=960)[0]
        H = r.orig_shape[0]
        b = r.boxes.xyxy.cpu().numpy() if r.boxes is not None else np.zeros((0, 4))
        hs = (b[:, 3] - b[:, 1]) if len(b) else np.array([])
        med = float(np.median(hs)) if len(hs) else 0.0
        mr = med / H if H else 0.0
        is_game = (len(b) >= n_min and mr < ratio)
        rows.append((i * step, len(b), round(mr, 3), bool(is_game)))
    for f in files:
        f.unlink()
    td.rmdir()
    return rows


def group_segments(rows, step, min_seg_sec):
    """连续 is_game 帧 → 段 [(t0,t1)]; 只保留 ≥min_seg_sec 的段。"""
    segs = []
    cur = None
    for t, _n, _mr, g in rows:
        if g:
            if cur is None:
                cur = [t, t]
            else:
                cur[1] = t
        else:
            if cur is not None:
                segs.append((cur[0], cur[1] + step))
                cur = None
    if cur is not None:
        segs.append((cur[0], cur[1] + step))
    return [(a, b) for a, b in segs if (b - a) >= min_seg_sec]


# ---------------- 单段: 追踪 + 匹配 ----------------
def run_segment(video, t0, t1, seg_dir, models, fps, topk, court_filter=True, min_evidence=2,
                use_ext_primitives=True):
    seg_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = seg_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    # 抽帧
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(t0), "-to", str(t1), "-i", str(video),
                    "-vf", f"fps={fps}", "-q:v", "3", str(frames_dir / "f%05d.jpg")], check=True)
    files = sorted(frames_dir.glob("f*.jpg"))
    if len(files) < 20:
        return None
    recs = [{"idx": i, "t": round(t0 + i / fps, 3), "path": str(p)} for i, p in enumerate(files)]
    (seg_dir / "frames.json").write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")
    # 追踪
    subprocess.run([sys.executable, str(ENG / "segment_detect_track.py"),
                    str(seg_dir / "frames.json"), str(seg_dir)],
                   capture_output=True, text=True, check=True)
    # 场上球员过滤（剔观众/替补；掩膜不可靠或过度过滤 → 回退原轨迹）
    tracks_use = seg_dir / "tracks.json"
    cf_stat = None
    if court_filter:
        try:
            cf_stat = cf.filter_tracks_json(tracks_use, frames_dir, seg_dir / "tracks_cf.json", 0.5)
            kd, dd = cf_stat["kept_detections"], cf_stat["dropped_detections"]
            frac = kd / (kd + dd) if (kd + dd) else 1.0
            cf_stat["kept_frac"] = round(frac, 3)
            if frac >= 0.15:                       # 保留率过低=掩膜失效 → 用原始轨迹
                tracks_use = seg_dir / "tracks_cf.json"
            else:
                cf_stat["fallback"] = "kept_frac<0.15 → 用原始轨迹"
        except Exception as e:  # noqa: BLE001
            cf_stat = {"error": str(e)[:150]}
    # 队色分配（A4.61 解锁路径①：逐帧独立判据，ID 碎片免疫）
    team_of, team_info = None, None
    try:
        team_of, team_info = at.compute_team_of(seg_dir, tracks_name=tracks_use.name)
    except Exception as e:  # noqa: BLE001
        team_info = {"error": str(e)[:150]}
    # 转契约
    tt.convert(tracks_use, frames_dir, seg_dir / "ball_tracks.json", team_of=team_of)
    # 匹配（复用 tactic_match_real 的载入/阈值导出）
    frames, excl, ball_src = tmr.load_clip(f"tnseg_{seg_dir.name}", str(seg_dir / "ball_tracks.json"))
    th = tmr.derive_thresholds(frames)
    events = tm.detect_primitives(frames, d_screen=th["d_screen_px"], d_handoff=th["d_handoff_px"],
                                  v_cut=th["v_cut_px"], min_run=th["min_run"],
                                  disp_med=th["median_frame_disp_px"],
                                  med_diag=th["median_player_diag_px"])
    # A类修复(2026-10-03): 扩展原语词表 —— 原 detect_primitives 只产 5 种原语,
    # 导致 key_primitive 门把 11/13 真值结构性淘汰。ext 从像素轨迹补 PASS/DRIVE/EXCHANGE/
    # ROLL + 掩护子类(STS/GHOST/EXIT/TOUCH)，全部阈值由 th 实测分布注入。
    try:
        if use_ext_primitives:
            events = ext.augment(frames, events, th)
        else:
            aug_err = None
    except Exception as e:  # noqa: BLE001
        events = events  # 扩展失败不阻塞主流程, 但记录
        aug_err = str(e)[:150]
    else:
        aug_err = None
    wins = tm.match_windowed(events, models, win=60, min_cov=0.5, min_events=2,
                             top_per_win=5, signature_evaluated=False, min_evidence=min_evidence)
    prims = dict(Counter(e["type"] + ("." + e["sub"] if e.get("sub") else "") for e in events))
    return {"t0": t0, "t1": t1, "n_frames": len(frames), "ball_src": ball_src,
            "court_filter": cf_stat, "used_tracks": tracks_use.name,
            "team_info": team_info, "augment_err": aug_err,
            "primitives": prims, "n_events": len(events),
            "windows": [{"model": w["model"], "score": w["score"], "coverage": w["coverage"],
                         "t0": w["t0"], "t1": w["t1"], "unverified": w["unverified"]} for w in wins[:topk]]}


def model_rank(windows, gt_ids):
    """真值模型在该段候选里的最佳排名(1-based); 无则 None。"""
    for i, w in enumerate(windows, 1):
        if w["model"] in gt_ids:
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个(试点)")
    ap.add_argument("--episodes", default="", help="逗号列表, 按期号(如 24,2,15)只跑这些")
    ap.add_argument("--step", type=float, default=2.0, help="探针抽帧步长(秒)")
    ap.add_argument("--n-min", type=int, default=6, help="实战帧最少人数")
    ap.add_argument("--size-ratio", type=float, default=0.5, help="实战帧中位框高/画面高 上限")
    ap.add_argument("--min-seg", type=float, default=6.0, help="最短片段(秒)")
    ap.add_argument("--max-seg", type=int, default=2, help="每视频最多取几段")
    ap.add_argument("--seg-cap", type=float, default=45.0,
                    help="每段最长(秒)；老程 2026-10-03 目标 40~50s 覆盖一次战术配合")
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--topk", type=int, default=6)
    ap.add_argument("--no-court-filter", action="store_true",
                    help="关闭「球场地面掩膜」剔观众(默认开启; 用于 A/B 对比)")
    ap.add_argument("--min-evidence", type=int, default=2,
                    help="复杂度先验分母下限(默认2=A类修复; =1 退回旧公式做 A/B 对照)")
    ap.add_argument("--no-ext-primitives", action="store_true",
                    help="关闭原语词表扩展(A/B 对照: 只用原 5 种原语)")
    ap.add_argument("--out", default=str(AW / "tactic_notes_batch"))
    a = ap.parse_args()

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = out_dir / "segments"
    clips_dir.mkdir(exist_ok=True)

    mj = json.load(open(AW / "tactic_models.json", encoding="utf-8"))
    models = mj["models"]
    alias, clip2tactics = load_gt_maps()
    model = YOLO(DEFAULT_W)

    vids = sorted(VID_DIR.glob("*.mp4"),
                  key=lambda p: (parse_ep(p.name) or "zzz"))
    if a.episodes:
        want = {f"ep{x.strip()}" for x in a.episodes.split(",") if x.strip()}
        vids = [v for v in vids if parse_ep(v.name) in want]
    if a.limit:
        vids = vids[:a.limit]

    print(f"[batch] 待分析 {len(vids)} 个视频; 探针 step={a.step}s 实战帧判据: ≥{a.n_min}人 且 中位框<{a.size_ratio}H")
    rows = []
    for vi, v in enumerate(vids, 1):
        ep = parse_ep(v.name) or "?"
        gt_ids = gt_model_ids(v.name, alias, clip2tactics)
        dur = probe_duration(v)
        cf = classify_game_frames(v, model, a.step, a.n_min, a.size_ratio)
        segs = group_segments(cf, a.step, a.min_seg)
        segs.sort(key=lambda s: -(s[1] - s[0]))
        segs = segs[:a.max_seg]
        seg_reports = []
        for si, (t0, t1) in enumerate(segs):
            t1 = min(t1, t0 + a.seg_cap)
            try:
                rep = run_segment(v, t0, t1, clips_dir / f"{ep}_s{si}", models, a.fps, a.topk,
                                  court_filter=not a.no_court_filter, min_evidence=a.min_evidence,
                                  use_ext_primitives=not a.no_ext_primitives)
            except Exception as e:  # noqa: BLE001
                rep = {"t0": t0, "t1": t1, "error": str(e)[:200]}
            if rep:
                rep["gt_rank"] = model_rank(rep.get("windows", []), gt_ids)
                seg_reports.append(rep)
        ranks = [r["gt_rank"] for r in seg_reports if r.get("gt_rank")]
        best = min(ranks) if ranks else None
        row = {
            "video": v.name, "ep": ep, "dur": round(dur, 1),
            "gt_models": gt_ids, "n_game_seg": len(segs),
            "seg_windows": [r.get("t0") for r in seg_reports],
            "gt_best_rank": best,
            "hit_at1": (best == 1), "hit_at3": (best is not None and best <= 3),
            "hit_atk": (best is not None),
            "top1_by_seg": [r["windows"][0]["model"] if r.get("windows") else None for r in seg_reports],
            "seg_detail": seg_reports,
        }
        rows.append(row)
        tag = "✅" if row["hit_at1"] else ("◯" if row["hit_atk"] else "✗")
        print(f"  [{vi}/{len(vids)}] {tag} {ep:8s} gt={gt_ids or '—'} 实战段={len(segs)} "
              f"真值最佳排名={best} seg_top1={row['top1_by_seg']}", flush=True)
        # 增量落盘(防中断丢全部)
        json.dump({"partial": True, "n_done": vi, "rows": rows},
                  open(out_dir / "batch_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 汇总
    ev = [r for r in rows if r["gt_models"]]
    n_ev = len(ev)
    h1 = sum(1 for r in ev if r["hit_at1"])
    h3 = sum(1 for r in ev if r["hit_at3"])
    hk = sum(1 for r in ev if r["hit_atk"])
    no_seg = sum(1 for r in ev if r["n_game_seg"] == 0)
    summary = {
        "n_videos": len(rows), "n_with_gt": n_ev, "n_no_gt": len(rows) - n_ev,
        "n_gt_but_no_game_seg": no_seg,
        "hit_at1": h1, "hit_at3": h3, "hit_atk": hk,
        "hit_at1_pct": round(100 * h1 / n_ev, 1) if n_ev else 0,
        "hit_at3_pct": round(100 * h3 / n_ev, 1) if n_ev else 0,
        "hit_atk_pct": round(100 * hk / n_ev, 1) if n_ev else 0,
    }
    json.dump({"summary": summary, "rows": rows},
              open(out_dir / "batch_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # CSV
    with open(out_dir / "batch_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ep", "video", "gt_models", "n_game_seg", "gt_best_rank",
                    "hit@1", "hit@3", "hit@k", "top1_by_seg"])
        for r in rows:
            w.writerow([r["ep"], r["video"], "|".join(r["gt_models"]), r["n_game_seg"],
                        r["gt_best_rank"], r["hit_at1"], r["hit_at3"], r["hit_atk"],
                        "|".join(str(x) for x in r["top1_by_seg"])])

    print("\n" + "=" * 60)
    print(f"[汇总] 视频 {summary['n_videos']} | 有真值 {n_ev} | 无真值 {summary['n_no_gt']} "
          f"| 有真值但没定位到实战段 {no_seg}")
    print(f"       真值命中: top1 {h1}/{n_ev} ({summary['hit_at1_pct']}%)  "
          f"top3 {h3}/{n_ev} ({summary['hit_at3_pct']}%)  "
          f"top-k {hk}/{n_ev} ({summary['hit_atk_pct']}%)")
    print(f"       产出 {out_dir}/batch_results.{{json,csv}}")


if __name__ == "__main__":
    main()
