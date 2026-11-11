#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多帧动态特征 v2：轨迹链 + 速度物理合理性 + 路径平直度。

v1 发现：信号不是"球动/人头静"，而是"球被邻帧一致重复检出、FP 在时间上孤立/跳变"。
v2 用真正的链式关联刻画这一点：
  chain_fwd/bwd：贪心链（邻帧最近候选，步长上限 R）能延伸多少帧
  spd_plaus    ：±1 帧最近候选是否落在"篮球物理合理步长"区间 [8,150]px（10fps ≈ 0.8–15 m/s）
  turn_cos     ：样本点处前后两步的夹角余弦（平滑路径→≈1；跳变→随机/负）
  extrap_resid ：下一步位置相对线性外推的残差（球近似直线，人头检出错乱）
输出 motion_rows2.json
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


def nearest(cands, x, y, R):
    """cands: [((cx,cy), conf), ...] -> (中心 or None, 最近距离)"""
    if not cands:
        return None, None
    d, best = min(((np.hypot(c[0][0] - x, c[0][1] - y), c[0]) for c in cands), key=lambda t: t[0])
    return (best, float(d)) if d <= R else (None, float(d))


def chain(idx, i, x, y, step, R, maxlen=12):
    pts = []
    for k in range(1, maxlen + 1):
        cs = idx.get(i + step * k, [])
        b, d = nearest(cs, x, y, R)
        if b is None:
            break
        x, y = b[0], b[1]
        pts.append((x, y))
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="_ball_verified")
    ap.add_argument("--R", type=float, default=130.0)
    a = ap.parse_args()

    bank = [r for r in json.loads((MS / "labels_bank.json").read_text())
            if r["label"] in ("TP", "FP")]
    idxs = {}
    for w in ("w1", "w2", "w3", "w4"):
        det = json.loads((AW / f"{w}{a.src}.json").read_text())
        idxs[w] = {int(f[1:6]): [(ctr(c["bbox"]), c.get("conf2", 0.0)) for c in cs]
                   for f, cs in det.items()}

    rows = []
    for r in bank:
        w = r["window"]
        idx = idxs[w]
        i = int(r["frame"][1:6])
        cx, cy = ctr(r["bbox"])
        fw = chain(idx, i, cx, cy, +1, a.R)
        bw = chain(idx, i, cx, cy, -1, a.R)
        d_prev = np.hypot(bw[0][0] - cx, bw[0][1] - cy) if bw else 999.0
        d_next = np.hypot(fw[0][0] - cx, fw[0][1] - cy) if fw else 999.0
        pl_p = float(8 <= d_prev <= 150)
        pl_n = float(8 <= d_next <= 150)
        # 平直度：前后两步向量夹角
        tc = 0.0
        if fw and bw:
            v1 = np.array([cx - bw[0][0], cy - bw[0][1]])
            v2 = np.array([fw[0][0] - cx, fw[0][1] - cy])
            n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
            if n1 > 1 and n2 > 1:
                tc = float(np.dot(v1, v2) / (n1 * n2))
        # 线性外推残差：用 bw[0]→(cx,cy) 的位移外推一步，看与 fw[0] 的差
        resid = 999.0
        if fw and bw:
            ex, ey = cx + (cx - bw[0][0]), cy + (cy - bw[0][1])
            resid = float(np.hypot(fw[0][0] - ex, fw[0][1] - ey))
        rows.append({
            "window": w, "frame": r["frame"], "label": r["label"],
            "d_prev": float(d_prev), "d_next": float(d_next),
            "plaus_prev": pl_p, "plaus_next": pl_n,
            "chain_tot": len(fw) + len(bw),
            "chain_fwd": len(fw), "chain_bwd": len(bw),
            "turn_cos": tc, "extrap_resid": float(min(resid, 999)),
        })
    (MS / "motion_rows2.json").write_text(json.dumps(rows, indent=1))

    from sklearn.metrics import roc_auc_score
    y = np.array([r["label"] == "TP" for r in rows]).astype(int)
    print(f"样本 {len(rows)} TP={y.sum()} FP={(1-y).sum()}  (R={a.R})")
    print(f"{'特征':<14}{'AUC':>8}{'TP中位':>10}{'FP中位':>10}")
    feats = [k for k in rows[0] if k not in ("window", "frame", "label")]
    with open(MS / "motion_auc2.json", "w") as fh:
        json.dump({}, fh)
    out = {}
    for k in feats:
        v = np.array([r[k] for r in rows], float)
        auc = roc_auc_score(y, v)
        out[k] = float(auc)
        m = " ←" if abs(auc - 0.5) > 0.08 else ""
        print(f"{k:<14}{auc:>8.4f}{np.median(v[y==1]):>10.2f}{np.median(v[y==0]):>10.2f}{m}")
    (MS / "motion_auc2.json").write_text(json.dumps(out, indent=1))
    print("\n分窗最强 3:")
    for w in ("w1", "w2", "w3", "w4"):
        m = np.array([r["window"] == w for r in rows])
        sc = sorted(((abs(roc_auc_score(y[m], np.array([r[k] for r in rows], float)[m]) - 0.5), k,
                      roc_auc_score(y[m], np.array([r[k] for r in rows], float)[m])) for k in feats),
                    reverse=True)[:3]
        print(f"  {w}(n={int(m.sum())}): " + "  ".join(f"{k}={au:.3f}" for _, k, au in sc))


if __name__ == "__main__":
    raise SystemExit(main())
