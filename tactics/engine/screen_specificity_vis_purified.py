#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screen_specificity_vis_purified.py —— V7/V8 命中视觉自证 + 量化证据(A4.62 净化后)
=================================================================================
读 screen_specificity_probe 的 V7_hits, 对每条命中:
  ① 渲染中段帧: 掩护者=红框, 通行者=绿框, 按队色描边 + 球 + 持球人标注;
  ② 量化证据(不靠看图也能判定真伪):
       - 两人躯干中位色到「段级两队色心(RGB)」的距离 → 若两心都远 ⇒ 非球员(裁判/观众残躯);
       - 两人的 on_frac / path_len(来自 team_assign_purified.json 净化统计) → 是否真实在场打球;
       - 持球人 H 是否真实(team 非 None)且是否与掩护者同队。
输出: action_work/validate/V7_purified/<seg>_<k>.png + stdout 证据表(verdict)。
用法: python engine/screen_specificity_vis_purified.py --probe JSON [--base DIR]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
import assign_team as at  # noqa: E402

BASES = [AW / "tactic_notes_batch_pilot_cf" / "segments",
         AW / "tactic_notes_batch" / "segments"]


def _find_seg(name):
    for b in BASES:
        sd = b / name
        if (sd / "ball_tracks_team.json").exists():
            return sd
    return None


def _torso_dist(seg_dir, fn, box, centers_rgb):
    """躯干中位色到两队色心的距离(min)。大 ⇒ 不像任何一队(裁判/观众残躯)。"""
    img = cv2.imread(str(seg_dir / "frames" / Path(fn).name))
    if img is None:
        img = cv2.imread(str(fn))
    if img is None:
        return None, None
    rgb = at.torso_median(img, box)  # BGR
    if rgb is None:
        return None, None
    rgb = rgb[::-1]  # BGR->RGB
    d0 = math.hypot(rgb[0] - centers_rgb[0][0], rgb[1] - centers_rgb[0][1], rgb[2] - centers_rgb[0][2])
    d1 = math.hypot(rgb[0] - centers_rgb[1][0], rgb[1] - centers_rgb[1][1], rgb[2] - centers_rgb[1][2])
    return min(d0, d1), (rgb[0], rgb[1], rgb[2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default=str(AW / "screen_specificity_probe_v7_purified.json"))
    ap.add_argument("--top", type=int, default=999, help="每段最多渲染几条")
    a = ap.parse_args()
    rows = json.load(open(a.probe, encoding="utf-8"))
    out_dir = AW / "validate" / "V7_purified"
    out_dir.mkdir(parents=True, exist_ok=True)
    team_col = {0: (40, 60, 230), 1: (230, 180, 40)}  # BGR: team0 红, team1 青

    for r in rows:
        seg = r["seg"]
        sd = _find_seg(seg)
        if sd is None:
            print(f"[skip] {seg} 无 ball_tracks_team.json")
            continue
        info = json.load(open(sd / "team_assign_purified.json", encoding="utf-8"))["info"]
        centers_rgb = info["centers_rgb"]
        detail = info["purify"]["detail"]
        raw = json.load(open(sd / "ball_tracks_team.json", encoding="utf-8"))
        file_by_frame = {fr["frame"]: fr.get("file") for fr in raw}
        print(f"\n=== {seg}  V7={r['V7']} V7_def={r['V7_def']} V8={r['V8']}  "
              f"队色={info['center_names']} 净化 {info['purify']['n_purified']}/{info['purify']['n_tids_total']} ===")
        for k, h in enumerate(r["V7_hits"][:a.top]):
            mid = (h["i0"] + h["i1"]) // 2
            fn = file_by_frame.get(mid)
            # 取中段帧两人框
            frec = next((fr for fr in raw if fr["frame"] == mid), None)
            box_s = box_t = None
            if frec:
                for p in frec.get("players", []):
                    if p["track_id"] == h["scr"]:
                        box_s = p["bbox"]
                    elif p["track_id"] == h["trav"]:
                        box_t = p["bbox"]
            dmin_s, rgb_s = (_torso_dist(sd, fn, box_s, centers_rgb) if box_s else (None, None))
            dmin_t, rgb_t = (_torso_dist(sd, fn, box_t, centers_rgb) if box_t else (None, None))
            ds = detail.get(str(h["scr"]), {})
            dt = detail.get(str(h["trav"]), {})
            # verdict: 先判同人碎片(IoU), 再判非球员(躯干远), 再判真实在场 → 候选真掩护
            iou = h.get("max_iou", 0.0)
            near_s = (dmin_s is not None and dmin_s < 90)
            near_t = (dmin_t is not None and dmin_t < 90)
            on_s = ds.get("gate_oncourt", False)
            on_t = dt.get("gate_oncourt", False)
            mv_s = ds.get("gate_motion", False)
            mv_t = dt.get("gate_motion", False)
            if iou >= 0.2:
                verdict = f"误报: 同人碎片(IoU={iou:.2f})"
            elif not (near_s and near_t):
                reasons = []
                if not near_s:
                    reasons.append(f"scr躯干远离两队色心(d={round(dmin_s) if dmin_s else '-'})")
                if not near_t:
                    reasons.append(f"trav躯干远离两队色心(d={round(dmin_t) if dmin_t else '-'})")
                verdict = "误报: 非球员(裁判/残躯) " + "; ".join(reasons)
            elif on_s and on_t and mv_s and mv_t:
                verdict = "候选真掩护✓(需老程目视; 队色white/white时异队不可信)"
            else:
                verdict = (f"误报: 非真实在场(scr on={ds.get('on_frac')} path={ds.get('path_len')}; "
                           f"trav on={dt.get('on_frac')} path={dt.get('path_len')})")
            # 渲染
            if fn:
                img = cv2.imread(str(sd / "frames" / Path(fn).name))
                if img is None:
                    img = cv2.imread(str(fn))
                if img is not None:
                    for tid, box, tcol in ((h["scr"], box_s, team_col.get(h["t_scr"], (0, 0, 255))),
                                           (h["trav"], box_t, team_col.get(h["t_trav"], (0, 200, 0)))):
                        if box:
                            cv2.rectangle(img, (int(box[0]), int(box[1])),
                                          (int(box[2]), int(box[3])), tcol, 3)
                    lab = f"{seg} V7#{k} scr={h['scr']}(t{h['t_scr']}) trav={h['trav']}(t{h['t_trav']}) H={h['H']} f{h['i0']}-{h['i1']}"
                    cv2.putText(img, lab[:80], (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (230, 230, 230), 2)
                    cv2.putText(img, verdict[:80], (12, img.shape[0] - 16),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    p = out_dir / f"{seg}_V7_{k:02d}.png"
                    cv2.imwrite(str(p), img)
            print(f"  #{k:02d} scr={h['scr']}(t{h['t_scr']},on={ds.get('on_frac')},path={ds.get('path_len')},"
                  f"d2c={round(dmin_s) if dmin_s else '-'}) "
                  f"trav={h['trav']}(t{h['t_trav']},on={dt.get('on_frac')},path={dt.get('path_len')},"
                  f"d2c={round(dmin_t) if dmin_t else '-'}) "
                  f"H={h['H']}({h.get('H_dist')}) iou={h['max_iou']} V8={h['V8']}  → {verdict}")


if __name__ == "__main__":
    main()
