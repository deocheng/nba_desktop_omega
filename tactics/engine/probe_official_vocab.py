#!/usr/bin/env python3
"""决定性探针：官方 35 词表 vs 自建词表 —— 分数区间对比。

背景（2026-09-23）：
  `thresholds.json`（官方）给出 243 个谓词的逐词 best_f1_thr，其中 **219/243 条 ≥ 0.95**，
  即官方推荐工作点在 score ≈ 0.98。但我们自建词表在同一帧的 max 只有 0.086、原生词表 0.364，
  相差 3–10 倍。到底是谁的问题？本脚本回答它。

  注意 thresholds.json 的 regime 是 `boxes: gt, pair_weight: 0`，
  与我们的 YOLO 检测框 + pair_weight=1 不是同一工况，结论要按工况解读。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import os
import sys

from common.nba_paths import tactics_data_file, workspace_file

sys.path.insert(0, str(tactics_data_file("RelateAnything")))
sys.path.insert(0, str(tactics_data_file("engine")))
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")

from PIL import Image  # noqa: E402
from relate_frame import detect  # noqa: E402
from relsgg.api import RelateAnything  # noqa: E402
from relsgg.vocabulary import DEFAULT_PREDICATES  # noqa: E402

IMAGE = str(tactics_data_file("frames/game_spurs_nyk_q3_t150.png"))
WEIGHTS = str(workspace_file("action_work/weights/yolo11n.pt"))
MODEL_DIR = str(workspace_file("action_work/models/relsgg-vits16plus"))

OURS_9 = [
    "is to the left of", "is to the right of", "is standing beside",
    "is in front of", "is behind", "is facing", "has their back turned to",
    "is holding the ball", "is dribbling the ball",
]
SPATIAL_6 = ["to the left of", "to the right of", "behind", "in front of",
             "beside", "standing beside"]
INTERACT_6 = ["holding", "watching", "looking at", "standing beside",
              "leaning against", "talking to"]


def main() -> int:
    boxes, labels, _scores, meta = detect(IMAGE, WEIGHTS, 60, 12, device="cpu", ball_conf=0.15)
    bxy = list(boxes)
    print(f"[detect] {len(bxy)} 框 | {meta}")

    ra = RelateAnything.from_checkpoint(os.path.join(MODEL_DIR, "model.pth"), device="cpu")
    print(f"[model]  calib a={ra.calib_a} b={ra.calib_b}")
    img = Image.open(IMAGE).convert("RGB")

    tests = [
        ("官方 DEFAULT_PREDICATES (35)", DEFAULT_PREDICATES),
        ("我们 smoke_test_minimal (9)", OURS_9),
        ("纯空间词 (6)", SPATIAL_6),
        ("纯交互词 (6)", INTERACT_6),
    ]

    for name, preds in tests:
        ra.set_vocabulary(preds)
        tri = ra.predict(img, bxy, box_labels=labels, topk=300, max_boxes=len(bxy))
        scores = [t.score for t in tri]
        hi = max(scores)
        lo = min(scores)
        print(f"\n=== {name} ===")
        print(f"    n={len(tri)}  max={hi:.4f}  min={lo:.4f}  spread={hi - lo:.4f}")
        for t in tri[:6]:
            print(f"      {t.subject_label} --{t.predicate} [{t.score:.4f}]--> {t.object_label}")

    print("\n[注] 官方 thresholds.json 的 best_f1_thr 中位数落在 0.98 附近，"
          "但其 regime 为 boxes=gt / pair_weight=0，与本脚本工况不同。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
