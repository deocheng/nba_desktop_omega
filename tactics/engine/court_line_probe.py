#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5.15 直线证据探针：把画面里所有「两侧一地板一非地板」的直线全量检出、按角度
分族，用 NBA 几何先验做自洽性检验。

老程指令（A5.15 方向，2026-10-01）：
  ① 场地边线被遮挡 ⇒ 虚拟边线 = 平行于识别出的一条边线（不再拟合掩膜下沿）
  ② 累积掩膜绿色=球场但没覆盖全场 ⇒ 用画面识别出的直线推测整个场地
  ③ 油漆区 + 合理冲撞区弧识别正确（非中圈）⇒ 可作已知尺寸锚点

探针问题（写场地推理器之前必须先回答，数字全从画面现读）：
  Q1 长度方向线族（~4°，边线+油漆区宽边）已知可检出；宽度方向线
     （底线/罚球线，应为陡斜线族）能否检出？角度是多少？
  Q2 NBA 几何自洽：油漆区两条宽边间距 × (50ft/16ft = 3.125) ≈ 两条边线间距？
  Q3 同段不同帧（f70 / f145）直线稳定吗？

用法: court_line_probe.py --seg ep24_s1 --idx 70 145
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
from court_homography_recover import paint_mask  # noqa: E402  (A5.14 已验证的油漆区抠取)

WOOD_LO, WOOD_HI = (10, 45, 140), (38, 255, 255)

# ---- NBA 标准尺寸（英尺）----
FT_COURT_RATIO = 50.0 / 16.0      # 场宽 50ft / 油漆区宽 16ft = 3.125


def wood_ratio(img, x, y, r=9):
    H, W = img.shape[:2]
    x0, x1 = max(0, x - r), min(W, x + r)
    y0, y1 = max(0, y - r), min(H, y + r)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    return float((cv2.inRange(hsv, WOOD_LO, WOOD_HI) > 0).mean())


def detect(img, minlen=90, subt_y=630, verbose_count=None):
    """全量检出两侧一地板一非地板的直线，粗去重。返回按长度降序的 list[dict]。"""
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    raw = []
    for lo, hi in [(40, 120), (80, 200)]:
        e = cv2.dilate(cv2.Canny(gray, lo, hi), np.ones((3, 3), np.uint8), 1)
        ls = cv2.HoughLinesP(e, 1, np.pi / 360, threshold=60,
                             minLineLength=minlen, maxLineGap=50)
        if ls is not None:
            raw += [tuple(int(v) for v in np.asarray(l).reshape(-1)) for l in ls]
    kept = []
    for (x1, y1, x2, y2) in raw:
        L = float(np.hypot(x2 - x1, y2 - y1))
        if L < minlen:
            continue
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        if subt_y is not None and my > subt_y:
            continue                                    # 字幕条区（ep24_s1: y≈660/700）
        ang = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if ang > 90:
            ang = 180 - ang
        dx, dy = x2 - x1, y2 - y1
        n = np.hypot(dx, dy)
        px, py = -dy / n, dx / n
        o = 16
        p1 = (int(mx + px * o), int(my + py * o))
        p2 = (int(mx - px * o), int(my - py * o))
        if not (0 <= p1[0] < W and 0 <= p1[1] < H and 0 <= p2[0] < W and 0 <= p2[1] < H):
            continue
        r1, r2 = wood_ratio(img, *p1), wood_ratio(img, *p2)
        if not ((r1 >= 0.35 and r2 <= 0.15) or (r2 >= 0.35 and r1 <= 0.15)):
            continue
        kept.append(dict(p=(x1, y1, x2, y2), L=L, ang=ang,
                         wood=(round(r1, 2), round(r2, 2))))
    kept.sort(key=lambda k: -k["L"])
    uniq = []
    for k in kept:
        x1, y1, x2, y2 = k["p"]
        mk = (int(k["ang"] // 4), (x1 + x2) // 2 // 45, (y1 + y2) // 2 // 45)
        if any(u["mk"] == mk for u in uniq):
            continue
        k["mk"] = mk
        uniq.append(k)
    return uniq


def y_at(k, x):
    """直线（近似）在横坐标 x 处的 y。竖线返回 None。"""
    x1, y1, x2, y2 = k["p"]
    if x2 == x1:
        return None
    a = (y2 - y1) / (x2 - x1)
    return a * (x - x1) + y1


def x_at(k, y):
    """直线（近似）在纵坐标 y 处的 x。横线返回 None。"""
    x1, y1, x2, y2 = k["p"]
    if y2 == y1:
        return None
    a = (x2 - x1) / (y2 - y1)
    return a * (y - y1) + x1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, nargs="+", default=[70, 145])
    ap.add_argument("--minlen", type=int, default=90)
    ap.add_argument("--subt-y", type=float, default=630)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)

    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    for idx in a.idx:
        img = cv2.imread(str(files[idx]))
        H, W = img.shape[:2]
        lines = detect(img, a.minlen, int(a.subt_y))
        famA = [k for k in lines if k["ang"] < 20]        # 长度方向（近水平）
        famB = [k for k in lines if k["ang"] >= 20]       # 其余（陡斜，找底线/罚球线）
        famA.sort(key=lambda k: (y_at(k, W / 2) if y_at(k, W / 2) is not None else 0))

        print(f"\n===== {a.seg} f{idx}  共 {len(lines)} 条 "
              f"(长度方向 {len(famA)} / 陡斜 {len(famB)}) =====")

        # 油漆区掩膜 + 判定哪些 famA 线中点落在油漆区内
        pm = paint_mask(img)
        inside_paint = []
        if pm is not None:
            pmd = cv2.dilate(pm, np.ones((31, 31), np.uint8))
            for k in famA:
                mx, my = (k["p"][0] + k["p"][2]) // 2, (k["p"][1] + k["p"][3]) // 2
                if 0 <= mx < W and 0 <= my < H and pmd[my, mx] > 0:
                    inside_paint.append(k)
        print(f"油漆区掩膜: {'OK' if pm is not None else '未检出'}; "
              f"famA 中点落在油漆区内的线: {len(inside_paint)} 条")

        print("-- 长度方向线（按 y@x=W/2 排序，Δ=与上一条的竖直间距@x=W/2）--")
        prev_y = None
        for i, k in enumerate(famA):
            yy = y_at(k, W / 2)
            d = (yy - prev_y) if (yy is not None and prev_y is not None) else None
            ip = " ◆油漆宽边" if k in inside_paint else ""
            print(f"  A#{i:>2} 角{k['ang']:>5.1f}° 长{k['L']:>5.0f} "
                  f"y@mid={yy:6.1f} Δ={('%6.1f' % d) if d is not None else '     -'} "
                  f"木{k['wood']} 端点{k['p']}{ip}")
            if yy is not None:
                prev_y = yy

        print("-- 陡斜线（底线/罚球线候选）--")
        for i, k in enumerate(famB):
            xx = x_at(k, H / 2)
            print(f"  B#{i:>2} 角{k['ang']:>5.1f}° 长{k['L']:>5.0f} "
                  f"x@H/2={('%6.1f' % xx) if xx is not None else '     -'} "
                  f"木{k['wood']} 端点{k['p']}")

        # NBA 几何自洽检验：油漆区宽边间距 × 3.125 ≈ 边线间距
        if pm is not None and len(inside_paint) == 2 and len(famA) >= 2:
            yA = [y_at(k, W / 2) for k in inside_paint]
            yA = [v for v in yA if v is not None]
            if len(yA) == 2:
                s_paint = abs(yA[1] - yA[0])
                y_top = y_at(famA[0], W / 2)
                y_bot = y_at(famA[-1], W / 2)
                if y_top is not None and y_bot is not None:
                    s_court = abs(y_bot - y_top)
                    r = s_court / s_paint if s_paint > 0 else float("nan")
                    print("-- NBA 几何自洽 (x=W/2) --")
                    print(f"  油漆宽边间距 s_paint = {s_paint:.1f}px")
                    print(f"  边线间距     s_court = {s_court:.1f}px  "
                          f"(最上 A#{0} ↔ 最下 A#{len(famA)-1})")
                    print(f"  实测比值 r = {r:.3f}   理论 50/16 = {FT_COURT_RATIO:.3f}   "
                          f"偏差 {100*(r/FT_COURT_RATIO-1):+.1f}%")

        # 叠图自证：famA 绿 / famB 品红 / 油漆区青轮廓
        vis = img.copy()
        for i, k in enumerate(famA):
            x1, y1, x2, y2 = k["p"]
            c = (0, 220, 0) if k not in inside_paint else (0, 255, 255)
            cv2.line(vis, (x1, y1), (x2, y2), (0, 0, 0), 5)
            cv2.line(vis, (x1, y1), (x2, y2), c, 3)
            tag = f"A{i}:{k['ang']:.1f}"
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.putText(vis, tag, (mx, my - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
            cv2.putText(vis, tag, (mx, my - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c, 2)
        for i, k in enumerate(famB):
            x1, y1, x2, y2 = k["p"]
            cv2.line(vis, (x1, y1), (x2, y2), (0, 0, 0), 5)
            cv2.line(vis, (x1, y1), (x2, y2), (255, 0, 255), 3)
            tag = f"B{i}:{k['ang']:.1f}"
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.putText(vis, tag, (mx, my - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
            cv2.putText(vis, tag, (mx, my - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)
        if pm is not None:
            cs, _ = cv2.findContours(pm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(vis, cs, -1, (255, 255, 0), 2)
        op = OUT / f"{a.seg}_f{idx}_lineprobe.png"
        cv2.imwrite(str(op), vis)
        print(f"-> {op}")


if __name__ == "__main__":
    main()
