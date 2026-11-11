#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rel_temporal_stab.py — 时序稳定层（直接针对 R3：「单帧关系无法区分正在做掩护 vs 恰好站位重叠」）。

为什么必须分通道、必须在连续帧上做
----------------------------------
- `defending` / `hitting` **不在官方 35 词内**，只能由 `full_vocabulary=True`（19,103 词）产出；
  官方 35 通道产出 `holding/carrying/using`。⇒ 两条通道**互斥**，分两次推理。
- 稳定性要求「同一关键边连续 N 帧成立」⇒ 必须有**连续帧**。
  实测：`sas_*` 全片只有 14–44 帧有球、**最长连续段 6 帧** ⇒ 无法承载 N≥3 的稳定性检验；
  而 **w1–w4 球覆盖 433/435 帧**（连续段 433）⇒ 时序层的试验台只能是 w1–w4。
  本脚本若不指定 --clip 会自动选**最长的连续球段**。

稳定化算子（N-of-M 持久化）
---------------------------
关键边 = (sub_track_id, obj, pred)。逐帧取该边分数 `s_t`（缺帧记 -inf）。
`确认(edge, t) = 在最近 M 个**有分**帧中，s ≥ thr 的帧数 ≥ N`。
  - M=N（默认）= 严格连续；`--gap-tol g` 允许中间缺 g 帧。
对 `holding/carrying/using → BALL` 另有一条**持球者归属**稳定化（同一 sub 连续 N 帧）。

三个读数（R3 的裁决）
--------------------
1. `flicker`  = 逐帧 top-1 边变化率（无/有稳定化对比）——稳定化是否真的压住了抖动。
2. `n_events` = 确认事件数 vs N —— 稳定化把多少"瞬时巧合"消掉。
3. **R3 核心** = 对确认后的 defending 边，「持球人出现在边某端」的比例 **vs 随机球员基线**。
   若稳定后仍与随机持平 ⇒ **时序聚合无法让 defending 携带对位信息**（诚实结论，不得粉饰）。

用法
    python engine/rel_temporal_stab.py --clip w1 --poss-suffix _poss_tile --len 120 --stride 1
    python engine/rel_temporal_stab.py --auto --len 100            # 自动挑最长连续段
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path

from common.nba_paths import tactics_data_file, workspace_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
REPO = ROOT / "RelateAnything"
sys.path.insert(0, str(REPO))
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")

import numpy as np  # noqa: E402
import torch  # noqa: E402
from relsgg.api import RelateAnything  # noqa: E402
from relsgg.vocabulary import DEFAULT_PREDICATES  # noqa: E402

DEF_MD = str(workspace_file("action_work/models/relsgg-vits16plus"))
BALL35 = {"holding", "carrying", "using"}
BALLN = {"hitting"}
DEFP = {"defending", "defending against", "tackling"}
N_SWEEP = (1, 2, 3, 4, 5, 6, 8, 10)
IOU_MIN = 0.02      # 「框相交」候选集的门槛（IoU>0 即几何相交，取 0.02 排除擦边）
BOOT = 1000         # 几何判别 bootstrap 次数


def _load_rv():
    spec = importlib.util.spec_from_file_location(
        "rv", str(ROOT / "engine" / "rel_handler_validate.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def longest_run(clip, suffix, gap=1):
    p = AW / f"{clip}{suffix}" / "ball_tracks.json"
    if not p.exists():
        return None
    recs = json.loads(p.read_text())
    idx = [i for i, f in enumerate(recs) if f.get("ball")]
    if not idx:
        return None
    runs, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= gap:
            cur.append(i)
        else:
            runs.append(cur)
            cur = [i]
    runs.append(cur)
    runs.sort(key=len, reverse=True)
    return recs, runs[0]


def load_plane_keep(path):
    """读 item 4 的清洗结果 -> {(clip, file): set(kept track_id)}。"""
    if not path or not Path(path).exists():
        return None
    d = json.loads(Path(path).read_text())
    out = {}
    for clip, v in d.items():
        for r in v["rows"]:
            if r["keep"]:
                out.setdefault((clip, r["file"]), set()).add(int(r["track_id"]))
    return out


def run_clip(clip, suffix, start, length, stride, ra35, raN, rv, keep_map=None):
    recs = json.loads((AW / f"{clip}{suffix}" / "ball_tracks.json").read_text())
    sel = [i for i in range(start, min(len(recs), start + length), stride)]
    frames = []
    n_box_raw = n_box_kept = 0
    for i in sel:
        f = recs[i]
        if not f.get("ball"):
            continue
        pls = [{"track_id": int(pl["track_id"]),
                "bbox": [float(v) for v in pl["bbox"]], "conf": float(pl["conf"])}
               for pl in f["players"]]
        n_box_raw += len(pls)
        if keep_map is not None:
            ks = keep_map.get((clip, f["file"]))
            if ks is not None:
                pls = [p for p in pls if p["track_id"] in ks]
        n_box_kept += len(pls)
        frames.append({
            "idx": i, "file": f["file"], "players": pls,
            "ball": [float(v) for v in f["ball"]["bbox"]],
            "poss": None if f.get("poss_track_id") is None else int(f["poss_track_id"]),
        })
    print(f"[{clip}] 选中连续球帧 {len(frames)}（起始 {start}，stride={stride}）"
          f" 球员框 {n_box_raw} → {n_box_kept}"
          f"（{'item4 清洗后' if keep_map is not None else '未清洗'}）")

    out = []
    for k, f in enumerate(frames):
        boxes = [[pl["bbox"] for pl in f["players"]], [f["ball"]]]
        boxes = [b for grp in boxes for b in grp]
        labels = [f"t{pl['track_id']}" for pl in f["players"]] + ["BALL"]
        confs = [pl["conf"] for pl in f["players"]] + [1.0]
        tri35 = rv.forward(ra35, str(AW / clip / f["file"]), boxes, labels, confs)
        triN = rv.forward(raN, str(AW / clip / f["file"]), boxes, labels, confs)
        edges = []
        for (s, a, b, p) in tri35:
            edges.append({"score": s, "sub": a, "obj": b, "pred": p, "ch": "35"})
        for (s, a, b, p) in triN:
            edges.append({"score": s, "sub": a, "obj": b, "pred": p, "ch": "native"})
        out.append({"idx": f["idx"], "file": f["file"], "poss": f["poss"],
                    "players": f["players"], "n_players": len(f["players"]),
                    "ball": f["ball"], "edges": edges})
        if k % 20 == 0:
            print(f"   {k}/{len(frames)}  {f['file']}  edges={len(edges)}")
    return out


def edge_stream(frames, ch, preds, obj):
    """{(sub,obj,pred) -> {frame_pos: score}}"""
    st = {}
    for t, f in enumerate(frames):
        for e in f["edges"]:
            if e["ch"] != ch or e["pred"] not in preds or e["obj"] != obj:
                continue
            k = (e["sub"], e["obj"], e["pred"])
            if st.get(k, {}).get(t, -1) < e["score"]:
                st.setdefault(k, {})[t] = e["score"]
    return st


def confirm(st, t, thr, N, M, gap_tol=0):
    """在最近 M(+gap_tol) 个**有分**帧中，分数 ≥ thr 的帧数 ≥ N。

    ⚠️ 修正（A4.21）：原实现 `range(t, t - M - 1, -1)` 实际扫 **M+1 帧**（off-by-one），
    于是 M=N=1 退化成「最近 2 帧里有 1 帧成立」= 隐含 1 帧容差，
    「严格连续 N 帧」名不副实、且在任意 N 上都放宽了一帧。现改为窗口恰为 M+gap_tol 帧。
    """
    win = M + gap_tol
    hit = 0
    for j in range(t, max(-1, t - win), -1):
        if j not in st:
            continue
        if st[j] >= thr:
            hit += 1
    return hit >= N


def _iou(b1, b2):
    x1 = max(b1[0], b2[0]); y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2]); y2 = min(b1[3], b2[3])
    iw, ih = x2 - x1, y2 - y1
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    a1 = max(0.0, b1[2] - b1[0]) * max(0.0, b1[3] - b1[1])
    a2 = max(0.0, b2[2] - b2[0]) * max(0.0, b2[3] - b2[1])
    un = a1 + a2 - inter
    return float(inter / un) if un > 0 else 0.0


def top1_per_frame(frames, thr_map):
    """逐帧 top-1（sub,pred,obj）用于抖动率。"""
    out = []
    for f in frames:
        best = None
        for e in f["edges"]:
            if e["obj"] != "BALL":
                continue
            if e["score"] < thr_map.get(e["ch"], 0.0):
                continue
            if best is None or e["score"] > best["score"]:
                best = e
        out.append(None if best is None else (best["sub"], best["pred"], best["obj"]))
    return out


def flicker_rate(seq):
    n = len(seq) - 1
    if n <= 0:
        return 0.0
    ch = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    return ch / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--poss-suffix", default="_poss_tile")
    ap.add_argument("--len", type=int, default=120)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--thr35", type=float, default=0.05, help="官方35 通道工作点（A4.20 实测）")
    ap.add_argument("--thrn", type=float, default=0.20, help="native 通道工作点（A4.20 实测）")
    ap.add_argument("--gap-tol", type=int, default=0)
    ap.add_argument("--model-dir", default=DEF_MD)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--plane-filter", default=None,
                    help="item 4 的 player_plane_filter.json；给了就只喂**清洗后**的球员框")
    ap.add_argument("--dump", default=str(AW / "validate" / "rel_temporal_stab.json"))
    ap.add_argument("--vis-dir", default=None, help="给出目录则渲染 R3-b 目视取证图")
    ap.add_argument("--vis-n", type=int, default=3, help="目视取证用哪个 N 的确认集合")
    ap.add_argument("--vis-per", type=int, default=8, help="每组取多少格")
    a = ap.parse_args()

    clips = ["w1", "w2", "w3", "w4"] if a.auto else [a.clip or "w1"]
    planning = []
    for c in clips:
        r = longest_run(c, a.poss_suffix)
        if r is None:
            print(f"[skip] {c}: 无 ball_tracks 或有球帧=0")
            continue
        recs, run = r
        planning.append((c, run[0], min(len(run), a.len), len(run)))
        print(f"[plan] {c}: 最长连续球段 {len(run)} 帧（起点 idx={run[0]}），取 {min(len(run), a.len)} 帧")
    if not planning:
        raise SystemExit("[终止] 没有任何可用连续段")

    dev = a.device
    if dev == "mps" and not torch.backends.mps.is_available():
        dev = "cpu"
    t0 = time.perf_counter()
    ra35 = RelateAnything.from_checkpoint(os.path.join(a.model_dir, "model.pth"), device=dev)
    ra35.set_vocabulary(DEFAULT_PREDICATES)
    raN = RelateAnything.from_checkpoint(os.path.join(a.model_dir, "model.pth"),
                                         device=dev, full_vocabulary=True)
    print(f"[模型] {time.perf_counter()-t0:.1f}s device={dev}  35={len(ra35.predicates)} "
          f"native={len(raN.predicates)}")

    rv = _load_rv()
    keep_map = load_plane_keep(a.plane_filter)
    if keep_map is not None:
        print(f"[item4] 载入清洗表：{len(keep_map)} (clip,frame) 键")
    result = {"thr35": a.thr35, "thrn": a.thrn, "stride": a.stride, "gap_tol": a.gap_tol,
              "plane_filter": a.plane_filter, "clips": {}}
    for c, start, ln, tot in planning:
        frames = run_clip(c, a.poss_suffix, start, ln, a.stride, ra35, raN, rv, keep_map)
        if len(frames) < 8:
            print(f"[skip] {c}: 有效帧仅 {len(frames)}")
            continue

        thr_map = {"35": a.thr35, "native": a.thrn}
        # ① 抖动率（无稳定化）
        seq_raw = top1_per_frame(frames, thr_map)
        fl_raw = flicker_rate(seq_raw)

        # 边流
        st_hold = edge_stream(frames, "35", BALL35, "BALL")
        st_hit = edge_stream(frames, "native", BALLN, "BALL")
        st_def = edge_stream(frames, "native", DEFP, "BALL")     # 占位（defending 的 obj 不是 BALL）
        st_def_all = {}
        for t, f in enumerate(frames):
            for e in f["edges"]:
                if e["ch"] == "native" and e["pred"] in DEFP:
                    k = (e["sub"], e["obj"], e["pred"])
                    if st_def_all.get(k, {}).get(t, -1) < e["score"]:
                        st_def_all.setdefault(k, {})[t] = e["score"]

        sweep = []
        for N in N_SWEEP:
            if N > len(frames):
                continue
            cc = {}
            for ch, st, thr in (("35", st_hold, a.thr35), ("native_hit", st_hit, a.thrn),
                                ("native_def", st_def_all, a.thrn)):
                ev = []
                for k, ts in st.items():
                    first = None
                    cnt = 0
                    for t in range(len(frames)):
                        if confirm(ts, t, thr, N, N, a.gap_tol):
                            cnt += 1
                            if first is None:
                                first = t
                    if cnt:
                        ev.append({"edge": list(k), "n_frames": cnt, "first": first,
                                   "max_score": round(max(ts.values()), 4)})
                cc[ch] = {"n_events": len(ev), "events": sorted(ev, key=lambda z: -z["n_frames"])[:40]}

            # 稳定化后的 top-1（仅统计通过确认的边）
            conf_ids = set()
            for k, ts in st_hold.items():
                if any(confirm(ts, t, a.thr35, N, N, a.gap_tol) for t in range(len(frames))):
                    conf_ids.add(k)
            for k, ts in st_hit.items():
                if any(confirm(ts, t, a.thrn, N, N, a.gap_tol) for t in range(len(frames))):
                    conf_ids.add(k)
            seq_stab = []
            for f in frames:
                best = None
                for e in f["edges"]:
                    if e["obj"] != "BALL":
                        continue
                    if (e["sub"], e["obj"], e["pred"]) not in conf_ids:
                        continue
                    if e["score"] < thr_map.get(e["ch"], 0.0):
                        continue
                    if best is None or e["score"] > best["score"]:
                        best = e
                seq_stab.append(None if best is None else (best["sub"], best["pred"], best["obj"]))
            sweep.append({"N": N, "flicker": round(flicker_rate(seq_stab), 4),
                          "n_conf_edges": len(conf_ids),
                          "events": {k: v["n_events"] for k, v in cc.items()},
                          "_cc": cc})

        # ③ R3-a：确认后的 defending 边，端点含持球人的比例 vs 精确随机基线
        #    ⚠️ 修正（A4.21）：旧实现基线 = 1/npl，但观测量是「poss 出现在边的**任一端**」
        #       ⇒ 精确零假设概率 = k/npl（k = 该边在本帧内的互异人端点数，通常 2）。
        #       用 1/npl 会把基线**砍半**，从而凭空造出「显著优于随机」。现改为精确值 + 置换检验。
        r3 = []
        poss_frames = [t for t, f in enumerate(frames) if f["poss"] is not None]
        labels_of = [sorted(set("t" + str(p["track_id"]) for p in f["players"])) for f in frames]
        n_perm = 400
        rng = np.random.default_rng(20260926)
        for N in N_SWEEP:
            if N > len(frames):
                continue
            visited = set()
            evals = []
            for k, ts in st_def_all.items():
                for t in range(len(frames)):
                    if t not in ts or ts[t] < a.thrn:
                        continue
                    if not confirm(ts, t, a.thrn, N, N, a.gap_tol):
                        continue
                    if (k, t) in visited:
                        continue
                    visited.add((k, t))
                    evals.append((t, k))
            conf_edges = {k for (_t, k) in evals}
            if not evals:
                r3.append({"N": N, "n_def_events": 0})
                continue
            # 只保留「持球者本人仍在本帧球员列表里」的评估点：
            # item4 若把持球者框清洗掉了，抽样空间里就没有正确答案，留着会系统性压低观测率。
            usable, n_skip = [], 0
            for (t, k) in evals:
                poss = frames[t]["poss"]
                if poss is None:
                    continue
                if f"t{poss}" not in labels_of[t]:
                    n_skip += 1
                    continue
                sub, obj, _p = k
                k_ends = len({e for e in (sub, obj) if e in labels_of[t]})
                if k_ends == 0:
                    continue
                usable.append((t, sub, obj, k_ends, len(labels_of[t])))
            if not usable:
                r3.append({"N": N, "n_def_events": len(conf_edges), "n_eval": 0,
                           "n_skip_poss_filtered": n_skip})
                continue
            LUT = {t: labels_of[t] for (t, _s, _o, _k, _n) in usable}
            labs = [LUT[t] for (t, _s, _o, _k, _n) in usable]
            n_arr = np.array([len(l) for l in labs], dtype=np.int64)
            r_sub = np.array([l.index(s) if s in l else -1
                              for l, (_t, s, _o, _k, _n) in zip(labs, usable)])
            r_obj = np.array([l.index(o) if o in l else -1
                              for l, (_t, _s, o, _k, _n) in zip(labs, usable)])
            obs_hits = np.array([1.0 if (s == f"t{frames[t]['poss']}"
                                         or o == f"t{frames[t]['poss']}") else 0.0
                                 for (t, s, o, _k, _n) in usable])
            obs = float(obs_hits.mean())
            an = float(np.mean([kk / nn for (_t, _s, _o, kk, nn) in usable]))
            nulls = np.empty(n_perm)
            for pi in range(n_perm):
                idx = rng.integers(0, n_arr)
                nulls[pi] = float(np.mean((idx == r_sub) | (idx == r_obj)))
            p_one = (int((nulls >= obs).sum()) + 1) / (n_perm + 1)

            # ⚠️ 构造性混淆的定量处方（A4.21）：
            #    本项目的 `poss_track_id` = **几何最近球的人**。于是「poss 出现在边的端点」
            #    在**定义上**等价于「端点在图像上离球最近」——纯几何就能刷到 1.0
            #    （ trivial predictor: 恒定选最近球者 ⇒ 该指标 = 1.0，语义含量 = 0）。
            #    ⇒ 必须量化模型端点本身的**空间近球偏差**，才能判断上面的富集是不是纯空间假象。
            d_end, d_rnd = [], []
            for bi2 in range(len(usable)):
                t, sub, obj = usable[bi2][0], usable[bi2][1], usable[bi2][2]
                bx, by = (frames[t]["ball"][0] + frames[t]["ball"][2]) / 2, \
                         (frames[t]["ball"][1] + frames[t]["ball"][3]) / 2
                lab_of = {p["track_id"]: p["bbox"] for p in frames[t]["players"]}
                hs = {tid: max(1.0, b[3] - b[1]) for tid, b in lab_of.items()}
                dc = {tid: math.hypot((b[0] + b[2]) / 2 - bx, (b[1] + b[3]) / 2 - by)
                      for tid, b in lab_of.items()}
                for e in (sub, obj):
                    tid = int(e[1:]) if e.startswith("t") and e[1:].isdigit() else None
                    if tid is None or tid not in dc:
                        continue
                    d_end.append(dc[tid] / hs[tid])          # 以身高归一化 ⇒ 跨深度可比
                if lab_of:
                    pool = sorted(dc, key=lambda z: dc[z])
                    pick = int(rng.integers(0, len(pool)))
                    d_rnd.append(dc[pool[pick]] / hs[pool[pick]])
            rec = {"N": N, "n_def_events": len(conf_edges),
                   "n_eval": len(usable),
                   "n_skip_poss_filtered": n_skip,
                   "holder_in_edge_rate": round(obs, 4),
                   "random_baseline_exact": round(an, 4),
                   "random_baseline_perm_mean": round(float(nulls.mean()), 4),
                   "random_baseline_perm_sd": round(float(nulls.std(ddof=1)), 4),
                   "p_one_sided": round(float(p_one), 4)}
            if d_end and d_rnd:
                rec["spatial_confound"] = {
                    "end_dist_to_ball_over_h_med": round(float(np.median(d_end)), 4),
                    "random_player_same_frames_med": round(float(np.median(d_rnd)), 4),
                    "near_ball_ratio_end": round(float(np.mean([d < 1.5 for d in d_end])), 4),
                    "near_ball_ratio_random": round(float(np.mean([d < 1.5 for d in d_rnd])), 4),
                    "trivial_predictor_ceiling": 1.0,
                    "note": "poss 参照=几何最近球 ⇒ 恒定选最近球者的平凡预测器即可拿 1.0；"
                            "该指标对语义无区分力，富集须由空间偏差解释。"}
            r3.append(rec)

        # ⑤ R3-b：几何可判别性——时序确认是否真的滤掉了「透视巧合」？
        #    「恰好站位重叠」的物理签名 = 图像上框相交 但**足点 y 差很多**（不同深度 ⇒ 场上其实离得远）。
        #    ⚠️ 修正（A4.21）：上一版把「确认组」取成 pair 在**所有相交帧**的观测，
        #       而横轴比的是"是否被 N 帧确认"，两者不对齐 ⇒ 数字不可解释。
        #       现改为只在**关系真正触发且通过确认的帧**上取样。
        #    ⚠️ IoU 混淆：关系模型天然偏好框重叠大的 pair，而 IoU 与 rel_dy 相关
        #       ⇒ 必须**按 IoU 分层**后再比，否则比的是 IoU 不是时序。
        cand = []            # [{t, pair, iou, rel_dy, rel_dc, conf}]
        for t, f in enumerate(frames):
            pls = f["players"]
            for i in range(len(pls)):
                for j in range(i + 1, len(pls)):
                    A, B = pls[i], pls[j]
                    iou = _iou(A["bbox"], B["bbox"])
                    if iou < IOU_MIN:
                        continue
                    fa, fb = A["bbox"][3], B["bbox"][3]
                    ha = max(1.0, fa - A["bbox"][1])
                    hb = max(1.0, fb - B["bbox"][1])
                    href = max(ha, hb)
                    ca = ((A["bbox"][0] + A["bbox"][2]) / 2, (A["bbox"][1] + A["bbox"][3]) / 2)
                    cb = ((B["bbox"][0] + B["bbox"][2]) / 2, (B["bbox"][1] + B["bbox"][3]) / 2)
                    dc = math.hypot(ca[0] - cb[0], ca[1] - cb[1])
                    cand.append({"t": t, "pair": frozenset((A["track_id"], B["track_id"])),
                                 "iou": iou,
                                 "rel_dy": abs(fa - fb) / href,
                                 "rel_dc": dc / href})
        TACTN = DEFP | BALLN            # 战术相关的 native 谓词
        geo = []
        IOU_BINS = ((0.02, 0.10), (0.10, 0.30), (0.30, 1.01))
        for N in N_SWEEP:
            if N > len(frames):
                continue
            # (帧, pair) → 该帧该 pair 有战术边 通过 N 帧确认
            conf_at = set()
            for kk, ts in st_def_all.items():
                sub, obj, pred = kk
                if pred not in TACTN:
                    continue
                a_, b_ = sub[1:], obj[1:]
                if not a_.isdigit() or not b_.isdigit():
                    continue
                pr = frozenset((int(a_), int(b_)))
                for t in range(len(frames)):
                    if t not in ts or ts[t] < a.thrn:
                        continue
                    if confirm(ts, t, a.thrn, N, N, a.gap_tol):
                        conf_at.add((t, pr))
            if not conf_at:
                geo.append({"N": N, "n_conf_pairs": 0})
                continue
            for _cc_item in cand:                     # ⚠️ 变量名不能再用 c（会覆盖外层 clip 名）
                _cc_item["conf"] = (_cc_item["t"], _cc_item["pair"]) in conf_at
            ent = {"N": N, "n_conf_obs_frames": len(conf_at)}
            for (lo, hi) in IOU_BINS:
                sub_ = [_z for _z in cand if lo <= _z["iou"] < hi]
                cy = [c["rel_dy"] for c in sub_ if c["conf"]]
                uy = [c["rel_dy"] for c in sub_ if not c["conf"]]
                if len(cy) < 5 or len(uy) < 5:
                    ent[f"iou[{lo},{hi})"] = {"n_conf": len(cy), "n_unconf": len(uy),
                                              "note": "样本不足"}
                    continue
                bs = np.empty(BOOT)
                for bi in range(BOOT):
                    s1 = rng.choice(cy, size=len(cy), replace=True)
                    s2 = rng.choice(uy, size=len(uy), replace=True)
                    bs[bi] = np.median(s1) - np.median(s2)
                try:
                    from scipy.stats import mannwhitneyu
                    p_dy = float(mannwhitneyu(cy, uy, alternative="less").pvalue)
                except Exception:                                       # pragma: no cover
                    p_dy = None
                ent[f"iou[{lo},{hi})"] = {
                    "n_conf": len(cy), "n_unconf": len(uy),
                    "med_rel_dy_conf": round(float(np.median(cy)), 4),
                    "med_rel_dy_unconf": round(float(np.median(uy)), 4),
                    "med_dy_diff": round(float(np.median(cy) - np.median(uy)), 4),
                    "ci95_dy_diff": [round(float(np.percentile(bs, 2.5)), 4),
                                     round(float(np.percentile(bs, 97.5)), 4)],
                    "p_dy_less": round(p_dy, 6) if p_dy is not None else None}
            geo.append(ent)

        if a.vis_dir:
            _render_r3b(a.vis_dir, c, frames, cand, conf_at, N=a.vis_n, per=a.vis_per)

        # ④ holding→BALL 命中率（稳定前后）
        def hold_hit(N):
            h = tt = 0
            for t, f in enumerate(frames):
                if f["poss"] is None:
                    continue
                best = None
                for k, ts in st_hold.items():
                    if N == 1 or confirm(ts, t, a.thr35, N, N, a.gap_tol):
                        if t in ts and ts[t] >= a.thr35 and (best is None or ts[t] > best[1]):
                            best = (k[0], ts[t])
                tt += 1
                if best and best[0] == f"t{f['poss']}":
                    h += 1
            return (round(h / tt, 4) if tt else None), tt

        hr = {str(N): hold_hit(N) for N in (1, 2, 3, 5, 8)}

        for s in sweep:
            s.pop("_cc", None)
        res = {"clip": c, "start": start, "n_frames": len(frames),
               "n_poss_frames": len(poss_frames),
               "flicker_raw": round(fl_raw, 4),
               "sweep": sweep, "r3_defending": r3, "r3_geometry": geo,
               "holding_to_poss": {k: {"rate": v[0], "n": v[1]} for k, v in hr.items()}}
        result["clips"][c] = res
        print(f"\n=== {c} 帧={len(frames)} 持球帧={len(poss_frames)} ===")
        print(f"  抖动率 原始={res['flicker_raw']}")
        for s in sweep:
            print(f"  N={s['N']:<2} 抖动={s['flicker']:<7} 确认边={s['n_conf_edges']:<4} 事件={s['events']}")
        print(f"  holding→持球者命中率: {res['holding_to_poss']}")
        print("  R3-a defending 端点含持球人（vs 精确随机基线 / 置换检验）:")
        for r in r3:
            if not r.get("n_eval"):
                print(f"    N={r['N']:<2} 无可评估事件 {r}")
                continue
            print(f"    N={r['N']:<2} 事件={r['n_def_events']:<4} 评估点={r['n_eval']:<5}"
                  f" 命中率={r['holder_in_edge_rate']:<7}"
                  f" 基线(精确)={r['random_baseline_exact']:<7}"
                  f" 基线(置换)={r['random_baseline_perm_mean']}±{r['random_baseline_perm_sd']}"
                  f"  p(单侧)={r['p_one_sided']}"
                  f"  [持球者被清洗 {r['n_skip_poss_filtered']}]")
            sc = r.get("spatial_confound")
            if sc:
                print(f"         ↳ 空间混淆：端点离球距离/身高 中位={sc['end_dist_to_ball_over_h_med']}"
                      f" vs 同帧随机球员={sc['random_player_same_frames_med']}"
                      f" | 近球(<1.5H)占比 {sc['near_ball_ratio_end']} vs {sc['near_ball_ratio_random']}")
        print("  R3-b 几何判别（框相交候选中，仅取**关系真正触发**的帧；按 IoU 分层去混淆）:")
        print("         rel_dy = |Δ足点y| / 身高；越小=越同深度=越可能是真实共处；"
              "越大=越可能是透视混叠的「恰好重叠」")
        for g in geo:
            if g.get("n_conf_obs_frames") is None:
                print(f"    N={g['N']:<2} 无可确认帧 {g}")
                continue
            print(f"    N={g['N']:<2} 确认帧-pair={g['n_conf_obs_frames']}")
            for key in [k for k in g if k.startswith("iou[")]:
                v = g[key]
                if v.get("med_rel_dy_conf") is None:
                    print(f"        {key}  样本不足 {v}")
                    continue
                print(f"        {key} n={v['n_conf']}/{v['n_unconf']}  "
                      f"med_rel_dy 确认={v['med_rel_dy_conf']:<7} 未确认={v['med_rel_dy_unconf']:<7}"
                      f" 差={v['med_dy_diff']:<8} CI95={v['ci95_dy_diff']}  p(less)={v['p_dy_less']}")

    Path(a.dump).write_text(json.dumps(result, ensure_ascii=False))
    print(f"\n[out] {a.dump}")


def _render_r3b(out_dir, clip, frames, cand, conf_at, N=3, per=8):
    """R3-b 目视取证：确认组/未确认组各取一组样本，画出裁剪图。
    必须看清楚「确认组里 rel_dy 大的那些」到底是**透视混叠**还是**真实互动**，
    否则整个 R3-b 的符号解释都站不住。"""
    import cv2
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    for (lo, hi) in ((0.02, 0.10), (0.10, 0.30)):
        pool = [_z for _z in cand if lo <= _z["iou"] < hi]
        conf_ = sorted([_z for _z in pool if _z["conf"]], key=lambda z: -z["rel_dy"])[:per]
        uncon = sorted([_z for _z in pool if not _z["conf"]], key=lambda z: z["rel_dy"])[:per]
        cells, meta = [], []
        for tag, group, col in (("CONF", conf_, (0, 255, 0)), ("UNCONF", uncon, (0, 0, 255))):
            for z in group:
                fr = frames[z["t"]]
                pm = {int(p["track_id"]): p["bbox"] for p in fr["players"]}
                ids = sorted(z["pair"])
                if len(ids) != 2 or any(i not in pm for i in ids):
                    continue
                img = cv2.imread(str(AW / clip / fr["file"]))
                if img is None:
                    continue
                b1, b2 = pm[ids[0]], pm[ids[1]]
                x1 = int(min(b1[0], b2[0]) - 60); y1 = int(min(b1[1], b2[1]) - 60)
                x2 = int(max(b1[2], b2[2]) + 60); y2 = int(max(b1[3], b2[3]) + 60)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
                crop = img[y1:y2, x1:x2].copy()
                oh, ow = crop.shape[:2]
                for i in ids:
                    b = pm[i]
                    cv2.rectangle(crop, (int(b[0]) - x1, int(b[1]) - y1),
                                  (int(b[2]) - x1, int(b[3]) - y1), col, 2)
                    cv2.putText(crop, f"t{i}", (int(b[0]) - x1, int(b[1]) - y1 - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
                # 足点横线：直观显示两人是否同深度
                for i in ids:
                    b = pm[i]
                    yy = int(b[3]) - y1
                    cv2.line(crop, (0, yy), (ow, yy), (255, 255, 0), 2)
                side = 320
                sc = side / max(oh, ow)
                crop = cv2.resize(crop, (max(1, int(ow * sc)), max(1, int(oh * sc))))
                pad = np.full((side - crop.shape[0], crop.shape[1], 3), 40, np.uint8) \
                    if crop.shape[0] < side else np.zeros((0, crop.shape[1], 3), np.uint8)
                cell = np.vstack([crop, pad]) if pad.shape[0] else crop
                pad2 = np.full((side, max(0, side - cell.shape[1]), 3), 40, np.uint8)
                cell = np.hstack([cell, pad2]) if pad2.shape[1] else cell
                cv2.putText(cell, f"{tag} dy={z['rel_dy']:.2f} iou={z['iou']:.2f}",
                            (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
                cells.append(cell)
                meta.append({"tag": tag, "frame": fr["file"], "pair": ids,
                             "rel_dy": round(z["rel_dy"], 3), "iou": round(z["iou"], 3)})
        if not cells:
            continue
        cols = 4
        while len(cells) % cols:
            cells.append(np.full((320, 320, 3), 40, np.uint8))
        rows = [np.hstack(cells[r:r + cols]) for r in range(0, len(cells), cols)]
        sheet = np.vstack(rows)
        fp = d / f"r3b_{clip}_N{N}_iou{int(lo*100):02d}.jpg"
        cv2.imwrite(str(fp), sheet)
        (d / f"r3b_{clip}_N{N}_iou{int(lo*100):02d}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1))
        print(f"  [vis] {fp}  ({len(meta)} 格)")


if __name__ == "__main__":
    main()
