#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 步：把官方 demo 的**稳定化层**移植到我们的关系层链上。

移植对象（`RelateAnything/deploy/render_video.py`，逐段照抄）：
  ① `Tracker` / `KalmanBox`  —— 两阶段 IoU 关联（ByteTrack 思路）+ 匀速卡尔曼框
  ② `RelationBelief`         —— 标定 **log-odds** 上的 1-D 卡尔曼（无速度项）
  ③ `Edge` / `EdgeBook`      —— EMA + 双阈值迟滞 + 去重 + 预算裁剪

为什么在本项目里这两件事必须**同时**做（否则结果无意义）
--------------------------------------------------------
官方稳定化层的状态键是 `(subject_track, object_track, predicate)` —— 它天然假设
两个端点有**跨帧持久身份**。而我们的 `players.json` 只有 `sel_id`（帧内按面积降序的
序号），实测：

    同名标签 `p_i` 跨帧 IoU>0.5 命中率 = **22.5%**（1240/5509）
    任意框最优匹配的上限        = **79.5%**（4616/5805）

⇒ 77.5% 的 `p_i` 在下一帧已经是**另一个人**。直接套时域滤波 = 对**随机配对**做平滑，
会产出「看起来很稳、语义全错」的输出。所以本脚本把 `idmode` 做成显式开关：
    sel   —— 用 sel_id 当身份（**复现"不补跟踪器硬上滤波"的后果**）
    track —— 用移植的 Tracker 给持久身份

用法:
  rel_stabilize.py <players.json> <rel_raw_dir> <outdir>
                   [--idmode sel|track|both] [--filter none|ema|belief|all]
                   [--topk 20] [--emit-relations]
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, namedtuple
from dataclasses import dataclass, field

import numpy as np


# ============================================================ 官方移植：跟踪
def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """[Na, Nb] pairwise IoU. Empty-safe, which the association loop relies on."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), np.float32)
    x0 = np.maximum(a[:, None, 0], b[None, :, 0])
    y0 = np.maximum(a[:, None, 1], b[None, :, 1])
    x1 = np.minimum(a[:, None, 2], b[None, :, 2])
    y1 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x1 - x0, 0, None) * np.clip(y1 - y0, 0, None)
    ar_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    ar_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return (inter / np.maximum(ar_a[:, None] + ar_b[None, :] - inter, 1e-6)).astype(np.float32)


class KalmanBox:
    """Constant-velocity Kalman filter on (cx, cy, w, h).  [原样照抄]"""

    __slots__ = ("x", "P", "_q", "_r")

    def __init__(self, box: np.ndarray, q: float = 1.0, r: float = 10.0):
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        w, h = box[2] - box[0], box[3] - box[1]
        self.x = np.array([cx, cy, w, h, 0, 0, 0, 0], np.float64)
        self.P = np.diag([10., 10., 10., 10., 1e3, 1e3, 1e3, 1e3])
        self._q, self._r = q, r

    def predict(self) -> None:
        self.x[:4] += self.x[4:]
        q = self._q
        self.P[:4, :4] += self.P[4:, 4:] + np.diag([q, q, q, q])
        self.P[4:, 4:] += np.diag([q * .01] * 4)

    def update(self, box: np.ndarray) -> None:
        z = np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
                      box[2] - box[0], box[3] - box[1]], np.float64)
        y = z - self.x[:4]
        S = self.P[:4, :4] + np.diag([self._r] * 4)
        K = np.zeros((8, 4))
        Sinv = np.linalg.inv(S)
        K[:4] = self.P[:4, :4] @ Sinv
        K[4:] = self.P[4:, :4] @ Sinv
        self.x += K @ y
        self.x[2:4] = np.maximum(self.x[2:4], 2.0)
        self.P[:4, :4] -= K[:4] @ self.P[:4, :4]
        self.P[4:, 4:] -= K[4:] @ self.P[:4, 4:]

    @property
    def box(self) -> np.ndarray:
        cx, cy, w, h = self.x[:4]
        return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], np.float32)


@dataclass
class Track:
    tid: int
    kf: KalmanBox
    conf: float
    votes: Counter = field(default_factory=Counter)
    hits: int = 0
    misses: int = 0
    alpha: float = 0.0

    @property
    def box(self) -> np.ndarray:
        return self.kf.box

    @property
    def label(self) -> str:
        return self.votes.most_common(1)[0][0] if self.votes else "?"


class Tracker:
    """Two-stage IoU association over Kalman-filtered boxes.  [原样照抄，去 mask]"""

    def __init__(self, iou_thr=0.3, low_iou_thr=0.5, merge_iou=0.75, max_age=12,
                 min_hits=2, high_conf=0.25, q=1.0, r=10.0, stride=1):
        self.iou_thr, self.low_iou_thr = iou_thr, low_iou_thr
        self.merge_iou, self.max_age, self.min_hits = merge_iou, max_age, min_hits
        self.high_conf, self.q, self.r = high_conf, q, r
        self.stride = max(1, int(stride))
        self.tracks: list[Track] = []
        self._next = 0

    def _match(self, cand, boxes, tracks, thr):
        if not cand or not tracks:
            return [], list(cand), list(tracks)
        M = iou_matrix(boxes[cand], np.stack([t.box for t in tracks]))
        pairs = sorted(((M[r_, c], r_, c) for r_ in range(M.shape[0])
                        for c in range(M.shape[1]) if M[r_, c] >= thr), reverse=True)
        used_d, used_t, out = set(), set(), []
        for _, r_, c in pairs:
            if r_ in used_d or c in used_t:
                continue
            used_d.add(r_); used_t.add(c)
            out.append((cand[r_], tracks[c]))
        return (out,
                [d for i, d in enumerate(cand) if i not in used_d],
                [t for i, t in enumerate(tracks) if i not in used_t])

    def observe(self, boxes, labels, confs, max_frac=1.0, frame_area=0.0):
        boxes = np.asarray(boxes, np.float32).reshape(-1, 4)
        confs = np.asarray(confs, np.float32)
        ok = np.ones(len(boxes), bool)
        if frame_area > 0 and max_frac < 1.0 and len(boxes):
            area = ((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]) / frame_area)
            ok &= area <= max_frac
        keep, kept_boxes = [], []
        for i in (np.argsort(-confs) if len(boxes) else []):
            if not ok[i]:
                continue
            if kept_boxes and iou_matrix(boxes[i:i + 1], np.array(kept_boxes)).max() > self.merge_iou:
                continue
            keep.append(int(i)); kept_boxes.append(boxes[i])

        hi = [d for d in keep if confs[d] >= self.high_conf]
        lo = [d for d in keep if confs[d] < self.high_conf]

        det2track: dict[int, int] = {}
        matched, un_hi, un_tracks = self._match(hi, boxes, self.tracks, self.iou_thr)
        matched2, _, un_tracks = self._match(lo, boxes, un_tracks, self.low_iou_thr)

        for d, t in matched + matched2:
            t.kf.update(boxes[d])
            t.conf = float(confs[d]); t.votes[labels[d]] += 1
            t.hits += 1; t.misses = 0
            det2track[d] = t.tid

        for d in un_hi:
            t = Track(self._next, KalmanBox(boxes[d], self.q, self.r), float(confs[d]))
            t.votes[labels[d]] += 1; t.hits = 1
            self.tracks.append(t); det2track[d] = t.tid
            self._next += 1

        for t in un_tracks:
            t.misses += 1
        self.tracks = [t for t in self.tracks if t.misses <= self.max_age]
        return det2track

    def step(self, W: int, H: int, fade=0.18):
        for t in self.tracks:
            t.kf.predict()
            b = t.kf.box
            b[0] = min(max(b[0], 0), W - 2); b[1] = min(max(b[1], 0), H - 2)
            b[2] = min(max(b[2], b[0] + 2), W); b[3] = min(max(b[3], b[1] + 2), H)
            t.kf.x[0] = (b[0] + b[2]) / 2; t.kf.x[1] = (b[1] + b[3]) / 2
            t.kf.x[2] = b[2] - b[0]; t.kf.x[3] = b[3] - b[1]
            vis = t.hits >= self.min_hits and t.misses <= 2
            t.alpha = min(1.0, t.alpha + fade) if vis else max(0.0, t.alpha - fade)

    def by_id(self):
        return {t.tid: t for t in self.tracks}


# ============================================================ 官方移植：关系稳定化
class RelationBelief:
    """A 1-D Kalman filter on the calibrated LOG-ODDS that one relation holds.
    [原样照抄；无速度项 —— 框有，关系不该有]"""

    __slots__ = ("x", "P")

    def __init__(self, z: float, P0: float = 4.0):
        self.x, self.P = float(z), float(P0)

    def predict(self, q: float = 0.05) -> None:
        self.P += q

    def update(self, z: float, r: float = 1.0, p_min: float = 0.04) -> None:
        K = self.P / (self.P + r)
        self.x += K * (z - self.x)
        self.P *= (1 - K)
        # 连续帧近似同一张图 ⇒ 测量强相关；若按独立证据处理，P 几帧内崩掉、
        # 此后任何证据都改不动信念。floor 住 P 才保留"改主意"的能力。
        self.P = max(self.P, p_min)

    @property
    def prob(self) -> float:
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, self.x))))


@dataclass
class Edge:
    sub: int
    obj: int
    pred: str
    score: float
    spatial: bool
    on: bool = False
    on_run: int = 0
    off_run: int = 0
    alpha: float = 0.0
    seen: int = 0
    bel: "RelationBelief | None" = None
    shown: float = 0.0


def _logit(p: float, eps: float = 1e-6) -> float:
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


Tri = namedtuple("Tri", "subject_idx object_idx predicate score")


class EdgeBook:
    """EMA + hysteresis over (subject track, object track, predicate).  [原样照抄]"""

    def __init__(self, score_ema=0.35, on_thr=0.45, off_thr=0.35,
                 on_frames=2, off_frames=6, fade=0.12, max_edges=8,
                 max_spatial=3, spatial_on_thr=0.42, belief=True,
                 kf_q=0.05, kf_r=1.0, p_max=8.0):
        self.score_ema, self.on_thr, self.off_thr = score_ema, on_thr, off_thr
        self.on_frames, self.off_frames = on_frames, off_frames
        self.fade, self.max_edges = fade, max_edges
        self.max_spatial = max_spatial
        self.spatial_on_thr = spatial_on_thr
        self.belief, self.kf_q, self.kf_r, self.p_max = belief, kf_q, kf_r, p_max
        self.edges: dict[tuple, Edge] = {}

    def observe(self, triplets, det2track, is_spatial: dict, raw=None):
        if raw is not None and self.belief:
            return self._observe_belief(triplets, det2track, is_spatial, raw)
        fresh: dict[tuple, float] = {}
        for t in triplets:
            s, o = det2track.get(t.subject_idx), det2track.get(t.object_idx)
            if s is None or o is None or s == o:
                continue
            k = (s, o, t.predicate)
            fresh[k] = max(fresh.get(k, 0.0), float(t.score))
        for k, sc in fresh.items():
            e = self.edges.get(k)
            if e is None:
                e = Edge(k[0], k[1], k[2], sc, bool(is_spatial.get(k[2], False)))
                self.edges[k] = e
            else:
                e.score = (1 - self.score_ema) * e.score + self.score_ema * sc
            if e.score >= self.off_thr:
                e.shown = e.score
            e.seen += 1
        for k, e in self.edges.items():
            if k not in fresh:
                e.score = (1 - self.score_ema) * e.score
        self._hysteresis()

    def _hysteresis(self):
        """Run counters advance per OBSERVATION，两条分数路径都要走到。"""
        for e in self.edges.values():
            on_thr = self.spatial_on_thr if e.spatial else self.on_thr
            if e.score >= on_thr:
                e.on_run += 1; e.off_run = 0
            elif e.score < self.off_thr:
                e.off_run += 1; e.on_run = 0
            else:
                e.on_run = e.off_run = 0       # dead band：保持现状
            if not e.on and e.on_run >= self.on_frames:
                e.on = True
            elif e.on and e.off_run >= self.off_frames:
                e.on = False

    def _observe_belief(self, triplets, det2track, is_spatial, raw):
        scores, kof, vidx = raw        # 官方只需 contract.fuse 后的值；本工程已落盘该矩阵
        track2det = {t: d for d, t in det2track.items()}

        for t in triplets:             # birth：只从 decode 暴露的三元组里提升
            s_, o_ = det2track.get(t.subject_idx), det2track.get(t.object_idx)
            v = vidx.get(t.predicate)
            if s_ is None or o_ is None or s_ == o_ or v is None:
                continue
            k = (s_, o_, t.predicate)
            if k not in self.edges:
                e = Edge(s_, o_, t.predicate, float(t.score),
                         bool(is_spatial.get(t.predicate, False)))
                e.bel = RelationBelief(_logit(float(t.score)))
                self.edges[k] = e

        dead = []
        for k, e in self.edges.items():
            v = vidx.get(e.pred)
            ds, do = track2det.get(e.sub), track2det.get(e.obj)
            kk = kof.get((ds, do)) if (ds is not None and do is not None) else None
            if kk is None or v is None:
                e.bel.predict(self.kf_q)          # 测不到：维持信念、只放大不确定度
            else:
                # 直接取原始矩阵，**不经过 decode**：decode 会施加 top-k 与阈值，
                # 低分对永不回流 ⇒ 负证据无法被观测。
                z = float(scores[kk, v])
                e.bel.update(z, self.kf_r)
                e.seen += 1
            e.score = e.bel.prob
            if e.score >= self.off_thr:
                e.shown = e.score
            if e.bel.P > self.p_max:
                dead.append(k)
        for k in dead:
            self.edges.pop(k, None)
        self._hysteresis()

    def step(self, live_tracks: set):
        dead = []
        for k, e in self.edges.items():
            if e.sub not in live_tracks or e.obj not in live_tracks:
                e.on, e.alpha = False, max(0.0, e.alpha - self.fade)
                if e.alpha <= 0:
                    dead.append(k)
                continue
            e.alpha = (min(1.0, e.alpha + self.fade) if e.on
                       else max(0.0, e.alpha - self.fade))
            if not e.on and e.alpha <= 0 and e.score < 0.05:
                dead.append(k)
        for k in dead:
            self.edges.pop(k, None)

    def visible(self) -> list:
        vis = [e for e in self.edges.values() if e.alpha > 0.01]
        best: dict[tuple, Edge] = {}
        for e in sorted(vis, key=lambda e: -max(e.shown, e.score)):
            best.setdefault((e.obj, e.pred), e)
        head: dict[tuple, Edge] = {}
        for e in sorted(best.values(), key=lambda e: -max(e.shown, e.score)):
            head.setdefault((e.sub, e.obj, e.pred.split()[0]), e)
        vis = list(head.values())
        vis.sort(key=lambda e: -max(e.shown, e.score))
        inter = [e for e in vis if not e.spatial]
        spat = [e for e in vis if e.spatial][:self.max_spatial]
        inter = inter[:max(0, self.max_edges - len(spat))]
        return inter + spat


# ============================================================ 驱动
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("players_json")
    ap.add_argument("rel_raw_dir")
    ap.add_argument("outdir")
    ap.add_argument("--idmode", default="both", choices=["sel", "track", "both"])
    ap.add_argument("--filter", default="all", choices=["none", "ema", "belief", "all"])
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--emit-relations", action="store_true")
    ap.add_argument("--frame-w", type=int, default=1920)
    ap.add_argument("--frame-h", type=int, default=1080)
    a = ap.parse_args()

    pd = json.load(open(a.players_json))
    meta = json.load(open(os.path.join(a.rel_raw_dir, "rel_raw_meta.json")))
    z = np.load(os.path.join(a.rel_raw_dir, "rel_raw.npz"))
    sub_idx, obj_idx, sc_all = z["sub_idx"], z["obj_idx"], z["scores"].astype(np.float32)
    dec = json.load(open(os.path.join(a.rel_raw_dir, "relations_dec_topk.json")))["frames"]
    vocab = meta["vocab"]
    vidx = {p: i for i, p in enumerate(vocab)}
    is_sp = meta["pred_is_spatial"]

    frames = pd["frames"]
    fmeta = meta["frames"]
    assert len(frames) == len(fmeta) == len(dec), "帧数不一致"

    idmodes = ["sel", "track"] if a.idmode == "both" else [a.idmode]
    filters = ["none", "ema", "belief"] if a.filter == "all" else [a.filter]
    os.makedirs(a.outdir, exist_ok=True)

    # ---- 预计算：两种身份模式下每帧的 det2track 与 live_tracks ----
    per_mode = {}
    for mode in idmodes:
        d2t_all, live_all, box_all = [], [], []
        if mode == "track":
            tr = Tracker(iou_thr=0.3, low_iou_thr=0.5, merge_iou=0.75,
                         max_age=8, min_hits=2, high_conf=0.25, q=1.0, r=10.0, stride=1)
            for f in frames:
                pls = f["players"]
                boxes = np.asarray([p["box"] for p in pls], np.float32).reshape(-1, 4)
                confs = np.asarray([p["conf"] for p in pls], np.float32)
                labs = [p.get("sel_id", f"p{i+1}") for i, p in enumerate(pls)]
                if len(boxes):
                    d2t = tr.observe(boxes, labs, confs)
                else:
                    d2t = {}
                d2t_all.append(d2t)
                box_all.append(boxes)
                tr.step(a.frame_w, a.frame_h)
                live_all.append({t.tid for t in tr.tracks})
        else:
            lmap: dict[str, int] = {}
            for f in frames:
                pls = f["players"]
                labs = [p.get("sel_id", f"p{i+1}") for i, p in enumerate(pls)]
                d2t = {}
                for i, l in enumerate(labs):
                    d2t[i] = lmap.setdefault(l, len(lmap))
                d2t_all.append(d2t)
                box_all.append(np.asarray([p["box"] for p in pls], np.float32).reshape(-1, 4))
                live_all.append({d2t[i] for i in range(len(labs))})
        per_mode[mode] = dict(d2t=d2t_all, live=live_all, box=box_all)

    # ---- 跟踪器质量（track 模式独有）----
    tracker_quality = None
    if "track" in per_mode:
        d2t_all = per_mode["track"]["d2t"]
        track_boxes: dict[int, list] = {}
        for i, d2t in enumerate(d2t_all):
            for d, tid in d2t.items():
                track_boxes.setdefault(tid, []).append(per_mode["track"]["box"][i][d])
        lens, cont_ok, cont_tot, jumps = [], 0, 0, 0
        for tid, bs in track_boxes.items():
            lens.append(len(bs))
            for k in range(len(bs) - 1):
                v = float(iou_matrix(bs[k][None, :], bs[k + 1][None, :])[0, 0])
                cont_tot += 1
                if v > 0.5:
                    cont_ok += 1
                elif v < 0.1:
                    jumps += 1
        tracker_quality = {
            "n_tracks": len(track_boxes),
            "track_len_p50": _pct(lens, .5), "track_len_p90": _pct(lens, .9),
            "track_len_max": max(lens) if lens else 0,
            "consecutive_box_iou_gt0.5": round(cont_ok / max(cont_tot, 1), 4),
            "consecutive_box_iou_lt0.1_jumps": jumps,
            "n_consecutive_pairs": cont_tot,
        }

    results = {}
    for mode in idmodes:
        d2t_all, live_all = per_mode[mode]["d2t"], per_mode[mode]["live"]
        box_all = per_mode[mode]["box"]
        for filt in filters:
            book = None
            if filt != "none":
                book = EdgeBook(score_ema=0.35, on_thr=0.45, off_thr=0.35,
                                on_frames=2, off_frames=6, fade=0.12, max_edges=8,
                                max_spatial=3, spatial_on_thr=0.42,
                                belief=(filt == "belief"), kf_q=0.05, kf_r=1.0, p_max=8.0)
            vis_hist = []          # 每帧可见边
            prev_phys = {}         # edge key -> (sub_box, obj_box) 上一可见帧
            key_reuse, key_stable = 0, 0
            out_frames = []
            for i in range(len(frames)):
                fi = fmeta[i]
                k0, k1 = fi["k0"], fi["k1"]
                labs = fi["labels"]
                d2t = d2t_all[i]
                if filt == "none":
                    tri = [Tri(d2t_inv(labs, t["s"], d2t), d2t_inv(labs, t["o"], d2t),
                               t["pred"], float(t["score"])) for t in dec[i]["triples"]]
                    vis = []
                    for t in tri:
                        if t.subject_idx is None or t.object_idx is None:
                            continue
                        s, o = d2t.get(t.subject_idx), d2t.get(t.object_idx)
                        if s is None or o is None or s == o:
                            continue
                        vis.append(Edge(s, o, t.predicate, t.score,
                                        bool(is_sp.get(t.predicate, False))))
                else:
                    tri = [Tri(d2t_inv(labs, t["s"], d2t), d2t_inv(labs, t["o"], d2t),
                               t["pred"], float(t["score"])) for t in dec[i]["triples"]]
                    raw = None
                    if filt == "belief" and k1 > k0:
                        kof = {}
                        for k in range(k0, k1):
                            kof.setdefault((int(sub_idx[k]), int(obj_idx[k])), k - k0)
                        raw = (sc_all[k0:k1], kof, vidx)
                    book.observe(tri, d2t, is_sp, raw)
                    book.step(live_all[i])
                    vis = book.visible()

                vis_hist.append(len(vis))
                # 身份完整性探针：同一 edge key 连续可见时，底层物理对是否还是同一对
                cur = {}
                for e in vis:
                    k = (e.sub, e.obj, e.pred)
                    ds, do = d2t_inv_rev(d2t, e.sub), d2t_inv_rev(d2t, e.obj)
                    cur[k] = (box_all[i][ds] if ds is not None and ds < len(box_all[i]) else None,
                              box_all[i][do] if do is not None and do < len(box_all[i]) else None)
                    if (k in prev_phys and prev_phys[k][0] is not None
                            and prev_phys[k][1] is not None
                            and cur[k][0] is not None and cur[k][1] is not None):
                        key_reuse += 1
                        if (iou_matrix(prev_phys[k][0][None, :], cur[k][0][None, :])[0, 0] > 0.5 and
                                iou_matrix(prev_phys[k][1][None, :], cur[k][1][None, :])[0, 0] > 0.5):
                            key_stable += 1
                prev_phys = cur
                if a.emit_relations:
                    out_frames.append({"idx": fi["idx"], "t": fi["t"], "n_player": fi["N"],
                                       "triples": [{"s": f"t{e.sub}", "o": f"t{e.obj}",
                                                    "pred": e.pred,
                                                    "score": round(max(e.shown, e.score), 6)}
                                                   for e in vis]})

            n_dist, ents, watch = [], [], []
            for fr in (out_frames if a.emit_relations else []):
                tr_ = fr["triples"]
                preds = [t["pred"] for t in tr_]
                n = len(preds) or 1
                n_dist.append(len(set(preds)))
                if len(set(preds)) > 1:
                    h = -sum((c / n) * math.log(c / n, 2)
                             for c in Counter(preds).values())
                    ents.append(h / math.log(len(set(preds)), 2))
                else:
                    ents.append(0.0)
                watch.append(sum(1 for p in preds if p == "watching") / n)

            key = f"{mode}_{filt}"
            res = {
                "idmode": mode, "filter": filt,
                "visible_per_frame_mean": round(float(np.mean(vis_hist)), 3),
                "visible_per_frame_p50": _pct(vis_hist, .5),
                "visible_per_frame_p90": _pct(vis_hist, .9),
                "visible_per_frame_max": max(vis_hist) if vis_hist else 0,
                "visible_total": int(sum(vis_hist)),
                "n_frames_with_edges": int(sum(1 for v in vis_hist if v > 0)),
                "identity_key_reuse_pairs": key_reuse,
                "identity_key_same_physical_pair": key_stable,
                "identity_consistency": (round(key_stable / key_reuse, 4) if key_reuse else None),
                "pred_hist": _hist_from(out_frames) if a.emit_relations else None,
                "n_distinct_pred_mean": (round(float(np.mean(n_dist)), 4) if n_dist else None),
                "entropy_norm_mean": (round(float(np.mean(ents)), 4) if ents else None),
                "watching_share_mean": (round(float(np.mean(watch)), 4) if watch else None),
                "n_edges_alive_at_end": len(book.edges) if book else None,
            }
            results[key] = res
            if a.emit_relations:
                with open(os.path.join(a.outdir, f"stab_{key}.json"), "w") as fp:
                    json.dump({"frames": out_frames, "vocab": vocab,
                               "meta": {"idmode": mode, "filter": filt,
                                        "score_is_pure": True}}, fp, ensure_ascii=False)
            print(f"[{key}] 可见边/帧 均值={res['visible_per_frame_mean']:.2f} "
                  f"p50={res['visible_per_frame_p50']} p90={res['visible_per_frame_p90']} "
                  f"总={res['visible_total']} 有边帧={res['n_frames_with_edges']} | "
                  f"key 复用 {key_reuse} 其中同物理对 {key_stable} "
                  f"一致率={res['identity_consistency']}")

    out = {"tracker_quality": tracker_quality, "configs": results,
           "official_defaults": {
               "Tracker": "iou_thr=0.3 low_iou_thr=0.5 merge_iou=0.75 max_age=8 min_hits=2 "
                          "high_conf=0.25 q=1.0 r=10.0",
               "EdgeBook": "score_ema=0.35 on_thr=0.45 off_thr=0.35 on_frames=2 off_frames=6 "
                           "fade=0.12 max_edges=8 max_spatial=3 spatial_on_thr=0.42 "
                           "belief=True kf_q=0.05 kf_r=1.0 p_max=8.0",
               "source": "RelateAnything/deploy/render_video.py CLI 默认值 + render_one() 接线",
               "note": "off_thr 实际取 min(0.38, on_thr-0.10)=0.35；belief 默认开启（--no_belief 才关）"},
           "env_note": "本窗口 10fps（dt=0.1s）；官方 reel 的 stride=2 在更高帧率下采样，"
                       "帧计数型参数（max_age/on_frames/off_frames）的绝对时长不同 ⇒ 需做敏感性对照"}
    with open(os.path.join(a.outdir, "b_stabilize.json"), "w") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    if tracker_quality:
        print(f"[tracker] {tracker_quality['n_tracks']} 条轨迹  "
              f"长度 p50={tracker_quality['track_len_p50']} p90={tracker_quality['track_len_p90']} "
              f"→ 连续帧框 IoU>0.5 占比 {tracker_quality['consecutive_box_iou_gt0.5']:.4f}  "
              f"跳变(<0.1) {tracker_quality['consecutive_box_iou_lt0.1_jumps']} 次")
    print(f"[out] {os.path.join(a.outdir, 'b_stabilize.json')}")
    return 0


def d2t_inv(labels, lab, d2t):
    """标签 → 检测序号（帧内）。"""
    try:
        return labels.index(lab)
    except ValueError:
        return None


def d2t_inv_rev(d2t, tid):
    for d, t in d2t.items():
        if t == tid:
            return d
    return None


def _pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def _hist_from(frames) -> dict:
    c = Counter()
    for fr in frames:
        for t in fr["triples"]:
            c[t["pred"]] += 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
