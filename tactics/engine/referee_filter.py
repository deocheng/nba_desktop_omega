#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""裁判过滤（只打 tag，不删除）—— 下游自行决定是否剔除。

来源：老程第二轮补充 `filter_referees()`。落地时对 3 处做了修正：

  F1 🔴 位置启发式 **默认关闭**。原稿 `near_sideline = (tx<80 or tx>920) and (ty>100)`
      会把**底角三分射手**标成裁判 —— 底角三分在半场战术板上恰恰位于边缘区
      (tx 靠近 0 或 1000，ty 已进入场内)。这是可证伪的误删，且会直接破坏
      「底角三分」这一高频战术的统计。⇒ use_position=False 默认。
      另：原稿还要求 `score < 0.6`，但低检测置信度更可能是**被遮挡的球员**
      而非裁判，用置信度当裁判判据方向反了。⇒ 该条件一并关闭。

  F2 颜色取**躯干 ROI** 而非整框。整框均值会把木地板/观众席背景混进球衣色，
      实测 HOU 主场（黑+红球衣）+ 木地板 的跨域场景下整框均值完全不可分。
      取框高 40%–75%、框宽 20%–80% 的躯干区。

  F3 色域阈值外置为参数（禁手写常量），且默认 require_both_signals=True：
      单靠颜色或单靠位置都不标裁判，必须两路同时命中 —— 宁可漏标不可误删。

  已封口事实（R4，2026-09-26）：
      "③ 裁判站在球场平面上（rel≈0）⇒ 透视判据原理上无法区分，只能靠球衣/姿态另做。"
      ⇒ 本模块只是候选标注器，不是判据。任何"裁判已剔除"的声明都必须附目视复核。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))

# F3：外置色域（HSV）。裁判常见黑/深灰条纹衫；但深色球衣队会撞车，故需双信号。
REF_COLOR_DEFAULT = {"v_max": 80.0, "s_max": 60.0}
# 躯干 ROI（相对框的比例）—— F2
TORSO = {"y0": 0.40, "y1": 0.75, "x0": 0.20, "x1": 0.80}


def _torso_crop(img, box):
    H, W = img.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(W - 1, x2), min(H - 1, y2)
    w, h = x2 - x1, y2 - y1
    if w <= 2 or h <= 2:
        return None
    sy0, sy1 = y1 + int(TORSO["y0"] * h), y1 + int(TORSO["y1"] * h)
    sx0, sx1 = x1 + int(TORSO["x0"] * w), x1 + int(TORSO["x1"] * w)
    c = img[sy0:sy1, sx0:sx1]
    return c if c.size else None


def referee_color_score(img, box, ref_color=None):
    """返回 (is_ref_color, v_mean, s_mean)。躯干 ROI 的 HSV 均值。"""
    rc = ref_color or REF_COLOR_DEFAULT
    if img is None or box is None:
        return False, None, None
    crop = _torso_crop(img, box)
    if crop is None:
        return False, None, None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    v_mean = float(np.mean(hsv[:, :, 2]))
    s_mean = float(np.mean(hsv[:, :, 1]))
    return bool(v_mean < rc["v_max"] and s_mean < rc["s_max"]), v_mean, s_mean


def filter_referees(players, img=None, use_position=False, use_color=True,
                    require_both_signals=True, ref_color=None,
                    board_edge_px=80.0, board_width=1000.0):
    """给疑似裁判打 role="referee" 标签，**不删除**。

    players: list[dict]，需含 box/bbox（或 x1,y1,x2,y2）与可选 tactical_x/y。
    返回 (players, report)。
    """
    tagged, color_only, pos_only, both = [], [], [], []
    for p in players:
        box = p.get("box") or p.get("bbox")
        if box is None and all(k in p for k in ("x1", "y1", "x2", "y2")):
            box = [p["x1"], p["y1"], p["x2"], p["y2"]]

        hit_color = False
        if use_color:
            hit_color, v_m, s_m = referee_color_score(img, box, ref_color)
            p["ref_color_v"], p["ref_color_s"] = v_m, s_m
        hit_pos = False
        if use_position:
            tx, ty = float(p.get("tactical_x", 0)), float(p.get("tactical_y", 0))
            hit_pos = (tx < board_edge_px or tx > board_width - board_edge_px) and ty > 100

        if require_both_signals and (use_position and use_color):
            mark = hit_color and hit_pos
            if hit_color and hit_pos:
                both.append(p.get("track_id", p.get("id")))
            elif hit_color:
                color_only.append(p.get("track_id", p.get("id")))
            elif hit_pos:
                pos_only.append(p.get("track_id", p.get("id")))
        else:
            mark = (hit_color and use_color) or (hit_pos and use_position)
            if hit_color:
                color_only.append(p.get("track_id", p.get("id")))
            if hit_pos:
                pos_only.append(p.get("track_id", p.get("id")))

        if mark:
            p["role"] = "referee"
            tagged.append(p.get("track_id", p.get("id")))
    report = {
        "tagged_referee": tagged,
        "color_signal_only": color_only,
        "position_signal_only": pos_only,
        "both_signals": both,
        "use_position": use_position,
        "use_color": use_color,
        "require_both_signals": require_both_signals,
        "note": "只打 tag 不删除；位置启发式默认关闭(会误删底角三分射手, F1)；"
                "裁判在透视判据上原理不可分(R4)，本结果必须配合目视复核",
    }
    return players, report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True)
    ap.add_argument("--det", required=True, help="检测 json: list of {box/x1..y2, tactical_x, tactical_y}")
    ap.add_argument("--use-position", action="store_true")
    ap.add_argument("--single-signal", action="store_true")
    a = ap.parse_args()

    img = cv2.imread(a.frame)
    dets = json.loads(Path(a.det).read_text(encoding="utf-8"))
    out, rep = filter_referees(dets, img, use_position=a.use_position,
                               require_both_signals=not a.single_signal)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
