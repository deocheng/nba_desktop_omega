#!/usr/bin/env python3
"""A5.4 多段复验：几何门放宽(base vs B60 vs B90) 是否在**多段**上稳住 ID 降幅与纯度。

证据动机：单段 ep1_s0 上 B(gate.60/.90) 把 ID 从 183 降到 95/83，且色不连续率维持低位
⇒ 推翻"宽松门必然错并"的假设。但单段不算数，本脚本跨多段复验。

复用：_detcache_<seg>_1280.json（若无则现场检测）；segment_detect_track.track_people。
纯度指标=合并轨迹内「腿部区色」不连续率（独立于关联用的躯干区）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
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
SEGS = ["ep1_s0", "ep10_s0", "ep11_s0", "ep24_s1", "ep5_s1"]
CONFIGS = [("base mm3 gate.16", 3, 0.16, 0.90),
           ("B60  mm30 gate.60", 30, 0.60, 0.90),
           ("B90  mm30 gate.90", 30, 0.90, 0.90)]


def get_raw(seg, frames, imgsz=1280):
    cache = ROOT / "action_work" / f"_detcache_{seg}_{imgsz}.json"
    if cache.exists():
        return json.load(open(cache))
    model = YOLO(W)
    out = []
    for fr in frames:
        r = model.predict(fr["path"], imgsz=imgsz, conf=0.02,
                          verbose=False, device="cpu")[0]
        out.append([[int(b.cls[0]), round(float(b.conf[0]), 4),
                     [round(float(v), 1) for v in b.xyxy[0].tolist()]]
                    for b in r.boxes])
    json.dump(out, open(cache, "w"))
    return out


def main():
    print(f"{'seg':10s}{'配置':<18}{'ID数':>6}{'寿命':>6}{'最长':>6}{'人数/帧':>8}{'色不连续':>9}")
    agg = {}
    for seg in SEGS:
        sd_dir = ROOT / "action_work" / "tactic_notes_batch_full" / "segments" / seg
        if not (sd_dir / "frames.json").exists():
            print(f"{seg:10s} 跳过(无 frames.json)"); continue
        frames = json.load(open(sd_dir / "frames.json"))
        raw = get_raw(seg, frames)
        _, H = Image.open(frames[0]["path"]).size
        feats = ta.build_feats(frames, raw, 0.25)
        # track_people 需要 {person,ball} 结构
        dets = [{"person": [{"box": d["box"], "conf": d["conf"]} for d in fd],
                 "ball": []} for fd in feats]
        for name, mm, gp, gs in CONFIGS:
            sd.GATE_POS, sd.GATE_SIZE = gp, gs
            pf, tr = sd.track_people(dets, frames, H, mm)
            lives = [len(t["frames"]) for t in tr.values()]
            ppl = statistics.mean(len(f["players"]) for f in pf)
            # 纯度：用 track_appearance 的独立腿部色（重算 feats 的 lower 已在 feats 里）
            # 简化：这里 feats 只算了 torso? build_feats 同时算 lower -> 可用
            disc = tot = 0
            lmap = {}
            for fi, fd in enumerate(feats):
                for d in fd:
                    lmap[(fi, tuple(round(v, 1) for v in d["box"]))] = d.get("lower")
            for t in tr.values():
                seq = []
                for fi, bx in zip(t["frames"], t["boxes"]):
                    c = lmap.get((fi, tuple(round(v, 1) for v in bx)))
                    if c is not None:
                        seq.append(c)
                for i in range(1, len(seq)):
                    dd = ta.cdist(seq[i - 1], seq[i])
                    if dd is None:
                        continue
                    tot += 1
                    if dd > ta.CONT_THRESH:
                        disc += 1
            rate = round(disc / max(tot, 1), 3)
            print(f"{seg:10s}{name:<18}{len(tr):>6}"
                  f"{statistics.median(lives):>6.0f}{max(lives):>6}{ppl:>8.1f}{rate:>9}")
            agg.setdefault(name, []).append((len(tr), statistics.median(lives), rate))
    print("\n=== 汇总(中位) ===")
    for name, vals in agg.items():
        ids = statistics.median(v[0] for v in vals)
        lf = statistics.median(v[1] for v in vals)
        rr = statistics.median(v[2] for v in vals)
        print(f"{name:<18} 中位ID={ids:.0f}  中位寿命={lf:.0f}  中位色不连续={rr}")


if __name__ == "__main__":
    main()
