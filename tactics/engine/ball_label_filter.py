#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ball_label_filter.py — 运动一致性过滤，砍掉静态假阳性（logo/场地线）。
原理：球在动，logo 不动。跨帧贪心最近邻链接候选成链，
只保留「链长≥min_chain 且链内位移≥min_disp_rel*宽」的候选。
输出保留 cand_id 供后续目视校验引用。
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates_json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-step-rel", type=float, default=0.03,
                    help="相邻帧候选中心最大位移(占帧宽比例)")
    ap.add_argument("--min-chain", type=int, default=3)
    ap.add_argument("--min-disp-rel", type=float, default=0.012,
                    help="链内净位移下限(占帧宽比例)")
    args = ap.parse_args()

    cands = json.loads(Path(args.candidates_json).read_text())
    names = sorted(cands.keys())
    if not names:
        Path(args.out).write_text("{}")
        print("empty")
        return

    # 假设帧名 fNNNNN.jpg → 序号
    def fidx(name):
        return int(name[1:6])

    w = 1920.0
    max_step = args.max_step_rel * w
    min_disp = args.min_disp_rel * w

    # 全局候选表
    all_c = {}
    cid = 0
    per_frame = {}
    for n in names:
        lst = []
        for c in cands[n]:
            all_c[cid] = {"frame": n, **c}
            lst.append(cid)
            cid += 1
        per_frame[n] = lst

    # 相邻帧链接（贪心最近邻，双向）
    chains = []  # list of list[cid]
    used = set()
    prev_frame = None
    for n in names:
        cur = per_frame[n]
        if prev_frame is None:
            prev_frame = n
            continue
        # 只链接相邻帧（fidx 差=1）
        if fidx(n) - fidx(prev_frame) != 1:
            prev_frame = n
            continue
        prev_list = per_frame[prev_frame]
        # 贪心配对
        pairs = []
        for a in prev_list:
            for b in cur:
                ax = (all_c[a]["bbox"][0] + all_c[a]["bbox"][2]) / 2
                ay = (all_c[a]["bbox"][1] + all_c[a]["bbox"][3]) / 2
                bx = (all_c[b]["bbox"][0] + all_c[b]["bbox"][2]) / 2
                by = (all_c[b]["bbox"][1] + all_c[b]["bbox"][3]) / 2
                d = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
                if d <= max_step:
                    pairs.append((d, a, b))
        pairs.sort()
        linked_a = set()
        linked_b = set()
        for d, a, b in pairs:
            if a in linked_a or b in linked_b:
                continue
            linked_a.add(a)
            linked_b.add(b)
            # 合并链
            ca = next((ch for ch in chains if ch[-1] == a), None)
            cb = next((ch for ch in chains if ch and ch[0] == b), None)
            if ca is not None and cb is not None and ca is not cb:
                ca.extend(cb)
                chains.remove(cb)
            elif ca is not None:
                ca.append(b)
            elif cb is not None:
                cb.insert(0, a)
            else:
                chains.append([a, b])
        prev_frame = n

    # 过滤：链长 + 位移
    keep = set()
    for ch in chains:
        if len(ch) < args.min_chain:
            continue
        xs = [(all_c[c]["bbox"][0] + all_c[c]["bbox"][2]) / 2 for c in ch]
        ys = [(all_c[c]["bbox"][1] + all_c[c]["bbox"][3]) / 2 for c in ch]
        disp = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        if disp < min_disp:
            continue
        keep.update(ch)

    out = {}
    for c in sorted(keep):
        rec = all_c[c]
        out.setdefault(rec["frame"], []).append({
            "cand_id": c, "bbox": rec["bbox"],
            "src": rec["src"], "score": rec["score"],
        })
    Path(args.out).write_text(json.dumps(out, indent=1))
    n_out = sum(len(v) for v in out.values())
    n_in = sum(len(v) for v in cands.values())
    print(f"candidates_in={n_in} -> after_motion_filter={n_out} "
          f"(frames_with={len(out)})")


if __name__ == "__main__":
    main()
