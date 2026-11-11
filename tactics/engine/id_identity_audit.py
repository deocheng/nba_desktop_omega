#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""id_identity_audit —— 红线门 ①-B「身份正确性」验收（ID 稳定化的另一半）。

存在理由：门 ①-A（track_stability_audit）只证明「ID 不碎」，**证明不了**
「同一个 ID 从头到尾是同一个球员」。rescue-g3 靠把 gate 放宽到 324px、
app-thresh 放宽到 0.10、w-app 降到 0.5 换来了 4/4 达标的超长中位寿命——
代价很可能是**一个 ID 在不同人之间跳**，此时 ①-A 的数字全是空心成绩。

方法（自带对照，不需要任何人工帧级标签）：
  T1 组间基线：同一帧内**不同**球员两两余弦 —— 「不同人」的对照分布
  T2 组内同 ID：同一 track 内相隔 L 帧的两帧余弦 —— 「同 ID 同一人」的假设
  若 within@L=10 已跟 between 没差别 ⇒ 长寿命是身份漂移换来的，空心。

判据（**事先注册，跑之前就定死，禁止事后调线**）：
  PASS 需同时满足三条：
    P1 主判据 : Δ10 = mean(within@L=10) - mean(between) >= 0.15
    P2 副判据 : track 内相邻帧外观突变(cos<0.5) 占比 <= 5%
    P3 单调性 : within@1 >= within@5 >= within@10 >= within@20（允许相等）

用法:
  python3 id_identity_audit.py --tracks ball_tracks.json --emb emb_dump.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

LAGS = (1, 5, 10, 20)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def audit(tracks_path, emb_path):
    fr = load(tracks_path)
    em = load(emb_path)
    if len(em) != len(fr):
        raise SystemExit(f"帧数不一致 tracks={len(fr)} emb={len(em)}")

    within = {L: [] for L in LAGS}
    adj = []       # 同 track 相邻帧（L=1）余弦
    between = []   # 同帧不同球员余弦
    store = {}     # 循环外累积：tid -> {frame: 嵌入向量}，跨帧配对必须在循环内先攒好

    for rec, erec in zip(fr, em):
        players = rec.get("players", []) or []
        tids = [p.get("track_id") for p in players]
        e = np.asarray(erec["embs"], np.float32)
        if len(e) != len(players) or len(e) < 2:
            continue
        fi = int(rec["frame"])

        # (a) T1 组间基线：同帧内不同球员
        pos_of = {}
        for i, t in enumerate(tids):
            if t is not None and t >= 0 and t not in pos_of:
                pos_of[t] = i
        idx = sorted(pos_of.values())
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                between.append(cos(e[idx[a]], e[idx[b]]))

        # (b) T2 组内：先按 tid 累积 (frame, 嵌入)，循环结束后再跨帧配对
        for i, t in enumerate(tids):
            if t is not None and t >= 0:
                store.setdefault(t, {})[fi] = e[i]

    # 注意：必须枚举 track 内**任意**跨 L 帧的两帧，不能只取相邻两项——
    # 相邻项的间隔等于「实际漏检长度」，只有恰好漏 L 帧才会计入，样本量会塌到个位数
    # （首版就犯了这个错：n@10 只有 6~13，主判据等于在噪声上做决定）。
    for t, m in store.items():
        ks = sorted(m)
        for k in range(len(ks)):
            for j in range(k + 1, len(ks)):
                Lf = ks[j] - ks[k]
                if Lf == 1:
                    adj.append(cos(m[ks[k]], m[ks[j]]))
                if Lf in within:
                    within[Lf].append(cos(m[ks[k]], m[ks[j]]))

    out = {"file": str(tracks_path)}
    for L in LAGS:
        v = within[L]
        out[f"within@{L}"] = round(float(np.mean(v)), 4) if v else None
        out[f"n@{L}"] = len(v)
    adj = np.array(adj) if adj else np.array([0.0])
    between = np.array(between) if between else np.array([0.0])
    out["n_between"] = int(between.size)
    out["adj_mean"] = round(float(adj.mean()), 4)
    out["adj_break_ratio(<0.5)"] = round(float((adj < 0.5).mean()), 4)
    out["between_mean"] = round(float(between.mean()), 4)
    out["between_p95"] = round(float(np.percentile(between, 95)), 4)

    w10, b = out["within@10"], out["between_mean"]
    out["delta10"] = round(w10 - b, 4) if w10 is not None else None

    # 补充：与门槛无关的分离度（Δ10 卡在 0.15，结果都挤在 0.055~0.175，
    # 只看 PASS/FAIL 会被阈值噪声误导，故补一个概率化 win-rate + Cohen's d）
    w10a = np.array(within[10], np.float32) if within[10] else np.array([0.0])
    bw = np.array(between, np.float32) if between.size else np.array([0.0])
    if bw.size and w10a.size:
        m = min(len(w10a), 400)
        sub = w10a[:m]
        out["win_rate_@10"] = round(float((sub[:, None] > bw[None, :]).mean()), 4)
        sd = float(np.sqrt((w10a.var() + bw.var()) / 2))
        out["cohen_d_@10"] = round(float((w10a.mean() - bw.mean()) / (sd + 1e-9)), 3)
    else:
        out["win_rate_@10"] = None
        out["cohen_d_@10"] = None

    # 判据（事前注册）
    p1 = out["delta10"] is not None and out["delta10"] >= 0.15
    p2 = out["adj_break_ratio(<0.5)"] <= 0.05
    ws = [out.get(f"within@{L}") for L in LAGS]
    ws = [x for x in ws if x is not None]
    p3 = len(ws) >= 3 and all(ws[i] >= ws[i + 1] - 1e-9 for i in range(len(ws) - 1))
    out["P1_delta10>=0.15"] = bool(p1)
    out["P2_break<=5%"] = bool(p2)
    out["P3_monotonic"] = bool(p3)
    out["VERDICT"] = "PASS" if (p1 and p2 and p3) else "FAIL"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", required=True)
    ap.add_argument("--emb", required=True)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    r = audit(a.tracks, a.emb)
    tag = Path(a.tracks).parent.name
    print(f"[{tag}]")
    print(f"  within@1={r.get('within@1')} within@5={r.get('within@5')} "
          f"within@10={r.get('within@10')} within@20={r.get('within@20')}")
    print(f"  between_mean={r['between_mean']}  delta10={r['delta10']}  "
          f"adj_break(<0.5)={r['adj_break_ratio(<0.5)']}")
    print(f"  win_rate@10={r.get('win_rate_@10')}  cohen_d@10={r.get('cohen_d_@10')}")
    print(f"  P1={r['P1_delta10>=0.15']} P2={r['P2_break<=5%']} P3={r['P3_monotonic']}"
          f"  => ①-B {r['VERDICT']}")
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  wrote", a.json)


if __name__ == "__main__":
    main()
