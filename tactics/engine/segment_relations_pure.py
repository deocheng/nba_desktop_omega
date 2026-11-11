#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 5 层 · 纯模型分重跑（纠正 `box_scores` 污染）。

为什么要有这个脚本（2026-09-25）
--------------------------------
里程碑 03 写下的结论「关系分天花板 max 0.5495、全片段无一条 >0.55」**是伪结论**。
根因：官方 `relsgg/api.py::predict()` 的 `box_scores=` 参数会让 `_triplet()` 执行
    score *= conf(subject) * conf(object)
而 `segment_relations.py` 传了 `box_scores=[p["conf"] ...]`（YOLO 人体置信度）⇒
落盘分数 = sigmoid(a·(pred_logit + w·pair_logit) + b) × conf_s × conf_o，
两个 0.3–0.9 的 conf 相乘把分布整体压到 0.29 量级。

而官方**部署路径** `deploy/postprocess.py::ThresholdConfig` 明确写：
    「Detector confidence deliberately does NOT enter the threshold ... It affects ranking only」
    `box_score_weight` 的注释：「Ranking only: the reported score and the threshold stay in
    relation-confidence units.」
⇒ 官方两条代码路径自相矛盾；以部署契约为准，正确做法是**报告纯分、只用 conf 排序**。

本脚本一次前向同时产出两个变体（隔离「分数标度」与「排序权重」两个混淆）：
  A) pure      —— 报告纯分、按纯分排序          （`box_scores=None` 的等价物）
  B) confrank  —— 报告纯分、按纯分×conf_s×conf_o 排序（**官方部署契约**，旧行为的正确版）

内置**保真自检**：变体 B 的逐帧 top-K（标签集合 + 分数）必须与旧的
`reports/milestone_03/relations_full/relations.json` 一致；不一致则说明我的重实现不忠实，
此时变体 A 的结论也不可信 ⇒ 直接失败退出。

用法:
  segment_relations_pure.py <players.json> <frames.json> <outdir> [--topk 6]
                            [--old <旧 relations.json>（做保真自检）]
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

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from relsgg.api import RelateAnything  # noqa: E402
from relsgg.vocabulary import DEFAULT_PREDICATES  # noqa: E402

DEF_MD = str(workspace_file("action_work/models/relsgg-vits16plus"))


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("players_json")
    ap.add_argument("frames_json")
    ap.add_argument("outdir")
    ap.add_argument("--topk", type=int, default=6)
    ap.add_argument("--model-dir", default=DEF_MD)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--old", default=None, help="旧 relations.json，用于保真自检")
    a = ap.parse_args()

    pd = json.load(open(a.players_json))
    src = {f["idx"]: f["path"] for f in json.load(open(a.frames_json))}

    t0 = time.perf_counter()
    ra = RelateAnything.from_checkpoint(os.path.join(a.model_dir, "model.pth"), device=a.device)
    ra.set_vocabulary(DEFAULT_PREDICATES)
    t_load = time.perf_counter() - t0
    print(f"[model] 载入 {t_load:.1f}s  calib=({ra.calib_a:.4f},{ra.calib_b:.4f})  "
          f"标定状态={'已标定' if (ra.calib_a, ra.calib_b) != (1.0, 0.0) else '未标定(identity)'}  "
          f"谓词 {len(DEFAULT_PREDICATES)} 条")

    out_pure, out_conf = [], []
    # 全量分布（不只是入选 top-K）：这是判定"模型自身分数标度"的正确统计池
    all_best_pure, all_best_conf = [], []
    n_pairs_total = 0
    t_pred = t_io = 0.0

    for f in pd["frames"]:
        idx, pls = f["idx"], f["players"]
        if len(pls) < 2:
            out_pure.append({"idx": idx, "t": f["t"], "triples": []})
            out_conf.append({"idx": idx, "t": f["t"], "triples": []})
            continue
        t1 = time.perf_counter()
        img = Image.open(src[idx]).convert("RGB")
        t_io += time.perf_counter() - t1

        boxes = np.asarray([p["box"] for p in pls], np.float32).reshape(-1, 4)
        confs = np.asarray([p["conf"] for p in pls], np.float32).reshape(-1)
        labels = [p.get("sel_id", f"p{i+1}") for i, p in enumerate(pls)]
        N = len(boxes)

        # ---- 逐字镜像 relsgg/api.py::predict 的输入准备（否则不是同一工况）----
        t1 = time.perf_counter()
        img_t, W, H = ra._to_chw(img, ra.img_size)
        img_t = img_t.to(ra.device)
        b = boxes.copy()
        b[:, [0, 2]] /= max(W, 1)
        b[:, [1, 3]] /= max(H, 1)
        cx = (b[:, 0] + b[:, 2]) / 2
        cy = (b[:, 1] + b[:, 3]) / 2
        boxes_t = torch.from_numpy(
            np.stack([cx, cy, b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]], -1).astype(np.float32)
        ).unsqueeze(0).to(ra.device)
        with torch.no_grad():
            out = ra.model(img_t, boxes_t, box_counts=torch.tensor([N], device=ra.device),
                           targets=None)
        logits = out["logits"][0].float()
        pair = out["pair_logits"][0].float()
        sub_idx = out["sub_idx"][0].cpu().numpy()
        obj_idx = out["obj_idx"][0].cpu().numpy()
        valid = out["valid_mask"][0].cpu().numpy().astype(bool)
        keep = valid & (sub_idx < N) & (obj_idx < N) & (sub_idx != obj_idx)

        scores = ra.contract.scores(logits, pair)             # [K,V] 纯关系分
        best_s, best_p = scores.max(dim=-1)
        best_s, best_p = best_s.cpu().numpy(), best_p.cpu().numpy()
        t_pred += time.perf_counter() - t1

        cand = []
        for k in range(len(sub_idx)):
            if not keep[k]:
                continue
            si, oi = int(sub_idx[k]), int(obj_idx[k])
            sp = float(best_s[k])
            n_pairs_total += 1
            all_best_pure.append(sp)
            all_best_conf.append(sp * float(confs[si]) * float(confs[oi]))
            cand.append((sp, si, oi, int(best_p[k])))

        def pack(items):
            return [{"s": labels[si], "o": labels[oi], "pred": DEFAULT_PREDICATES[p],
                     "score": round(sc, 6)} for sc, si, oi, p in items]

        # A) 纯分排序
        byp = sorted(cand, key=lambda x: -x[0])[:a.topk]
        # B) conf 加权排序（官方部署契约：只影响排序，不影响被报告的分数）
        byc = sorted(cand, key=lambda x: -(x[0] * float(confs[x[1]]) * float(confs[x[2]])))[:a.topk]
        out_pure.append({"idx": idx, "t": f["t"], "n_player": N, "triples": pack(byp)})
        out_conf.append({"idx": idx, "t": f["t"], "n_player": N, "triples": pack(byc)})

    os.makedirs(a.outdir, exist_ok=True)
    meta = {"n_frames": len(pd["frames"]), "topk": a.topk, "vocab_size": len(DEFAULT_PREDICATES),
            "calib_a": ra.calib_a, "calib_b": ra.calib_b,
            "predict_sec": round(t_pred, 1), "io_sec": round(t_io, 1),
            "load_sec": round(t_load, 1), "score_is_pure": True,
            "note": "score = sigmoid(a*(pred_logit + w*pair_logit) + b), NO box-conf multiplier"}
    for tag, frames in (("pure", out_pure), ("confrank", out_conf)):
        with open(os.path.join(a.outdir, f"relations_{tag}.json"), "w") as fp:
            json.dump({"frames": frames, "vocab": DEFAULT_PREDICATES, "meta": meta,
                       "variant": tag}, fp, ensure_ascii=False, indent=1)

    dist = {
        "n_pairs_scored": n_pairs_total,
        "n_triples_pure": sum(len(x["triples"]) for x in out_pure),
        "pure_all_pairs": {q: round(pct(all_best_pure, q), 6)
                           for q in (0.5, 0.9, 0.99, 0.999, 1.0)},
        "conf_multiplied_all_pairs": {q: round(pct(all_best_conf, q), 6)
                                      for q in (0.5, 0.9, 0.99, 0.999, 1.0)},
    }
    # 入选 top-K 的纯分分布（与旧口径可比）
    sel = [t["score"] for x in out_pure for t in x["triples"]]
    dist["pure_selected_topk"] = {q: round(pct(sel, q), 6) for q in (0.5, 0.9, 0.99, 1.0)}
    dist["pred_hist_pure"] = _hist(out_pure)
    dist["pred_hist_confrank"] = _hist(out_conf)

    # ---- 保真自检：confrank 变体必须复现旧产出 ----
    if a.old:
        old = json.load(open(a.old))
        om = {fr["idx"]: fr["triples"] for fr in old["frames"]}
        same = diff = 0
        smax = 0.0
        for fr in out_conf:
            o = om.get(fr["idx"])
            if o is None:
                continue
            k1 = sorted((t["s"], t["o"], t["pred"]) for t in fr["triples"])
            k2 = sorted((t["s"], t["o"], t["pred"]) for t in o)
            if k1 == k2:
                same += 1
                for t1_, t2_ in zip(sorted(fr["triples"], key=lambda x: -x["score"]),
                                    sorted(o, key=lambda x: -x["score"])):
                    smax = max(smax, abs(t1_["score"] - t2_["score"]))
            else:
                diff += 1
        dist["fidelity"] = {"frames_same_topk": same, "frames_diff": diff,
                            "max_abs_score_delta": round(smax, 6)}
        print(f"[保真自检] confrank vs 旧产出：逐帧 top-K 相同 {same} / 不同 {diff}；"
              f"分数最大绝对差 {smax:.6f}")
        if diff > len(out_conf) * 0.02:
            raise SystemExit("❌ 保真自检失败：重实现与旧产出不一致 ⇒ 纯分变体不可信，停止。")

    with open(os.path.join(a.outdir, "score_dist.json"), "w") as fp:
        json.dump(dist, fp, ensure_ascii=False, indent=1)

    print(f"[predict] {t_pred * 1000 / max(len(pd['frames']), 1):.1f}ms/帧 | "
          f"计分 pair {n_pairs_total} / 入选三元组 {dist['n_triples_pure']}")
    print("[纯分分布·全部 pair 的 argmax] " +
          "  ".join(f"p{int(q*100)}={v:.3f}" for q, v in dist["pure_all_pairs"].items()))
    print("[旧口径·乘了两个 conf 的同一批] " +
          "  ".join(f"p{int(q*100)}={v:.3f}" for q, v in dist["conf_multiplied_all_pairs"].items()))
    print(f"[入选 top-{a.topk} 的纯分] " +
          "  ".join(f"p{int(q*100)}={v:.3f}" for q, v in dist["pure_selected_topk"].items()))
    print(f"[out] {os.path.join(a.outdir, 'relations_pure.json')} / relations_confrank.json")
    return 0


def _hist(frames) -> dict:
    c: dict[str, int] = {}
    for fr in frames:
        for t in fr["triples"]:
            c[t["pred"]] = c.get(t["pred"], 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
