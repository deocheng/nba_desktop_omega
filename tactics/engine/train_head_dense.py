#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_head_dense.py — A4.42 头再校准：密集池(multiscale)上重训球验证头（老程授权方案A）。

与 ball_head_joint.py 的差异（其余同配方：build_all 特征 + StandardScaler/LogisticRegression）：
  1) 标签来源：bank 帧(人工裁定过有/无球)内的密集池候选，几何匹配自动标注——
     TP = 与该帧人工 GT 框 IoU>=0.3；FP = bank 帧内其余候选。
     锚定人工真值（GT 框人工确认、无球帧人工确认），非 A4.24 已证伪的 AI 自标 conf 路线。
  2) 🔴 class_weight='balanced'（显式偏离原配方）：1:96 失衡下不加权会被 FP 侧淹没。
  3) 评估直接在训练特征上算 GT top-1 正确性（GT 帧 ⊂ bank 帧，省全量重打分）：
     每个含球帧 argmax-prob 候选是否命中 GT（strict≤12px/inbox）+ 无球帧假阳率@th。
  4) LOCO 跨转播：train(sas_lal)→test(sas_det) 与反向，报 GT top-1 + AUC。
产出: <out> joblib + <out>.eval.json（指标）+ <out>.bankscores.json（bank 帧打分，供离线评估）
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
MS = ROOT / "reports/milestone_05/measure"
sys.path.insert(0, str(ROOT / "engine"))
import ball_feats_all as B  # noqa: E402

IOU_MATCH = 0.3   # 候选↔人工GT 判 TP 的几何口径（方案A 授权口径）


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def load_banks():
    """每片: gt {frame: [bbox]}（人工TP框）、no_ball_frames（人工裁定无球帧）。"""
    out = {}
    for clip, bp in (("sas_lal", AW / "validate/sas_lal_label_bank_final351.json"),
                     ("sas_det", AW / "validate/sas_det_label_bank_human.json")):
        labs = json.loads(bp.read_text())["labels"]
        gt, allf = {}, set()
        for L in labs:
            allf.add(L["frame"])
            if L.get("label") == "TP":
                gt.setdefault(L["frame"], []).append(L["bbox"])
        out[clip] = {"gt": gt, "bank_frames": allf,
                     "no_ball_frames": sorted(f for f in allf if f not in gt)}
    return out


def work_at(y, p, target):
    best = (0.0, None)
    for th in np.arange(0.05, 0.998, 0.002):
        pred = p > th
        tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
        if tp + fp == 0:
            continue
        P = tp / (tp + fp)
        if P >= target and tp / max(1, int(y.sum())) > best[0]:
            best = (tp / max(1, int(y.sum())), (float(th), float(P), tp, fp))
    return best


def gt_top1_full(rows_meta, prob, gt, px=12):
    """rows_meta: [(clip, frame, bbox)] 与 prob 对齐 → 每片 GT top-1。"""
    per = {}
    for (c, fr, bbox), p in zip(rows_meta, prob):
        per.setdefault(c, {}).setdefault(fr, []).append((bbox, float(p)))
    out = {}
    for c, byf in per.items():
        st = ib = 0
        miss = []
        frames = sorted(gt[c])
        for fr in frames:
            cands = byf.get(fr, [])
            if not cands:
                miss.append(fr); continue
            bbox, _ = max(cands, key=lambda t: t[1])
            cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
            hs = hi = False
            for g in gt[c][fr]:
                gx1, gy1, gx2, gy2 = g
                if np.hypot(cx - (gx1 + gx2) / 2, cy - (gy1 + gy2) / 2) <= px:
                    hs = True
                if gx1 <= cx <= gx2 and gy1 <= cy <= gy2:
                    hi = True
            st += hs; ib += hi
            if not (hs or hi):
                miss.append(fr)
        n = len(frames)
        out[c] = {"strict": st, "inbox": ib, "n": n,
                  "strict_pct": round(100 * st / n, 1), "inbox_pct": round(100 * ib / n, 1),
                  "miss": miss}
    return out


def empty_frame_fpr(prob_by_clip_frame, no_ball_frames, th):
    """无球帧中 max prob > th 的占比（越低越好）。"""
    out = {}
    for c, frames in no_ball_frames.items():
        byf = prob_by_clip_frame[c]
        hit = sum(1 for fr in frames if byf.get(fr) and max(byf[fr]) > th)
        out[c] = {"n": len(frames), "fp_frames": hit,
                  "rate": round(hit / len(frames), 4) if frames else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(MS / "ball_head_dense_a442.joblib"))
    ap.add_argument("--dev", default="mps")
    ap.add_argument("--target-p", type=float, default=0.80)
    a = ap.parse_args()

    pools = {c: json.loads((AW / "validate" / f"{c}_cands_multiscale.json").read_text())[c]
             for c in ("sas_lal", "sas_det")}
    banks = load_banks()

    # ---- 几何标注 ----
    rows, y, g, meta = [], [], [], []
    stats = {}
    for c in ("sas_lal", "sas_det"):
        gt = banks[c]["gt"]
        n_tp = n_fp = 0
        for fr in sorted(banks[c]["bank_frames"]):
            for cand in pools[c].get(fr, []):
                hit = any(iou(cand["bbox"], gbox) >= IOU_MATCH for gbox in gt.get(fr, []))
                rows.append({"window": c, "frame": fr, "bbox": cand["bbox"],
                             "conf1": cand.get("conf1", 0.0), "conf2": cand.get("conf2", 0.0)})
                y.append(1 if hit else 0)
                g.append(f"{c}|{fr}")
                meta.append((c, fr, cand["bbox"]))
                n_tp += hit; n_fp += (not hit)
        stats[c] = {"bank_frames": len(banks[c]["bank_frames"]),
                    "gt_frames": len(gt), "no_ball_frames": len(banks[c]["no_ball_frames"]),
                    "cands": n_tp + n_fp, "tp": n_tp, "fp": n_fp}
        print(f"[{c}] bank帧 {stats[c]['bank_frames']}（含球 {stats[c]['gt_frames']} / 无球 {stats[c]['no_ball_frames']}）"
              f"  候选 {stats[c]['cands']}  TP侧 {n_tp}  FP侧 {n_fp}", flush=True)
    y = np.array(y); g = np.array(g)
    print(f"合计样本 {len(y)}  TP={int(y.sum())}  FP={int((1-y).sum())}  失衡 1:{int((1-y).sum()//max(1,int(y.sum())))}", flush=True)

    # ---- 特征（带缓存：崩在评估段时不重算 40 分钟）----
    feats_cache = MS / "feats_dense_a442.npy"
    if feats_cache.exists():
        X = np.load(feats_cache)
        assert X.shape[0] == len(rows), f"缓存行数不符 {X.shape[0]} != {len(rows)}"
        print(f"特征(缓存) {X.shape}", flush=True)
    else:
        idx = {c: B.build_det_index(pools[c]) for c in pools}
        X = B.build_all(rows, idx, dev=a.dev, progress=True)
        np.save(feats_cache, X)
        print(f"特征 {X.shape}（已缓存 → {feats_cache.name}）", flush=True)

    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    # class_weight='balanced'：1:96 失衡的显式处理（对原配方 C=1.0 无权重的唯一偏离）
    def mk():
        return make_pipeline(StandardScaler(),
                             LogisticRegression(max_iter=4000, C=1.0, class_weight="balanced"))

    ev = {"config": {"iou_match": IOU_MATCH, "class_weight": "balanced", "C": 1.0,
                     "dev": a.dev, "stats": stats}, "n": int(len(y))}

    # ---- 合并 CV ----
    cv = cross_val_predict(mk(), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0),
                           method="predict_proba")[:, 1]
    auc_s = roc_auc_score(y, cv)
    r_s, w_s = work_at(y, cv, a.target_p)
    gcv = cross_val_predict(mk(), X, y, cv=GroupKFold(5), groups=g,
                            method="predict_proba")[:, 1]
    auc_g = roc_auc_score(y, gcv)
    r_g, w_g = work_at(y, gcv, a.target_p)
    print(f"[合并 Stratified5] AUC={auc_s:.4f}  " + (f"P>={a.target_p}: th={w_s[0]:.3f} P={w_s[1]*100:.1f}% R={r_s*100:.1f}%" if w_s else f"无 P>={a.target_p} 工作点"), flush=True)
    r_s5, w_s5 = work_at(y, cv, 0.5)
    print("                   P>=0.5: " + (f"th={w_s5[0]:.3f} P={w_s5[1]*100:.1f}% R={r_s5*100:.1f}%" if w_s5 else "无工作点"), flush=True)
    print(f"[合并 GroupByFrame5] AUC={auc_g:.4f}  " + (f"P>={a.target_p}: th={w_g[0]:.3f} P={w_g[1]*100:.1f}% R={r_g*100:.1f}%" if w_g else f"无 P>={a.target_p} 工作点"), flush=True)
    r_g5, w_g5 = work_at(y, gcv, 0.5)
    print("                   P>=0.5: " + (f"th={w_g5[0]:.3f} P={w_g5[1]*100:.1f}% R={r_g5*100:.1f}%" if w_g5 else "无工作点"), flush=True)
    ev["auc_stratified"] = float(auc_s); ev["auc_group_frame"] = float(auc_g)
    ev["work_stratified"] = w_s; ev["work_group"] = w_g
    ev["work_stratified_p50"] = w_s5; ev["work_group_p50"] = w_g5

    # ---- 合并模型：GT top-1（in-sample，直接衡量密集池可用性）----
    pipe = mk(); pipe.fit(X, y)
    prob = pipe.predict_proba(X)[:, 1]
    prob_by_cf = {}
    for (c, fr, _), p in zip(meta, prob):
        prob_by_cf.setdefault(c, {}).setdefault(fr, []).append(p)
    top1_in = gt_top1_full(meta, prob, {c: banks[c]["gt"] for c in banks})
    ev["gt_top1_insample"] = top1_in
    for c, t in top1_in.items():
        print(f"[GT top-1 in-sample {c}] strict={t['strict']}/{t['n']}={t['strict_pct']}%  "
              f"inbox={t['inbox_pct']}%  miss={t['miss'][:8]}", flush=True)
    ev["empty_fpr_insample"] = empty_frame_fpr(prob_by_cf, {c: banks[c]["no_ball_frames"] for c in banks},
                                               th=w_g[0] if w_g else 0.5)
    print(f"[无球帧假阳率@th] {ev['empty_fpr_insample']}", flush=True)

    # ---- LOCO 跨转播 ----
    loco_res = {}
    for c in ("sas_lal", "sas_det"):
        tr = np.array([i for i in range(len(y)) if not g[i].startswith(c + "|")])
        te = np.array([i for i in range(len(y)) if g[i].startswith(c + "|")])
        m = mk(); m.fit(X[tr], y[tr])
        p = m.predict_proba(X[te])[:, 1]
        auc = roc_auc_score(y[te], p)
        r, w = work_at(y[te], p, a.target_p)
        te_meta = [meta[i] for i in te]
        top1 = gt_top1_full(te_meta, p, {c: banks[c]["gt"] for c in banks})
        loco_res[c] = {"auc": float(auc), "work": w, "gt_top1": top1}
        print(f"[LOCO 排除{c}→测试{c}] AUC={auc:.4f}  "
              + (f"P>={a.target_p} th={w[0]:.3f} P={w[1]*100:.1f}% R={r*100:.1f}%" if w else "无工作点")
              + f"  GT top-1 strict={top1[c]['strict']}/{top1[c]['n']}={top1[c]['strict_pct']}%", flush=True)
    ev["loco"] = loco_res

    # ---- 落盘 ----
    joblib.dump({"pipe": pipe, "target_p": a.target_p, "clips": ["sas_lal", "sas_det"],
                 "auc_stratified": float(auc_s), "auc_group_frame": float(auc_g),
                 "loco_auc": {k: v["auc"] for k, v in loco_res.items()},
                 "threshold": float(w_g[0]) if w_g else 0.5,
                 "n": int(len(y)), "feat_dim": int(X.shape[1]),
                 "labels_source": f"dense-pool geometric match vs human GT (IoU>={IOU_MATCH}), class_weight=balanced",
                 "banks": {c: str(bp) for c, bp in
                           (("sas_lal", "sas_lal_label_bank_final351.json"),
                            ("sas_det", "sas_det_label_bank_human.json"))}}, a.out)
    print(f"[out] {a.out}", flush=True)

    # bank 帧打分（供离线评估/覆盖衔接）
    bs = {}
    for (c, fr, bbox), p in zip(meta, prob):
        bs.setdefault(c, {}).setdefault(fr, []).append({"bbox": bbox, "prob": float(p)})
    Path(a.out + ".bankscores.json").write_text(json.dumps(bs))
    Path(a.out + ".eval.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1))
    print(f"[out] {a.out}.eval.json / .bankscores.json", flush=True)


if __name__ == "__main__":
    main()
