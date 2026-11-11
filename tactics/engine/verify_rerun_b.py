#!/usr/bin/env python3
"""A5.4 回归门 + 抽检包：base(tracks.json) vs B(tracks_b.json) 全 177 段。

Part A 回归（JSON-only，全量）：
  - ID 数降幅、寿命提升、**每帧人数是否逐段不变（硬门）**。
Part B 抽检包：挑「降幅最大 / 中位 / 降幅最小」3 段，渲染 base vs B 轨迹叠加图，
  供老程逐条目视（判定权归老程）。
"""
import json
import statistics
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUTD = ROOT / "action_work" / "validate" / "A5_4"


def seg_stats(tr):
    fr = tr.get("frames") or []
    ids = {}
    for x in fr:
        for p in x.get("players") or []:
            ids[p["id"]] = ids.get(p["id"], 0) + 1
    lives = list(ids.values())
    ppl = statistics.mean(len(x.get("players") or []) for x in fr) if fr else 0
    return len(ids), (statistics.median(lives) if lives else 0), ppl, len(fr)


def part_a():
    rows = []
    for d in sorted(SEGD.iterdir()):
        f0, f1 = d / "tracks.json", d / "tracks_b.json"
        if not (f0.exists() and f1.exists()):
            continue
        b = seg_stats(json.load(open(f0)))
        B = seg_stats(json.load(open(f1)))
        rows.append({"seg": d.name, "base_ids": b[0], "b_ids": B[0],
                     "base_life": b[1], "b_life": B[1],
                     "base_ppl": round(b[2], 3), "b_ppl": round(B[2], 3)})
    n = len(rows)
    ti = sum(r["base_ids"] for r in rows)
    tI = sum(r["b_ids"] for r in rows)
    mbi = statistics.median(r["base_ids"] for r in rows)
    mBi = statistics.median(r["b_ids"] for r in rows)
    mbl = statistics.median(r["base_life"] for r in rows)
    mBl = statistics.median(r["b_life"] for r in rows)
    diff = [r for r in rows if abs(r["base_ppl"] - r["b_ppl"]) > 1e-6]
    print(f"=== A5.4 回归门（{n} 段）===")
    print(f"ID 总数    : {ti} -> {tI}  (降 {100*(1-tI/ti):.1f}%)")
    print(f"中位 ID/段 : {mbi:.0f} -> {mBi:.0f}")
    print(f"中位 寿命  : {mbl:.0f} -> {mBl:.0f} 帧")
    print(f"每帧人数不变(硬门): {'PASS' if not diff else f'FAIL ({len(diff)} 段不同)'}")
    if diff:
        for r in diff[:5]:
            print(f"   {r['seg']}: base={r['base_ppl']} B={r['b_ppl']}")
    return rows, diff


def render(seg):
    d = SEGD / seg
    frames = json.load(open(d / "frames.json"))
    img = cv2.imread(frames[len(frames) // 2]["path"])
    h, w = img.shape[:2]
    rng = np.random.default_rng(0)
    panels = []
    for tag in ("tracks.json", "tracks_b.json"):
        t = json.load(open(d / tag))
        canvas = img.copy()
        ids = {}
        for x in t.get("frames") or []:
            for p in x.get("players") or []:
                b = p["box"]
                fx, fy = int((b[0] + b[2]) / 2), int(b[3])
                ids.setdefault(p["id"], []).append((fx, fy))
        for tid, pts in ids.items():
            if len(pts) < 5:
                continue
            c = tuple(int(v) for v in rng.integers(60, 255, 3))
            for k in range(1, len(pts)):
                if abs(pts[k][0] - pts[k - 1][0]) < w * 0.3:
                    cv2.line(canvas, pts[k - 1], pts[k], c, 2)
        nid = len(ids)
        cv2.putText(canvas, f"{tag}  n_ids={nid}", (14, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 5)
        cv2.putText(canvas, f"{tag}  n_ids={nid}", (14, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (60, 240, 255), 2)
        panels.append(canvas)
    comb = np.hstack([cv2.resize(p, (w // 2, h // 2)) for p in panels])
    OUTD.mkdir(parents=True, exist_ok=True)
    out = OUTD / f"{seg}_base_vs_B.png"
    cv2.imwrite(str(out), comb)
    return out


def part_b(rows):
    rows = [r for r in rows if r["base_ids"] > 0]
    for r in rows:
        r["red"] = 1 - r["b_ids"] / r["base_ids"]
    rows.sort(key=lambda r: r["red"])
    picks = [rows[0]["seg"], rows[len(rows) // 2]["seg"], rows[-1]["seg"]]
    print("\n=== 抽检包（渲染 base vs B 轨迹叠加）===")
    for s in picks:
        r = next(x for x in rows if x["seg"] == s)
        p = render(s)
        print(f"  {s:10s} 降幅{100*r['red']:.0f}%  ID {r['base_ids']}->{r['b_ids']}  -> {p.name}")


if __name__ == "__main__":
    rows, diff = part_a()
    part_b(rows)
