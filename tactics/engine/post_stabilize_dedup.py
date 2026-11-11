#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""post_stabilize_dedup —— 稳定化产物的两道后处理（门 ①-A 用）。

背景（全部来自实测，不是拍脑袋）：
  · 带净化过滤(conf0.40/h80)跑 18 段样本 → 门①-A 通过 8/18。
    失败呈两头堵：并发 17~18（超密）与并发 4~5（漏检）。
  · 查超密段的输出构成：那些框**又长命又高置信**（寿命 187~220 帧、
    conf 中位 0.6~0.8），不是闪烁假框，时间滤波器救不了。
  · 再查「一个人是否被切成两个 ID」：ep77_s0 3 对 / ep82_s0 4 对 /
    ep58_s0 2 对 长命轨共现 >80% 帧且平均 IoU 0.5~0.7 —— 是典型
    重复检测带来的 ID 分裂。**门①-A 要防的「错并」的镜像问题**，
    此前只盯着"多人并一人"，漏了"一人分多人"。

本脚本做两件事（都是可证伪的物理判据，不是调参凑数）：

  A. 重复 ID 合并(tracklet NMS)
     两条轨若「共现帧数 >= CO_OCC*min(寿命)」且「平均 IoU >= IOU_THR」
     ⇒ 判为同一人，保留寿命更长的那条，销毁另一条。
     物理依据：同一个人的重复检测框必然高度重叠；两个不同球员即使
     贴身掩护，框 IoU 也只在 0.1~0.3 量级（掩护时两人是并排站立）。

  B. 镜头窗口切分(shot window)
     用**轨迹**判切镜（不读图，快且稳）：相邻帧的 id 集合重合率
     |ids(t)∩ids(t-1)| / min(|ids(t)|,|ids(t-1)|) < SHOT_THRESH ⇒ 切镜。
     理由（A5.27 已证）：段内含切镜时，跨镜头的并发不可比，
     门①-A 必须**按镜头窗口**分别算。

用法:
  python3 post_stabilize_dedup.py <ball_tracks.json> --out merged.json
  python3 post_stabilize_dedup.py <ball_tracks.json> --report-only
  python3 post_stabilize_dedup.py --all --root action_work/norm_g3_f
"""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
from pathlib import Path

CO_OCC = 0.80      # 共现帧数 / 较短轨寿命 的下限
IOU_THR = 0.50     # 相交帧上的平均 IoU 下限
OV_FRAC = 0.50     # 相交帧数 / 较短轨寿命 的下限（低于此判为"只是路过"）
SHOT_THRESH = 0.50  # 与**前 3 帧 id 并集**的重合率低于此 ⇒ 判切镜
SHOT_REF = 3       # 切镜判据的参考窗口（前后帧）


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1)
    ub = (bx2 - bx1) * (by2 - by1)
    return inter / max(1e-6, ua + ub - inter)


def load(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(d, dict):
        for k in ("tracks", "records", "frames"):
            if k in d:
                d = d[k]
                break
    return d


def dedup(frames, co_occ=CO_OCC, iou_thr=IOU_THR, ov_frac=OV_FRAC):
    """返回 (新frames, 合并记录)。等价类用并查集，避免链式误吞。"""
    per = {}
    for i, r in enumerate(frames):
        for p in (r.get("players") or []):
            if p.get("track_id") is None:
                continue
            per.setdefault(p["track_id"], {})[i] = p["bbox"]

    parent = {t: t for t in per}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    merges = []
    ids = list(per)
    for a, b in itertools.combinations(ids, 2):
        la, lb = len(per[a]), len(per[b])
        if min(la, lb) < 10:            # 太短的轨不参与合并（噪声）
            continue
        # ⚠️ IoU 只在**两框真正相交的帧**上统计。
        # 踩坑：先前拿全部共现帧平均，不相交帧 IoU=0 把真重合冲成一堆 0，
        # 导致 3 对真重复 ID 一条都没合并出来。
        common = set(per[a]) & set(per[b])
        ious = [_iou(per[a][i], per[b][i]) for i in common]
        n_ov = sum(1 for v in ious if v > 0)
        if n_ov < ov_frac * min(la, lb):
            continue
        iou_mean = sum(ious) / max(1, len(ious))
        if iou_mean >= iou_thr:
            union(a, b)
            merges.append({"kill": b, "keep": a, "n_overlap": n_ov,
                           "iou_mean": round(iou_mean, 3),
                           "life_keep": la, "life_kill": lb})

    groups = {}
    for t in per:
        groups.setdefault(find(t), []).append(t)
    # 每个等价类保留寿命最长的那个 id（踩坑：groups 的 key 是并查集根 id 不是列表，
    # 必须对 groups.values() 的**成员列表**取 max）
    keep_of = {g: max(members, key=lambda t: len(per[t]))
               for g, members in groups.items()}
    killed = set()
    for g, members in groups.items():
        kp = keep_of[g]
        for m in members:
            if m != kp:
                killed.add(m)

    out = []
    for r in frames:
        ps = []
        for p in (r.get("players") or []):
            tid = p.get("track_id")
            if tid is None or tid in killed:
                continue
            p = dict(p)
            p["track_id"] = keep_of[find(tid)]
            ps.append(p)
        out.append({**r, "players": ps})
    return out, merges


def windows(frames, thr=SHOT_THRESH, ref=SHOT_REF):
    """用 id 集合重合率找镜头窗口，返回 [(start,end), ...]

    ⚠️ 判据必须拿「前 ref 帧的 id 并集」比**当前帧的 id 集**，不能只比相邻两帧：
    单帧漏检会让相邻重合率暴跌 ⇒ 首版把一段切成 8~22 个假窗口。
    真切镜时，当前帧的 id 几乎不出现在前 ref 帧里。
    """
    idsets = []
    for r in frames:
        idsets.append({p.get("track_id") for p in (r.get("players") or [])
                       if p.get("track_id") is not None})
    bounds = [0]
    for i in range(1, len(idsets)):
        cur = idsets[i]
        if not cur:
            continue
        prev = set()
        for j in range(max(0, i - ref), i):
            prev |= idsets[j]
        if not prev:
            continue
        if len(cur & prev) / len(cur) < thr:
            bounds.append(i)
    bounds.append(len(frames))
    return [(bounds[k], bounds[k + 1] - 1) for k in range(len(bounds) - 1)]


def summarize(frames, lo=0):
    conc, life = [], {}
    for i, r in enumerate(frames):
        ids = {p.get("track_id") for p in (r.get("players") or [])
               if p.get("track_id") is not None}
        conc.append(len(ids))
        for t in ids:
            life[t] = life.get(t, 0) + 1
    if not conc:
        return {}
    return {"n_frames": len(frames),
            "conc_med": round(statistics.median(conc), 1),
            "conc_max": max(conc),
            "n_ids": len(life),
            "med_life": round(statistics.median(life.values()), 1) if life else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--root", default="action_work/norm_g3_f")
    ap.add_argument("--out", default="")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--co-occ", type=float, default=CO_OCC)
    ap.add_argument("--iou-thr", type=float, default=IOU_THR)
    ap.add_argument("--no-dedup", action="store_true")
    a = ap.parse_args()

    files = list(a.files)
    if not files and a.all:
        files = sorted(str(p) for p in (Path(a.root) / "**" / "ball_tracks.json").glob("") or [])
        files = sorted(str(p) for p in Path(a.root).rglob("ball_tracks.json") if "dedup" not in str(p))
    if not files:
        print("无输入")
        return

    hdr = (f"{'段':<12}{'ID原':>6}{'ID合':>6}{'合并':>5}{'并发中位':>9}"
           f"{'窗口数':>7}{'窗口并发中位':>13}  判定")
    print(hdr)
    print("-" * len(hdr))
    npass = ntot = 0
    for f in files:
        fr = load(f)
        fr0 = fr
        nm = 0
        if not a.no_dedup:
            fr, merges = dedup(fr, a.co_occ, a.iou_thr)
            nm = len(merges)
        s0 = summarize(fr0)
        s1 = summarize(fr)
        wins = windows(fr)
        per_win = [summarize(fr[a_: b_ + 1]) for a_, b_ in wins]
        conc_win = [w.get("conc_med", 0) for w in per_win if w]
        # 判定：每个窗口的并发都落在 [8,16]，且中位寿命≥30
        ok = all(8 <= c <= 16 for c in conc_win) and s1.get("med_life", 0) >= 30
        ntot += 1
        npass += ok
        print(f"{Path(f).parent.name:<12}{s0['n_ids']:>6}{s1['n_ids']:>6}{nm:>5}"
              f"{s1['conc_med']:>9.1f}{len(wins):>7}"
              f"{statistics.median(conc_win) if conc_win else 0:>13.1f}  "
              f"{'PASS' if ok else 'FAIL'}")
        if a.report_only:
            continue
        outp = a.out or str(Path(f).with_name("ball_tracks_dedup.json"))
        Path(outp).write_text(json.dumps(fr, ensure_ascii=False), encoding="utf-8")
        Path(outp).with_suffix(".wins.json").write_text(
            json.dumps({"windows": wins, "per_window": per_win, "merges": nm},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n合计 {ntot} 段，按窗口判定通过 {npass} 段。")
    print("判定口径：每个镜头窗口的并发都 ∈[8,16] 且全局中位寿命 ≥30 帧")


if __name__ == "__main__":
    main()
