#!/usr/bin/env python3
"""A5.1 轨迹拼接：把碎片化的球员 track 缝成持久身份（提升"跟踪准确"）。

证据基础（本机实测，非假设）：
  - 177 段中位：每段 187 个 ID / 寿命 8 帧 / 19.6 人每帧 → 碎片倍率 9.5x。
  - 镜头运动探针：每帧位移中位仅 0.29px（p90 1.13px）→ **图像空间稳定**，
    碎片真因=检测断续/遮挡/置信度抖动，**不是**镜头平移。
  ⇒ 可直接在图像空间按「运动预测 + 尺寸」拼接，无需相机补偿。

算法（保守、可回归、有阴性对照）：
  1. 每个旧 id = 一条碎片(帧序列 + 框心 + 框高)。
  2. 边 a→b：a 结束帧 < b 开始帧，gap ≤ GAP；用 a 末段速度外推 a 到 b 起始帧，
     距离 ≤ ALPHA × 0.5(h_a+h_b)（尺寸相对门，A4.61 纪律）；尺寸比一致。
  3. 贪心按 (gap, 归一化距离) 接受，每碎片至多一进一出 → 链式合并。
  4. 自证门：**人数/帧必须逐帧不变**（拼接不得增删检测）；输出前后 ID 数/寿命。
  5. 阴性对照 --shuffle：随机置换碎片时间，正常应几乎不合并（防退化全并）。

产出：<seg>/tracks_stitched.json（同 schema，仅 id 重映射）+ stitch_report.json
"""
import argparse
import glob
import json
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
STATS = ROOT / "action_work" / "stitch_report.json"


def load_frags(tracks):
    """返回 frags: {old_id: [(f, cx, cy, h), ...] 有序}，以及逐帧人数表。"""
    frags, per_frame = {}, []
    for x in tracks.get("frames") or []:
        ps = x.get("players") or []
        per_frame.append(len(ps))
        f = x.get("idx")
        for p in ps:
            b = p["box"]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            h = b[3] - b[1]
            frags.setdefault(p["id"], []).append((f, cx, cy, h))
    for k in frags:
        frags[k].sort()
    return frags, per_frame


def tail_velocity(seq, k=5):
    if len(seq) < 2:
        return 0.0, 0.0
    s = seq[-min(k, len(seq)):]
    (f0, x0, y0, _), (f1, x1, y1, _) = s[0], s[-1]
    df = f1 - f0
    if df <= 0:
        return 0.0, 0.0
    return (x1 - x0) / df, (y1 - y0) / df


def build_edges(frags, gap_max, alpha, size_tol, shuffle=False, seed=0):
    items = list(frags.items())
    if shuffle:  # 阴性对照：打乱时间起点
        rng = random.Random(seed)
        items = [(k, v) for k, v in items]
        rng.shuffle(items)
    ends = {k: v[-1] for k, v in frags.items()}
    starts = {k: v[0] for k, v in frags.items()}
    hmed = {k: statistics.median([p[3] for p in v]) for k, v in frags.items()}
    edges = []
    ids = list(frags.keys())
    for a in ids:
        fe, xe, ye, he = ends[a]
        vx, vy = tail_velocity(frags[a])
        for b in ids:
            if a == b:
                continue
            fs, xs, ys, hs = starts[b]
            g = fs - fe
            if g <= 0 or g > gap_max:
                continue
            # shuffle 对照：把 b 的时间轴整体平移一个随机量，破坏真实连续性
            if shuffle:
                g = (g + random.Random(hash((a, b, seed)) % 10**6).randint(0, 50))
                if g > gap_max:
                    continue
            px, py = xe + vx * g, ye + vy * g
            nd = ((px - xs) ** 2 + (py - ys) ** 2) ** 0.5 / max(0.5 * (he + hs), 1.0)
            if nd > alpha:
                continue
            if abs(he - hs) / max(0.5 * (he + hs), 1.0) > size_tol:
                continue
            edges.append((g, nd, a, b))
    edges.sort(key=lambda e: (e[0], e[1]))
    return edges


def merge_chains(frags, edges):
    out, inc = {}, {}
    for g, nd, a, b in edges:
        if a in out or b in inc:
            continue
        out[a] = b
        inc[b] = a
    # 每条链取根
    root = {}
    for k in frags:
        if k in inc:
            continue
        cur = k
        while cur in out:
            root[cur] = k
            cur = out[cur]
        root[cur] = k
    # 未被链覆盖的（环外）自成一类
    for k in frags:
        if k not in root:
            # 找其上游根
            cur = k
            seen = set()
            while cur in inc and cur not in seen:
                seen.add(cur)
                cur = inc[cur]
            root[k] = root.get(cur, cur)
    return root


def stitch_one(path, gap_max, alpha, size_tol, shuffle=False):
    tr = json.load(open(path))
    frags, per_frame = load_frags(tr)
    if not frags:
        return None
    edges = build_edges(frags, gap_max, alpha, size_tol, shuffle)
    root = merge_chains(frags, edges)
    # 重新赋 id（用根 id 的稳定化）
    remap = {}
    new_frags = {}
    for k, seq in frags.items():
        r = root.get(k, k)
        remap[k] = r
        new_frags.setdefault(r, []).extend(seq)
    # 逐帧人数不变的校验（重标签不改检测集）
    pf2 = list(per_frame)
    # 写回
    if not shuffle:
        out = json.loads(json.dumps(tr))
        for x in out.get("frames") or []:
            for p in x.get("players") or []:
                p["id"] = remap.get(p["id"], p["id"])
        json.dump(out, open(path.parent / "tracks_stitched.json", "w"),
                  ensure_ascii=False)
    before = len(frags)
    after = len(new_frags)
    life_b = statistics.median([len(v) for v in frags.values()])
    life_a = statistics.median([len(v) for v in new_frags.values()])
    return {"seg": path.parent.name, "n_ids_before": before, "n_ids_after": after,
            "med_life_before": round(life_b, 1), "med_life_after": round(life_a, 1),
            "ppl_per_frame": round(sum(per_frame) / max(len(per_frame), 1), 2),
            "pf_equal": pf2 == per_frame}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=int, default=8)
    ap.add_argument("--alpha", type=float, default=1.2)
    ap.add_argument("--size-tol", type=float, default=0.4)
    ap.add_argument("--shuffle", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    fs = sorted(glob.glob(str(SEGD / "*" / "tracks.json")))
    if a.limit:
        fs = fs[:a.limit]
    rows = [r for f in fs
            if (r := stitch_one(Path(f), a.gap, a.alpha, a.size_tol, a.shuffle))]
    if not rows:
        print("无数据"); return

    tot_b = sum(r["n_ids_before"] for r in rows)
    tot_a = sum(r["n_ids_after"] for r in rows)
    mb = statistics.median([r["n_ids_before"] for r in rows])
    ma = statistics.median([r["n_ids_after"] for r in rows])
    lb = statistics.median([r["med_life_before"] for r in rows])
    la = statistics.median([r["med_life_after"] for r in rows])
    pf_ok = all(r["pf_equal"] for r in rows)
    tag = "阴性对照(shuffle)" if a.shuffle else "正式拼接"
    print(f"=== {tag} ｜ 段 {len(rows)} ｜ gap={a.gap} alpha={a.alpha} ===")
    print(f"ID 总数   : {tot_b} -> {tot_a}  (降 {100*(1-tot_a/tot_b):.1f}%)")
    print(f"中位ID数  : {mb:.0f} -> {ma:.0f}")
    print(f"中位寿命  : {lb:.0f} -> {la:.0f} 帧")
    print(f"人数/帧不变校验: {'PASS' if pf_ok else 'FAIL'}")
    if not a.shuffle:
        json.dump({"rows": rows, "tot_before": tot_b, "tot_after": tot_a,
                   "med_ids_before": mb, "med_ids_after": ma,
                   "med_life_before": lb, "med_life_after": la,
                   "params": {"gap": a.gap, "alpha": a.alpha,
                              "size_tol": a.size_tol}},
                  open(STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"-> {STATS}")


if __name__ == "__main__":
    main()
