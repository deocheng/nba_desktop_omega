#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时序一致性门禁分析：真球连续运动 vs FP 孤立/静止。

对 labels3_visual.json 的 60 个真实目视标注样本，在 w*_ball_verified_t1.json
的 top1 检测序列上计算：
  nn_k(t) = 帧 t±k 中最近邻检测的中心距（k=1..K，无检出帧跳过）
  support = min_k ( nn_k / (r0 * k) )  —— 归一化：≤1 表示符合线性位移容差
扫描 support 阈值，报严格/宽松口径下的 (precision, recall)。
另报「静止度」：该帧与其±K 帧内最近邻的距离是否≈0（观众席静坐误检特征）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
K = 5           # 前后各看 5 帧
R0 = 90.0       # 基础位移容差 px（帧1），线性放宽 r0*k

labels = json.loads((MS / "labels3_visual.json").read_text())


def fno(frame):
    return int(frame[1:].split(".")[0])


rows = []
for w in ("w1", "w2", "w3", "w4"):
    det = json.loads((AW / f"{w}_ball_verified_t1.json").read_text())
    pts = {}   # frame_no -> center
    for fn, kept in det.items():
        if kept:
            b = kept[0]["bbox"]
            pts[fno(fn)] = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    for r in labels:
        if r["window"] != w:
            continue
        t = fno(r["frame"])
        me = pts.get(t)
        nn, still = [], []
        for k in range(1, K + 1):
            best = None
            for tt in (t - k, t + k):
                if tt in pts and me:
                    d = ((pts[tt][0] - me[0]) ** 2 + (pts[tt][1] - me[1]) ** 2) ** 0.5
                    best = d if best is None else min(best, d)
            nn.append(best)
        sup = min((d / (R0 * k)) for k, d in enumerate(nn, 1) if d is not None) \
            if any(d is not None for d in nn) else 99.0
        anynn = next((d for d in nn if d is not None), None)
        rows.append({**r, "support": round(sup, 3),
                     "nn1": round(nn[0]) if nn[0] is not None else -1,
                     "nn_any": round(anynn) if anynn is not None else -1})

(MS / "temporal_rows.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))

for strict, unc_as in (("严格(unc=FP)", "FP"), ("宽松(unc=TP)", "TP")):
    tp = [r for r in rows if r["label"] == "TP" or (r["label"] == "unc" and unc_as == "TP")]
    fp = [r for r in rows if r["label"] == "FP" or (r["label"] == "unc" and unc_as == "FP")]
    print(f"\n=== {strict}: TP={len(tp)} FP={len(fp)} ===")
    print("TP support:", sorted(r["support"] for r in tp))
    print("FP support:", sorted(r["support"] for r in fp))
    print(f"{'阈值':>8} {'P':>6} {'R':>6} {'杀FP':>5} {'损TP':>5}")
    for th in (0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 99):
        ktp = sum(1 for r in tp if r["support"] <= th)
        kfp = sum(1 for r in fp if r["support"] <= th)
        P = ktp / (ktp + kfp) if ktp + kfp else 0
        R = ktp / len(tp) if tp else 0
        print(f"{th:>8} {P*100:>5.1f}% {R*100:>5.1f}% {len(fp)-kfp:>4} {len(tp)-ktp:>4}")

# FP 逐条（严格口径）看 support，找可分性证据
print("\n严格口径 FP 明细（window/frame/nn1/nn_any/support）:")
for r in rows:
    if r["label"] in ("FP", "unc"):
        print(f"  {r['window']}/{r['frame']} label={r['label']:>3} "
              f"nn1={r['nn1']:>5} nn_any={r['nn_any']:>5} sup={r['support']:>7.3f}  {r['note'][:20]}")
