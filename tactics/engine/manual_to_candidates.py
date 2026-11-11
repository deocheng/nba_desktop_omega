#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manual_to_candidates.py — 把人工「补标球心」注入候选池并生成带来源标记的 bank。

为什么需要：候选池召回上限 71.2%（52 真有球帧 / 15 帧候选云无球）——头只能给已提出的候选打分，
没提出的球再准也救不回来。老程在原帧上点出的球心 = **候选池的真值位置**，注入后可：
  ① 训练：给头补上"小/模糊/边缘"正样本（f00205 类：检测器在该位置只给 conf1=0.054）；
  ② 评测：量化候选池召回，进而调 tile/NMS/阈值（真正攻天花板的路径）。

🔴 skew 防护（必须）：
  - 只注入 vis=clear/blur 的补标；**invisible（完全看不见球）绝不注入**，只进召回分母；
  - 注入框默认 26×26px（与检测器小目标尺度一致，真球实测 p25/med/p75=20/22/25、max 33）；
  - 评估时**必须分开报**（候选池内样本 pool vs 补标样本 manual）。

🔴🔴 conf 必须实测，禁止用 TP 中位数填充（2026-09-27 修正）：
  老版用 TP 候选中位数填 conf1/conf2（f00205 填了 0.587 / 0.208），但该真值球位**实测**
  conf1=0.054（中心距 15.1px 的检测框）、conf2=0.000。填充把「低 conf 也可能是球」这个
  **最需要被学习的信号抹掉了**，且会教头错误的特征-标签关系（conf2=0.208 是球 / 实测 0）。
  实测口径（与 validate_clips.py 逐位一致）：
    conf1 = tile 检测(640x384/ov96/thresh0.05, 不截断) 中，中心距补标点 <= --match-r 的最高分
    conf2 = 256px 裁切 -> 384^2 -> 与注入框 IoU>0.3 的最高分

用法:
  python engine/manual_to_candidates.py --clip sas_lal \
      --labels action_work/validate/human_label_f00205.json \
      --cands action_work/validate/sas_lal_cands.json \
      --bank  action_work/validate/sas_lal_label_bank_human.json \
      --out-cands action_work/validate/sas_lal_cands_manual.json \
      --out-bank  action_work/validate/sas_lal_label_bank_manual.json [--box 26]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
sys.path.insert(0, str(ROOT / "engine"))


def ctr(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def measure(frames_dir, items, box_size, match_r, dev):
    """对每个补标点实测 conf1/conf2。items: [(frame, cx, cy)] -> {key: dict}"""
    import cv2
    import probe_gt_detector as P
    import torch
    from transformers import AutoImageProcessor, AutoModelForObjectDetection

    dev = dev if (dev != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(str(P.RF))
    model = AutoModelForObjectDetection.from_pretrained(str(P.RF)).to(dev).eval()
    print(f"[measure] dev={dev}  match_r={match_r}px")

    res = {}
    cache = {}
    for fr, cx, cy, bx in items:
        if fr not in cache:
            img = cv2.imread(str(frames_dir / fr))
            assert img is not None, f"读不到 {frames_dir/fr}"
            rec, ntile = P.tiled_raw(proc, model, dev, img)
            cache[fr] = (img, rec, ntile)
        img, rec, ntile = cache[fr]

        pt = (cx, cy)
        cand = [r for r in rec if dist(ctr(r["bbox"]), pt) <= match_r]
        c1 = round(max([r["conf"] for r in cand], default=0.0), 3)
        best = max(cand, key=lambda r: r["conf"]) if cand else None
        c2, mapped, win = P.conf2_of(proc, model, dev, img, bx)
        c2_any = round(max([m["conf"] for m in mapped], default=0.0), 3)
        res[(fr, cx, cy)] = {
            "conf1": c1, "conf2": c2,
            "conf2_any_in_crop": c2_any,          # 诊断：裁切内最高分（不限 IoU）
            "matched_tile_det": ({"bbox": [round(v, 1) for v in best["bbox"]],
                                  "conf": round(best["conf"], 3),
                                  "ctr_dist": round(dist(ctr(best["bbox"]), pt), 1)}
                                 if best else None),
            "tile_raw_n": len(rec), "crop_window": list(win),
        }
        print(f"  {fr} ({cx},{cy})  实测 conf1={c1}  conf2={c2}  "
              f"(裁切内最高 {c2_any})  tile原始 {len(rec)} 个")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--cands", required=True)
    ap.add_argument("--bank", required=True)
    ap.add_argument("--out-cands", required=True)
    ap.add_argument("--out-bank", required=True)
    ap.add_argument("--box", type=float, default=26.0)
    ap.add_argument("--frames-dir", default=None)
    ap.add_argument("--match-r", type=float, default=20.0,
                    help="conf1 匹配半径：tile 检测中心距补标点 <= r 才计入（球直径量级）")
    ap.add_argument("--no-measure", action="store_true",
                    help="跳过实测（仅干跑结构校验；产出的 conf 为 0 且标注 conf_source=skipped）")
    ap.add_argument("--device", default="mps")
    a = ap.parse_args()

    cands = json.loads(Path(a.cands).read_text())[a.clip]
    labels = json.loads(Path(a.labels).read_text())
    bank = json.loads(Path(a.bank).read_text())

    # 填充值仅作诊断参考（不再作为 conf1/conf2 入模）
    tp1 = [r["conf1"] for r in bank["labels"] if r["label"] == "TP" and r.get("conf1") is not None]
    tp2 = [r["conf2"] for r in bank["labels"] if r["label"] == "TP" and r.get("conf2") is not None]
    fill1 = float(np.median(tp1)) if tp1 else 0.0
    fill2 = float(np.median(tp2)) if tp2 else 0.0
    print(f"TP 中位数（仅诊断，不再入模）: conf1={fill1:.3f} conf2={fill2:.3f}  (n_TP={len(tp1)})")

    items, meta_rows = [], []
    for r in labels:
        if r.get("invisible"):
            continue
        m = r.get("manual")
        if not m:
            continue
        cx, cy = float(m["cx"]), float(m["cy"])
        h = a.box / 2.0
        items.append((r["frame"], cx, cy, [cx - h, cy - h, cx + h, cy + h]))
        meta_rows.append((r["frame"], m.get("vis")))

    meas = {}
    if items and not a.no_measure:
        fdir = Path(a.frames_dir) if a.frames_dir else ROOT / "action_work" / a.clip
        meas = measure(fdir, items, a.box, a.match_r, a.device)

    n_man = n_inv = 0
    new_bank = [dict(r, source=r.get("source", "pool")) for r in bank["labels"]]
    for r in labels:
        fr = r["frame"]
        if r.get("invisible"):
            n_inv += 1
            continue                      # 真漏检：只计数，不注入
        m = r.get("manual")
        if not m:
            continue
        cx, cy = float(m["cx"]), float(m["cy"])
        h = a.box / 2.0
        bbox = [cx - h, cy - h, cx + h, cy + h]
        mm = meas.get((fr, cx, cy), {})
        c1 = mm.get("conf1", 0.0)
        c2 = mm.get("conf2", 0.0)
        cs = cands.setdefault(fr, [])
        idx = len(cs)
        cs.append({"bbox": bbox, "conf1": c1, "conf2": c2, "source": "manual"})
        new_bank.append({"clip": a.clip, "frame": fr, "idx": idx, "bbox": bbox,
                         "conf1": c1, "conf2": c2,
                         "conf1_tpmedian": round(fill1, 3), "conf2_tpmedian": round(fill2, 3),
                         "label": "TP", "source": "manual", "vis": m.get("vis"),
                         "measure": mm,
                         "conf_source": "measured" if mm else ("skipped" if a.no_measure else "missing")})
        n_man += 1

    out = {"meta": {**bank.get("meta", {}),
                    "manual_injected": n_man, "invisible_frames": n_inv,
                    "conf_tpmedian_diagnostic": {"conf1": fill1, "conf2": fill2},
                    "conf_rule": ("conf1 = tile检测(640x384/ov96/thr0.05,不截断) 中心距<=%.0fpx 最高分；"
                                  "conf2 = 256px裁切->384^2->IoU>0.3 最高分" % a.match_r),
                    "box_size": a.box,
                    "conf_is_measured": not a.no_measure,
                    "note": ("补标样本 source=manual，conf 为实测值；评估必须分开报（pool vs manual）。"
                             "老版(TP中位数填充)已废弃：会把『低conf也可能是球』这一关键信号抹掉")},
           "labels": new_bank}
    Path(a.out_cands).write_text(json.dumps({a.clip: cands}))
    Path(a.out_bank).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[out] {a.out_cands}  补标注入 {n_man} 个候选 · 真漏检(不注入) {n_inv} 帧")
    print(f"[out] {a.out_bank}  样本 {len(new_bank)}（pool={len(bank['labels'])} / manual={n_man}）")


if __name__ == "__main__":
    main()
