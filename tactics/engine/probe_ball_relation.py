#!/usr/bin/env python3
"""关系层退化诊断 + 球区域注入实验（RelateAnything 第 5 层）。

背景（2026-09-23 里程碑 03）：
    在 435 帧片段上跑 12 帧验证子集，得到 72 条三元组，其中
    `watching` 66 条（91.7%）、`beside` 6 条 —— **输出退化，无区分力**。
    本脚本回答两个问题，都要求可测量的数字，不靠印象：

    Q1 **退化是不是因为混进了场外人员？**
       对比三种名单口径下的谓词分布：
         A) 全部框（原口径，13.4 人/帧，含观众/替补席/裁判）
         B) 只保留脚点落在球场范围内 + 框高 ≥ H_min 的（≈ 场上球员）
         C) 只保留面积最大的 Top-K（最靠近镜头的）
       若 B/C 下 `watching` 占比明显下降 ⇒ 是名单污染；若仍是压倒性 `watching`
       ⇒ 是模型在「人—人」对上的固有退化，与名单无关。

    Q2 **把球的框作为额外 region 注入，模型能否产出 `holding` / `carrying`？**
       这是关系层唯一有实用价值的输出方向（球在谁手里）。
       只用**已目视确认的真球**帧（`ball_truth.json`），把球框加进 box 列表，
       统计「与球相关的三元组里 holding/carrying 的占比」。
       多个球员框时，看球框最近的球员是否就是 holding 的主体。

用法：
  probe_ball_relation.py <players.json> <frames.json> <truth.json> <out.json>
                         [--max-frames 20] [--h-min 60] [--topk 6]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import collections
import json
import os
import sys

from common.nba_paths import tactics_data_file, workspace_file

REPO = str(tactics_data_file("RelateAnything"))
sys.path.insert(0, REPO)

from PIL import Image  # noqa: E402
from relsgg.api import RelateAnything  # noqa: E402
from relsgg.vocabulary import DEFAULT_PREDICATES  # noqa: E402

DEF_MD = str(workspace_file("action_work/models/relsgg-vits16plus"))

# 球场范围（1920×1080 下，地板光学范围的保守内缩框）——用于 Q1 口径 B
COURT_ROI = (0.03, 0.28, 0.99, 0.98)   # 归一化 x1,y1,x2,y2


def in_court(foot, w=1920, h=1080):
    x1, y1, x2, y2 = COURT_ROI
    return x1 * w <= foot[0] <= x2 * w and y1 * h <= foot[1] <= y2 * h


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _median(xs):
    xs = sorted(xs)
    return round(xs[len(xs) // 2], 1) if xs else None


def _safe_rate(flags):
    flags = list(flags)
    return (sum(1 for f in flags if f) / len(flags)) if flags else float("nan")


def box_dist(pt, box):
    """点到矩形的最短距离（0 = 点在框内）。

    球在空中的高度 y≈170–600，而球员脚点 y≈600–900，用「点到脚点」会把
    所有帧的距离都推到 100px 以上、失去区分力（首版就踩了这个坑）。
    正确的「谁离球最近」应该用点到球员框的距离。
    """
    x1, y1, x2, y2 = box
    dx = max(x1 - pt[0], 0.0, pt[0] - x2)
    dy = max(y1 - pt[1], 0.0, pt[1] - y2)
    return (dx * dx + dy * dy) ** 0.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("players_json")
    ap.add_argument("frames_json")
    ap.add_argument("truth_json")
    ap.add_argument("out_json")
    ap.add_argument("--max-frames", type=int, default=20)
    ap.add_argument("--h-min", type=float, default=60.0)
    ap.add_argument("--topk", type=int, default=6)
    ap.add_argument("--ball-pad", type=float, default=24.0)
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    pl = json.load(open(a.players_json))
    src = {f["idx"]: f["path"] for f in json.load(open(a.frames_json))}
    truth = json.load(open(a.truth_json))
    tp = truth["verified_ball_timeline"]

    # 已目视确认的真球点。两个来源（都在 ball_truth.json 内有明文出处）：
    #  ① verified_balls_6x.real 是 **1-based 序号**，指向同目录 tight_candidates.json
    #     的第 N 条候选（该文件是 list，每条含 cx/cy/idx/t/path）。
    #  ② rising_segment.points 是 [t, x, y] 三元组列表（6.3x 确认的上升段）。
    cand_path = os.path.join(os.path.dirname(os.path.abspath(a.truth_json)),
                             "tight_candidates.json")
    cands = json.load(open(cand_path))
    src_pts = []
    for n in truth["method"]["verified_balls_6x"]["real"]:
        c = cands[n - 1]
        src_pts.append((c["t"], c["cx"], c["cy"], f"6.3x#{n}"))
    for t, x, y in tp["rising_segment"]["points"]:
        src_pts.append((t, x, y, "rising"))

    # 去重 + 落到 10fps 网格（t = 204.5 + idx/10）
    seen, uniq = set(), []
    for t, x, y, tag in src_pts:
        idx = round((t - 204.5) * 10)
        if 0 <= idx <= 434 and idx not in seen:
            seen.add(idx)
            uniq.append({"idx": idx, "t": round(204.5 + idx / 10.0, 1),
                         "xy": [round(x, 1), round(y, 1)], "src": tag})
    uniq.sort(key=lambda z: z["idx"])
    print(f"[truth] 可用目视真球帧 {len(uniq)}  "
          f"(idx: {' '.join(str(z['idx']) for z in uniq)})")

    ra = RelateAnything.from_checkpoint(os.path.join(DEF_MD, "model.pth"), device=a.device)
    ra.set_vocabulary(DEFAULT_PREDICATES)
    print(f"[model] 载入完成，谓词 {len(DEFAULT_PREDICATES)} 条")

    by_idx = {f["idx"]: f for f in pl["frames"]}
    rep = {"Q1_scope_effect": {}, "Q2_ball_holding": {}}

    # ---------- Q1：三种名单口径 ----------
    probe_idxs = [z["idx"] for z in uniq][:a.max_frames]
    # 补几个无真球的帧做对照
    probe_idxs += [0, 199, 434]
    probe_idxs = sorted(set(probe_idxs))
    scope_stats = {"A_all": collections.Counter(), "B_oncourt": collections.Counter(),
                   "C_topk6": collections.Counter()}
    scope_nbox = {"A_all": [], "B_oncourt": [], "C_topk6": []}

    for idx in probe_idxs:
        f = by_idx.get(idx)
        if not f or not f["players"]:
            continue
        img = Image.open(src[idx]).convert("RGB")
        allp = f["players"]
        onc = [p for p in allp if in_court(p["foot"]) and p["h"] >= a.h_min]
        top = sorted(allp, key=lambda p: -p["h"])[:6]
        for key, sel in (("A_all", allp), ("B_oncourt", onc), ("C_topk6", top)):
            if len(sel) < 2:
                continue
            tri = ra.predict(img, [p["box"] for p in sel],
                             box_labels=[p["sel_id"] for p in sel],
                             box_scores=[p["conf"] for p in sel],
                             topk=a.topk, max_boxes=len(sel))
            scope_stats[key].update(t.predicate for t in tri)
            scope_nbox[key].append(len(sel))

    for key in scope_stats:
        c = scope_stats[key]
        tot = sum(c.values()) or 1
        rep["Q1_scope_effect"][key] = {
            "n_box_per_frame": round(sum(scope_nbox[key]) / max(len(scope_nbox[key]), 1), 2),
            "n_triples": sum(c.values()),
            "top_predicates": c.most_common(6),
            "watching_share": round(c.get("watching", 0) / tot, 4),
            "distinct_predicates": len(c),
        }
        print(f"[Q1:{key}] 框/帧={rep['Q1_scope_effect'][key]['n_box_per_frame']} "
              f"三元组={sum(c.values())} 不同谓词={len(c)} "
              f"watching占比={rep['Q1_scope_effect'][key]['watching_share']:.3f}")

    # ---------- Q2：球框注入 + 随机位置对照 ----------
    # 🔴 对照组是必需的：`holding` 若在「随机位置的同样大小方框」上也照样触发，
    #    那就只说明模型对任意小框都倾向于输出 holding，与球无关。
    #    随机点采样在**球场 ROI 内**，并保留与真球相同的垂直分量分布（y ∈ [0.1,0.75]·H），
    #    以匹配「球高度通常高于脚点」的实际条件。
    hold_preds = {"holding", "carrying", "wearing", "riding", "using"}
    import random  # noqa: E402
    random.seed(20260924)
    N_CTRL = 6
    rows = []
    ctrl_pred = collections.Counter()
    ctrl_hold_frames = 0
    ctrl_frames = 0
    ctrl_inbox, ctrl_inbox_hit = [], []
    for z in uniq[:a.max_frames]:
        idx = z["idx"]
        f = by_idx.get(idx)
        if not f or not f["players"]:
            continue
        img = Image.open(src[idx]).convert("RGB")
        sel = [p for p in f["players"] if in_court(p["foot"]) and p["h"] >= a.h_min]
        if len(sel) < 2:
            sel = sorted(f["players"], key=lambda p: -p["h"])[:6]
        bx, by = z["xy"]
        npad = a.ball_pad
        boxes = [p["box"] for p in sel] + [[bx - npad, by - npad, bx + npad, by + npad]]
        labels = [p["sel_id"] for p in sel] + ["ball"]
        scores = [p["conf"] for p in sel] + [1.0]
        tri = ra.predict(img, boxes, box_labels=labels, box_scores=scores,
                         topk=a.topk, max_boxes=len(boxes))
        btri = [t for t in tri if "ball" in (t.subject_label, t.object_label)]
        # 点到框的距离，最近者 = 几何意义上的持球人
        ranked = sorted(sel, key=lambda p: box_dist(z["xy"], p["box"]))
        near = ranked[0]
        holds = [t for t in btri if t.predicate in hold_preds]
        subj_ok = [t for t in holds if t.subject_label == near["sel_id"]]

        # 随机位置对照
        x1r, y1r, x2r, y2r = COURT_ROI
        ctrl_this = []
        for _ in range(N_CTRL):
            rx = random.uniform(x1r, x2r) * 1920
            ry = random.uniform(0.10, 0.75) * 1080
            cboxes = [p["box"] for p in sel] + [[rx - npad, ry - npad, rx + npad, ry + npad]]
            ctri = ra.predict(img, cboxes, box_labels=labels, box_scores=scores,
                              topk=a.topk, max_boxes=len(cboxes))
            cp = [t.predicate for t in ctri if "ball" in (t.subject_label, t.object_label)]
            # 🔴 关键分层变量：随机点是否落在某个球员框内。
            #    首轮对照发现「随机位置 59.1% > 真球位置 40.9%」，必须查清原因——
            #    若对照也只是被「点在框内」驱动，则 `holding` 只是几何包含的复述。
            c_in = any(box_dist((rx, ry), p["box"]) == 0.0 for p in sel)
            ctrl_inbox.append(c_in)
            ctrl_inbox_hit.append(any(p in hold_preds for p in cp))
            ctrl_this.extend(cp)
            ctrl_pred.update(cp)
            if any(p in hold_preds for p in cp):
                ctrl_hold_frames += 1
            ctrl_frames += 1

        rows.append({
            "idx": idx, "t": z["t"], "ball_xy": z["xy"], "n_box": len(sel),
            "nearest_player": near["sel_id"],
            "nearest_box_dist_px": round(box_dist(z["xy"], near["box"]), 1),
            "nearest_in_box": box_dist(z["xy"], near["box"]) == 0.0,
            "ball_triples": [{"s": t.subject_label, "o": t.object_label,
                              "pred": t.predicate, "score": round(t.score, 4)}
                             for t in btri],
            "ball_predicates": [t.predicate for t in btri],
            "n_hold": len(holds),
            "hold_subject_is_nearest": len(subj_ok) > 0,
            "ctrl_predicates": ctrl_this,
            "ctrl_n_hold": sum(1 for p in ctrl_this if p in hold_preds),
        })

    n_hold_frames = sum(1 for r in rows if r["n_hold"] > 0)
    n_near_ok = sum(1 for r in rows if r["hold_subject_is_nearest"])
    n_inbox = sum(1 for r in rows if r["nearest_in_box"])
    hold_counter = collections.Counter(p for r in rows for p in r["ball_predicates"])
    ctrl63 = collections.Counter(p for r in rows for p in r["ctrl_predicates"])
    rep["Q2_ball_holding"] = {
        "n_frames": len(rows),
        "n_frames_with_ball_triple": sum(1 for r in rows if r["ball_triples"]),
        "n_frames_with_leading_verb": n_hold_frames,
        "leading_verb_rate": round(n_hold_frames / max(len(rows), 1), 4),
        "hold_subject_is_nearest_frames": n_near_ok,
        "hold_subject_is_nearest_rate": round(n_near_ok / max(n_hold_frames, 1), 4),
        "ball_triples_empty_frames": sum(1 for r in rows if not r["ball_triples"]),
        "nearest_in_box_frames": n_inbox,
        "nearest_box_dist_px_median": _median([r["nearest_box_dist_px"] for r in rows]),
        "ball_predicate_distribution": hold_counter.most_common(),
        "hold_predicate_set": sorted(hold_preds),
        "control": {
            "design": f"每帧把球框平移到 {N_CTRL} 个随机位置（球场 ROI 内，y∈[0.10,0.75]·H，"
                      f"边长与真球框相同），同样跑一次预测",
            "n_ctrl_predictions": ctrl_frames,
            "ctrl_hold_frames": ctrl_hold_frames,
            "ctrl_hold_rate": round(ctrl_hold_frames / max(ctrl_frames, 1), 4),
            "ctrl_predicate_distribution": ctrl63.most_common(),
            "ctrl_hold_rate_per_call": round(
                sum(1 for r in rows for _ in range(r["ctrl_n_hold"])) / max(ctrl_frames, 1), 4),
            "ctrl_stratified_by_inside_player_box": {
                "about": "把对照按『随机点是否落在某个球员框内』分层——用于判定 "
                         "`holding` 是语义判断还是几何包含的复述",
                "inside_box": {
                    "n": sum(1 for v in ctrl_inbox if v),
                    "hold_rate": round(_safe_rate(
                        [h for v, h in zip(ctrl_inbox, ctrl_inbox_hit) if v]), 4),
                },
                "outside_box": {
                    "n": sum(1 for v in ctrl_inbox if not v),
                    "hold_rate": round(_safe_rate(
                        [h for v, h in zip(ctrl_inbox, ctrl_inbox_hit) if not v]), 4),
                },
            },
        },
        "true_stratified_by_inside_player_box": {
            "inside_box": {
                "n": sum(1 for r in rows if r["nearest_in_box"]),
                "hold_rate": round(_safe_rate(
                    [r["n_hold"] > 0 for r in rows if r["nearest_in_box"]]), 4),
            },
            "outside_box": {
                "n": sum(1 for r in rows if not r["nearest_in_box"]),
                "hold_rate": round(_safe_rate(
                    [r["n_hold"] > 0 for r in rows if not r["nearest_in_box"]]), 4),
            },
        },
        "rows": rows,
    }
    q2 = rep["Q2_ball_holding"]
    print(f"[Q2] 帧 {len(rows)}  有球三元组 {q2['n_frames_with_ball_triple']}  "
          f"命中持球类动词 {n_hold_frames} → 真位 {q2['leading_verb_rate']:.3f}  "
          f"| 对照随机位 {q2['control']['ctrl_hold_rate']:.3f}"
          f"（{ctrl_hold_frames}/{ctrl_frames}）")
    print(f"[Q2] 主体=几何最近球员 {n_near_ok}/{n_hold_frames} = "
          f"{q2['hold_subject_is_nearest_rate']:.3f}  |  球落在球员框内 {n_inbox}/{len(rows)}"
          f"  |  最近框距中位 {q2['nearest_box_dist_px_median']}px")
    print(f"[Q2] 球相关谓词 {hold_counter.most_common()}")
    print(f"[Q2] 对照谓词 {ctrl63.most_common()}")

    os.makedirs(os.path.dirname(a.out_json), exist_ok=True)
    with open(a.out_json, "w") as fp:
        json.dump(rep, fp, ensure_ascii=False, indent=1)
    print(f"[out] {a.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
