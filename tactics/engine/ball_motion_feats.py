#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多帧动态特征（用户假说：球在动、人头不动）。

对每个已标注样本（labels_bank.json），在 ±K 帧邻域内找最近候选，量化：
  静止性（static_frac / recur20）、位移统计（d_med/d_max）、密度、conf 稳定性。
输出 motion_rows.json + 逐特征 AUC（TP vs FP）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))


def ctr(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--K", type=int, default=5)
    ap.add_argument("--src", default="_ball_verified")
    a = ap.parse_args()

    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    cache = {}
    for w in ("w1", "w2", "w3", "w4"):
        det = json.loads((AW / f"{w}{a.src}.json").read_text())
        idx = {}
        for f, cs in det.items():
            i = int(f[1:6])
            idx[i] = [(ctr(c["bbox"]), c.get("conf2", 0.0), c["bbox"]) for c in cs]
        cache[w] = (idx, max(idx) if idx else 0)
        print(f"{w}: 帧 {len(idx)}  有候选帧 {sum(1 for v in idx.values() if v)}")

    rows = []
    for r in bank:
        w = r["window"]
        idx, maxi = cache[w]
        i = int(r["frame"][1:6])
        cx, cy = ctr(r["bbox"])
        bw = r["bbox"][2] - r["bbox"][0]
        ds, n_cand, confs = [], [], []
        for k in range(-a.K, a.K + 1):
            if k == 0:
                continue
            cs = idx.get(i + k, [])
            n_cand.append(len(cs))
            if not cs:
                ds.append(np.nan)
                continue
            d, best = min(((np.hypot(c[0][0] - cx, c[0][1] - cy), c) for c in cs), key=lambda t: t[0])
            ds.append(d)
            confs.append(best[1])
        d = np.array(ds, float)
        fin = d[~np.isnan(d)]
        # 同点复现率：±1..±10 帧内存在「离原中心 <20px」候选的帧占比
        recur = []
        for k in range(-10, 11):
            if k == 0:
                continue
            cs = idx.get(i + k, [])
            recur.append(any(np.hypot(c[0][0] - cx, c[0][1] - cy) < 20 for c in cs))
        rows.append({
            "window": w, "frame": r["frame"], "label": r["label"],
            "d_med": float(np.nanmedian(d)) if fin.size else 999.0,
            "d_min": float(np.nanmin(d)) if fin.size else 999.0,
            "d_max": float(np.nanmax(d)) if fin.size else 999.0,
            "d_min_norm": float(np.nanmin(d)) / max(1.0, bw) if fin.size else 99.0,
            "static_frac": float(np.mean(fin < 15)) if fin.size else 0.0,
            "near25_frac": float(np.mean(fin < 25)) if fin.size else 0.0,
            "nframe_with": float(np.mean(np.array(n_cand) > 0)),
            "ncand_med": float(np.median(n_cand)),
            "recur20": float(np.mean(recur)),
            "conf_std": float(np.std(confs)) if len(confs) > 1 else 0.0,
        })
    (MS / "motion_rows.json").write_text(json.dumps(rows, indent=1))

    # ---- 逐特征 AUC ----
    from sklearn.metrics import roc_auc_score
    y = np.array([r["label"] == "TP" for r in rows]).astype(int)
    print(f"\n样本 {len(rows)}  TP={y.sum()} FP={(1-y).sum()}")
    print(f"{'特征':<14}{'AUC':>8}{'TP中位':>10}{'FP中位':>10}")
    feats = [k for k in rows[0] if k not in ("window", "frame", "label")]
    res = {}
    for k in feats:
        v = np.array([r[k] for r in rows], float)
        auc = roc_auc_score(y, v)
        res[k] = auc
        tp_m, fp_m = np.median(v[y == 1]), np.median(v[y == 0])
        flag = " ←" if abs(auc - 0.5) > 0.08 else ""
        print(f"{k:<14}{auc:>8.4f}{tp_m:>10.2f}{fp_m:>10.2f}{flag}")
    # 分窗最强特征
    print("\n分窗 AUC（|AUC-0.5| 前 3）:")
    for w in ("w1", "w2", "w3", "w4"):
        m = np.array([r["window"] == w for r in rows])
        yy = y[m]
        scored = sorted(((abs(roc_auc_score(yy, np.array([r[k] for r in rows], float)[m]) - 0.5),
                          k, roc_auc_score(yy, np.array([r[k] for r in rows], float)[m])) for k in feats),
                        reverse=True)[:3]
        print(f"  {w}: " + "  ".join(f"{k}={au:.3f}" for _, k, au in scored))


if __name__ == "__main__":
    raise SystemExit(main())
