#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关系层 **原始矩阵转储** —— 为移植官方稳定化层（B 步）准备输入。

为什么必须转储原始矩阵（官方源码的理由，逐字照抄 `deploy/render_video.py`）：

    "Straight off the raw matrices, NOT through decode: decode applies top-k and a
     threshold, so a pair that scored low never comes back and negative evidence can
     never be observed."

即：只保留 top-k 解码结果会**丢掉负证据** —— 某个 (球员对, 谓词) 这帧得分低，
它就不会出现在 top-k 里，稳定化层便无法登记「它被观测过、而且很低」，
只能当成「没测到」而无限维持旧信念。两件事必须区分：
    低分（真实负证据）  vs  端点没检测到（无测量）

输出 `<outdir>/rel_raw.npz`：
  sub_idx  int16 [Ktot]      每行一条有向对的 subject 检测序号（帧内）
  obj_idx  int16 [Ktot]      object 检测序号
  scores   float16 [Ktot, V] 纯关系分（已标定 sigmoid，**不乘 box conf**）
  frames   JSON 元数据：每帧 {idx, t, N, labels[], k0, k1}

用法:
  rel_dump_raw.py <players.json> <frames.json> <outdir> [--topk 20] [--device cpu]
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

from common.nba_paths import tactics_data_file, workspace_file

REPO = str(tactics_data_file("RelateAnything"))
sys.path.insert(0, REPO)

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from relsgg.api import RelateAnything  # noqa: E402
from relsgg.vocabulary import DEFAULT_PREDICATES  # noqa: E402

DEF_MD = str(workspace_file("action_work/models/relsgg-vits16plus"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("players_json")
    ap.add_argument("frames_json")
    ap.add_argument("outdir")
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--model-dir", default=DEF_MD)
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    pd = json.load(open(a.players_json))
    src = {f["idx"]: f["path"] for f in json.load(open(a.frames_json))}

    t0 = time.perf_counter()
    ra = RelateAnything.from_checkpoint(os.path.join(a.model_dir, "model.pth"), device=a.device)
    ra.set_vocabulary(DEFAULT_PREDICATES)
    print(f"[model] 载入 {time.perf_counter()-t0:.1f}s  calib=({ra.calib_a:.4f},{ra.calib_b:.4f})  "
          f"谓词 {len(DEFAULT_PREDICATES)} 条  box_scores=未传（纯关系分口径）")

    subs, objs, scr = [], [], []
    fmeta, dec = [], []
    t_pred = 0.0
    for f in pd["frames"]:
        idx, pls = f["idx"], f["players"]
        labels = [p.get("sel_id", f"p{i+1}") for i, p in enumerate(pls)]
        N = len(pls)
        if N < 2:
            fmeta.append({"idx": idx, "t": f["t"], "N": N, "labels": labels,
                          "k0": len(subs), "k1": len(subs)})
            dec.append([])
            continue
        t1 = time.perf_counter()
        img = Image.open(src[idx]).convert("RGB")
        boxes = np.asarray([p["box"] for p in pls], np.float32).reshape(-1, 4)

        img_t, W, H = ra._to_chw(img, ra.img_size)
        img_t = img_t.to(ra.device)
        b = boxes.copy()
        b[:, [0, 2]] /= max(W, 1)
        b[:, [1, 3]] /= max(H, 1)
        cx, cy = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
        boxes_t = torch.from_numpy(
            np.stack([cx, cy, b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]], -1).astype(np.float32)
        ).unsqueeze(0).to(ra.device)
        with torch.no_grad():
            out = ra.model(img_t, boxes_t, box_counts=torch.tensor([N], device=ra.device),
                           targets=None)
        logits = out["logits"][0].float()
        pair = out["pair_logits"][0].float()
        si = out["sub_idx"][0].cpu().numpy()
        oi = out["obj_idx"][0].cpu().numpy()
        keep = out["valid_mask"][0].cpu().numpy().astype(bool)
        keep &= (si < N) & (oi < N) & (si != oi)

        with torch.no_grad():
            sc = ra.contract.scores(logits, pair).float().cpu().numpy()   # [K,V]
        t_pred += time.perf_counter() - t1

        ks = np.flatnonzero(keep)
        k0 = len(subs)
        for k in ks:
            subs.append(int(si[k]))
            objs.append(int(oi[k]))
        if len(ks):
            scr.append(sc[ks].astype(np.float16))
        fmeta.append({"idx": idx, "t": f["t"], "N": N, "labels": labels,
                      "k0": k0, "k1": k0 + len(ks)})

        # 解码 top-K（纯分）供 EMA 路径与对照使用
        bl = sc[ks].max(axis=-1) if len(ks) else np.zeros(0, np.float32)
        bp = sc[ks].argmax(axis=-1) if len(ks) else np.zeros(0, np.int64)
        order = np.argsort(-bl)[:a.topk]
        dec.append([{"s": labels[int(si[ks[r]])], "o": labels[int(oi[ks[r]])],
                     "pred": DEFAULT_PREDICATES[int(bp[r])], "score": round(float(bl[r]), 6)}
                    for r in order])

    os.makedirs(a.outdir, exist_ok=True)
    sub_a = np.asarray(subs, np.int16)
    obj_a = np.asarray(objs, np.int16)
    sc_a = np.concatenate(scr, 0) if scr else np.zeros((0, len(DEFAULT_PREDICATES)), np.float16)
    np.savez_compressed(os.path.join(a.outdir, "rel_raw.npz"),
                        sub_idx=sub_a, obj_idx=obj_a, scores=sc_a)
    # 谓词的 spatial/semantic 类型（官方 `_type_vector`，EdgeBook 用它分配预算）
    is_sp = [bool(x) for x in np.asarray(ra._type_vector()).reshape(-1).tolist()]
    with open(os.path.join(a.outdir, "rel_raw_meta.json"), "w") as fp:
        json.dump({"frames": fmeta, "topk": a.topk, "vocab": DEFAULT_PREDICATES,
                   "pred_is_spatial": dict(zip(DEFAULT_PREDICATES, is_sp)),
                   "calib_a": ra.calib_a, "calib_b": ra.calib_b,
                   "predict_sec": round(t_pred, 1), "n_rows": int(len(sub_a)),
                   "note": "scores = sigmoid(a*(pred_logit + w*pair_logit) + b)，未乘 box conf"},
                  fp, ensure_ascii=False, indent=1)
    with open(os.path.join(a.outdir, "relations_dec_topk.json"), "w") as fp:
        json.dump({"frames": [{"idx": m["idx"], "t": m["t"], "n_player": m["N"],
                               "triples": d} for m, d in zip(fmeta, dec)],
                   "vocab": DEFAULT_PREDICATES,
                   "meta": {"topk": a.topk, "score_is_pure": True}},
                  fp, ensure_ascii=False, indent=1)

    sz = os.path.getsize(os.path.join(a.outdir, "rel_raw.npz")) / 1e6
    print(f"[dump] 行数 Ktot={len(sub_a)}  V={len(DEFAULT_PREDICATES)}  "
          f"npz={sz:.1f}MB  ({t_pred*1000/max(len(fmeta),1):.1f}ms/帧)")
    print(f"[out] {os.path.join(a.outdir, 'rel_raw.npz')} + rel_raw_meta.json + "
          f"relations_dec_topk.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
