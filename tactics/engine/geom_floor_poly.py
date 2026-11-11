#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场地板区域轮廓（wood + 涂装 + 暗色地板）+ 候选的"越界"几何特征。

动机（里程碑 05 · 球精度攻关）
--------------------------------
FP 家族 = 观众席衣物 / 球员躯干手部 / 场边设备 —— 其中**观众席衣物**位于
「场地地板在图像中的上边界之外」。2D 掩膜的根本局限：远侧观众在图像上正好位于
球场区域「正上方」，所以直接把掩膜向上延伸必然纳入观众。

本脚本做三件事：
  ① 逐帧求「地板区域」外轮廓（含 wood 木色 + TOR 紫色涂装 + 暗色地板/广告牌区），
     只取最大连通域，避免把观众衣服/球衣的近似色算进来；
  ② 用外轮廓的**上边界折线**计算候选的越界量：
       above_top   = 上边界 y − 候选中心 y   （>0 即在边界之上 = 越界）
       d_top       = 同上（连续量，单位 px）
       in_floor    = 中心是否在地板区域内
       foot_in     = 框底中点是否在内
  ③ 用真值库逐特征算 AUC（TP vs FP），给方向性裁定。

用法:
  python engine/geom_floor_poly.py --probe w1            # 打印采样点 HSV
  python engine/geom_floor_poly.py --render w1 f00010    # 渲染轮廓叠加图
  python engine/geom_floor_poly.py --auc                 # 全窗 AUC 表 + 落盘
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

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))

# 颜色区间（OpenCV HSV，H 0-180）
WOOD_H = (6, 32)          # 暖橙木色
WOOD_S, WOOD_V = 60, 55
PURPLE_H = (118, 168)     # TOR 紫色涂装
PURPLE_S, PURPLE_V = 45, 45
DARK_V_MAX = 62           # 暗色地板/广告牌（V 很低）——需与黑球衣区分：靠最大连通域

SPLIT = 3                 # 上边界折线的横向列数（分位）


def floor_mask(img, scale=0.25):
    small = cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)),
                       interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    wood = (H >= WOOD_H[0]) & (H <= WOOD_H[1]) & (S >= WOOD_S) & (V >= WOOD_V)
    pur = (H >= PURPLE_H[0]) & (H <= PURPLE_H[1]) & (S >= PURPLE_S) & (V >= PURPLE_V)
    m = (wood | pur).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return np.zeros(small.shape[:2], np.uint8)
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    comp = (lab == i).astype(np.uint8) * 255
    # 大核闭合：把被人物/文字割裂的地板缝成一片
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, k2)
    comp = cv2.morphologyEx(comp, cv2.MORPH_OPEN, k2)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(comp, 8)
    if n > 1:
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        comp = (lab == i).astype(np.uint8) * 255
    return comp, scale


def poly_top(mask):
    """外轮廓 + 上边界折线：返回 (contour, xs, ys_top)。"""
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None, None, None
    c = max(cs, key=cv2.contourArea).reshape(-1, 2)
    xs = np.quantile(c[:, 0], np.linspace(0.01, 0.99, SPLIT)).astype(int)
    ys = []
    for x in xs:
        sel = c[np.abs(c[:, 0] - x) <= 6]
        ys.append(int(sel[:, 1].min()) if len(sel) else int(c[:, 1].min()))
    return c, xs, np.array(ys, float)


def probe(win):
    frames = sorted((AW / win).glob("f*.jpg"))[:1]
    img = cv2.imread(str(frames[0]))
    small = cv2.resize(img, (img.shape[1] // 4, img.shape[0] // 4), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    pts = {"木地板(1600,676)": (1600, 676), "紫涂装(533,711)": (533, 711),
           "暗色地板(1102,604)": (1102, 604), "看台观众(1200,120)": (1200, 120),
           "场边暗区(200,700)": (200, 700), "球场近端(900,880)": (900, 880)}
    print(f"[{win}] {frames[0].name}")
    for k, (x, y) in pts.items():
        h, s, v = hsv[y // 4, x // 4]
        print(f"  {k:22s} HSV=({h:3d},{s:3d},{v:3d})")
    m, sc = floor_mask(img)
    print(f"  掩膜占比(25%尺度) {(m > 0).mean() * 100:.1f}%")


def render(win, frame, out=None):
    img = cv2.imread(str(AW / win / frame))
    m, sc = floor_mask(img)
    full = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    ov = img.copy()
    ov[full > 0] = (ov[full > 0] * 0.6 + np.array([30, 110, 40]) * 0.4).astype(np.uint8)
    c, xs, ys = poly_top(full)
    if c is not None:
        cv2.polylines(ov, [c.reshape(-1, 1, 2)], True, (0, 255, 255), 2)
        pts = np.stack([xs, ys.astype(int)], 1).reshape(-1, 1, 2)
        cv2.polylines(ov, [pts], False, (255, 0, 255), 3)
        for x, y in zip(xs, ys):
            cv2.circle(ov, (int(x), int(y)), 6, (255, 0, 255), -1)
            cv2.putText(ov, f"{int(x)},{int(y)}", (int(x) + 6, int(y) - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
    cv2.putText(ov, f"{win} {frame}  floor={(m>0).mean()*100:.1f}%", (20, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    out = out or str(MS / f"floorpoly_{win}_{Path(frame).stem}.jpg")
    cv2.imwrite(out, ov, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}")


def feats_for(mask_full, box):
    """box: x1,y1,x2,y2 -> 几何特征字典"""
    H, W = mask_full.shape
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    fx, fy = cx, y2
    c, xs, ys = poly_top(mask_full)
    def top_at(x):
        if xs is None:
            return float(H)
        return float(np.interp(x, xs, ys))
    in_c = 1.0 if (0 <= int(cy) < H and 0 <= int(cx) < W and mask_full[int(cy), int(cx)] > 0) else 0.0
    in_f = 1.0 if (0 <= int(fy) < H and 0 <= int(fx) < W and mask_full[int(fy), int(fx)] > 0) else 0.0
    d_c = top_at(cx) - cy
    d_f = top_at(fx) - fy
    return {"in_floor": in_c, "foot_in_floor": in_f, "above_top": d_c, "above_top_foot": d_f,
            "top_row": top_at(cx)}


def auc(y, x):
    y = np.asarray(y, float); x = np.asarray(x, float)
    if y.sum() in (0, len(y)):
        return float("nan")
    r = np.argsort(np.argsort(x)) + 1.0
    n1, n0 = y.sum(), (1 - y).sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def run_auc(wins=("w1", "w2", "w3", "w4")):
    bank = json.loads((MS / "labels_bank.json").read_text())
    all_rows = []
    for w in wins:
        rows = [r for r in bank if r["window"] == w and r["label"] in ("TP", "FP")]
        cache = {}
        out = []
        for r in rows:
            if r["frame"] not in cache:
                img = cv2.imread(str(AW / w / r["frame"]))
                m, _ = floor_mask(img)
                cache[r["frame"]] = cv2.resize(m, (img.shape[1], img.shape[0]),
                                               interpolation=cv2.INTER_NEAREST)
            f = feats_for(cache[r["frame"]], r["bbox"])
            f.update({"window": w, "frame": r["frame"], "label": r["label"]})
            out.append(f)
        all_rows += out
        y = [1 if r["label"] == "TP" else 0 for r in out]
        line = "  ".join(f"{k} AUC={auc(y, [r[k] for r in out]):.3f}"
                         for k in ("in_floor", "foot_in_floor", "above_top", "above_top_foot"))
        print(f"[{w}] n={len(out)} TP={sum(y)}  {line}")
    y = [1 if r["label"] == "TP" else 0 for r in all_rows]
    line = "  ".join(f"{k} AUC={auc(y, [r[k] for r in all_rows]):.3f}"
                     for k in ("in_floor", "foot_in_floor", "above_top", "above_top_foot"))
    print(f"[ALL] n={len(all_rows)} TP={sum(y)}  {line}")
    (MS / "geom_rows.json").write_text(json.dumps(all_rows, ensure_ascii=False))
    print(f"[out] {MS / 'geom_rows.json'}")
    # 分位数：TP vs FP 的 above_top
    for lab in ("TP", "FP"):
        v = np.array([r["above_top"] for r in all_rows if r["label"] == lab], float)
        print(f"  above_top {lab}: p10={np.percentile(v,10):7.1f} 中位={np.median(v):7.1f} "
              f"p90={np.percentile(v,90):7.1f}  >0 比例={np.mean(v>0)*100:5.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default=None)
    ap.add_argument("--render", nargs=2, default=None, metavar=("WIN", "FRAME"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--auc", action="store_true")
    a = ap.parse_args()
    if a.probe:
        probe(a.probe)
    if a.render:
        render(a.render[0], a.render[1], a.out)
    if a.auc:
        run_auc()


if __name__ == "__main__":
    main()
