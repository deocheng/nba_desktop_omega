#!/usr/bin/env python3
"""母语探针 —— 让模型用它自己的 19,103 词训练词表描述篮球帧

背景：注入篮球专有谓词（掩护/换防/背身）得分为零，说明域外词表失效（R1 实锤）。
本探针反过来做：不施加任何自定义词表，看模型原生会说什么，
再据此把它的原生谓词映射到篮球战术语义。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from common.nba_paths import tactics_data_file, workspace_file

REPO = str(tactics_data_file("RelateAnything"))
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--conf", type=float, default=0.08)
    ap.add_argument("--min-person-h", type=int, default=55)
    ap.add_argument("--max-persons", type=int, default=10)
    ap.add_argument("--topk", type=int, default=40)
    ap.add_argument("--outdir", default=str(workspace_file("action_work/results")))
    a = ap.parse_args()

    sys.path.insert(0, REPO)
    from PIL import Image
    from relsgg import RelateAnything
    from ultralytics import YOLO

    m = YOLO(a.weights)
    r = m.predict(a.image, verbose=False, device="cpu", conf=a.conf, imgsz=a.imgsz)[0]
    persons, balls = [], []
    for b in r.boxes:
        cls, cf = int(b.cls[0]), float(b.conf[0])
        xy = [float(v) for v in b.xyxy[0].tolist()]
        if cls == 0 and (xy[3] - xy[1]) >= a.min_person_h:
            persons.append((xy, cf))
        elif cls == 32:
            balls.append((xy, cf))
    persons.sort(key=lambda p: -p[1])
    persons = persons[:a.max_persons]
    balls.sort(key=lambda b: -b[1])
    boxes = [p[0] for p in persons] + [b[0] for b in balls[:1]]
    labels = [f"P{i+1}" for i in range(len(persons))] + (["BALL"] if balls else [])
    scores = [p[1] for p in persons] + ([balls[0][1]] if balls else [])
    print(f"[detect] {len(persons)} 球员 + {len(balls[:1])} 球")

    image = Image.open(a.image).convert("RGB")
    import time
    t0 = time.perf_counter()
    ra = RelateAnything.from_checkpoint(os.path.join(a.model_dir, "model.pth"),
                                        device="cpu", full_vocabulary=True)
    print(f"[model] 载入 {time.perf_counter()-t0:.1f}s | 原生词表 {len(ra.predicates)} 条")

    t0 = time.perf_counter()
    tri = ra.predict(image, boxes, box_labels=labels, box_scores=scores, topk=a.topk)
    print(f"[predict] {(time.perf_counter()-t0)*1000:.0f} ms | {len(tri)} 三元组")

    sc = [t.score for t in tri]
    print(f"得分 min={min(sc):.4f} max={max(sc):.4f} mean={sum(sc)/len(sc):.4f} "
          f"spread={max(sc)-min(sc):.4f}\n")
    print("=== 模型原生描述（top-40）===")
    for t in tri:
        print(f"  {t.subject_label:>4} --{t.predicate} [{t.score:.4f}]--> {t.object_label:<4}")
    print(f"\n谓词种类数: {len(set(t.predicate for t in tri))} / {len(tri)}")
    print(f"分布: {dict(Counter(t.predicate for t in tri))}")

    os.makedirs(a.outdir, exist_ok=True)
    p = os.path.join(a.outdir, "native_probe.json")
    Path(p).write_text(json.dumps({
        "image": a.image,
        "n_native_vocab": len(ra.predicates),
        "triplets": [{"s": t.subject_label, "p": t.predicate,
                      "score": round(float(t.score), 5), "o": t.object_label}
                     for t in tri]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
