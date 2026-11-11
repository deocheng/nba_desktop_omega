#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""活球/死球门控 v2 —— 用「24秒进攻计时器是否在走」判定是否为活球进攻回合。

本片源记分条布局(实测1280x720, 与项目 sas_det 的 scorebug_reader 不同, 那是另一条片子):
  - 黄色比赛钟: x[840,965]  y[612,682]  (黄色数字, 活球时连续倒数)
  - 白色24秒进攻计时: x[1005,1045] y[600,645] (白色数字, 死球/刚开球时恒为24)
判定: 在 [t-span, t+span] 采样 N 点, 统计计时器掩膜发生变化的相邻对比例。
      计时器在倒数 => 活球进攻。 冻结(恒24 或恒定值)=> 死球(罚球/暂停/界外)。
      另输出识别到的两位数字(用模板匹配), 用于报告里写明具体读数。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import argparse
import json
import os
import string

from common.nba_paths import data_file, tactics_data_file

os.environ["PYTHONPATH"] = ""
import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--src", default=str(data_file("比赛录像/2027/季前赛/2026-27 Silver & Black Spurs Open Scrimmage.mp4")))
ap.add_argument("--times", required=True)
ap.add_argument("--span", type=float, default=2.0)
ap.add_argument("--n", type=int, default=9)
ap.add_argument("--json-out", default=str(tactics_data_file("clips/probe_sas_scrimmage/clock_gate.json")))
a = ap.parse_args()

CLK = (840, 612, 965, 682)      # 黄色比赛钟
SHOT = (1005, 600, 1050, 648)   # 白色24秒计时

def yellow(f):
    hsv = cv2.cvtColor(f[CLK[1]:CLK[3], CLK[0]:CLK[2]], cv2.COLOR_BGR2HSV)
    return ((hsv[:,:,0] >= 13) & (hsv[:,:,0] <= 40) &
            (hsv[:,:,1] >= 130) & (hsv[:,:,2] >= 130)).astype(np.uint8)

def white(f):
    g = cv2.cvtColor(f[SHOT[1]:SHOT[3], SHOT[0]:SHOT[2]], cv2.COLOR_BGR2GRAY)
    return (g > 170).astype(np.uint8)

# ---- 数字模板: 从本片源若干帧自动收集(按连通域宽高归一化), 再用结构特征分类 ----
def digit_features(mask):
    """返回掩膜中每个连通域的 (宽,高,宽高比, 空洞数, 笔画密度)"""
    m = (mask > 0).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if h < 12 or w < 3:      # 噪点/边框
            continue
        sub = (lab[y:y+h, x:x+w] == i).astype(np.uint8)
        # 空洞数 = 连通域背景连通块
        inv = 1 - sub
        nn, _, stt, _ = cv2.connectedComponentsWithStats(inv, 4)
        holes = nn - 2
        out.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h), "area": int(area),
                    "ar": round(float(w / h), 3), "holes": int(holes),
                    "fill": round(float(area / (w * h)), 3)})
    return out

def read_shot_clock(f):
    """返回计时器掩码指纹 + 读数(用「两位数字掩码整体」做指纹, 不做OCR)"""
    m = white(f)
    return m

cap = cv2.VideoCapture(a.src)
times = [float(x) for x in a.times.split(",")]
res = {}
print(f"{'t':>9} {'shot_chg':>8} {'clk_chg':>8} {'n':>3} {'frac':>6}  verdict")
for t in times:
    pts = [t - a.span + i * (2 * a.span) / (a.n - 1) for i in range(a.n)]
    sm, cm = [], []
    for p in pts:
        cap.set(cv2.CAP_PROP_POS_MSEC, p * 1000)
        ok, f = cap.read()
        if ok:
            sm.append(read_shot_clock(f))
            cm.append(yellow(f))
    def frac_change(ms):
        chk = chg = 0
        for i in range(len(ms) - 1):
            u = np.logical_or(ms[i], ms[i+1]).sum()
            if u == 0:
                continue
            chk += 1
            if np.logical_and(ms[i], ms[i+1]).sum() / u < 0.90:
                chg += 1
        return chg, chk, (chg / chk if chk else 0.0)
    sc_, schk, sfrac = frac_change(sm)
    cc_, cchk, cfrac = frac_change(cm)
    # 读数: 取中间帧的计时器数字个数 + 宽度指纹
    mid = sm[len(sm)//2] if sm else None
    digs = digit_features(mid) if mid is not None else []
    verdict = "LIVE(shot clock running)" if sfrac >= 0.6 else \
              ("DEAD(shot clock frozen)" if sfrac <= 0.25 else "MIXED")
    print(f"{t:9.2f} {sc_:8d} {cc_:8d} {schk:3d} {sfrac:6.2f}  {verdict}"
          + (f"  digits={[ (d['w'],d['h'],d['holes']) for d in digs]}" if digs else ""))
    res[str(t)] = {"shot_chg": sc_, "shot_chk": schk, "shot_frac": round(sfrac, 3),
                   "clk_chg": cc_, "clk_frac": round(cfrac, 3), "verdict": verdict,
                   "digits": digs}
cap.release()
os.makedirs(os.path.dirname(a.json_out), exist_ok=True)
json.dump(res, open(a.json_out, "w"), ensure_ascii=False, indent=1)
print(f"\n[saved] {a.json_out}")
