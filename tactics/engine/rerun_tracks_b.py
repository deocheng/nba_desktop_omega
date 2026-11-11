#!/usr/bin/env python3
"""A5.4 全量重跑（B 配置）：177 段用放宽几何门重做球员跟踪，写 tracks_b.json。

纪律：
  - **不覆盖原 tracks.json** → 写 tracks_b.json（可回滚）。
  - 检测缓存复用（_detcache_<seg>_1280.json），无则现场跑 YOLO。
  - 逐段容错：单段异常不中断全量；写段级统计 + 汇总。
  - B 配置来自 A5.2/A5.3 实测：max_missed=30, GATE_POS=0.60, conf_person=0.25。
  - 回归指标：ID 数(base vs B)、每帧人数（硬门：不得降）、色不连续率（腿部区独立信号）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

from common.nba_paths import workspace_file

os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import segment_detect_track as sd  # noqa: E402
import track_appearance as ta  # noqa: E402
from PIL import Image  # noqa: E402
from ultralytics import YOLO  # noqa: E402

W = str(workspace_file("action_work/weights/yolo11n.pt"))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
REPORT = ROOT / "action_work" / "rerun_b_report.json"

MM, GP, GS = 30, 0.60, 0.90
IMGSZ = 1280


def get_raw(seg, frames, model):
    cache = ROOT / "action_work" / f"_detcache_{seg}_{IMGSZ}.json"
    if cache.exists():
        return json.load(open(cache)), False
    out = []
    for fr in frames:
        r = model.predict(fr["path"], imgsz=IMGSZ, conf=0.02,
                          verbose=False, device="cpu")[0]
        out.append([[int(b.cls[0]), round(float(b.conf[0]), 4),
                     [round(float(v), 1) for v in b.xyxy[0].tolist()]]
                    for b in r.boxes])
    json.dump(out, open(cache, "w"))
    return out, True


def stats_of(tracks):
    s = {}
    for tid, tr in tracks.items():
        p = tr["path"]
        pl = sum(((p[i][0]-p[i-1][0])**2 + (p[i][1]-p[i-1][1])**2) ** 0.5
                 for i in range(1, len(p)))
        hs = [b[3]-b[1] for b in tr["boxes"]]
        s[tid] = {"id": tid, "n_frames": len(tr["frames"]),
                  "first_frame": tr["frames"][0], "last_frame": tr["frames"][-1],
                  "path_len": round(pl, 1), "mean_h": round(sum(hs)/len(hs), 1),
                  "start_foot": [round(v, 1) for v in p[0]],
                  "end_foot": [round(v, 1) for v in p[-1]]}
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 段（冒烟用）")
    arg = ap.parse_args()
    segdirs = sorted([d for d in SEGD.iterdir() if d.is_dir()
                      and (d / "frames.json").exists() and (d / "tracks.json").exists()])
    if arg.limit:
        segdirs = segdirs[:arg.limit]
    print(f"[B全段] 待处理 {len(segdirs)} 段 ｜ 配置 mm={MM} gate={GP} conf=0.25",
          flush=True)
    sd.GATE_POS, sd.GATE_SIZE = GP, GS
    model = YOLO(W)
    rows, t0, ndet = [], time.perf_counter(), 0
    for i, sd_dir in enumerate(segdirs, 1):
        seg = sd_dir.name
        try:
            frames = json.load(open(sd_dir / "frames.json"))
            _, H = Image.open(frames[0]["path"]).size
            raw, fresh = get_raw(seg, frames, model)
            if fresh:
                ndet += 1
            dets = [{"person": [{"box": b[2], "conf": b[1]} for b in bx
                                if b[0] == 0 and b[1] >= 0.25],
                     "ball": [{"box": b[2], "conf": b[1]} for b in bx
                              if b[0] == 32 and b[1] >= 0.08]}
                    for bx in raw]
            pframes, tr = sd.track_people(dets, frames, H, MM)
            # 补球字段（沿用原 tracks.json 的球，球不变）
            orig = json.load(open(sd_dir / "tracks.json"))
            ball_by = {f["idx"]: {k: f.get(k) for k in
                       ("ball", "ball_handler", "handler_dist")}
                       for f in orig.get("frames") or []}
            for f in pframes:
                f.update(ball_by.get(f["idx"], {}))
            # 纯度（腿部区独立信号）
            feats = ta.build_feats(frames, raw, 0.25)
            lmap = {}
            for fi, fd in enumerate(feats):
                for d in fd:
                    lmap[(fi, tuple(round(v, 1) for v in d["box"]))] = d.get("lower")
            disc = tot = 0
            for t in tr.values():
                seq = [lmap[(fi, tuple(round(v, 1) for v in bx))]
                       for fi, bx in zip(t["frames"], t["boxes"])]
                seq = [c for c in seq if c is not None]
                for k in range(1, len(seq)):
                    dd = ta.cdist(seq[k-1], seq[k])
                    if dd is None:
                        continue
                    tot += 1
                    if dd > ta.CONT_THRESH:
                        disc += 1
            out = {"frames": pframes, "tracks": stats_of(tr),
                   "ball_track": orig.get("ball_track"),
                   "meta": {**{k: v for k, v in (orig.get("meta") or {}).items()
                               if k not in ("n_tracks",)},
                            "n_tracks": len(tr), "img_size": [0, H],
                            "config_B": {"max_missed": MM, "gate_pos": GP,
                                         "gate_size": GS, "conf_person": 0.25},
                            "source": "rerun_tracks_b"}}
            json.dump(out, open(sd_dir / "tracks_b.json", "w"), ensure_ascii=False)
            lives = [len(t["frames"]) for t in tr.values()]
            ppl = statistics.mean(len(f["players"]) for f in pframes)
            rows.append({"seg": seg, "n_ids": len(tr),
                         "med_life": statistics.median(lives),
                         "ppl_per_frame": round(ppl, 2),
                         "color_disc": round(disc / max(tot, 1), 3)})
            print(f"[{i}/{len(segdirs)}] {seg:10s} ID={len(tr):4d} "
                  f"寿命={statistics.median(lives):4.0f} 人数/帧={ppl:.1f} "
                  f"色不连续={disc/max(tot,1):.3f}"
                  f"{'  (新检测)' if fresh else ''}", flush=True)
        except Exception as e:
            print(f"[{i}/{len(segdirs)}] {seg} 失败: {type(e).__name__}: {e}",
                  flush=True)
    tot = time.perf_counter() - t0
    summ = {"n_seg_done": len(rows), "n_seg_total": len(segdirs),
            "n_fresh_detect": ndet, "elapsed_min": round(tot / 60, 1),
            "params": {"max_missed": MM, "gate_pos": GP, "conf_person": 0.25},
            "med_n_ids": statistics.median([r["n_ids"] for r in rows]) if rows else 0,
            "med_life": statistics.median([r["med_life"] for r in rows]) if rows else 0,
            "med_color_disc": statistics.median([r["color_disc"] for r in rows]) if rows else 0,
            "rows": rows}
    json.dump(summ, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n=== 完成 {len(rows)}/{len(segdirs)} 段 用时 {tot/60:.1f}min ===",
          flush=True)
    print(f"中位 ID={summ['med_n_ids']:.0f} 中位寿命={summ['med_life']:.0f} "
          f"中位色不连续={summ['med_color_disc']:.3f}", flush=True)
    print(f"-> {REPORT}", flush=True)


if __name__ == "__main__":
    main()
