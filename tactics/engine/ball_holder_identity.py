#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ball_holder_identity —— 门①-B 的**球锚点**路线（老程 10-02 批准，路线 A）。

### 为什么需要它（承 A5.31e）
门①-A 只证明「ID 个数 = 检测框个数」。它**测不出身份漂移**：
一个人把 ID 让给别人，框依然连续、运动依然平滑、寿命依然长 —— 身份错误
正好落在所有自洽性指标的盲区。上任何模型这个盲区都在。

### 球锚点能给什么、不能给什么（必须先划清，否则又绕回循环论证）
✅ 能：每帧有一个**独立于球员检测的球位置**（`ball:{bbox,conf}`，独立通道）。
   ⇒ "t 时刻球在谁的框里/最近" 是**物理可判**的命题，不依赖跟踪器。
   ⇒ 球有**自己的运动**，所以可以判「球没动、人也基本没动、ID 却换了」——
      这一条是**纯物理不自洽**，把"漏检导致 track 重连"排除在外（门①-A 那段盲区）。
❌ 不能：它给不了"这个人穿几号"。只能锚住**持球位置**，给不了队内身份。
   （队服颜色只能分队，A5.31c；号码 OCR 已于 A5.12 证伪无判别力。）

### 🔴 已自我推翻的一处（10-02 自证，勿复活）
初版用 `BALL_CONF=0.50` 过滤"不可信球"。实测**该门槛无证据支持**：
按 conf 分层看球框到最近球员的距离 —— conf<0.05 中位 23.8px / p90 196.6px，
conf>=0.50 中位 9.6px / p90 99.4px，框宽 18.5 vs 22.2。**conf 与球框质量不相关**。
⇒ 改成物理判据：用 `r_ball = 球中心到最近球员框的距离 / 该框高` 判"有没有持球人"，
   样本 314 帧（3%）→ 8455 帧（总帧 27.2%）。conf 只记录不设门。

### 指标（可证伪，不是凑好看的）
对相邻两帧 t、t+1 都有持球人（r_ball < R_HOLD）的情况：
  · 若 holder ID 相同 → 统计运动连续性（同 ID 却大幅位移 = 真·跳人）
  · 若 holder ID 变了 → 取球位移 d_ball 与新老持球人框的中心距 d_h，按各自/平均框高归一：
        ① 球没动(d_ball<R_BALL_MOVE) + 新框≈旧框(d_h<SWITCH_R) ⇒ **铁证漂移**（一人分多 ID）
        ② 球没动 + 新框远离旧框 ⇒ 物理矛盾（异常，记录）
        ③ 球动了 + 新框≈旧框 ⇒ 弱嫌疑（运球微动 / 边界抖动）
        ④ 球动了 + 新框远离旧框 ⇒ 正常换手（传球、抢断）

### 用法
  python3 ball_holder_identity.py --root action_work/norm_g3
  python3 ball_holder_identity.py --seg ep77_s0 ep41_s1 --render /tmp/holder.png
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

SEGBASE = Path(str(tactics_data_file("action_work/tactic_notes_batch_full/segments")))

R_HOLD = 0.50          # 球中心到最近球员框的距离/框高 < 此值 ⇒ 判"有持球人"
SWITCH_R = 0.50        # 新老持球人框中心距/平均框高 的分界（景别无关）
R_BALL_MOVE = 0.50
_BALL_H = []            # 采样用：所有球框高（景别分布）     # 球在相邻帧位移/平均框高 的分界（大了=球在动：传球/运球）

# ---------------------------------------------------------------- 基础量


def ct(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def box_h(b):
    return max(1.0, b[3] - b[1])


def dist_point_box(p, b):
    dx = max(b[0] - p[0], 0.0, p[0] - b[2])
    dy = max(b[1] - p[1], 0.0, p[1] - b[3])
    return float((dx * dx + dy * dy) ** 0.5)


def center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def cdist(b1, b2):
    c1, c2 = center(b1), center(b2)
    return float(((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5)


def holder_of(rec):
    """返回 (track_id, r_ball, 框高)；球框缺失或帧内无球员时返回 None。"""
    ball = rec.get("ball") or {}
    b = ball.get("bbox")
    if not b:
        return None
    _BALL_H.append(box_h(b))
    bc = ct(b)
    best, bd = None, None
    for p in (rec.get("players") or []):
        pb = p.get("bbox")
        if not pb:
            continue
        d = dist_point_box(bc, pb)
        if bd is None or d < bd:
            bd, best = d, p
    if best is None:
        return None
    h = box_h(best["bbox"])
    return (best.get("track_id"), bd / h, h)


def box_by_pid(rec, tid):
    for p in (rec.get("players") or []):
        if p.get("track_id") == tid and p.get("bbox"):
            return p["bbox"]
    return None


# ---------------------------------------------------------------- 单段
def analyze(root: Path, seg, r_hold=R_HOLD):
    d = json.loads((root / seg / "ball_tracks.json").read_text(encoding="utf-8"))
    hs = []
    for r in d:
        h = holder_of(r)
        hs.append(h if (h and h[1] < r_hold) else None)

    n = len(d)
    n_hold = sum(1 for x in hs if x)
    q1 = q2 = q3 = q4 = 0                 # 四象限
    switch_n = same_move = same_stick = 0
    r_dh, r_db = [], []

    for i in range(n - 1):
        a, b = hs[i], hs[i + 1]
        if a is None or b is None:
            continue
        ba, bb = box_by_pid(d[i], a[0]), box_by_pid(d[i + 1], b[0])
        if ba is None or bb is None:
            continue
        h_avg = 0.5 * (box_h(ba) + box_h(bb))
        d_h = cdist(ba, bb) / max(1.0, h_avg)          # 新老持球人框的差（归一球员框高）
        # 🔴 球的位移必须归一到**球自身框高**：球的投影尺度随景别变，用球员框高归一化
        #    会让特写帧的 d_ball 系统性偏小 ⇒ 「球没动」判据在不同景别下不等价。
        bb_t = (d[i].get("ball") or {}).get("bbox") or [0, 0, 0, 0]
        bb_n = (d[i + 1].get("ball") or {}).get("bbox") or [0, 0, 0, 0]
        bh = 0.5 * (box_h(bb_t) + box_h(bb_n))
        d_b = cdist(bb_t, bb_n) / max(1.0, bh) if bh > 1 else 99.0
        if a[0] != b[0]:
            switch_n += 1
            r_dh.append(d_h)
            r_db.append(d_b)
            ball_still, move_far = (d_b < R_BALL_MOVE), (d_h >= SWITCH_R)
            if ball_still and not move_far:
                q1 += 1                                 # 铁证漂移
            elif ball_still and move_far:
                q2 += 1                                 # 物理矛盾
            elif (not ball_still) and not move_far:
                q3 += 1                                 # 弱嫌疑
            else:
                q4 += 1                                 # 正常换手
        else:
            if d_h >= SWITCH_R:
                same_move += 1
            else:
                same_stick += 1

    def med(x):
        return round(float(np.median(x)), 3) if x else None

    return {
        "seg": seg, "n_frames": n, "n_hold": n_hold,
        "hold_rate": round(n_hold / max(1, n), 3),
        "switch_n": switch_n,
        "Q1_铁证漂移": q1, "Q2_物理矛盾": q2,
        "Q3_弱嫌疑": q3, "Q4_正常换手": q4,
        "Q1_rate": round(q1 / max(1, switch_n), 3),
        "same_move": same_move,
        "same_stick": same_stick,
        "same_move_rate": round(same_move / max(1, same_stick + same_move), 3),
        "d_h_switch_med": med(r_dh), "d_ball_switch_med": med(r_db),
        "ball_h_med": round(float(np.median(_BALL_H)), 1) if _BALL_H else None,
    }


# ---------------------------------------------------------------- 深入：漂移 vs 双胞胎 + ID 寿命
def alive_after(d, i, tid, k):
    """ID 在 i+k 帧之后是否还出现在 players 里。"""
    if i + k >= len(d):
        return None
    for p in (d[i + k].get("players") or []):
        if p.get("track_id") == tid:
            return True
    return False


def drift_fate(root: Path, seg):
    """Q1 事件后，旧 holder 的 ID 去哪了：
       vanished=被夺走（ID 漂移）｜alive=同一物理人被两个 ID 占（双胞胎，更严重）"""
    d = json.loads((root / seg / "ball_tracks.json").read_text(encoding="utf-8"))
    hs = [holder_of(r) for r in d]
    van = alive = 0
    for i in range(len(d) - 1):
        a, b = hs[i], hs[i + 1]
        if not (a and b) or a[0] == b[0]:
            continue
        ba, bb = box_by_pid(d[i], a[0]), box_by_pid(d[i + 1], b[0])
        if not (ba and bb):
            continue
        bh = 0.5 * (box_h((d[i].get("ball") or {}).get("bbox") or [0, 0, 0, 0])
                    + box_h((d[i + 1].get("ball") or {}).get("bbox") or [0, 0, 0, 0]))
        db_ = cdist((d[i].get("ball") or {}).get("bbox") or [0, 0, 0, 0],
                    (d[i + 1].get("ball") or {}).get("bbox") or [0, 0, 0, 0])
        db_ = db_ / max(1.0, bh) if bh > 1 else 99.0
        dh_ = cdist(ba, bb) / max(1.0, 0.5 * (box_h(ba) + box_h(bb)))
        if db_ < R_BALL_MOVE and dh_ < SWITCH_R:
            k = 5
            while alive_after(d, i, a[0], k) is None:
                k *= 2
                if k > len(d):
                    break
            v = alive_after(d, i, a[0], min(k, len(d) - 1))
            if v:
                alive += 1
            else:
                van += 1
    return {"seg": seg, "Q1_oldID_vanished": van, "Q1_oldID_alive": alive}


def holder_stints(root: Path, seg, r_hold=R_HOLD):
    """持球人 ID 的连续持有段长度（帧）。中位数 = 持球人平均能保住同一个 ID 多少帧。"""
    d = json.loads((root / seg / "ball_tracks.json").read_text(encoding="utf-8"))
    cur, start = None, None
    out = []
    for i, r in enumerate(d):
        h = holder_of(r)
        tid = h[0] if (h and h[1] < r_hold) else None
        if tid != cur:
            if cur is not None and start is not None and i - start > 1:
                out.append(i - start)
            cur, start = tid, i
        else:
            continue
    if cur is not None and start is not None:
        out.append(len(d) - start)
    return {"seg": seg, "stints": sorted(out)}


# ---------------------------------------------------------------- 视觉自证
def render(root: Path, seg, out="/tmp/holder.png", ncells=4):
    d = json.loads((root / seg / "ball_tracks.json").read_text(encoding="utf-8"))
    fs = sorted((SEGBASE / seg / "frames").glob("*.jpg")) or \
        sorted((SEGBASE / seg / "frames").glob("*.png"))
    idx = [i for i, r in enumerate(d)
           if (holder_of(r) and holder_of(r)[1] < R_HOLD)]
    if not idx:
        print("该段无持球帧"); return
    step = max(1, len(idx) // ncells)
    pick = idx[::step][:ncells]
    cells = []
    for fi in pick:
        im = cv2.imread(str(fs[fi]))
        if im is None:
            continue
        im = cv2.resize(im, (880, 495))
        rec = d[fi]
        ball = rec.get("ball") or {}
        h = holder_of(rec)
        if ball.get("bbox"):
            x1, y1, x2, y2 = [int(v) for v in ball["bbox"]]
            cv2.rectangle(im, (x1, y1), (x2, y2), (40, 40, 235), 3)
            cv2.putText(im, f"ball c={ball.get('conf', 0):.2f} r={h[1]:.2f}",
                        (x1, max(14, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 235), 2)
        if h:
            bb = box_by_pid(rec, h[0])
            if bb:
                x1, y1, x2, y2 = [int(v) for v in bb]
                cv2.rectangle(im, (x1, y1), (x2, y2), (0, 255, 0), 4)
                cv2.putText(im, f"holder id={h[0]} h={int(h[2])}px",
                            (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(im, f"{seg} f{rec.get('frame')}  绿=持球人 红=球 白=其他球员",
                    (8, 484), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        for p in (rec.get("players") or []):
            pb = p.get("bbox")
            if not pb or (h and p.get("track_id") == h[0]):
                continue
            cv2.rectangle(im, [int(v) for v in pb], (220, 220, 220), 1)
        cells.append(im)
    if not cells:
        print("无帧可画"); return
    h_, w_ = cells[0].shape[:2]
    pad = np.full((h_, 10, 3), 40, np.uint8)
    cols = [cells[i:i + 2] for i in range(0, len(cells), 2)]
    for c in cols:
        if len(c) < 2:
            c.append(np.zeros_like(cells[0]))
    h, w = cells[0].shape[:2]
    out_im = np.zeros((h * len(cells) + 10 * (len(cells) - 1), w, 3), np.uint8)
    for i, im in enumerate(cells):
        y = i * (h + 10)
        out_im[y:y + h, 0:w] = im
        if i + 1 < len(cells):
            out_im[y + h:y + h + 10, 0:w] = pad[:, :, 0]
    cv2.imwrite(out, out_im)
    print("wrote", out, "cells", len(cells))


# ---------------------------------------------------------------- 主
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="action_work/norm_g3")
    ap.add_argument("--seg", nargs="*", default=[])
    ap.add_argument("--render", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--r-hold", type=float, default=R_HOLD)
    a = ap.parse_args()

    root = Path(a.root)
    if a.render:
        render(root, a.seg[0] if a.seg else "ep77_s0", a.render)
        return

    segs = a.seg or sorted(d.name for d in root.iterdir()
                           if d.is_dir() and (d / "ball_tracks.json").exists())
    rows = [analyze(root, s, a.r_hold) for s in segs]

    hdr = (f"{'段':<11}{'帧':>5}{'持球帧':>7}{'持球率':>7}{'换ID':>6}"
           f"{'Q1铁证':>7}{'Q2矛盾':>7}{'Q3弱':>6}{'Q4正常':>7}{'Q1率':>7}"
           f"{'同ID位移':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows[:40]:
        print(f"{r['seg']:<11}{r['n_frames']:>5}{r['n_hold']:>7}{r['hold_rate']:>7.2f}"
              f"{r['switch_n']:>6}{r['Q1_铁证漂移']:>7}{r['Q2_物理矛盾']:>7}"
              f"{r['Q3_弱嫌疑']:>6}{r['Q4_正常换手']:>7}{r['Q1_rate']:>7.2f}"
              f"{r['same_move']:>8}")

    n = len(rows)
    s_ = lambda k: sum(r[k] for r in rows)
    nf, nh = s_("n_frames"), s_("n_hold")
    print(f"\n段数 {n}  总帧 {nf}  持球帧 {nh}（{nh/max(1,nf)*100:.1f}%）"
          f"  换持球人ID {s_('switch_n')} 次")
    print(f"  Q1 球没动+人框没换+ID换了（铁证一人分多ID）: {s_('Q1_铁证漂移')}"
          f"  = {s_('Q1_铁证漂移')/max(1,s_('switch_n'))*100:.1f}% 的 ID 变更")
    print(f"  Q2 球没动+人框换到远处（物理矛盾）        : {s_('Q2_物理矛盾')}")
    print(f"  Q3 球动了+人框没换  （弱嫌疑/边界抖动）    : {s_('Q3_弱嫌疑')}")
    print(f"  Q4 球动了+人框换到远（正常传球/抢断）      : {s_('Q4_正常换手')}")
    n_same = sum(r["same_move"] + r["same_stick"] for r in rows)
    print(f"  同 ID 却大幅位移（真·跳人）: {s_('same_move')}"
          f" = {s_('same_move')/max(1,n_same)*100:.1f}% 的持有连续帧")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote", a.json)


if __name__ == "__main__":
    main()
