#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 步敏感性：官方稳定化参数是**帧计数型**，与本窗口 10fps 的绝对时长不匹配 ⇒ 扫一遍。

纪律：本项目铁律「参数扫描能推翻『显著』」「数量级吻合不可作为构造正确的证据」。
本脚本只报告**观测量随参数的变化**，不做 fishing、不挑参数。

扫的轴（其余固定为官方默认）：
  on_frames   ∈ {1,2,3,5}     迟滞「开」所需连续观测帧数
  score_ema   ∈ {0.20,0.35,0.50}
  max_age     ∈ {4,8,16}      轨迹允许丢失帧数
  belief q/r  ∈ (0.05,1.0) / (0.05,0.5) / (0.5,1.0)

用法:
  rel_stab_sweep.py <players.json> <rel_raw_dir> <out.json>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rel_stabilize import Edge, EdgeBook, Tracker, Tri, _pct, iou_matrix  # noqa: E402


def run_one(frames, fmeta, dec, sc_all, sub_idx, obj_idx, vidx, is_sp,
            frame_w, frame_h, filt, *, on_frames=2, score_ema=0.35, max_age=8,
            kf_q=0.05, kf_r=1.0, on_thr=0.45, off_thr=0.35, off_frames=6,
            min_hits=2):

    def build_tracks(mode):
        if mode == "track":
            tr = Tracker(iou_thr=0.3, low_iou_thr=0.5, merge_iou=0.75,
                         max_age=max_age, min_hits=min_hits, high_conf=0.25,
                         q=1.0, r=10.0, stride=1)
            d2t_all, live_all, box_all = [], [], []
            for f in frames:
                pls = f["players"]
                boxes = np.asarray([p["box"] for p in pls], np.float32).reshape(-1, 4)
                confs = np.asarray([p["conf"] for p in pls], np.float32)
                labs = [p.get("sel_id", f"p{i+1}") for i, p in enumerate(pls)]
                d2t_all.append(tr.observe(boxes, labs, confs) if len(boxes) else {})
                box_all.append(boxes)
                tr.step(frame_w, frame_h)
                live_all.append({t.tid for t in tr.tracks})
            return d2t_all, live_all, box_all
        lmap, d2t_all, live_all, box_all = {}, [], [], []
        for f in frames:
            pls = f["players"]
            labs = [p.get("sel_id", f"p{i+1}") for i, p in enumerate(pls)]
            d2t = {i: lmap.setdefault(l, len(lmap)) for i, l in enumerate(labs)}
            d2t_all.append(d2t)
            box_all.append(np.asarray([p["box"] for p in pls], np.float32).reshape(-1, 4))
            live_all.append(set(d2t.values()))
        return d2t_all, live_all, box_all

    book = EdgeBook(score_ema=score_ema, on_thr=on_thr, off_thr=off_thr,
                    on_frames=on_frames, off_frames=off_frames, fade=0.12,
                    max_edges=8, max_spatial=3, spatial_on_thr=0.42,
                    belief=(filt == "belief"), kf_q=kf_q, kf_r=kf_r, p_max=8.0)
    watch, ndis, ents, visn = [], [], [], []
    prev = {}
    reuse = stable = 0
    for mode in ("track", "sel"):
        pass
    return book


def sweep(frames, fmeta, dec, sc_all, sub_idx, obj_idx, vidx, is_sp, fw, fh,
          axis, values, filt):
    """对给定轴做单变量扫描，mode 固定 track（身份可信档）。"""
    out = []
    for v in values:
        kw = {"on_frames": 2, "score_ema": 0.35, "max_age": 8, "kf_q": 0.05, "kf_r": 1.0}
        if axis == "belief":
            kw["kf_q"], kw["kf_r"] = v
        else:
            kw[axis] = v
        r = _evaluate(frames, fmeta, dec, sc_all, sub_idx, obj_idx, vidx, is_sp,
                      fw, fh, filt, kw)
        r[f"{axis}"] = v
        out.append(r)
    return out


def _evaluate(frames, fmeta, dec, sc_all, sub_idx, obj_idx, vidx, is_sp,
              fw, fh, filt, kw):
    tr = Tracker(iou_thr=0.3, low_iou_thr=0.5, merge_iou=0.75, max_age=kw["max_age"],
                 min_hits=2, high_conf=0.25, q=1.0, r=10.0, stride=1)
    book = EdgeBook(score_ema=kw["score_ema"], on_thr=0.45, off_thr=0.35,
                    on_frames=kw["on_frames"], off_frames=6, fade=0.12,
                    max_edges=8, max_spatial=3, spatial_on_thr=0.42,
                    belief=(filt == "belief"), kf_q=kw["kf_q"], kf_r=kw["kf_r"],
                    p_max=8.0)
    visn, watch, ndis, ents = [], [], [], []
    prev = {}
    reuse = stable = 0
    for i in range(len(frames)):
        fi, pls = fmeta[i], frames[i]["players"]
        boxes = np.asarray([p["box"] for p in pls], np.float32).reshape(-1, 4)
        confs = np.asarray([p["conf"] for p in pls], np.float32)
        labs = [p.get("sel_id", f"p{j+1}") for j, p in enumerate(pls)]
        d2t = tr.observe(boxes, labs, confs) if len(boxes) else {}
        live = {t.tid for t in tr.tracks}
        tri = []
        for t in dec[i]["triples"]:
            try:
                si = fi["labels"].index(t["s"]); oi = fi["labels"].index(t["o"])
            except ValueError:
                continue
            tri.append(Tri(si, oi, t["pred"], float(t["score"])))
        raw = None
        k0, k1 = fi["k0"], fi["k1"]
        if filt == "belief" and k1 > k0:
            kof = {}
            for k in range(k0, k1):
                kof.setdefault((int(sub_idx[k]), int(obj_idx[k])), k - k0)
            raw = (sc_all[k0:k1], kof, vidx)
        book.observe(tri, d2t, is_sp, raw)
        tr.step(fw, fh)
        book.step(live)
        vis = book.visible()
        visn.append(len(vis))
        preds = [e.pred for e in vis]
        n = len(preds) or 1
        watch.append(sum(1 for p in preds if p == "watching") / n)
        ndis.append(len(set(preds)))
        if len(set(preds)) > 1:
            h = -sum((c / n) * math.log(c / n, 2) for c in Counter(preds).values())
            ents.append(h / math.log(len(set(preds)), 2))
        else:
            ents.append(0.0)
        cur = {}
        d2tr = {v: k for k, v in d2t.items()}
        for e in vis:
            k = (e.sub, e.obj, e.pred)
            ds, do = d2tr.get(e.sub), d2tr.get(e.obj)
            cur[k] = (boxes[ds] if ds is not None else None,
                      boxes[do] if do is not None else None)
            p = prev.get(k)
            if (p and p[0] is not None and p[1] is not None
                    and cur[k][0] is not None and cur[k][1] is not None):
                reuse += 1
                if (iou_matrix(p[0][None, :], cur[k][0][None, :])[0, 0] > 0.5 and
                        iou_matrix(p[1][None, :], cur[k][1][None, :])[0, 0] > 0.5):
                    stable += 1
        prev = cur
    return {"visible_per_frame_mean": round(float(np.mean(visn)), 3),
            "visible_total": int(sum(visn)),
            "watching_share_mean": round(float(np.mean(watch)), 4),
            "n_distinct_pred_mean": round(float(np.mean(ndis)), 4),
            "entropy_norm_mean": round(float(np.mean(ents)), 4),
            "key_reuse": reuse, "key_same_physical": stable,
            "identity_consistency": (round(stable / reuse, 4) if reuse else None)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("players_json")
    ap.add_argument("rel_raw_dir")
    ap.add_argument("out_json")
    a = ap.parse_args()

    pd = json.load(open(a.players_json))
    meta = json.load(open(os.path.join(a.rel_raw_dir, "rel_raw_meta.json")))
    z = np.load(os.path.join(a.rel_raw_dir, "rel_raw.npz"))
    sub_idx, obj_idx, sc_all = z["sub_idx"], z["obj_idx"], z["scores"].astype(np.float32)
    dec = json.load(open(os.path.join(a.rel_raw_dir, "relations_dec_topk.json")))["frames"]
    vocab = meta["vocab"]
    vidx = {p: i for i, p in enumerate(vocab)}
    is_sp = meta["pred_is_spatial"]
    frames, fmeta = pd["frames"], meta["frames"]

    res = {"axes": {}, "fixed": "mode=track（身份经 KalmanBox+IoU 关联），其余参数=官方默认"}
    for filt in ("ema", "belief"):
        res["axes"][f"on_frames[{filt}]"] = sweep(
            frames, fmeta, dec, sc_all, sub_idx, obj_idx, vidx, is_sp, 1920, 1080,
            "on_frames", [1, 2, 3, 5], filt)
        res["axes"][f"score_ema[{filt}]"] = sweep(
            frames, fmeta, dec, sc_all, sub_idx, obj_idx, vidx, is_sp, 1920, 1080,
            "score_ema", [0.20, 0.35, 0.50], filt)
        res["axes"][f"max_age[{filt}]"] = sweep(
            frames, fmeta, dec, sc_all, sub_idx, obj_idx, vidx, is_sp, 1920, 1080,
            "max_age", [4, 8, 16], filt)
    res["axes"]["belief_qr"] = sweep(
        frames, fmeta, dec, sc_all, sub_idx, obj_idx, vidx, is_sp, 1920, 1080,
        "belief", [(0.05, 1.0), (0.05, 0.5), (0.5, 1.0)], "belief")

    with open(a.out_json, "w") as fp:
        json.dump(res, fp, ensure_ascii=False, indent=1)
    for name, rows in res["axes"].items():
        print(f"== {name} ==")
        for r in rows:
            key = next(k for k in r if k in ("on_frames", "score_ema", "max_age", "belief"))
            print(f"  {key}={r[key]!s:>14s}  边/帧={r['visible_per_frame_mean']:>6} "
                  f"watching={r['watching_share_mean']:.4f} 种数={r['n_distinct_pred_mean']:.4f} "
                  f"熵={r['entropy_norm_mean']:.4f} 身份一致率={r['identity_consistency']}")
    print(f"[out] {a.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
