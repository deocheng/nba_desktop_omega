#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_probe_floormask.py — 球场掩膜变体试验（找跨域可用的"球场区域"口径）。

背景：`geom_floor_poly.floor_mask` 只认「木色 H∈[6,32] + 紫涂装 H∈[118,168]」。
- TOR 主场：木色 + 紫涂装 ⇒ 基本可用（floor 45.4%）。
- HOU 主场：木色 + **黑色中圈带** + **红色禁区/边线带** ⇒ 掩膜只剩木色部分，
  floor 掉到 30.1%，画面左侧 1/3 的球场被判在场外；而且连通域在右上看台鼓包。

本脚本只做**候选口径的目视对比**，不写任何结论数字之外的判断。
变体：
  V1 现状            wood | purple
  V2 V1 + 暗色漆面    + (V<=DARK_V_MAX)  —— 黑漆中圈带
  V3 V2 + 红漆面      + 红色区间（H<=6 或 H>=170, S>=Smin, V>=Vmin）
  V4 V3 最大连通域 + 填洞 + 凸包（closing 后取 hull）

用法：
  python engine/_probe_floormask.py --clip sas_hou --frame f00001
  python engine/_probe_floormask.py --clip w1 --frame f00001
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import importlib.util
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
OUT = AW / "validate"


def _base():
    spec = importlib.util.spec_from_file_location("gfp", str(ROOT / "engine" / "geom_floor_poly.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def variants(img, scale=0.25):
    gfp = _base()
    small = cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)),
                       interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    Hh, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    wood = (Hh >= 6) & (Hh <= 32) & (S >= 60) & (V >= 55)
    pur = (Hh >= 118) & (Hh <= 168) & (S >= 45) & (V >= 45)
    red = ((Hh <= 6) | (Hh >= 170)) & (S >= 70) & (V >= 60)
    dark = (V <= 62)

    def clean(m, k1=7, k2=25):
        m = (m.astype(np.uint8)) * 255
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k1, k1))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        if n <= 1:
            return np.zeros_like(m)
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        comp = (lab == i).astype(np.uint8) * 255
        kk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k2, k2))
        comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, kk)
        comp = cv2.morphologyEx(comp, cv2.MORPH_OPEN, kk)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(comp, 8)
        if n > 1:
            i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            comp = (lab == i).astype(np.uint8) * 255
        return comp

    v1 = clean(wood | pur)
    v2 = clean(wood | pur | dark)
    v3raw = wood | pur | red
    v3 = clean(v3raw)
    # V4: V3 填洞 + 凸包
    cs, _ = cv2.findContours(v3, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    v4 = np.zeros_like(v3)
    if cs:
        c = max(cs, key=cv2.contourArea)
        hull = cv2.convexHull(c)
        cv2.drawContours(v4, [hull], -1, 255, -1)
    return {"V1 wood|pur": v1, "V2 +dark": v2, "V3 +red": v3, "V4 V3+凸包": v4}, scale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--frame", required=True)
    ap.add_argument("--stack", action="store_true", help="叠加四个面板竖直拼接")
    a = ap.parse_args()
    img = cv2.imread(str(AW / a.clip / a.frame))
    vs, sc = variants(img)
    OUT.mkdir(parents=True, exist_ok=True)
    tiles = []
    for name, m in vs.items():
        full = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        ov = img.copy()
        ov[full > 0] = (ov[full > 0] * 0.65 + np.array([40, 130, 40]) * 0.35).astype(np.uint8)
        cs, _ = cv2.findContours(full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cs:
            cv2.polylines(ov, [max(cs, key=cv2.contourArea).reshape(-1, 1, 2)], True,
                          (0, 255, 255), 2)
        cv2.putText(ov, f"{name}  area={full.mean() / 255:.1%}", (20, 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(ov, (900, 506), interpolation=cv2.INTER_AREA))
    if a.stack:
        rows = [np.hstack(tiles[0:2]), np.hstack(tiles[2:4])]
        grid = np.vstack(rows)
        o = OUT / f"floormask_variants_{a.clip}_{Path(a.frame).stem}.jpg"
        cv2.imwrite(str(o), grid, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"[out] {o}")
    else:
        for name, t in zip(vs.keys(), tiles):
            o = OUT / f"floormask_{name.split()[0]}_{a.clip}_{Path(a.frame).stem}.jpg"
            cv2.imwrite(str(o), t, [cv2.IMWRITE_JPEG_QUALITY, 90])
            print(f"[out] {o}")


if __name__ == "__main__":
    main()
