#!/usr/bin/env python3
"""第 5 层：逐帧关系预测（RelateAnything + 官方 35 条裸短语）。

谓词选择的依据（2026-09-23 实测，见词表文件 native_mapping）：
    官方 `DEFAULT_PREDICATES`（35 条裸短语）在同一帧上 max=0.5133，
    远优于自建长句式（0.0860）与 full_vocabulary 19,103（0.3643）。
    所以推理时**一律用官方 35 条**，篮球语义放到下游「谓词 → 战术语义」映射层做。

同时输出**几何基线**（左右/前后/距离），作为模型输出的交叉验证：
    RelateAnything 只给关系名，几何量是确定的，两者互相印证可暴露模型幻觉。

输出 `relations.json`：
  frames[] 每帧 {idx, t, triples[{s,o,pred,score}], pairs[{s,o,dist_norm,dx,dy}]}
  vocab    本次使用的谓词表
  meta     耗时统计

用法：
  segment_relations.py <players.json> <frames.json> <outdir>
                       [--topk 6] [--model-dir <dir>]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
import sys
import time

from common.nba_paths import tactics_data_file, workspace_file

REPO = str(tactics_data_file("RelateAnything"))
sys.path.insert(0, REPO)

from PIL import Image  # noqa: E402
from relsgg.api import RelateAnything  # noqa: E402
from relsgg.vocabulary import DEFAULT_PREDICATES  # noqa: E402

SRC = str(tactics_data_file("RelateAnything"))
DEF_MD = str(workspace_file("action_work/models/relsgg-vits16plus"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("players_json")
    ap.add_argument("frames_json")
    ap.add_argument("outdir")
    ap.add_argument("--topk", type=int, default=6)
    ap.add_argument("--model-dir", default=DEF_MD)
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    pd = json.load(open(a.players_json))
    src = {f["idx"]: f["path"] for f in json.load(open(a.frames_json))}

    t0 = time.perf_counter()
    ckpt = os.path.join(a.model_dir, "model.pth")
    ra = RelateAnything.from_checkpoint(ckpt, device=a.device)
    ra.set_vocabulary(DEFAULT_PREDICATES)
    t_load = time.perf_counter() - t0
    print(f"[model] 载入 {t_load:.1f}s  calib=({ra.calib_a},{ra.calib_b})  "
          f"谓词 {len(DEFAULT_PREDICATES)} 条")

    out_frames = []
    t_pred = 0.0
    t_io = 0.0
    for f in pd["frames"]:
        idx = f["idx"]
        pls = f["players"]
        if not pls:
            out_frames.append({"idx": idx, "t": f["t"], "triples": [], "pairs": []})
            continue
        t1 = time.perf_counter()
        img = Image.open(src[idx]).convert("RGB")
        t_io += time.perf_counter() - t1

        boxes = [p["box"] for p in pls]
        # 标签优先用跨帧稳定 pid（select_tracks.json），退化为帧内 sel_id
        labels = [f"pid{p['pid']}" if "pid" in p else p.get("sel_id", f"p{i+1}")
                  for i, p in enumerate(pls)]
        scores = [p["conf"] for p in pls]

        t1 = time.perf_counter()
        tri = ra.predict(img, boxes, box_labels=labels, box_scores=scores,
                         topk=a.topk, max_boxes=len(boxes))
        t_pred += time.perf_counter() - t1

        out_frames.append({
            "idx": idx, "t": f["t"],
            "n_player": len(pls),
            "triples": [{"s": t.subject_label, "o": t.object_label,
                         "pred": t.predicate, "score": round(t.score, 4)}
                        for t in tri],
            "pairs": _pairs(pls),
        })

    dt = time.perf_counter() - t0
    meta = {"n_frames": len(pd["frames"]), "vocab_size": len(DEFAULT_PREDICATES),
            "topk": a.topk, "load_sec": round(t_load, 1),
            "predict_sec": round(t_pred, 1),
            "predict_ms_per_frame": round(t_pred * 1000 / max(len(pd["frames"]), 1), 1),
            "io_sec": round(t_io, 1), "total_sec": round(dt, 1)}

    os.makedirs(a.outdir, exist_ok=True)
    with open(os.path.join(a.outdir, "relations.json"), "w") as fp:
        json.dump({"frames": out_frames, "vocab": DEFAULT_PREDICATES, "meta": meta},
                  fp, ensure_ascii=False, indent=1)

    n_tri = sum(len(x["triples"]) for x in out_frames)
    allsc = [t["score"] for x in out_frames for t in x["triples"]]
    print(f"[predict] {meta['predict_ms_per_frame']}ms/帧 | 三元组 {n_tri} 条 "
          f"({n_tri/max(len(out_frames),1):.1f}/帧)")
    print(f"[score] min={min(allsc):.4f} 中位={sorted(allsc)[len(allsc)//2]:.4f} "
          f"max={max(allsc):.4f}")
    print(f"[调时] 模型载入 {t_load:.1f}s | 预测 {t_pred:.1f}s | 读图 {t_io:.1f}s | "
          f"合计 {dt:.1f}s")
    print(f"[out] {os.path.join(a.outdir, 'relations.json')}")
    return 0


def _lab(p: dict) -> str:
    return f"pid{p['pid']}" if "pid" in p else p.get("sel_id", "?")


def _pairs(pls: list[dict]) -> list[dict]:
    """几何基线：对每对球员给出归一化距离与方位（模型输出的交叉验证量）。

    距离用脚点欧氏距离 / 两者框高的均值归一化（尺度无关）。
    方位用 x 排序（左右）与 y 排序（前后 = 更靠近画面底部为近端）。
    """
    out = []
    for i in range(len(pls)):
        for j in range(i + 1, len(pls)):
            a, b = pls[i], pls[j]
            ax, ay = a["foot"]
            bx, by = b["foot"]
            d = math.hypot(ax - bx, ay - by)
            scale = max((a["h"] + b["h"]) / 2.0, 1.0)
            out.append({"s": _lab(a), "o": _lab(b),
                        "dist_norm": round(d / scale, 3),
                        "dx": round(bx - ax, 1), "dy": round(by - ay, 1),
                        "s_left_of_o": ax < bx, "s_nearer": ay > by})
    return out


if __name__ == "__main__":
    raise SystemExit(main())
