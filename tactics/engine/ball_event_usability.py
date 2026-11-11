#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ball_event_usability.py — 把「识别精度 ≥90%」门禁重定义为「任务级事件可用性」并现场测算。

背景（见 MEMORY A4.12 / A6 第 5 条）
-----------------------------------
- 产品 = 战术分析；tactical_pressure/movement/screen/dashboard 已用 player-movement 信号交付，
  不依赖球检测。关系层路线已封口（A+B 步，否定 ×3）。
- 绝对「每帧球框精度 ≥90%」当前**不可测也不可达**：
  * 无可信真值库（labels_bank 与 labels3 仅 76.7% 一致；自判者门禁试点 REJECT_SELF_AS_ANNOTATOR，74.4% 封顶）；
  * 验证头在单一工作点无法同时满足 P≥90% 且 R≥90%（PR 权衡：th=0.4→P=0.768/R=0.869；
    th=0.975→P=0.903/R=0.638，且 90% 仅落在 CI 内，未被确立；库外 231/344 宣称无真值）。

本脚本回答「任务级事件可用性」这一**可交付、可测算**的替代门禁：
  Q1 在高置信工作点（th=0.975，验证头分数高度可分：TP 中位 0.996 / FP 中位 0.012）下，
      球信号在每窗的「帧覆盖」「连续跟踪片段数/长度」「轨迹平滑度（可跟踪比例）」是多少？
      —— 这些是下游战术事件（球入区/快攻/攻防转换）能被动提取的**自洽性**信号，不需要逐帧框真值。
  Q2 漏标队列：th≥0.975 的宣称中，有多少落在人工库外（无真值）？→ 即「要确立绝对精度还需补标多少」的清单。

⚠️ 这是「可用性/自洽性」信号，不是精度认证。精度认证仍需可信真值（路径 A 用户抽检 / 路径 B VLM）。
输入: action_work/ball_cand_scores_v2.json, reports/milestone_05/measure/labels_bank.json (仅用于算漏标)
输出: reports/milestone_05/measure/ball_event_usability.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
import os

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
AW = os.path.join(ROOT, "action_work")
MS = os.path.join(ROOT, "reports", "milestone_05", "measure")
WINS = ("w1", "w2", "w3", "w4")
TH = 0.975          # 高置信工作点（operating_point.json: 该点 P=0.903, CI 含 0.90）
GAP_TOL = 3         # 连续跟踪片段允许的最大断帧数（桥接短暂漏检）
SMOOTH_PX = 80.0    # 相邻帧球心位移 < 该值视为「可跟踪」（10fps 下快攻球 ~100px/帧，FP 抖动常 > 该值）


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def centroid(bb):
    return ((bb[0]+bb[2])/2.0, (bb[1]+bb[3])/2.0)


def fkey(k):
    return int("".join(ch for ch in k if ch.isdigit()))


def main():
    scores = json.load(open(os.path.join(AW, "ball_cand_scores_v2.json")))
    bank = [r for r in json.load(open(os.path.join(MS, "labels_bank.json")))
            if r["label"] in ("TP", "FP")]

    out, spot = {}, {}
    # 漏标队列：每窗 th 以上宣称中与 bank 任意框 IoU<0.5 的候选
    for w in WINS:
        frames = scores.get(w, {})
        items = sorted(((fkey(k), k) for k in frames.keys()))
        n_frames = len(items)
        # 每帧 top-1 高置信候选
        present, top1 = {}, {}
        uncovered = []
        for num, k in items:
            cs = [c for c in frames[k] if c["prob"] > TH]
            if not cs:
                continue
            best = max(cs, key=lambda c: c["prob"])
            present[num] = best
            top1[num] = centroid(best["bbox"])
            # 漏标判定
            covered = any(iou(best["bbox"], r["bbox"]) >= 0.5
                          for r in bank if r["window"] == w and r["frame"] == k)
            if not covered:
                uncovered.append({"frame": k, "num": num, "prob": round(float(best["prob"]), 4),
                                  "bbox": [round(x, 1) for x in best["bbox"]]})
        spot[w] = uncovered

        n_claim = len(present)
        cov = n_claim / n_frames if n_frames else 0.0

        # 连续跟踪片段（允许 GAP_TOL 断帧）
        nums = [num for num, _ in items]
        eps, cur, last = [], [], None
        for f in nums:
            if f in present:
                if last is not None and f - last > GAP_TOL + 1:
                    if cur:
                        eps.append(cur)
                    cur = []
                cur.append(f)
                last = f
            else:
                if cur and (last is not None and f - last > GAP_TOL):
                    eps.append(cur)
                    cur = []
                    last = None
        if cur:
            eps.append(cur)

        ep_lens = [len(e) for e in eps]
        mean_ep = sum(ep_lens)/len(ep_lens) if ep_lens else 0.0

        # 轨迹平滑度：片段内相邻帧球心位移
        steps, smooth = [], 0
        for e in eps:
            for a, b in zip(e, e[1:]):
                if a in top1 and b in top1:
                    d = math.hypot(top1[b][0]-top1[a][0], top1[b][1]-top1[a][1])
                    steps.append(d)
        if steps:
            ss = sorted(steps)
            med = ss[len(ss)//2]
            trackable = sum(1 for d in steps if d < SMOOTH_PX) / len(steps)
        else:
            med, trackable = 0.0, 0.0

        out[w] = {
            "n_frames": n_frames,
            "n_claim_frames": n_claim,
            "frame_coverage": round(cov, 4),
            "n_episodes": len(eps),
            "mean_episode_len": round(mean_ep, 2),
            "median_step_px": round(med, 1),
            "trackable_frac": round(trackable, 4),
            "uncovered_claims": len(uncovered),
        }
        print(f"{w}: 帧 {n_frames}  覆盖 {cov*100:.1f}%  片段 {len(eps)}  "
              f"均长 {mean_ep:.1f}  中位步长 {med:.0f}px  可跟踪 {trackable*100:.1f}%  "
              f"漏标 {len(uncovered)}")

    tot_unc = sum(len(v) for v in spot.values())
    res = {"th": TH, "gap_tol": GAP_TOL, "smooth_px": SMOOTH_PX,
           "windows": out, "spotcheck_queue": spot, "spotcheck_total": tot_unc}
    json.dump(res, open(os.path.join(MS, "ball_event_usability.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"\n漏标队列合计 {tot_unc} 条（即「要确立绝对精度还需补标」的候选上限）")
    print(f"→ {os.path.join(MS, 'ball_event_usability.json')}")


if __name__ == "__main__":
    main()
