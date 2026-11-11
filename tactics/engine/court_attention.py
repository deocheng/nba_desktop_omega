#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球场注意力掩膜（court attention）—— 把处理范围压到「球场 + 球员 + 篮筐」。

── 为什么需要（实测链条）─────────────────────────────────────
1. 球检测器把**木地板上的橙色印记**当球（红圈落在 (1016,669)，真球在 (1236,349)）；
2. 用户指令「颜色作为第一识别条件」——实测色相确实能分开球与木地板
   （球 H≈4–18° vs 地板 H≈32–38°）；
3. **但纯色相掩膜捞出 62 个候选，全是观众席的红色衣物**。
   ⇒ 颜色的污染源不是地板，是**观众席**。
4. 用户指令：**引入注意力机制，先去观众席，注意力放在球场、球员、篮筐。**

── 本层做法 ──────────────────────────────────────────────────
**球场可能性图**（court-likeness），只用两类高可靠像素：
  · 木地板：色相 18–48°（橙黄木色），中高饱和、较亮
  · 紫色油漆区：色相 230–290°，中高饱和
（**不用白色界线**——观众席的白色衣物/广告牌会污染）

然后：
  1. 取**最大连通域** → 球场主区域
  2. **凸包 + 填充** → 把站在场上的球员造成的空洞补上
  3. 做形态学闭运算，得到**球场多边形**

**注意力区域** = 球场多边形
              ∪ 球员框（向下延伸到脚点、向上到头顶）
              ∪ 篮筐区（背板上方一片，保证投篮瞬间不丢）

**篮筐单独处理**：篮筐/篮圈本身也是**橙色**，是球之外的第二个橙色干扰源，
必须显式建模（标定其位置并在球候选里降权/剔除）。

── 产出 ────────────────────────────────────────────────────
注意力掩膜 png（目视核对）+ 多边形顶点 + 覆盖率统计 + 候选削减率。
"""
import argparse
import json
import os

import cv2
import numpy as np


def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def court_likeness(bgr):
    """木地板 ∪ 紫色油漆区 → 二值图。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    # OpenCV 色相 0-179；木色 18-48° → 9-24；紫色 230-290° → 115-145
    wood = ((H >= 9) & (H <= 24) & (S >= 55) & (V >= 70))
    paint = ((H >= 112) & (H <= 148) & (S >= 60) & (V >= 40))
    return (wood | paint).astype(np.uint8)


def court_mask(bgr, open_k=9, close_k=25):
    """court-likeness → 最大连通域 → 闭运算桥接球员 → 填洞 → 球场掩膜。

    ⚠️ 不用凸包：凸包会把「场外但位于两顶点之间」的区域一起吃进来
    （实测会把左侧观众席一并覆盖）。改用「最大连通域 + 闭运算 + 填洞」，
    既补上球员占据的空洞，又不越界。
    """
    m = court_likeness(bgr)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        h, w = m.shape
        return np.ones_like(m, dtype=np.uint8), np.array([[0, 0], [w, 0], [w, h], [0, h]], np.int32)
    big = 1 + int(np.argmax(stats[1:, 4]))
    comp = (lab == big).astype(np.uint8)
    # 用大核闭运算跨越球员/椅子造成的缺口，再填内部空洞
    comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 45)))
    ff = comp.copy()
    h, w = comp.shape
    mask2 = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, mask2, (0, 0), 1)
    holes = (ff == 0).astype(np.uint8)
    comp = (comp | holes).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = max(cnts, key=cv2.contourArea) if cnts else None
    if hull is not None:
        eps = 0.004 * cv2.arcLength(hull, True)
        poly = cv2.approxPolyDP(hull, eps, True).reshape(-1, 2)
    else:
        poly = np.array([[0, 0], [0, 0], [0, 0]], np.int32)
    return comp, poly


def detect_hoop(bgr, court, players=None):
    """定位篮筐：**白色背板 + 其下方橙色篮圈** —— 两个条件同时成立才算。

    为什么要这样组合：只找白色矩形会命中观众席的白色衣物/广告牌
    （实测 t=219.5 把中场的白色块当成了篮筐）。篮筐的定义性特征是
    「白色板子下面挂着橙色圆环」，加上这条约束后误检基本消失。
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    Hch, S, V = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    H_img, W_img = S.shape
    white = ((S < 50) & (V > 170)).astype(np.uint8) * 255
    orange = (((Hch <= 16) | (Hch >= 168)) & (S >= 70) & (V >= 60)).astype(np.uint8)
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if not (35 <= w <= 240 and 18 <= h <= 150):
            continue
        ar = w / max(h, 1)
        if ar < 1.0:
            continue
        cy = y + h / 2
        if cy > H_img * 0.42:                 # 篮筐在画面上部
            continue
        fill = cv2.contourArea(c) / float(w * h)
        if fill < 0.45:
            continue
        # 判据：正下方 10–70px 内有橙色像素（篮圈）
        y1, y2 = min(H_img, y + h), min(H_img, y + h + 70)
        x1, x2 = max(0, x - 8), min(W_img, x + w + 8)
        if y2 <= y1 or x2 <= x1:
            continue
        band = orange[y1:y2, x1:x2]
        if band.sum() < 12:
            continue
        score = w * h * (1.0 + ar) + band.sum() * 4
        if best is None or score > best[0]:
            best = (score, (x, y, w, h))
    return best[1] if best else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--times", required=True, help="逗号分隔")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--sel", default=None, help="select_tracks.json（用于并入球员框）")
    ap.add_argument("--hybrid", default=None, help="hybrid_ball.json（用于算候选削减率）")
    ap.add_argument("--t0", type=float, default=204.5)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--pad-player", type=int, default=12)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    sel = load(a.sel) if a.sel and os.path.exists(a.sel) else None
    tlist = [float(x) for x in a.times.split(",")]

    summary = []
    for t in tlist:
        fi = int(round((t - a.t0) * a.fps)) + 1
        p = os.path.join(a.frames_dir, f"f{fi:05d}.jpg")
        if not os.path.exists(p):
            print(f"  缺帧 {p}")
            continue
        bgr = cv2.imread(p)
        H, W = bgr.shape[:2]
        cmask, poly = court_mask(bgr)

        # 球员框（并入注意力）
        pmask = np.zeros_like(cmask)
        players = []
        if sel:
            idx = fi - 1
            if 0 <= idx < len(sel["frames"]):
                for pl in sel["frames"][idx]["players"]:
                    x1, y1, x2, y2 = [int(v) for v in pl["box"]]
                    pd = a.pad_player
                    cv2.rectangle(pmask, (x1 - pd, y1 - pd), (x2 + pd, y2 + pd), 1, -1)
                    players.append([x1, y1, x2, y2])

        hoop = detect_hoop(bgr, cmask, players)
        hmask = np.zeros_like(cmask)
        if hoop:
            x, y, w, h = hoop
            # 篮筐区：背板上下各扩，覆盖球入筐前后的轨迹
            cv2.rectangle(hmask, (x - 30, max(0, y - 70)), (x + w + 30, y + h + 50), 1, -1)

        attn = ((cmask > 0) | (pmask > 0) | (hmask > 0)).astype(np.uint8)

        # 覆盖率
        cov_court = float(cmask.mean())
        cov_attn = float(attn.mean())

        # 目视核对图
        vis = bgr.copy()
        overlay = np.zeros_like(bgr)
        overlay[:, :, 1] = 255                     # 绿=球场
        vis = np.where(attn[:, :, None] > 0, (0.72 * vis + 0.28 * overlay).astype(np.uint8), vis)
        cv2.polylines(vis, [poly.reshape(-1, 1, 2)], True, (0, 255, 255), 2)
        for (x1, y1, x2, y2) in players:
            cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 160, 60), 2)
        if hoop:
            x, y, w, h = hoop
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 165, 255), 3)
            cv2.putText(vis, "HOOP", (x, max(18, y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
        cv2.putText(vis, f"t={t}s  court={cov_court*100:.1f}%  attn={cov_attn*100:.1f}%",
                    (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
        outp = os.path.join(a.outdir, f"attn_t{int(t*10):05d}.jpg")
        cv2.imwrite(outp, vis, [cv2.IMWRITE_JPEG_QUALITY, 88])

        summary.append({
            "t": t, "frame": fi,
            "court_coverage": round(cov_court, 4),
            "attn_coverage": round(cov_attn, 4),
            "poly": poly.tolist(),
            "hoop_box": list(hoop) if hoop else None,
            "n_players": len(players),
            "vis": outp,
        })
        print(f"  t={t:>6.1f}  球场覆盖 {cov_court*100:5.1f}%  注意力覆盖 {cov_attn*100:5.1f}%"
              f"  球员 {len(players):>2}  篮筐 {'✅ ' + str(hoop) if hoop else '❌ 未检出'}")

    out = os.path.join(a.outdir, "court_attention.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f"\n[out] {out}")


if __name__ == "__main__":
    main()
