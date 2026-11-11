#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ball_label_filter2.py — 运动补偿帧差过滤（里程碑 12 点名方案）。
用相位相关估计相邻帧全局平移(镜头摇移)，扣除后：
  - 静止的场上物体(logo/地板补丁) 在补偿后残差≈0 → 判为静止 → 剔除
  - 真正相对球场运动的物体(球) 残差显著 → 保留
再对保留候选跨帧链化(链长≥min_chain)，输出高精度球候选。
不依赖人工目视，规避里程碑12「手工判据天花板≈44%」。
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def fidx(name):
    import re
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0


def fname(idx, ref):
    """按参考帧名的前缀/后缀拼出第 idx 帧名，如 f00001.jpg。"""
    import re
    prefix = ref.split("0")[0] if "0" in ref else ref[0]
    ext = ref.rsplit(".", 1)[-1]
    return f"{prefix}{idx:05d}.{ext}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates_json")
    ap.add_argument("frames_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--static-tol", type=float, default=8.0,
                    help="补偿后与静态对应点匹配容差(px, 全分辨率)")
    ap.add_argument("--chain-tol", type=float, default=60.0,
                    help="链化相邻帧最大步长(px)")
    ap.add_argument("--min-chain", type=int, default=3)
    ap.add_argument("--min-resid", type=float, default=10.0,
                    help="链内净位移下限(px)")
    args = ap.parse_args()

    cands = json.loads(Path(args.candidates_json).read_text())
    names = sorted(cands.keys())
    if not names:
        Path(args.out).write_text("{}")
        print("empty")
        return

    # 相邻帧全局平移（相位相关，降采样加速）
    DS = 480.0
    shifts = {}  # name -> (dx, dy) 全分辨率, 表示 prev->cur
    prev_name = None
    prev_small = None
    for n in names:
        img = cv2.imread(str(Path(args.frames_dir) / n), cv2.IMREAD_GRAYSCALE)
        if img is None:
            prev_name = n
            prev_small = None
            continue
        h, w = img.shape
        sc = DS / w
        small = cv2.resize(img, (int(w * sc), int(h * sc))).astype(np.float32)
        if prev_small is not None and prev_name is not None and fidx(n) - fidx(prev_name) == 1:
            (dx, dy), resp = cv2.phaseCorrelate(prev_small, small)
            shifts[n] = (dx / sc, dy / sc)
        prev_name = n
        prev_small = small

    def center(c):
        b = c["bbox"]
        return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)

    # 标记：对每个候选，找它在上一帧的"静态对应位置"；若无匹配 → 相对球场运动
    moving = {}
    for n in names:
        lst = cands[n]
        if not lst:
            continue
        if n not in shifts:
            moving[n] = list(lst)  # 无平移信息（首帧/跳帧）先全留
            continue
        dx, dy = shifts[n]
        prev = cands.get(fname(fidx(n) - 1, n), [])
        prev_centers = [center(c) for c in prev]
        kept = []
        for c in lst:
            cx, cy = center(c)
            px, py = cx - dx, cy - dy  # 静态对应预测位置
            matched = any(((px - qx) ** 2 + (py - qy) ** 2) ** 0.5 <= args.static_tol
                          for (qx, qy) in prev_centers)
            if not matched:
                kept.append(c)
        moving[n] = kept

    # 链化 moving 候选
    all_keep = []
    chains = []
    for n in names:
        cur = moving.get(n, [])
        prev_n = fname(fidx(n) - 1, n)
        prev = moving.get(prev_n, [])
        pairs = []
        for ic, c in enumerate(prev):
            cx, cy = center(c)
            for jc, d in enumerate(cur):
                ex, ey = center(d)
                dist = ((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5
                if dist <= args.chain_tol:
                    pairs.append((dist, (prev_n, ic), (n, jc)))
        pairs.sort()
        used_prev, used_cur = set(), set()
        for dist, a, b in pairs:
            if a in used_prev or b in used_cur:
                continue
            used_prev.add(a)
            used_cur.add(b)
            ca = next((ch for ch in chains if ch[-1] == a), None)
            cb = next((ch for ch in chains if ch and ch[0] == b), None)
            if ca is not None and cb is not None and ca is not cb:
                ca.extend(cb); chains.remove(cb)
            elif ca is not None:
                ca.append(b)
            elif cb is not None:
                cb.insert(0, a)
            else:
                chains.append([a, b])
        # 起始建链
        for jc, d in enumerate(cur):
            if (n, jc) not in used_cur:
                chains.append([(n, jc)])

    keep = set()
    for ch in chains:
        if len(ch) < args.min_chain:
            continue
        pts = [center(moving[n][i]) for (n, i) in ch]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        resid = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        if resid < args.min_resid:
            continue
        keep.update(ch)

    out = {}
    cid = 0
    for n in names:
        lst = [moving[n][i] for (nn, i) in sorted(keep) if nn == n]
        if not lst:
            continue
        recs = []
        for c in lst:
            recs.append({"cand_id": cid, "bbox": c["bbox"],
                         "src": c.get("src"), "score": c.get("score")})
            cid += 1
        out[n] = recs
    Path(args.out).write_text(json.dumps(out, indent=1))
    n_out = sum(len(v) for v in out.values())
    print(f"candidates_in={sum(len(v) for v in cands.values())} "
          f"-> after_pancomp_motion={n_out} (frames_with={len(out)})")


if __name__ == "__main__":
    main()
