#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reid_relink —— 路线A：离线外观 gallery + 后处理 k-NN 重连（加性，不改 stabilize 内核）。

设计（基于已核实事实）：
  - stabilize 的「外观」只用 EMA 滑动平均，track 死亡后外观被丢弃（stabilize_tracks_v2.py:276,320-325），
    长遮挡后无法恢复身份 → 门①-B 结构性瓶颈。
  - 本脚本在 stabilize 产物（norm_g3 的 ball_tracks.json）之上做**后处理重连**：
      ① 用 stabilize 的 torso_crop + embed_crops（已缓存 DINOv2-small）重算每段 per-track 外观 gallery；
      ② 对每个「gap 后新开」track B，比对同段已死亡 track A 的 gallery，
         top-1 余弦 ≥ tau 且 team 标签一致（若双方有标签）⇒ 合并（A 的 id 续给 B）；
      ③ union-find 解析，改写 ball_tracks 的 track_id；嵌入与帧/球员顺序不变。
  - 输出与 id_identity_audit 兼容的 emb_dump.json（按帧/球员顺序），供双指标验收当护栏：
    错并不同球员会被 Δ10 下跌抓住。

输入：
  --root        norm_g3 段目录（每段 ball_tracks.json）
  --frames-root tactic_notes_batch_full/segments（每段 frames/）
输出（--out，默认 action_work/norm_g3_reid/<seg>/）：
  ball_tracks.json      重连后（同结构，仅 track_id 变）
  ball_tracks_base.json 原样备份（基线审计/分类用）
  emb_dump.json         审计格式嵌入（基线/重连共用，顺序对齐）
  gallery.json          每段 per-track 外观缓存（τ 重调免重算 DINOv2）
  relink_log.json       合并明细 + tau + track 数前后

纪律：纯加性，不修改 stabilize_tracks_v2.py 任何逻辑与产物。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ENG = Path(__file__).resolve().parent
sys.path.insert(0, str(ENG))
import stabilize_tracks_v2 as S  # noqa: E402


def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def compute_gallery(d, frames_dir):
    """返回 (G, emb_dump)。G: {int tid: {mean, first, last, team, n}}。"""
    per_track = {}
    emb_dump = []
    for rec in d:
        fn = rec.get("file")
        img = cv2.imread(str(frames_dir / fn)) if fn else None
        dets = rec.get("players", []) or []
        crops = [S.torso_crop(p["bbox"], img) for p in dets]
        embs = S.embed_crops(crops)  # [N,384] L2-归一化
        fi = int(rec.get("frame", 0))
        erec = []
        for j, p in enumerate(dets):
            e = embs[j]
            erec.append([float(v) for v in e])
            t = p.get("track_id")
            if isinstance(t, int) and t > 0:
                g = per_track.setdefault(
                    t, {"embs": [], "first": 1e18, "last": -1, "team": None, "n": 0}
                )
                g["embs"].append(e)
                g["first"] = min(g["first"], fi)
                g["last"] = max(g["last"], fi)
                g["n"] += 1
                if g["team"] is None and isinstance(p.get("team"), int):
                    g["team"] = p["team"]
        emb_dump.append({"frame": fi, "embs": erec})
    G = {}
    for t, g in per_track.items():
        if g["embs"]:
            m = np.mean(np.stack(g["embs"]), axis=0)
            m = m / (np.linalg.norm(m) + 1e-9)
            G[t] = {
                "mean": [float(v) for v in m],
                "first": int(g["first"]),
                "last": int(g["last"]),
                "team": g["team"],
                "n": g["n"],
            }
    return G, emb_dump


def relink(G, tau, max_gap=2000, min_frames=3, allow_overlap=False, team_strict=True):
    """返回 (mapping: old_tid->canonical_tid, log)。

    allow_overlap=False（默认）：仅合并「A 在 B 出生前已死」的遮挡分裂对（路线A原设计）。
    allow_overlap=True：额外允许合并时间区间重叠的高相似 track（同一球员碎片化场景），
        但合并重叠 track 有风险（重叠帧会出现两人同 id），须由 Δ10 审计兜底。
    team_strict=True：双方都有队标且不同则跳过（强负信号）；False：忽略团队标签。
    """
    tids = sorted(G.keys(), key=lambda t: (G[t]["first"], t))
    uf = UF()
    merges = []
    for B in tids:
        gb = G[B]
        if gb["n"] < min_frames:
            continue
        bestA, best_sim = None, -1.0
        for A in tids:
            if A == B:
                continue
            ga = G[A]
            if ga["n"] < min_frames:
                continue
            gap = gb["first"] - ga["last"]
            if not allow_overlap:
                if ga["last"] >= gb["first"]:
                    continue  # A 必须在 B 出生前已死
                if gap > max_gap:
                    continue
            ta, tb = ga["team"], gb["team"]
            if team_strict and isinstance(ta, int) and isinstance(tb, int) and ta >= 0 and tb >= 0 and ta != tb:
                continue  # team 标签冲突，强负信号
            sim = cosine(np.array(ga["mean"]), np.array(gb["mean"]))
            if sim >= tau and sim > best_sim:
                best_sim, bestA = sim, A
        if bestA is not None:
            uf.union(bestA, B)
            merges.append(
                {"a": bestA, "b": B, "sim": round(best_sim, 4),
                 "gap": int(gap), "team_a": ga["team"], "team_b": gb["team"]}
            )
    # 每个连通分量取 first 最小的 tid 作代表（保留时间线最早的 id）
    comp_rep = {}
    for t in tids:
        r = uf.find(t)
        fr = G[t]["first"]
        if r not in comp_rep or fr < comp_rep[r][1]:
            comp_rep[r] = (t, fr)
    mapping = {t: comp_rep[uf.find(t)][0] for t in tids}
    return mapping, {"merges": merges, "tau": tau,
                     "n_tracks_in": len(tids), "n_merges": len(merges)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="action_work/norm_g3")
    ap.add_argument("--frames-root", default="action_work/tactic_notes_batch_full/segments")
    ap.add_argument("--out", default="action_work/norm_g3_reid")
    ap.add_argument("--seg", nargs="*", default=[])
    ap.add_argument("--tau", type=float, default=0.60, help="合并余弦阈值")
    ap.add_argument("--max-gap", type=int, default=2000, help="死亡→新生最大帧间隔")
    ap.add_argument("--min-frames", type=int, default=3, help="参与重连的 track 最小帧数")
    ap.add_argument("--no-cache", action="store_true", help="强制重算 gallery（不读 gallery.json）")
    a = ap.parse_args()

    root, froot, out = Path(a.root), Path(a.frames_root), Path(a.out)
    segs = a.seg or sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and (d / "ball_tracks.json").exists()
    )
    for seg in segs:
        bt_path = root / seg / "ball_tracks.json"
        frames_dir = froot / seg / "frames"
        odir = out / seg
        odir.mkdir(parents=True, exist_ok=True)
        d = json.loads(bt_path.read_text(encoding="utf-8"))

        # 基线备份（供审计/分类对照）
        (odir / "ball_tracks_base.json").write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8"
        )

        gcache = odir / "gallery.json"
        if (not a.no_cache) and gcache.exists():
            G = json.loads(gcache.read_text(encoding="utf-8"))
            emb_dump = json.loads((odir / "emb_dump.json").read_text(encoding="utf-8"))
        else:
            print(f"[{seg}] 计算外观 gallery（DINOv2）…")
            G, emb_dump = compute_gallery(d, frames_dir)
            gcache.write_text(json.dumps(G, ensure_ascii=False), encoding="utf-8")
            (odir / "emb_dump.json").write_text(
                json.dumps(emb_dump, ensure_ascii=False), encoding="utf-8"
            )
        # JSON 键还原为 int（gallery.json 序列化后键变 str，避免与 ball_tracks 的 int track_id 不匹配）
        G = {int(k): v for k, v in G.items()}

        mapping, log = relink(G, a.tau, a.max_gap, a.min_frames)
        relinked = []
        for rec in d:
            players = []
            for p in rec.get("players", []) or []:
                t = p.get("track_id")
                if isinstance(t, int) and t > 0 and t in mapping and mapping[t] != t:
                    np_ = dict(p)
                    np_["track_id"] = mapping[t]
                    players.append(np_)
                else:
                    players.append(p)
            relinked.append({**rec, "players": players})

        (odir / "ball_tracks.json").write_text(
            json.dumps(relinked, ensure_ascii=False), encoding="utf-8"
        )
        (odir / "relink_log.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        n_after = len({mapping.get(t, t) for t in G})
        print(f"[{seg}] tracks {len(G)} -> {n_after}  "
              f"merges={log['n_merges']}  tau={a.tau:.2f}")


if __name__ == "__main__":
    main()
