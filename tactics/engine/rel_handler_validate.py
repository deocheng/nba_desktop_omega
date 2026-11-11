#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rel_handler_validate.py — 验证官方 35 词 / native 域外词与**已有持球者归属**的一致性。

为什么必须先做这一步
--------------------
- 官方 35 词里**没有** defending / hitting（那两个是 full_vocabulary 19,103 的域外词）。
  ⇒ 两者**互斥**，必须分两次推理，不能"一次跑齐"。
- 已有持球者归属 `poss_track_id` 的定义就是「距球最近的球员」= **几何基线**。
  ⇒ 若关系模型只是复现几何，命中率会很高，但**不带来任何新信息**。
  因此本脚本**同时报** ①对 poss 的命中率 ②随机基线 ③**与几何的一致性** ④分歧帧清单。

验证命题
--------
- H1（官方35）: obj=BALL 且 pred ∈ {holding, carrying, using} 的**最高分边**的 sub 是否 == poss_track_id
- H2（native）: obj=BALL 且 pred == "hitting" 的最高分边的 sub 是否 == poss_track_id
- H3（native）: 持球人是否出现在 defending / defending against 边的某一端
  （对照：随机球员出现在 defending 边的概率）—— 用于判断 defending 是否携带对位信息

产出
----
  action_work/validate/rel_handler_validate.json   逐帧明细 + 汇总

用法
----
  python engine/rel_handler_validate.py --clips sas_hou,sas_nop,sas_det \
      --poss-suffix _poss_tile_fp --per-clip 30 [--device mps]
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
from pathlib import Path

from common.nba_paths import tactics_data_file, workspace_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
REPO = ROOT / "RelateAnything"
sys.path.insert(0, str(REPO))
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from relsgg.api import RelateAnything  # noqa: E402
from relsgg.vocabulary import DEFAULT_PREDICATES  # noqa: E402

DEF_MD = str(workspace_file("action_work/models/relsgg-vits16plus"))
BALL_PREDS_35 = {"holding", "carrying", "using"}
BALL_PREDS_NATIVE = {"hitting"}
DEF_PREDS = {"defending", "defending against", "tackling"}


def rect_dist(bx, by, b):
    dx = max(b[0] - bx, 0.0, bx - b[2])
    dy = max(b[1] - by, 0.0, by - b[3])
    return math.hypot(dx, dy)


def load_frames(clip, poss_suffix, per_clip):
    """返回 [{idx, file, players:[{track_id,bbox,conf}], ball:bbox, poss}] —— 只取持球者已解出的帧。"""
    d = AW / f"{clip}{poss_suffix}"
    p = d / "ball_tracks.json"
    if not p.exists():
        return []
    out = []
    for f in json.loads(p.read_text()):
        if not f.get("ball") or f.get("poss_track_id") is None:
            continue
        out.append({
            "idx": int(f["frame"]),
            "file": f["file"],
            "players": [{"track_id": int(pl["track_id"]), "bbox": [float(v) for v in pl["bbox"]],
                         "conf": float(pl["conf"])} for pl in f["players"]],
            "ball": [float(v) for v in f["ball"]["bbox"]],
            "poss": int(f["poss_track_id"]),
        })
    if per_clip and len(out) > per_clip:
        step = len(out) / per_clip
        out = [out[int(i * step)] for i in range(per_clip)]
    return out


def forward(ra, img_path, boxes, labels, confs):
    """镜像 relsgg/api.py::predict 的输入准备，返回 [(score, s_label, o_label, pred)]。"""
    img = Image.open(img_path).convert("RGB")
    img_t, W, H = ra._to_chw(img, ra.img_size)
    img_t = img_t.to(ra.device)
    b = np.asarray(boxes, np.float32).copy()
    b[:, [0, 2]] /= max(W, 1)
    b[:, [1, 3]] /= max(H, 1)
    cx, cy = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
    boxes_t = torch.from_numpy(
        np.stack([cx, cy, b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]], -1).astype(np.float32)
    ).unsqueeze(0).to(ra.device)
    N = len(boxes)
    with torch.no_grad():
        out = ra.model(img_t, boxes_t, box_counts=torch.tensor([N], device=ra.device),
                       targets=None)
    logits, pair = out["logits"][0].float(), out["pair_logits"][0].float()
    sub_idx, obj_idx = out["sub_idx"][0].cpu().numpy(), out["obj_idx"][0].cpu().numpy()
    valid = out["valid_mask"][0].cpu().numpy().astype(bool)
    keep = valid & (sub_idx < N) & (obj_idx < N) & (sub_idx != obj_idx)
    scores = ra.contract.scores(logits, pair)
    best_s, best_p = scores.max(dim=-1)
    best_s, best_p = best_s.cpu().numpy(), best_p.cpu().numpy()
    res = []
    for k in range(len(sub_idx)):
        if keep[k]:
            res.append((float(best_s[k]), str(labels[int(sub_idx[k])]),
                        str(labels[int(obj_idx[k])]), ra.predicates[int(best_p[k])]))
    return res


def pick_ball_edge(tri, preds, obj_tag="BALL"):
    cand = [t for t in tri if t[3] in preds and t[2] == obj_tag]
    cand.sort(key=lambda x: -x[0])
    return cand[0] if cand else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default="sas_hou,sas_nop,sas_det")
    ap.add_argument("--poss-suffix", default="_poss_tile_fp")
    ap.add_argument("--per-clip", type=int, default=30)
    ap.add_argument("--model-dir", default=DEF_MD)
    ap.add_argument("--device", default="mps")
    a = ap.parse_args()

    dev = a.device
    if dev == "mps" and not torch.backends.mps.is_available():
        dev = "cpu"
    t0 = time.perf_counter()
    ra35 = RelateAnything.from_checkpoint(os.path.join(a.model_dir, "model.pth"), device=dev)
    ra35.set_vocabulary(DEFAULT_PREDICATES)
    raN = RelateAnything.from_checkpoint(os.path.join(a.model_dir, "model.pth"),
                                         device=dev, full_vocabulary=True)
    print(f"[模型] 载入 {time.perf_counter()-t0:.1f}s  device={dev}  "
          f"官方35={len(ra35.predicates)}  native={len(raN.predicates)}")

    report = {"poss_suffix": a.poss_suffix, "per_clip": a.per_clip, "device": dev, "clips": {}}
    for clip in [c for c in a.clips.split(",") if c.strip()]:
        frames = load_frames(clip, a.poss_suffix, a.per_clip)
        if not frames:
            print(f"[跳过] {clip}: 无持球者已解出帧")
            continue
        fdir = AW / clip
        recs, t_pred = [], 0.0
        for fr in frames:
            imgp = fdir / fr["file"]
            if not imgp.exists():
                continue
            pls = fr["players"]
            boxes = [p["bbox"] for p in pls] + [fr["ball"]]
            labels = [str(p["track_id"]) for p in pls] + ["BALL"]
            confs = [p["conf"] for p in pls] + [1.0]
            bx, by = (fr["ball"][0] + fr["ball"][2]) / 2, (fr["ball"][1] + fr["ball"][3]) / 2

            t1 = time.perf_counter()
            tri35 = forward(ra35, imgp, boxes, labels, confs)
            triN = forward(raN, imgp, boxes, labels, confs)
            t_pred += time.perf_counter() - t1

            # 几何最近球员（= poss 的定义式，独立重算一遍做交叉校验）
            geo = min(pls, key=lambda p: rect_dist(bx, by, p["bbox"]))["track_id"]
            e35 = pick_ball_edge(tri35, BALL_PREDS_35)
            eN = pick_ball_edge(triN, BALL_PREDS_NATIVE)
            def_edges = [t for t in triN if t[3] in DEF_PREDS]
            poss_s = str(fr["poss"])
            handler_in_def = any(poss_s in (t[1], t[2]) for t in def_edges)
            # 随机基线：随机一个球员落在 defending 边里的概率
            rand_in_def = len({x for t in def_edges for x in (t[1], t[2])
                               if x != "BALL"}) / max(1, len(pls))
            # 全量候选边（供阈值扫描，不只 top-1）
            c35 = sorted([{"sub": t[1], "pred": t[3], "score": round(t[0], 5)}
                          for t in tri35 if t[3] in BALL_PREDS_35 and t[2] == "BALL"],
                         key=lambda x: -x["score"])
            cN = sorted([{"sub": t[1], "pred": t[3], "score": round(t[0], 5)}
                         for t in triN if t[3] in BALL_PREDS_NATIVE and t[2] == "BALL"],
                        key=lambda x: -x["score"])
            recs.append({
                "idx": fr["idx"], "file": fr["file"], "poss": fr["poss"], "geo": geo,
                "n_player": len(pls),
                "cand35": c35, "candN": cN,
                "e35": None if e35 is None else {"pred": e35[3], "sub": e35[1], "score": round(e35[0], 4)},
                "eN": None if eN is None else {"pred": eN[3], "sub": eN[1], "score": round(eN[0], 4)},
                "n_def_edges": len(def_edges),
                "def_edges": [{"s": t[1], "p": t[3], "o": t[2], "score": round(t[0], 4)}
                              for t in def_edges[:8]],
                "handler_in_def": handler_in_def,
                "rand_in_def": round(rand_in_def, 3),
            })

        n = len(recs)
        ok35 = sum(1 for r in recs if r["e35"] and r["e35"]["sub"] == str(r["poss"]))
        okN = sum(1 for r in recs if r["eN"] and r["eN"]["sub"] == str(r["poss"]))
        has35 = sum(1 for r in recs if r["e35"])
        hasN = sum(1 for r in recs if r["eN"])
        geo_ok = sum(1 for r in recs if r["geo"] == r["poss"])
        hid = sum(1 for r in recs if r["handler_in_def"])
        rnd = sum(r["rand_in_def"] for r in recs) / max(1, n)
        base = 1.0 / max(1, recs[0]["n_player"]) if recs else 0.0
        s = {
            "n_frames": n,
            "random_baseline_player": round(base, 3),
            "geo_vs_poss_agree": round(geo_ok / max(1, n), 3),
            "H1_official35": {"has_edge": has35, "top1_hit": ok35,
                              "hit_rate_of_all": round(ok35 / max(1, n), 3),
                              "hit_rate_of_has": round(ok35 / max(1, has35), 3)},
            "H2_native_hitting": {"has_edge": hasN, "top1_hit": okN,
                                  "hit_rate_of_all": round(okN / max(1, n), 3),
                                  "hit_rate_of_has": round(okN / max(1, hasN), 3)},
            "H3_defending": {"frames_with_def_edge": sum(1 for r in recs if r["n_def_edges"]),
                             "handler_in_def": hid,
                             "handler_in_def_rate": round(hid / max(1, n), 3),
                             "random_player_in_def_rate": round(rnd, 3)},
            "pred_sec": round(t_pred, 1),
        }
        report["clips"][clip] = {"summary": s, "records": recs}
        print(f"\n=== {clip}  n={n}帧  推理 {t_pred:.0f}s ===")
        print(f"  几何最近 == poss           : {s['geo_vs_poss_agree']:.3f}（应为 1.0，校验定义一致性）")
        print(f"  随机基线（1/球员数）        : {base:.3f}")
        print(f"  H1 官方35(holding/carry/using): 有边 {has35}/{n}  "
              f"top1命中 {ok35}  命中率(全){s['H1_official35']['hit_rate_of_all']:.3f}  "
              f"(有边){s['H1_official35']['hit_rate_of_has']:.3f}")
        print(f"  H2 native hitting            : 有边 {hasN}/{n}  "
              f"top1命中 {okN}  命中率(全){s['H2_native_hitting']['hit_rate_of_all']:.3f}  "
              f"(有边){s['H2_native_hitting']['hit_rate_of_has']:.3f}")
        print(f"  H3 defending 边             : 有边帧 {s['H3_defending']['frames_with_def_edge']}/{n}  "
              f"持球人在边内 {hid} ({s['H3_defending']['handler_in_def_rate']:.3f})  "
              f"vs 随机球员 {rnd:.3f}")

    out = AW / "validate" / "rel_handler_validate.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\n[写盘] {out}")


if __name__ == "__main__":
    main()
