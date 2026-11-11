#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全片粗扫：找「比赛进行中」的连续段落，再按活跃度形态挑完整配合候选。
不目视，只用可算指标。低采样（每 stride 帧取1）以处理 1~2 小时长片。
输出：活跃度序列 + 切镜点 + 候选配合区间（形态判据：低谷→上升→峰）。
"""
import json
import os
import sys

import cv2
import numpy as np

STRIDE = 10          # 每10帧取1（60fps→6Hz）
SB_Y0F, SB_Y1F = 0.80, 0.96


def scan(path, stride=STRIDE, max_sec=None):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if max_sec:
        n = min(n, int(max_sec * fps))
    prev = None
    ts, act, sbv = [], [], []
    i = 0
    while i < n:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            break
        small = cv2.cvtColor(cv2.resize(fr, None, fx=0.25, fy=0.25), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            act.append(float(np.mean(cv2.absdiff(small, prev))))
            ts.append(i / fps)
        prev = small
        h = fr.shape[0]
        sb = cv2.resize(fr[int(h * SB_Y0F):int(h * SB_Y1F), :], (32, 6))
        sbv.append(cv2.cvtColor(sb, cv2.COLOR_BGR2GRAY).astype(np.float32).ravel())
        i += stride
    cap.release()
    return fps, np.array(ts), np.array(act), np.array(sbv)


def find_segments(ts, act, low_thr=None, min_len_s=6.0, merge_gap_s=1.5):
    """活跃度 > 阈值的连续段 = 比赛进行中"""
    if low_thr is None:
        low_thr = np.percentile(act, 35)
    mask = act > low_thr
    segs, cur = [], None
    for j, m in enumerate(mask):
        if m:
            if cur is None:
                cur = [j, j]
            else:
                cur[1] = j
        else:
            if cur is not None:
                segs.append(cur); cur = None
    if cur:
        segs.append(cur)
    out = []
    for a, b in segs:
        s, e = ts[a], ts[b]
        if e - s >= min_len_s:
            if out and s - out[-1][1] <= merge_gap_s:
                out[-1][1] = e
            else:
                out.append([s, e])
    return out, low_thr


def shape_ok(seg_act):
    """完整配合形态：低谷→上升→峰"""
    if len(seg_act) < 5:
        return False, None
    b = seg_act[1:]
    pk = int(np.argmax(b))
    if pk == 0:
        return False, None
    tr = int(np.argmin(b[:pk + 1]))
    rise = b[pk] - b[tr]
    dec = sum(1 for j in range(1, len(b)) if b[j] < b[j - 1]) / (len(b) - 1)
    ok = (tr < pk) and (rise > 3.0)
    return ok, {"trough": round(float(b[tr]), 2), "peak": round(float(b[pk]), 2),
                "rise": round(float(rise), 2), "dec_frac": round(float(dec), 2)}


if __name__ == "__main__":
    path = sys.argv[1]
    max_sec = float(sys.argv[2]) if len(sys.argv) > 2 else None
    out = sys.argv[3] if len(sys.argv) > 3 else "/tmp/scan.json"
    print("扫描:", os.path.basename(path))
    fps, ts, act, sbv = scan(path, max_sec=max_sec)
    print(f"  采样点={len(ts)}  跨度={ts[-1]/60:.1f}min  "
          f"活跃度 中位={np.median(act):.1f} p90={np.percentile(act,90):.1f} 最大={act.max():.1f}")
    segs, thr = find_segments(ts, act)
    print(f"  活跃段阈值={thr:.1f}  找到 {len(segs)} 段")
    cands = []
    for s, e in segs:
        m = (ts >= s) & (ts <= e)
        a = act[m]
        ok, info = shape_ok(a)
        cands.append({"start": round(float(s), 1), "end": round(float(e), 1),
                      "dur": round(float(e - s), 1), "shape_ok": ok, "info": info,
                      "act_peak": round(float(a.max()), 1), "act_med": round(float(np.median(a)), 1)})
    good = [c for c in cands if c["shape_ok"] and c["dur"] >= 6]
    print(f"\n=== 候选配合（形态合格 & ≥6s）：{len(good)}/{len(cands)} ===")
    print(f"{'起':<8}{'止':<8}{'时长':<7}{'谷':<8}{'峰':<8}{'升幅':<8}{'递减占比':<9}活跃中位")
    for c in sorted(good, key=lambda x: -x["info"]["rise"])[:25]:
        i = c["info"]
        print(f"{c['start']:<8}{c['end']:<8}{c['dur']:<7}{i['trough']:<8}{i['peak']:<8}"
              f"{i['rise']:<8}{i['dec_frac']:<9}{c['act_med']}")
    json.dump({"file": os.path.basename(path), "fps": fps, "n_samples": len(ts),
               "candidates": cands, "good": good}, open(out, "w"), ensure_ascii=False, indent=1)
    print("\nwrote", out)
