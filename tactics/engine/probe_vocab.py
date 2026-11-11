#!/usr/bin/env python3
"""词表区分度探针 —— 验证 R1 风险

问题：RelateAnything 训练语料 RA-4M 来自通用图像，篮球专有谓词属域外。
必须实证：(a) 得分是否有非退化的区分度；(b) 通用词 vs 篮球专有词谁更稳。

做法：一次载入模型，同一帧跑多个 bundle，输出各自的得分分布 / top 关系 /
谓词直方图，并渲染一张框+关系的叠加图便于目视核对。
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
VOCAB = str(tactics_data_file("vocab/basketball_tactics.json"))
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")


def load_bundle(bundle: str):
    spec = json.loads(Path(VOCAB).read_text(encoding="utf-8"))
    preds = {p["id"]: p for p in spec["predicates"]}
    ids = spec["bundles"][bundle]["ids"]
    return [preds[i]["en"] for i in ids], [preds[i]["cn"] for i in ids]


def detect(image_path: str, weights: str, imgsz: int, conf: float,
           min_person_h: int, max_persons: int):
    from ultralytics import YOLO
    model = YOLO(weights)
    r = model.predict(image_path, verbose=False, device="cpu", conf=conf,
                      imgsz=imgsz)[0]
    persons, balls = [], []
    for b in r.boxes:
        cls, cf = int(b.cls[0]), float(b.conf[0])
        xy = [float(v) for v in b.xyxy[0].tolist()]
        h, w = xy[3] - xy[1], xy[2] - xy[0]
        if cls == 0:
            persons.append((xy, cf, h, w))
        elif cls == 32:
            balls.append((xy, cf))
    raw = len(persons)
    persons = [p for p in persons if p[2] >= min_person_h and p[3] >= min_person_h * 0.35]
    persons.sort(key=lambda p: -p[1])
    persons = persons[:max_persons]
    balls.sort(key=lambda b: -b[1])
    return persons, balls, raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--bundles", default="smoke_test_minimal,halfcourt_offense")
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--conf", type=float, default=0.10)
    ap.add_argument("--min-person-h", type=int, default=55)
    ap.add_argument("--max-persons", type=int, default=12)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--outdir", default=str(workspace_file("action_work/results")))
    a = ap.parse_args()

    sys.path.insert(0, REPO)
    from PIL import Image, ImageDraw
    from relsgg import RelateAnything

    persons, balls, raw = detect(a.image, a.weights, a.imgsz, a.conf,
                                 a.min_person_h, a.max_persons)
    print(f"[detect] imgsz={a.imgsz} conf={a.conf} | 原始 person {raw} -> "
          f"保留 {len(persons)} | 球 {len(balls)}")
    for i, (b, cf) in enumerate(balls[:5]):
        print(f"          ball{i}: conf={cf:.3f} box={[round(v) for v in b]}")

    boxes = [p[0] for p in persons] + [b[0] for b in balls[:1]]
    labels = [f"P{i+1}" for i in range(len(persons))] + (["BALL"] if balls else [])
    scores = [p[1] for p in persons] + ([balls[0][1]] if balls else [])
    if len(boxes) < 2:
        print("区域不足"); return 2

    image = Image.open(a.image).convert("RGB")
    print(f"[image] {image.size}")

    import time
    t0 = time.perf_counter()
    ra = RelateAnything.from_checkpoint(os.path.join(a.model_dir, "model.pth"),
                                       device="cpu")
    print(f"[model] 载入 {time.perf_counter()-t0:.1f}s calib=({ra.calib_a:.3f},{ra.calib_b:.3f})")

    os.makedirs(a.outdir, exist_ok=True)
    summary = {}
    for bundle in a.bundles.split(","):
        en, cn = load_bundle(bundle)
        cn_of = dict(zip(en, cn))
        t0 = time.perf_counter()
        ra.set_vocabulary(en)
        enc_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        tri = ra.predict(image, boxes, box_labels=labels, box_scores=scores,
                         topk=a.topk)
        ms = (time.perf_counter() - t0) * 1000

        sc = [t.score for t in tri]
        hist = Counter(t.predicate for t in tri)
        print(f"\n=== bundle={bundle} | {len(en)} 谓词 | 编码 {enc_ms:.0f}ms | "
              f"预测 {ms:.0f}ms | top-k {len(tri)} ===")
        print(f"    得分 min={min(sc):.4f} max={max(sc):.4f} "
              f"mean={sum(sc)/len(sc):.4f} spread={max(sc)-min(sc):.4f}")
        for t in tri[:8]:
            print(f"    {t.subject_label:>4} --{t.predicate} [{t.score:.4f}]--> "
                  f"{t.object_label:<4} | {cn_of.get(t.predicate,'')}")
        print(f"    谓词分布: {dict(hist)}")
        summary[bundle] = {
            "n_predicates": len(en), "encode_ms": round(enc_ms, 1),
            "predict_ms": round(ms, 1),
            "score_min": round(min(sc), 5), "score_max": round(max(sc), 5),
            "score_mean": round(sum(sc)/len(sc), 5), "spread": round(max(sc)-min(sc), 5),
            "histogram": dict(hist),
            "triplets": [{"s": t.subject_label, "p": t.predicate,
                          "p_cn": cn_of.get(t.predicate, ""),
                          "score": round(float(t.score), 5), "o": t.object_label}
                         for t in tri],
        }

    # 叠加图
    img = image.copy()
    d = ImageDraw.Draw(img)
    for i, (b, lab) in enumerate(zip(boxes, labels)):
        col = (255, 60, 60) if lab != "BALL" else (255, 200, 0)
        d.rectangle(b, outline=col, width=3)
        d.text((b[0] + 3, b[1] + 3), lab, fill=col)
    ov = os.path.join(a.outdir, "overlay_boxes.png")
    img.save(ov)
    print(f"\n[out] {ov}")

    jp = os.path.join(a.outdir, "vocab_probe.json")
    Path(jp).write_text(json.dumps({
        "image": a.image, "detector": {"imgsz": a.imgsz, "conf": a.conf,
                                       "raw_persons": raw, "kept": len(persons),
                                       "balls": len(balls)},
        "boxes": [{"label": l, "box": [round(v, 1) for v in b], "score": round(s, 4)}
                  for l, b, s in zip(labels, boxes, scores)],
        "bundles": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {jp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
