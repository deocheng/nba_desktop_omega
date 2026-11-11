#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""篮圈检测 v2 —— 红篮圈 + 白篮网 + 跨帧交叉相关。

── 为什么白板判据必然失败（两次失败的真因）─────────────────────
NBA 篮板是**透明玻璃**。透过它看到的是**穿白衣的观众**，
而场边 LED 广告板（白字/白底）与观众白衬衫处在同一图像高度。
所以任何「找白色实心矩形」的判据都会命中它们 ——
实测先是把中场白色块当成篮筐 (686,390)，后又误报 LED 板与计时器。

── v2 的两条真判据 ────────────────────────────────────────────
1. **篮圈是鲜艳红色**（不是木色橙）：
   实测篮圈 `R=120 G=52 B=49` → `R−G=68`；真球 `R−G=42`；木地板 `R−G=43`。
   ⇒ 篮圈明显比球/地板更红，这是**球与篮圈之分的判据**。
   高饱和红掩膜 `(H≤8 或 H≥172) & S≥140 & V≥90` 实测捞出
   `bbox=(1246,235,48,25)`，距人工真值仅 **12.7px**，48×25 的宽扁形状正是侧视篮圈。
2. **篮圈正下方挂着白色网格（篮网）** —— 比玻璃篮板可靠得多的签名特征。
   用「下方带内的低饱和高亮像素占比 + 边缘密度」做二次确认，
   用来把篮圈从画面里其它红色物体（球衣/广告）中挑出来。
3. **跨帧交叉相关**：同一镜头内篮筐位置基本不动，用首帧模板做 NCC 逐帧定位，
   漂移 > `--drift` 时自动重捕（重新跑单帧检测）。这样拿到的是**时序一致**的篮筐。

⚠️ 篮圈本身是**球之外的第二个橙色/红色干扰源**，必须显式建模，
并在球候选中降权/剔除（`ball_detect_hybrid` 已把篮筐区单列）。

═══════════════════════════════════════════════════════════════
🔴 实测结论（2026-09-23）：**本素材里篮圈无法靠颜色/形状自动定位**
═══════════════════════════════════════════════════════════════
这是继「白板判据失败」之后的**第三个失败模式**。全部证据如下，勿重复踩：

**✅ 红篮圈判据在篮筐真的在场且够大时是准的**：
  t=216.0 → box [1253,236,65,26]（目视确认正好压在红篮圈上）
  t=219.5 → box [1226,236,65,27]，中心 (1258,250) vs 人工真值 (1270,247) → **误差 11.8px**

**❌ 但同一套判据在其余取景下全是假阳性。逐帧目视核对结果**：
  | t | 检出框 | 目视实际是什么 |
  |---|---|---|
  | 216.0 | [1253,236,65,26] | **红篮圈 ✅** |
  | 219.5 | [1226,236,65,27] | **红篮圈 ✅** |
  | 204.5 | [414,161,15,11] | 场边**红光小显示屏** ✗（篮筐其实在场，但在左侧未被选中）|
  | 222.0 | [1634,47,37,26] | 观众席**穿红衣的人** ✗ |
  | 230.0 | [892,69,28,16] | 观众席**红衣** ✗ |
  | 236.5 | [1200,20,32,19] | 观众席**红衣** ✗ |
  | 240.0 | [1239,146,51,36] | 场边**红色物体** ✗ |
  | 246.9 | [395,208,51,32] | 场边**红色物体** ✗ |

**已试过且失败的判别特征（含实测数值，全部重叠，不可用）**：

| 特征 | 真篮圈 | 假目标（红衣/红物） | 可分? |
|---|---|---|---|
| 边缘密度（篮网网格） | 0.156–0.165 | 0.169–0.289 | ❌ 重叠 |
| 填充率 `area/(w*h)` | 0.44–0.46 | 0.41–0.67 | ❌ 重叠 |
| **中心空心率**（篮圈是"环"，中心可看穿） | 0.25–0.38 | 0.00–0.66 | ❌ 重叠 |
| 下方带白色像素占比（篮网） | 0.32 | 0.25–0.63 | ❌ 重叠 |
| 宽扁比 | 2.4–2.5 | 1.3–2.9 | ❌ 重叠 |
| 面积 | 741–788 | 110–780 | ❌ 重叠 |

**时序一致性也救不回来**：全 435 帧检出 415 帧（判据过松），
按"中心±40px + 面积一致"做连续段搜索得 40 段，最长 25 帧
（t=233.7–236.1 中心 (1178,57)）——但**那段目视是静止的观众红衣/红色看板**，不是篮筐。
篮筐所在位置 (1258–1286, 249) 附近**没有**形成任何长一致段。

**⇒ 本素材的正解**：
  ① **人工标注**篮筐（本片段所需窗口 t≈214–221.5 内篮筐清晰可见，
     人工真值 rim bbox=(1246,235,48,25)，中心 (1270,247)）；
  ② 或训练专用检测器（篮板/篮圈）；
  ③ 或在没有篮筐的取景里**明确输出 null，不得猜**。

`--verified-range` 参数即为此设计：只在该窗口内输出框，窗口外一律 `null`
且 `mode="outside_window"`。**宁可没有，不可有假。**
"""
from __future__ import annotations

import argparse
import json
import os

import cv2
import numpy as np


# ─────────────────────── 单帧检测 ───────────────────────
def red_rim_mask(bgr):
    """高饱和红掩膜。用中位数而非均值——红区色相在 0/180 处环绕，
    对跨环绕的 patch 求 H 的算术平均会得到垃圾值（实测篮圈真值 2.5° 会算成 92.4°）。
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    m = (((H <= 8) | (H >= 172)) & (S >= 140) & (V >= 90)).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))


def net_score(bgr, rim_box):
    """篮圈正下方是否有白色网格（篮网）。返回 (white_frac, edge_density)。"""
    x, y, w, h = rim_box
    H_img, W_img = bgr.shape[:2]
    y1, y2 = min(H_img, y + h + 2), min(H_img, y + h + 62)
    x1, x2 = max(0, x - 10), min(W_img, x + w + 10)
    if y2 - y1 < 12 or x2 - x1 < 12:
        return 0.0, 0.0
    band = bgr[y1:y2, x1:x2]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    S, V = hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    white = ((S < 70) & (V > 85)).astype(np.uint8)
    g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(g, 60, 160)
    return float(white.mean()), float((edges > 0).mean())


def detect_hoop_single(bgr, min_area=110, max_area=1300,
                       y_frac_max=0.72, net_min=0.20, edge_min=0.14,
                       ar_min=1.15, ar_max=3.2):
    """单帧篮圈检测。返回 (best, cands)，best = {box, score, detail} 或 None。

    判据（按区分力排序，实测标定）：
      · **边缘密度 ≥ 0.14**（最强判别量）—— 篮网的网格结构产生高频边缘。
        实测真篮筐 0.165–0.282；画面低处的红色地板字/广告只有 0.090–0.110。
      · **面积 ≤ 1300** —— 真篮筐 338–788；地板红字 2020–2843。
      · 宽扁比 1.15–3.2 —— 真篮筐 1.68–2.41（侧视篮圈）；地板红字 3.5–5.4。
      · 下方带内白色像素占比 ≥ 0.20（篮网）。
    打分刻意**加重边缘与网、压低面积权重**：早期版本面积权重过大，
    导致画面低处的大块红色地板字压过真篮筐。
    """
    H_img, W_img = bgr.shape[:2]
    lbl_n, lab, stats, cent = cv2.connectedComponentsWithStats(red_rim_mask(bgr), 8)
    best = None
    cands = []
    for i in range(1, lbl_n):
        x, y, w, h, area = stats[i]
        if not (min_area <= area <= max_area):
            continue
        if y > H_img * y_frac_max:                 # 篮筐必在画面上部
            continue
        if h < 8 or w < 14:
            continue
        ar = w / max(h, 1)
        if not (ar_min <= ar <= ar_max):           # 侧视篮圈是宽扁的，但不能太扁
            continue
        wf, ed = net_score(bgr, (x, y, w, h))
        if wf < net_min or ed < edge_min:          # 必须有篮网（网格 → 高频边缘）
            continue
        score = ed * 22.0 + wf * 3.0 - area / 900.0 - abs(ar - 2.1) * 0.4
        cands.append({"box": [int(x), int(y), int(w), int(h)], "area": int(area),
                      "aspect": round(ar, 2), "white_frac": round(wf, 3),
                      "edge_dens": round(ed, 3), "score": round(score, 3)})
        if best is None or score > best["score"]:
            best = {"box": [int(x), int(y), int(w), int(h)], "score": round(score, 3),
                    "detail": {"area": int(area), "aspect": round(ar, 2),
                               "white_frac": round(wf, 3), "edge_dens": round(ed, 3)}}
    cands.sort(key=lambda c: -c["score"])
    return best, cands


# ─────────────────────── 跨帧跟踪 ───────────────────────
def track_hoop(frames, init_box, pad=60, search=90, drift=20, recheck_every=25):
    """用首帧模板做 NCC 逐帧定位；漂移过大则重捕。

    frames: [(idx, bgr), ...]   已按时间升序
    init_box: [x,y,w,h] 首帧篮筐框
    返回 [{idx, box, mode, ncc}]，mode ∈ template / redetect / hold / none
    """
    x, y, w, h = init_box
    pad = max(pad, 8)
    tmpl = None
    ref_box = init_box
    out = []
    since_redetect = 0
    for k, (idx, bgr) in enumerate(frames):
        H_img, W_img = bgr.shape[:2]
        box, mode, ncc = None, "none", None

        if tmpl is not None:
            rx, ry, rw, rh = ref_box
            sx0, sy0 = max(0, rx - search), max(0, ry - search)
            sx1, sy1 = min(W_img, rx + rw + search), min(H_img, ry + rh + search)
            win = bgr[sy0:sy1, sx0:sx1]
            th, tw = tmpl.shape[:2]
            if win.shape[0] >= th and win.shape[1] >= tw:
                res = cv2.matchTemplate(win, tmpl, cv2.TM_CCOEFF_NORMED)
                _, maxv, _, maxloc = cv2.minMaxLoc(res)
                bx, by = sx0 + maxloc[0] - pad, sy0 + maxloc[1] - pad
                ncc = float(maxv)
                bx = max(0, min(W_img - w, bx))
                by = max(0, min(H_img - h, by))
                box, mode = [int(bx), int(by), int(w), int(h)], "template"

        # 需要（或应当）重捕：无模板 / NCC 太低 / 漂移过大 / 周期复核
        need = (box is None or ncc is None or ncc < 0.45
                or (abs(box[0] - ref_box[0]) + abs(box[1] - ref_box[1])) > drift * 3
                or since_redetect >= recheck_every)
        if need:
            cand, _ = detect_hoop_single(bgr)
            if cand:
                box, mode, since_redetect = cand["box"], "redetect", 0
            elif box is None:
                out.append({"idx": idx, "box": None, "mode": "none", "ncc": None})
                tmpl = None
                continue
            else:
                since_redetect += 1
        else:
            since_redetect += 1

        tx, ty, tw_, th_ = box
        if (0 <= tx and 0 <= ty and tx + tw_ <= W_img and ty + th_ <= H_img
                and tw_ > 6 and th_ > 4):
            patch = bgr[ty:ty + th_, tx:tx + tw_]
            tmpl = patch.copy() if tmpl is None else cv2.addWeighted(tmpl, 0.7, patch, 0.3, 0)
            ref_box = box
        out.append({"idx": idx, "box": box, "mode": mode,
                    "ncc": round(ncc, 3) if ncc is not None else None})
    return out


def _ncc_step(bgr, ref_box, tmpl, search):
    """在 ref_box ± search 内做模板匹配，返回 (box, ncc)。"""
    H_img, W_img = bgr.shape[:2]
    rx, ry, rw, rh = ref_box
    sx0, sy0 = max(0, rx - search), max(0, ry - search)
    sx1, sy1 = min(W_img, rx + rw + search), min(H_img, ry + rh + search)
    win = bgr[sy0:sy1, sx0:sx1]
    th, tw = tmpl.shape[:2]
    if win.shape[0] < th or win.shape[1] < tw:
        return None, None
    res = cv2.matchTemplate(win, tmpl, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    bx = max(0, min(W_img - rw, sx0 + maxloc[0]))
    by = max(0, min(H_img - rh, sy0 + maxloc[1]))
    return [int(bx), int(by), int(rw), int(rh)], float(maxv)


def track_hoop_windowed(seq, tmap, anchor_t, anchor_box, win_sec,
                        search=55, ncc_good=0.60, ncc_min=0.30,
                        cross_check=True):
    """人工核实窗口内的**锚定跟踪**；窗口外绝不输出框。

    ── 为什么要这么设计 ─────────────────────────────────────────
    全自动篮圈定位在本素材已被证伪（见模块头：三个失败模式、6 个特征全部重叠）。
    诚实的做法只剩一条：以**人工核实的框**为锚，在**短窗**内用 NCC 跟随镜头平移，
    并明确记录每帧的 NCC 置信度。锚点帧的框就是人工真值本身——
    所以"锚点帧通过验证"是同义反复，**真正的质量指标是 NCC 与独立复核**，
    报告中必须这样表述，不得把它当作自动检测的成功。

    cross_check=True 时，每个窗内帧额外跑一次 `detect_hoop_single`，
    记录"独立单帧检测是否落在跟踪框 ±30px 内"——这是**弱但真实**的一致性证据。

    返回 (rows, cc) —— rows: [{idx, box, mode, ncc}]，cc: 交叉复核统计。
    """
    t0, t1 = win_sec
    in_win = [(i, b) for i, b in seq if t0 - 0.05 <= tmap.get(i, -1e9) <= t1 + 0.05]
    if not in_win:
        return [], {"n": 0, "hit": 0, "note": "窗口内无帧"}
    tidx = [i for i, _ in in_win]
    seed_k = min(range(len(tidx)), key=lambda k: abs(tmap[tidx[k]] - anchor_t))
    seed_i, seed_bgr = in_win[seed_k]

    rows = {seed_i: {"idx": seed_i, "box": list(anchor_box),
                     "mode": "verified_anchor", "ncc": None}}
    tmpl = seed_bgr[anchor_box[1]:anchor_box[1] + anchor_box[3],
                    anchor_box[0]:anchor_box[0] + anchor_box[2]].copy()
    if tmpl.size == 0:
        return [], {"n": 0, "hit": 0, "note": "锚点框越界"}

    def walk(order):
        ref = list(anchor_box)
        cur_tmpl = tmpl
        for k in order:
            i, bgr = in_win[k]
            box, ncc = _ncc_step(bgr, ref, cur_tmpl, search)
            if box is None:
                rows[i] = {"idx": i, "box": list(ref), "mode": "hold", "ncc": None}
                continue
            if ncc >= ncc_good:
                mode = "window_ncc"
                patch = bgr[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]
                if patch.size and patch.shape == cur_tmpl.shape:
                    cur_tmpl = cv2.addWeighted(cur_tmpl, 0.7, patch, 0.3, 0)
            elif ncc >= ncc_min:
                mode = "window_ncc_weak"
            else:
                mode = "degraded"
            rows[i] = {"idx": i, "box": box, "mode": mode, "ncc": round(ncc, 3)}
            if ncc >= ncc_min:
                ref = list(box)

    walk(list(range(seed_k + 1, len(in_win))))          # 向前
    walk(list(range(seed_k - 1, -1, -1)))               # 向后

    out = [rows[i] for i in tidx if i in rows]

    cc = {"n": 0, "hit": 0, "miss": 0, "no_det": 0, "detail": []}
    if cross_check:
        for r in out:
            i = r["idx"]
            bgr = dict(in_win)[i]
            cand, _ = detect_hoop_single(bgr)
            if not r["box"]:
                continue
            cx, cy = r["box"][0] + r["box"][2] / 2, r["box"][1] + r["box"][3] / 2
            if cand is None:
                cc["no_det"] += 1
                cc["detail"].append({"idx": i, "t": round(tmap[i], 1),
                                     "verdict": "no_detection", "dx": None, "dy": None})
                continue
            c2, c3 = cand["box"][0] + cand["box"][2] / 2, cand["box"][1] + cand["box"][3] / 2
            d = ((c2 - cx) ** 2 + (c3 - cy) ** 2) ** 0.5
            ok = d <= 30.0
            cc["n"] += 1
            cc["hit" if ok else "miss"] += 1
            cc["detail"].append({"idx": i, "t": round(tmap[i], 1),
                                 "verdict": "agree" if ok else "disagree",
                                 "dx": round(c2 - cx, 1), "dy": round(c3 - cy, 1),
                                 "dist": round(d, 1), "auto_box": cand["box"]})
    if cc["n"]:
        cc["rate"] = round(cc["hit"] / cc["n"], 3)
    return out, cc


def hoop_region(box, up=70, down=50, side=30):
    """把篮筐框扩成注意力区（覆盖球入筐前后的飞行轨迹）。"""
    if not box:
        return None
    x, y, w, h = box
    return (x - side, max(0, y - up), x + w + side, y + h + down)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--frames-json", default=None)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 帧（0=全部）")
    ap.add_argument("--verified-range", default="",
                    help="只在该时间窗内输出篮筐框（逗号分隔 t0,t1）。"
                         "窗口外一律 null —— 见模块头「实测结论」。"
                         "本片段窗口取 214,221.5（篮筐在此清晰可见，已人工核实）。")
    ap.add_argument("--anchor", default="219.5:1246,235,48,25",
                    help="人工核实的锚点。格式 t:x,y,w,h（默认 t=219.5 的 rim 真值）。")
    ap.add_argument("--anchor-search", type=int, default=55,
                    help="锚定跟踪的单帧搜索半径 px。")
    ap.add_argument("--no-cross-check", action="store_true",
                    help="跳过窗内逐帧独立单帧检测复核（更慢但更可审）。")
    a = ap.parse_args()

    vr = None
    if a.verified_range:
        xs = [float(v) for v in a.verified_range.split(",")]
        vr = (xs[0], xs[1])

    at, abox = None, None
    if a.anchor:
        lhs, rhs = a.anchor.split(":")
        at = float(lhs)
        abox = [int(v) for v in rhs.split(",")]

    if a.frames_json:
        meta = json.load(open(a.frames_json, encoding="utf-8"))
        idxs = [(r["idx"], r["t"]) for r in meta]
    else:
        fs = sorted(f for f in os.listdir(a.frames_dir) if f.startswith("f") and f.endswith(".jpg"))
        idxs = [(i, 204.5 + i / 10.0) for i in range(len(fs))]
    if a.limit:
        idxs = idxs[:a.limit]

    os.makedirs(a.outdir, exist_ok=True)
    # 先找首帧
    first_bgr = None
    for i, t in idxs:
        p = os.path.join(a.frames_dir, f"f{i+1:05d}.jpg")
        if os.path.exists(p):
            first_bgr = cv2.imread(p)
            first_i = i
            break
    if first_bgr is None:
        print("无帧"); return
    cand, allc = detect_hoop_single(first_bgr)
    print(f"首帧 f{first_i+1:05d} 单帧检测: {cand['box'] if cand else '❌ 未检出'}")
    if cand:
        print(f"  score={cand['score']} detail={cand['detail']}")
    print(f"  红色候选 {len(allc)} 个:")
    for c in allc[:6]:
        ok = "✅" if (c["white_frac"] >= 0.045 and c["edge_dens"] >= 0.055) else "  "
        print(f"   {ok} box={c['box']} area={c['area']} ar={c['aspect']} "
              f"白网={c['white_frac']} 边缘={c['edge_dens']} score={c['score']}")

    if not cand:
        # 用第一帧兜底：取红色候选中最大的
        if allc:
            cand = {"box": allc[0]["box"]}
        else:
            print("首帧无红色候选，无法跟踪"); return

    seq = []
    for i, t in idxs:
        p = os.path.join(a.frames_dir, f"f{i+1:05d}.jpg")
        if os.path.exists(p):
            seq.append((i, cv2.imread(p)))
    tmap = {i: t for i, t in idxs}

    cc = None
    if vr and at is not None:
        print(f"\n── 锚定跟踪模式：窗口 {vr[0]}–{vr[1]}s，锚点 t={at} box={abox} ──")
        print("   （全自动定位已证伪，见模块头；窗口外一律 null）")
        res, cc = track_hoop_windowed(seq, tmap, at, abox, vr,
                                      search=a.anchor_search,
                                      cross_check=not a.no_cross_check)
    else:
        res = track_hoop(seq, cand["box"])
    resmap = {r["idx"]: r for r in res}

    out = []
    n_ok = n_out = 0
    for i, t in idxs:
        if vr and not (vr[0] - 0.05 <= t <= vr[1] + 0.05):
            n_out += 1
            out.append({"idx": i, "t": t, "frame": i + 1, "hoop_box": None,
                        "mode": "outside_window", "ncc": None, "region": None})
            continue
        r = resmap.get(i)
        if r is None:
            n_out += 1
            out.append({"idx": i, "t": t, "frame": i + 1, "hoop_box": None,
                        "mode": "no_row", "ncc": None, "region": None})
            continue
        b = r["box"]
        if b:
            n_ok += 1
        out.append({"idx": i, "t": t, "frame": i + 1,
                    "hoop_box": b, "mode": r["mode"], "ncc": r["ncc"],
                    "region": list(hoop_region(b)) if b else None})

    p = os.path.join(a.outdir, "hoop_track.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n跟踪 {len(out)} 帧：有框 {n_ok}，窗口外 null {n_out}")
    modes = {}
    for r in out:
        modes[r["mode"]] = modes.get(r["mode"], 0) + 1
    print("  模式分布:", modes)
    print(f"[out] {p}")

    # ── 验证点：t=219.5 应落在 (1246,235,48,25) ±20px 内 ──
    for r in out:
        if r["t"] is not None and abs(r["t"] - 219.5) < 0.06:
            b = r["hoop_box"]
            if b:
                cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
                ex, ey = 1246 + 48 / 2, 235 + 25 / 2
                d = ((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5
                tag = "✅ 通过" if d <= 20 else "❌ 超差"
                print(f"\n🎯 验证点 t=219.5 box={b} 中心({cx:.0f},{cy:.0f}) "
                      f"vs 真值({ex:.0f},{ey:.0f}) → 误差 {d:.1f}px {tag}")
                print("   ⚠️ 该帧即锚点帧，等价性检查（同义反复），"
                      "真正的质量指标见下：")
            else:
                print("\n🎯 验证点 t=219.5 → 无框（应为锚点，异常）")

    if cc:
        q = os.path.join(a.outdir, "hoop_crosscheck.json")
        with open(q, "w", encoding="utf-8") as f:
            json.dump(cc, f, ensure_ascii=False, indent=1)
        if cc["n"]:
            print(f"\n🔎 窗内独立单帧检测复核（±30px 判一致）："
                  f"{cc['hit']}/{cc['n']} = {cc['rate']*100:.1f}%"
                  f"   （无检出 {cc.get('no_det',0)} 帧）")
        else:
            print(f"\n🔎 窗内独立单帧检测复核：全部无检出（无检出 {cc.get('no_det',0)} 帧）")
        print(f"[out] {q}")


if __name__ == "__main__":
    main()
