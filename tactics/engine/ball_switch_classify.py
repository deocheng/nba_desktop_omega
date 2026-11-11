#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ball_switch_classify —— Q1/Q2 假阳性分离（路线 A 收尾，纯数据零标注）。

对「球没动时发生的持球人 ID 变更」(Q1+Q2 全集) 做三类**互斥**分类：
  ① replace（ID 漂移/重连）：新 ID b 在 t 帧不存在(是 t+1 新生 track)。
        ⇒ 旧 ID a 的框被重新分配成新 track b，最确定性的一人两 ID。
  ② twin（双胞胎）：b 在 t 帧已存在，且 a、b 在 t+1 帧共存且两框中心距/平均框高<0.3。
        ⇒ 同一物理位置被两个 track 同时占 ⇒ 一人两 ID。
  ③ two_real（贴身两人）：其余(b 在 t 帧已存在且非双胞胎)。
        ⇒ 两个真人在球附近，holder 判定在两人间跳，非 ID 错误。

判据复用 ball_holder_identity 的辅助函数（已视觉自证过的口径）：
  R_HOLD=0.5 判持球人；R_BALL_MOVE=0.5 判球没动(归一球自身框高)；
  SWITCH_R=0.5 区分"人框没动/动了"；TWIN=0.3 判同位置。

用法：
  python3 ball_switch_classify.py --root action_work/norm_g3
  python3 ball_switch_classify.py --root action_work/norm_g3 --visual /tmp/q1cls
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ball_holder_identity as B  # noqa: E402

SEGBASE = Path(str(tactics_data_file("action_work/tactic_notes_batch_full/segments")))
R_HOLD = 0.50
R_BALL_MOVE = 0.50
SWITCH_R = 0.50
TWIN = 0.30


def ball_still(d, i):
    bb_t = (d[i].get("ball") or {}).get("bbox") or [0, 0, 0, 0]
    bb_n = (d[i + 1].get("ball") or {}).get("bbox") or [0, 0, 0, 0]
    bh = 0.5 * (B.box_h(bb_t) + B.box_h(bb_n))
    if bh <= 1:
        return False
    return (B.cdist(bb_t, bb_n) / bh) < R_BALL_MOVE


def classify_seg(d):
    hs = [h if (h and h[1] < R_HOLD) else None for h in (B.holder_of(r) for r in d)]
    c = {"replace": 0, "twin": 0, "two_real": 0}
    for i in range(len(d) - 1):
        a, b = hs[i], hs[i + 1]
        if not (a and b) or a[0] == b[0]:
            continue
        if not ball_still(d, i):          # 只分析「球没动」的换 ID（Q1+Q2 全集）
            continue
        ta, tb = a[0], b[0]
        b_at_t = B.box_by_pid(d[i], tb) is not None
        if not b_at_t:
            c["replace"] += 1
            continue
        a_at_t1 = B.box_by_pid(d[i + 1], ta)
        bb_at_t1 = B.box_by_pid(d[i + 1], tb)
        if a_at_t1 and bb_at_t1:
            h = 0.5 * (B.box_h(a_at_t1) + B.box_h(bb_at_t1))
            if B.cdist(a_at_t1, bb_at_t1) / max(1.0, h) < TWIN:
                c["twin"] += 1
                continue
        c["two_real"] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="action_work/norm_g3")
    ap.add_argument("--seg", nargs="*", default=[])
    ap.add_argument("--visual", default="")
    ap.add_argument("--n-per", type=int, default=2)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    root = Path(a.root)
    segs = a.seg or sorted(d.name for d in root.iterdir()
                           if d.is_dir() and (d / "ball_tracks.json").exists())

    rows = []
    for s in segs:
        d = json.loads((root / s / "ball_tracks.json").read_text(encoding="utf-8"))
        c = classify_seg(d)
        rows.append({"seg": s, **c, "total": sum(c.values())})

    s_ = lambda k: sum(r[k] for r in rows)
    tot = s_("total")
    print(f"{'段':<12}{'球没动换ID':>11}{'replace/重连':>13}{'twin/双胞胎':>13}{'two_real/贴身':>14}")
    print("-" * 64)
    for r in rows[:40]:
        print(f"{r['seg']:<12}{r['total']:>11}{r['replace']:>13}{r['twin']:>13}{r['two_real']:>14}")
    print("\n=== 全语料汇总（球没动时发生的持球人 ID 变更 = Q1+Q2 全集）===")
    print(f"  总事件            : {tot}")
    print(f"  replace 重连/漂移 : {s_('replace'):>5}  ({s_('replace')/max(1,tot)*100:5.1f}%)  ← 确定性一人两 ID")
    print(f"  twin   双胞胎     : {s_('twin'):>5}  ({s_('twin')/max(1,tot)*100:5.1f}%)  ← 一人两 ID(同位置双 track)")
    print(f"  two_real 贴身两人 : {s_('two_real'):>5}  ({s_('two_real')/max(1,tot)*100:5.1f}%)  ← 非 ID 错误(holder 抖动)")
    print(f"  ⇒ 真·身份错误(replace+twin) = {s_('replace')+s_('twin')} "
          f"({ (s_('replace')+s_('twin'))/max(1,tot)*100:.1f}% of 球没动换ID)")

    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote", a.json)

    if a.visual:
        out = Path(a.visual); out.mkdir(parents=True, exist_ok=True)
        draw_samples(root, segs, out, n_per=a.n_per)


def draw_samples(root, segs, out, n_per=2):
    """每类随机挑 n_per 个样本画 t / t+1 对照；两帧都画 a(绿)+b(蓝)。"""
    np.random.seed(11)
    buckets = {"replace": [], "twin": [], "two_real": []}
    for s in segs:
        d = json.loads((root / s / "ball_tracks.json").read_text(encoding="utf-8"))
        hs = [h if (h and h[1] < R_HOLD) else None for h in (B.holder_of(r) for r in d)]
        for i in range(len(d) - 1):
            a, b = hs[i], hs[i + 1]
            if not (a and b) or a[0] == b[0] or not ball_still(d, i):
                continue
            ta, tb = a[0], b[0]
            if B.box_by_pid(d[i], tb) is None:
                kind = "replace"
            elif (B.box_by_pid(d[i + 1], ta) and B.box_by_pid(d[i + 1], tb)
                  and B.cdist(B.box_by_pid(d[i + 1], ta), B.box_by_pid(d[i + 1], tb)) /
                  (0.5 * (B.box_h(B.box_by_pid(d[i + 1], ta)) + B.box_h(B.box_by_pid(d[i + 1], tb))))
                  < TWIN):
                kind = "twin"
            else:
                kind = "two_real"
            buckets[kind].append((s, i, ta, tb))
    fs_cache = {}
    for kind, items in buckets.items():
        picks = np.random.choice(len(items), min(n_per, len(items)), replace=False)
        for k in picks:
            s, i, ta, tb = items[k]
            if s not in fs_cache:
                fs_cache[s] = sorted((SEGBASE / s / "frames").glob("*.jpg"))
            d = json.loads((root / s / "ball_tracks.json").read_text(encoding="utf-8"))
            cells = []
            for off in (0, 1):
                rec = d[i + off]
                im = cv2.imread(str(fs_cache[s][i + off]))
                if im is None:
                    continue
                im = cv2.resize(im, (880, 495))
                for tid, col in ((ta, (0, 255, 0)), (tb, (255, 0, 0))):
                    pb = B.box_by_pid(rec, tid)
                    if pb:
                        cv2.rectangle(im, [int(v) for v in pb], col, 5)
                        cv2.putText(im, f"id={tid}", [int(pb[0]), max(14, int(pb[1]) - 10)],
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, col, 2)
                ball = rec.get("ball") or {}
                if ball.get("bbox"):
                    bx = [int(v) for v in ball["bbox"]]
                    cv2.rectangle(im, bx[:2], bx[2:], (40, 40, 235), 3)
                cv2.putText(im, f"{s} f{rec.get('frame')}{'(t)' if off==0 else '(t+1)'} 绿=id{ta} 蓝=id{tb}",
                            (8, 484), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cells.append(im)
            if len(cells) == 2:
                H, W = cells[0].shape[:2]
                pad = np.full((H, 10, 3), 40, np.uint8)
                cv2.imwrite(str(out / f"{kind}_{s}_{i}.png"),
                            np.hstack([cells[0], pad, cells[1]]))
                print(f"wrote {out}/{kind}_{s}_{i}.png  id{tid}→...")


if __name__ == "__main__":
    main()
