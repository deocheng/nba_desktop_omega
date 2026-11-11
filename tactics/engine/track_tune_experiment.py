#!/usr/bin/env python3
"""A5.2 单段对照实验：球员跟踪参数扫描（"不丢人"为硬门）。

背景：A5.1 定位碎片根因=上游跟踪，`segment_detect_track.py` 自研 SORT-lite
      `max_missed=3` ⇒ 漏检>3帧即重开 ID。本实验扫 max_missed / conf_person / gate。

设计（省算力、可复现）：
  - 检测**只跑一次**（imgsz/全局conf 固定），原始框缓存 → 各配置仅换过滤阈值。
  - 跟踪直接复用 segment_detect_track.track_people（monkeypatch 其模块常量）。
  - 指标：ID数(↓好) / 中位寿命(↑好) / **每帧人数(硬门:不得下降)** / 长间隔续接次数(风险指示)。
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
from PIL import Image  # noqa: E402
from ultralytics import YOLO  # noqa: E402

DEFAULT_W = str(workspace_file("action_work/weights/yolo11n.pt"))


def detect_cache(model, frames, imgsz, cache):
    if cache.exists():
        return json.load(open(cache))
    raw = []
    t0 = time.perf_counter()
    for fr in frames:
        r = model.predict(fr["path"], imgsz=imgsz, conf=0.02,
                          verbose=False, device="cpu")[0]
        raw.append([[int(b.cls[0]), round(float(b.conf[0]), 4),
                     [round(float(v), 1) for v in b.xyxy[0].tolist()]]
                    for b in r.boxes])
    print(f"检测 {len(frames)} 帧 @ imgsz={imgsz} 用时 {time.perf_counter()-t0:.1f}s")
    json.dump(raw, open(cache, "w"))
    return raw


def metrics(tracks, pframes):
    n = len(tracks)
    lives = [len(t["frames"]) for t in tracks.values()]
    med = statistics.median(lives)
    # 每帧实际发出的球员数（硬门：不得下降）
    ppl = statistics.mean(len(f["players"]) for f in pframes)
    # 长间隔续接：轨迹内相邻记录帧号差 >3 的次数（coasting 风险指示）
    gaps = 0
    for t in tracks.values():
        fs = t["frames"]
        gaps += sum(1 for i in range(1, len(fs)) if fs[i] - fs[i - 1] > 3)
    return {"n_ids": n, "med_life": round(med, 1), "max_life": max(lives),
            "ppl_per_frame": round(ppl, 2),
            "long_reattach": gaps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep1_s0")
    ap.add_argument("--imgsz", type=int, default=1280)
    a = ap.parse_args()

    segdir = ROOT / "action_work" / "tactic_notes_batch_full" / "segments" / a.seg
    frames = json.load(open(segdir / "frames.json"))
    W, H = Image.open(frames[0]["path"]).size
    print(f"段={a.seg} 帧={len(frames)} 分辨率={W}x{H}")

    cache = ROOT / "action_work" / f"_detcache_{a.seg}_{a.imgsz}.json"
    raw = detect_cache(YOLO(DEFAULT_W), frames, a.imgsz, cache)

    def build_dets(conf_person):
        out = []
        for boxes in raw:
            ps = [{"box": b[2], "conf": b[1]} for b in boxes
                  if b[0] == 0 and b[1] >= conf_person]
            bs = [{"box": b[2], "conf": b[1]} for b in boxes
                  if b[0] == 32 and b[1] >= 0.08]
            out.append({"person": ps, "ball": bs})
        return out

    # 参考：原配置（应与该段 tracks.json 一致）
    print(f"\n{'配置':<34}{'ID数':>6}{'中位寿命':>9}{'最长':>6}"
          f"{'每帧人数':>9}{'长续接':>7}")
    configs = [
        ("conf.25 mm3  gate.16 (base)", 0.25, 3, 0.16, 0.90),
        ("conf.25 mm30 gate.16", 0.25, 30, 0.16, 0.90),
        ("conf.25 mm30 gate.25", 0.25, 30, 0.25, 0.90),
        ("conf.25 mm30 gate.40", 0.25, 30, 0.40, 0.90),
        ("conf.25 mm30 gate.25 sz1.3", 0.25, 30, 0.25, 1.30),
        ("conf.25 mm50 gate.40 sz1.3", 0.25, 50, 0.40, 1.30),
    ]
    rows = []
    for name, cp, mm, gp, gsz in configs:
        sd.GATE_POS, sd.GATE_SIZE = gp, gsz
        dets = build_dets(cp)
        det_ppl = statistics.mean(len(d["person"]) for d in dets)
        pframes, tracks = sd.track_people(dets, frames, H, mm)
        m = metrics(tracks, pframes)
        m["name"] = name
        m["det_ppl"] = round(det_ppl, 2)
        rows.append(m)
        print(f"{name:<34}{m['n_ids']:>6}{m['med_life']:>9}"
              f"{m['max_life']:>6}{m['ppl_per_frame']:>9}{m['long_reattach']:>7}")

    out = ROOT / "action_work" / f"track_tune_{a.seg}.json"
    json.dump({"seg": a.seg, "imgsz": a.imgsz, "n_frames": len(frames),
               "img_size": [W, H], "rows": rows},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n每帧检测人数(过滤后, 应各配置相同): "
          f"{sorted({r['det_ppl'] for r in rows})}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
