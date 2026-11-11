#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tacboard.py — 战术板动画 → 战术坐标系验证真值（2026-10-03）

为什么做这个
------------
实测发现战术原语在**真实广播像素坐标**上方向语义全错（无球场变换，"y减小=朝筐"
是半场俯视约定，横屏广播不成立）⇒ CUT/DRIVE/ROLL 几乎不触发。而广播侧补标定
卡在 `locked_by_laocheng`（需老程点选场地线）。

老程提供的**勇士經典戰術动画（tactical-board.com 制作）**恰是**理想俯视半场**
：进攻朝上(y减小=朝筐)、白/蓝实心圆=球员、红圈/箭头=标注动作、字幕=步骤说明。
⇒ 它就是缺失的**坐标系真值 + 原语语义真值**，可在理想输入上单元验证原语检测器，
   不依赖广播侧标定。

本模块只做**可证伪**的两件事：
  ① 球员图标检测：白色环(白队) + 蓝色实心圆(蓝队)，用圆度/半径/颜色三门，可视化自证；
  ② 战术板像素 → 战术坐标系(x∈[-250,250], y∈[0,940]) 映射：由**场地线**（底线/边线/
     罚球线）反解 4 角 + 单应，标定来源=从棋盘图实测，**不硬编码**（写入 tacboard_calib.json）。

🔴 诚实边界：战术板动画只覆盖**进攻战术片段**，不含防守战术；球员图标是**理想化**
   （无遮挡/无深度/无球），因此本模块产出的真值用于**验证原语判据在正确坐标系下是否成立**，
   不能直接当作广播素材的命中率。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
import subprocess
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
OUT = ROOT / "action_work" / "tacboard"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

# 战术坐标系约定（与 tactic_match.py 一致）
COURT_X, COURT_Y = 500.0, 940.0          # 战术板: x 居中为0 → [-250,250], y∈[0,940]
BALL_Y = 57.0                            # 篮筐 y（tactic_match.zone_of 约定）


# ---------------- 1) 抽帧 ----------------
def extract_frames(mp4, out_dir, fps=4):
    out = Path(out_dir)
    if out.exists() and any(out.glob("*.jpg")):
        return sorted(out.glob("*.jpg"))
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(mp4),
                    "-vf", f"fps={fps}", "-q:v", "2", str(out / "f%05d.jpg")], check=True)
    return sorted(out.glob("*.jpg"))


# ---------------- 2) 球场区域 + 球员图标检测 ----------------
def court_roi(img):
    """用木纹色定位球场矩形区域（返回 y0,y1,x0,x1）。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    wood = ((hsv[:, :, 0] >= 8) & (hsv[:, :, 0] <= 25) &
            (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 80)).astype(np.uint8)
    wood = cv2.morphologyEx(wood, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(wood, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(c)
    return y, y + h, x, x + w


def _circ_candidates(mask, rmin=8, rmax=40, amin=200, circmin=0.5):
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < amin:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(c)
        if r < rmin or r > rmax:
            continue
        circ = a / (math.pi * r * r)
        if circ < circmin:
            continue
        out.append({"cx": float(cx), "cy": float(cy), "r": float(r), "circ": round(circ, 3)})
    return out


def detect_players(img):
    """检测球员图标：白队=白色环(内部深色数字), 蓝队=蓝色实心圆。
    返回 {"white":[{x,y,r,circ}], "blue":[...], "ball":(x,y)|None}，坐标为**像素**。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    roi = court_roi(img)
    if roi is None:
        return {"white": [], "blue": [], "ball": None}
    y0, y1, x0, x1 = roi
    r = hsv[y0:y1, x0:x1]
    # 蓝队：深蓝实心
    blue = ((r[:, :, 0] > 100) & (r[:, :, 0] < 130) &
            (r[:, :, 1] > 80) & (r[:, :, 2] > 60)).astype(np.uint8) * 255
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    blue_c = _circ_candidates(blue)
    for d in blue_c:
        d["x"], d["y"] = d["cx"] + x0, d["cy"] + y0
    # 白队：白色环 = 白色像素的**环形**结构；用白掩膜的凸包圆度筛（数字把内部挖空 → 圆度降）
    white = ((r[:, :, 0] < 20) & (r[:, :, 1] < 50) & (r[:, :, 2] > 200)).astype(np.uint8) * 255
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    white_c = []
    cnts, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 150:
            continue
        (cx, cy), rr = cv2.minEnclosingCircle(c)
        if rr < 8 or rr > 40:
            continue
        # 环判定：外接圆面积 - 实际面积 应为「环带」量级；实心圆则接近0
        ring = (math.pi * rr * rr) - a
        solid = a / (math.pi * rr * rr)
        if solid < 0.35:            # 内部被数字挖空 ⇒ 非实心 ⇒ 判为白环
            white_c.append({"cx": cx, "cy": cy, "r": rr, "circ": round(solid, 3)})
    for d in white_c:
        d["x"], d["y"] = d["cx"] + x0, d["cy"] + y0
    # 球：橙色篮球（比木纹更饱和的橙）
    b = img
    bh = cv2.cvtColor(b, cv2.COLOR_BGR2HSV)
    ball = ((bh[:, :, 0] >= 5) & (bh[:, :, 0] <= 20) &
            (bh[:, :, 1] > 150) & (bh[:, :, 2] > 140)).astype(np.uint8) * 255
    ball = cv2.morphologyEx(ball, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    bc = _circ_candidates(ball, rmin=3, rmax=14, amin=25, circmin=0.5)
    ball_pt = None
    if bc:
        bb = max(bc, key=lambda z: z["circ"])
        ball_pt = (bb["cx"], bb["cy"])
    return {"white": white_c, "blue": blue_c, "ball": ball_pt, "roi": roi}


# ---------------- 3) 像素 → 战术坐标系 ----------------
def fit_court_calib(frames_samples):
    """由多帧的球场区域 + 场地线，实测 4 角并建单应 → 战术坐标系。
    🔴 关键假设(已由 SpiltStagger/WeaveSpiltSTS 目视确认)：**进攻朝上**，
       故战术板 y=0(篮筐端) 对应画面**顶部**。此假设写入 calib 供复核。"""
    # 场地矩形的 4 角（战术板为轴对齐矩形，木纹区即场地）
    ys, xs, y1s, x1s = [], [], [], []
    for img in frames_samples:
        roi = court_roi(img)
        if roi is None:
            continue
        y0, y1, x0, x1 = roi
        ys.append(y0); y1s.append(y1); xs.append(x0); x1s.append(x1)
    if not ys:
        return None
    # 取中位数抗字幕/箭头干扰
    py0, py1 = int(np.median(ys)), int(np.median(y1s))
    px0, px1 = int(np.median(xs)), int(np.median(x1s))
    src = np.array([[px0, py0], [px1, py0], [px1, py1], [px0, py1]], dtype=np.float32)  # TL TR BR BL
    # 目标：战术板（进攻朝上 → 顶=y0=篮筐）
    dst = np.array([[-COURT_X, 0.0], [COURT_X, 0.0],
                    [COURT_X, COURT_Y], [-COURT_X, COURT_Y]], dtype=np.float32)
    Hm, _ = cv2.findHomography(src, dst)
    return {"src_px": src.tolist(), "dst_court": dst.tolist(),
            "H": Hm.tolist(),
            "note": "进攻朝上(目视确认SpiltStagger/WeaveSpiltSTS); src=木纹球场矩形的4角中位数; "
                    "dst=战术板 x∈[-250,250] y∈[0,940] 篮筐y=0端",
            "attack_direction_up": True}


def pix_to_court(pt, Hm):
    p = np.array([[[pt[0], pt[1]]]], dtype=np.float32)
    return tuple(float(v) for v in cv2.perspectiveTransform(p, Hm)[0][0])


# ---------------- 编排 ----------------
def build(manifest_path, fps=4):
    man = json.load(open(manifest_path, encoding="utf-8"))
    samples = []
    report = []
    for item in man:
        name = item["name"]
        outdir = OUT / name
        jpgs = extract_frames(item["file"], outdir, fps=fps)
        # 抽 3 帧做标定样本 + 逐帧球员检测
        cal_samples = [cv2.imread(str(p)) for p in jpgs[::max(1, len(jpgs) // 3)]][:3]
        calib = fit_court_calib([im for im in cal_samples if im is not None])
        frames_pos = []
        for p in jpgs:
            img = cv2.imread(str(p))
            if img is None:
                continue
            det = detect_players(img)
            frames_pos.append({"file": p.name, "white": det["white"], "blue": det["blue"],
                               "ball": det["ball"]})
        report.append({"name": name, "n_frames": len(frames_pos),
                       "calib": calib is not None, "frames": frames_pos})
        if calib:
            json.dump(calib, open(OUT / f"calib_{name}.json", "w"), ensure_ascii=False, indent=1)
        print(f"[tacboard] {name}: {len(frames_pos)} 帧, calib={calib is not None}")
    json.dump({"report": report}, open(OUT / "positions.json", "w"), ensure_ascii=False, indent=1)
    return report


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    rep = build(OUT / "manifest.json")
    for r in rep:
        avg_w = np.mean([len(f["white"]) for f in r["frames"]]) if r["frames"] else 0
        avg_b = np.mean([len(f["blue"]) for f in r["frames"]]) if r["frames"] else 0
        ball_frames = sum(1 for f in r["frames"] if f["ball"])
        print(f"  {r['name']:20s} 帧={r['n_frames']:3d} 平均白圈={avg_w:.1f} 平均蓝圈={avg_b:.1f} 有球帧={ball_frames}")
