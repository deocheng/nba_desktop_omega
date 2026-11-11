#!/usr/bin/env python3
"""完整 17 关键点姿态缓存（YOLO11n-pose）—— 供「骨架运动特征 → 动作」层使用。

背景与动机（2026-09-23）：
    `pose_hi_cache.json` 当初**只留了 `boxes` 与 `wrists`**（因为球检测只需要手腕），
    导致后续想做动作识别时拿不到骨架：跳跃、封盖、抢篮板这些动作的核心判据
    （踝关节离地、手腕高于头、躯干折叠）全都在被丢弃的关键点上。
    本脚本重跑一遍推理，把 **17 个 COCO 关键点的 (x, y, conf) 全量落盘**，
    一次算清、后续复用，不再重跑模型。

COCO-17 顺序:
    0 nose, 1/2 eye, 3/4 ear, 5/6 shoulder, 7/8 elbow, 9/10 wrist,
    11/12 hip, 13/14 knee, 15/16 ankle
    （左 5/7/9/11/13/15，右 6/8/10/12/14/16）

输出契约:
    {"frames": {"<idx>": {"persons": [{"box": [x1,y1,x2,y2], "conf": float,
                                         "kpt": [[x,y,conf] × 17]}]}},
     "meta": {...}}

用法:
  pose_keypoints.py <frames.json> <weights> <out.json> [--imgsz 1280] [--conf 0.35]
                    [--device cpu] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import time

os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")

KPT_NAMES = ["nose", "l_eye", "r_eye", "l_ear", "r_ear",
             "l_shoulder", "r_shoulder", "l_elbow", "r_elbow", "l_wrist", "r_wrist",
             "l_hip", "r_hip", "l_knee", "r_knee", "l_ankle", "r_ankle"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_json")
    ap.add_argument("weights")
    ap.add_argument("out_json")
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    from ultralytics import YOLO

    frames = json.load(open(a.frames_json))
    if a.limit:
        frames = frames[:a.limit]
    model = YOLO(a.weights)

    out, t0, n_person = {}, time.perf_counter(), 0
    for i, f in enumerate(frames):
        res = model.predict(f["path"], imgsz=a.imgsz, conf=a.conf,
                            device=a.device, verbose=False)[0]
        persons = []
        if res.keypoints is not None and len(res.keypoints):
            kp = res.keypoints.xy.cpu().numpy()
            kc = (res.keypoints.conf.cpu().numpy() if res.keypoints.conf is not None
                  else None)
            bx = res.boxes.xyxy.cpu().numpy()
            bc = res.boxes.conf.cpu().numpy()
            for j in range(len(kp)):
                kpt = [[round(float(kp[j, k, 0]), 1), round(float(kp[j, k, 1]), 1),
                        round(float(kc[j, k]), 3) if kc is not None else 1.0]
                       for k in range(17)]
                persons.append({
                    "box": [round(float(v), 1) for v in bx[j]],
                    "conf": round(float(bc[j]), 4),
                    "kpt": kpt,
                })
        n_person += len(persons)
        out[str(f["idx"])] = {"persons": persons}
        if (i + 1) % 50 == 0 or i + 1 == len(frames):
            dt = time.perf_counter() - t0
            print(f"  {i + 1}/{len(frames)}  {dt / (i + 1) * 1000:.0f} ms/帧  "
                  f"累计 {dt:.0f}s", flush=True)

    dt = time.perf_counter() - t0
    with open(a.out_json, "w") as fp:
        json.dump({"frames": out,
                   "meta": {"n_frames": len(frames), "n_person": n_person,
                            "imgsz": a.imgsz, "conf": a.conf, "device": a.device,
                            "kpt_names": KPT_NAMES,
                            "total_sec": round(dt, 1)}}, fp)
    print(f"[out] {a.out_json}")
    print(f"[stat] 帧 {len(frames)}  人物框 {n_person}  "
          f"均 {n_person / max(len(frames), 1):.2f} 人/帧  耗时 {dt:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
