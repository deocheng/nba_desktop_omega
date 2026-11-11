#!/usr/bin/env python3
"""动作分析系统 · 单帧关系预测（L2 检测追踪 + L3 关系预测）

用法:
    python relate_frame.py --image frame.png --bundle smoke_test_minimal --device cpu
    python relate_frame.py --image frame.png --bundle halfcourt_offense --device mps

流程: 图像 -> YOLO 检测(球员/球) -> 过滤(剔除观众席) -> RelateAnything 关系预测 -> 三元组

设计约束:
  - 区域只来自检测器，模型看不到类别标签（RelateAnything 的契约）
  - 观众席小人必须过滤掉，否则每帧几十个 person 框会污染关系图
  - 输出 JSON 便于 L4 时序聚合消费
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
import time
from pathlib import Path

from common.nba_paths import tactics_data_file, workspace_file

REPO = str(tactics_data_file("RelateAnything"))
VOCAB = str(tactics_data_file("vocab/basketball_tactics.json"))

os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")


def load_bundle(bundle: str) -> tuple[list[str], list[str]]:
    """返回 (注入模型的英文谓词, 对应中文注释)"""
    spec = json.loads(Path(VOCAB).read_text(encoding="utf-8"))
    preds = {p["id"]: p for p in spec["predicates"]}
    if bundle not in spec["bundles"]:
        raise SystemExit(f"未知 bundle: {bundle}，可选 {sorted(spec['bundles'])}")
    ids = spec["bundles"][bundle]["ids"]
    en = [preds[i]["en"] for i in ids]
    cn = [preds[i]["cn"] for i in ids]
    return en, cn


def detect(image_path: str, weights: str, min_person_h: int, max_persons: int,
           device: str, ball_conf: float):
    """YOLO 检测。COCO: 0=person, 32=sports ball"""
    from ultralytics import YOLO
    t0 = time.perf_counter()
    model = YOLO(weights)
    r = model.predict(image_path, verbose=False, device=device, conf=0.25)[0]
    det_ms = (time.perf_counter() - t0) * 1000

    names = r.names
    persons, balls = [], []
    for b in r.boxes:
        cls = int(b.cls[0])
        conf = float(b.conf[0])
        xyxy = [float(v) for v in b.xyxy[0].tolist()]
        h = xyxy[3] - xyxy[1]
        w = xyxy[2] - xyxy[0]
        if cls == 0:
            persons.append({"xyxy": xyxy, "conf": conf, "h": h, "w": w})
        elif cls == 32:
            balls.append({"xyxy": xyxy, "conf": conf})
    raw_person = len(persons)

    persons = [p for p in persons if p["h"] >= min_person_h and p["w"] >= min_person_h * 0.35]
    persons.sort(key=lambda p: -p["conf"])
    persons = persons[:max_persons]
    balls = [b for b in balls if b["conf"] >= ball_conf]
    balls.sort(key=lambda b: -b["conf"])

    boxes = [p["xyxy"] for p in persons] + [b["xyxy"] for b in balls[:1]]
    labels = [f"P{i+1}" for i in range(len(persons))] + \
             (["BALL"] if balls else [])
    scores = [p["conf"] for p in persons] + ([balls[0]["conf"]] if balls else [])
    meta = {"raw_person_boxes": raw_person, "kept_persons": len(persons),
            "balls": len(balls[:1]), "ball_conf": balls[0]["conf"] if balls else None,
            "detect_ms": round(det_ms, 1)}
    return boxes, labels, scores, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--bundle", default="smoke_test_minimal")
    ap.add_argument("--weights", default="yolo11n.pt")
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    ap.add_argument("--model-device", default="cpu", choices=["cpu", "mps"])
    ap.add_argument("--min-person-h", type=int, default=60)
    ap.add_argument("--max-persons", type=int, default=12)
    ap.add_argument("--ball-conf", type=float, default=0.15)
    ap.add_argument("--topk", type=int, default=15)
    ap.add_argument("--out", default="")
    ap.add_argument("--model-dir", default=os.environ.get(
        "RELSGG_LOCAL",
        str(workspace_file("action_work/models/relsgg-vits16plus"))),
        help="本地权重目录（含 model.pth / text_student.pt）；空则走 HF Hub")
    a = ap.parse_args()

    sys.path.insert(0, REPO)

    en, cn = load_bundle(a.bundle)
    print(f"[vocab] bundle={a.bundle} 注入 {len(en)} 条谓词")

    boxes, labels, scores, meta = detect(a.image, a.weights, a.min_person_h,
                                         a.max_persons, a.device, a.ball_conf)
    print(f"[detect] 原始 person 框 {meta['raw_person_boxes']} -> 保留 {meta['kept_persons']}"
          f" | 球 {meta['balls']} (conf={meta['ball_conf']}) | {meta['detect_ms']} ms")
    if len(boxes) < 2:
        print("[detect] 区域不足 2 个，无法预测关系")
        return 2

    from PIL import Image
    image = Image.open(a.image).convert("RGB")
    print(f"[image] {image.size[0]}x{image.size[1]}")

    t0 = time.perf_counter()
    from relsgg import RelateAnything
    if a.model_dir and os.path.exists(os.path.join(a.model_dir, "model.pth")):
        ckpt = os.path.join(a.model_dir, "model.pth")
        ra = RelateAnything.from_checkpoint(ckpt, device=a.model_device)
        src = f"local:{a.model_dir}"
    else:
        ra = RelateAnything.from_pretrained("maelic/relsgg-vits16plus",
                                            device=a.model_device)
        src = "hub"
    load_s = time.perf_counter() - t0
    print(f"[model] 载入 {load_s:.1f}s device={a.model_device} src={src} "
          f"calib=({ra.calib_a:.3f},{ra.calib_b:.3f})")

    t0 = time.perf_counter()
    ra.set_vocabulary(en)
    vocab_ms = (time.perf_counter() - t0) * 1000
    print(f"[vocab] 文本编码 {vocab_ms:.0f} ms")

    t0 = time.perf_counter()
    tri = ra.predict(image, boxes, box_labels=labels, box_scores=scores,
                     topk=a.topk)
    pred_ms = (time.perf_counter() - t0) * 1000
    print(f"[predict] {pred_ms:.0f} ms  ({len(boxes)} 区域, {len(tri)} 三元组)")

    print("\n=== 关系三元组 (按置信度降序) ===")
    cn_of = dict(zip(en, cn))
    rows = []
    for t in tri:
        print(f"  {t.subject_label:>4} --{t.predicate} [{t.score:.3f}]--> {t.object_label:<4}"
              f"   | {cn_of.get(t.predicate,'')}")
        rows.append({"subject": t.subject_label, "subject_idx": t.subject_idx,
                     "predicate": t.predicate, "predicate_cn": cn_of.get(t.predicate, ""),
                     "score": round(float(t.score), 4),
                     "object": t.object_label, "object_idx": t.object_idx,
                     "subject_box": [round(float(v), 1) for v in t.subject_box],
                     "object_box": [round(float(v), 1) for v in t.object_box]})

    scores_all = [r["score"] for r in rows]
    if scores_all:
        print(f"\n[区分度] min={min(scores_all):.3f} max={max(scores_all):.3f} "
              f"spread={max(scores_all)-min(scores_all):.3f}")

    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({
            "image": a.image, "bundle": a.bundle,
            "predicates": en,
            "boxes": [{"label": l, "box": [round(v,1) for v in b], "score": round(s,4)}
                      for l, b, s in zip(labels, boxes, scores)],
            "triplets": rows,
            "timing": {"detect_ms": meta["detect_ms"], "vocab_ms": round(vocab_ms, 1),
                       "predict_ms": round(pred_ms, 1), "model_load_s": round(load_s, 2)},
            "detector_meta": meta,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[out] -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
