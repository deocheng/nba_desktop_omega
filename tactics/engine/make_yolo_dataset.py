#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_yolo_dataset.py — 目视验收结果 → YOLO 训练集。
输入 candidates_filtered(含cand_id) + decisions.json({"accept":[id..],"reject":[id..]})
输出 ultralytics 可训练目录:
  images/{train,val}/*.jpg   (复制原图)
  labels/{train,val}/*.txt   ("0 cx cy w h" 归一化；全拒帧=空文件作负样本)
  dataset.yaml
未出现在 decisions 里的候选帧不进训练集（避免未验证帧污染）。
"""
import argparse
import json
import random
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates_json")
    ap.add_argument("decisions_json")
    ap.add_argument("frames_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cands = json.loads(Path(args.candidates_json).read_text())
    dec = json.loads(Path(args.decisions_json).read_text())
    accept = set(dec.get("accept", []))
    reject = set(dec.get("reject", []))

    # 帧 → 接受的框
    frame_boxes = {}
    verified_frames = set()
    for name, lst in cands.items():
        acc = [c["bbox"] for c in lst if c["cand_id"] in accept]
        rej = [c for c in lst if c["cand_id"] in reject]
        if acc or rej:
            verified_frames.add(name)
            if acc:
                frame_boxes[name] = acc

    out = Path(args.out)
    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    names = sorted(verified_frames)
    random.Random(args.seed).shuffle(names)
    n_val = max(1, int(len(names) * args.val_frac))
    val_set = set(names[:n_val])

    n_pos = n_neg = 0
    for name in names:
        split = "val" if name in val_set else "train"
        src = Path(args.frames_dir) / name
        shutil.copy2(src, out / "images" / split / name)
        h, w = 1080, 1920
        lines = []
        for (x1, y1, x2, y2) in frame_boxes.get(name, []):
            cx = (x1 + x2) / 2.0 / w
            cy = (y1 + y2) / 2.0 / h
            bw = (x2 - x1) / w
            bh = (y2 - y1) / h
            lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        (out / "labels" / split / (name.rsplit(".", 1)[0] + ".txt")).write_text(
            "\n".join(lines))
        if lines:
            n_pos += 1
        else:
            n_neg += 1

    yaml = (f"path: {out}\n"
            f"train: images/train\n"
            f"val: images/val\n"
            f"names:\n  0: ball\n")
    (out / "dataset.yaml").write_text(yaml)
    print(f"frames_used={len(names)} pos={n_pos} neg={n_neg} val={len(val_set)}")
    print(f"dataset.yaml at {out/'dataset.yaml'}")


if __name__ == "__main__":
    main()
