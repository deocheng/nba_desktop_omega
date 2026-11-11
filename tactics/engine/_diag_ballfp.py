#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_diag_ballfp.py — 球点 FP 诊断（里程碑 05 · A4.19 降 FP 第 1 步）

目的
----
不假设阈值，先把每个球点的「物理合理性」证据摆出来，用分布定阈值。
对 <clip>_poss_tile/ball_tracks.json 的每一个带球帧计算：
  1. d_rect  = 球心到最近球员**框矩形**的距离（框内=0）
  2. d_center= 球心到最近球员**框中心**的距离
  3. inside  = 球心是否落在某个球员框内
  4. y_rel   = 球心 y / 帧高（画面顶端观众席区 FP 模式）
  5. size    = 球框边长（px）
  6. poss    = poss_track_id 是否非空
  7. n_player= 该帧球员数（用于排除球员检测崩掉的帧）

输出
----
stdout：每个片段的分位数表 + 分层占比
JSON：action_work/measure/ball_fp_diag.json

用法
----
python engine/_diag_ballfp.py [--clips sas_hou,sas_nop,sas_det]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AW = ROOT / "action_work"


def rect_dist(bx, by, box):
    x1, y1, x2, y2 = box
    dx = max(x1 - bx, 0.0, bx - x2)
    dy = max(y1 - by, 0.0, by - y2)
    return (dx * dx + dy * dy) ** 0.5


def q(v, ps=(10, 25, 50, 75, 90)):
    v = [x for x in v if x is not None]
    if not v:
        return {}
    s = sorted(v)
    out = {}
    for p in ps:
        i = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
        out[f"p{p}"] = round(s[i], 1)
    return out


def diag_clip(clip, wh=None):
    p = AW / f"{clip}_poss_tile" / "ball_tracks.json"
    if not p.exists():
        return None
    frames = json.loads(p.read_text())
    # 帧尺寸：从球员框/球框的最大坐标推断（避免读图）
    W = H = 0.0
    for f in frames:
        for pl in f.get("players", []):
            W = max(W, pl["bbox"][2])
            H = max(H, pl["bbox"][3])
    if wh:
        W, H = wh
    diag = (W * W + H * H) ** 0.5

    rows = []
    for f in frames:
        b = f.get("ball")
        if not b:
            continue
        x1, y1, x2, y2 = b["bbox"]
        bx, by = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        size = max(x2 - x1, y2 - y1)
        pl = f.get("players", [])
        d_rect = d_center = None
        inside = False
        for ppl in pl:
            dr = rect_dist(bx, by, ppl["bbox"])
            cx = (ppl["bbox"][0] + ppl["bbox"][2]) / 2.0
            cy = (ppl["bbox"][1] + ppl["bbox"][3]) / 2.0
            dc = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
            if d_rect is None or dr < d_rect:
                d_rect = dr
            if d_center is None or dc < d_center:
                d_center = dc
            if ppl["bbox"][0] <= bx <= ppl["bbox"][2] and ppl["bbox"][1] <= by <= ppl["bbox"][3]:
                inside = True
        rows.append({
            "frame": f["frame"],
            "file": f["file"],
            "conf": round(float(b.get("conf", 0.0)), 3),
            "x": round(bx, 1), "y": round(by, 1),
            "y_rel": round(by / H, 3) if H else None,
            "size": round(size, 1),
            "d_rect": round(d_rect, 1) if d_rect is not None else None,
            "d_center": round(d_center, 1) if d_center is not None else None,
            "inside": inside,
            "poss": f.get("poss_track_id"),
            "n_player": len(pl),
        })
    return {"clip": clip, "W": W, "H": H, "diag": round(diag, 1), "rows": rows}


def report(res):
    print(f"\n{'='*72}")
    print(f"片段 {res['clip']}   帧尺寸 {int(res['W'])}x{int(res['H'])}  对角线 {res['diag']}px")
    print(f"球点总数 {len(res['rows'])}   球员数/帧中位 "
          f"{q([r['n_player'] for r in res['rows']]).get('p50')}")
    R = res["rows"]

    n_nop = sum(1 for r in R if r["d_rect"] is None)
    if n_nop:
        print(f"    ⚠ 无球员可比的球点: {n_nop}（该帧 player 检测为空，单独处理）")

    print("\n[1] 球心到最近球员框矩形距离 d_rect (px)")
    print("   ", q([r["d_rect"] for r in R]))
    for th in (0, 20, 40, 60, 88, 120, 160, 200, 260):
        n = sum(1 for r in R if r["d_rect"] is not None and r["d_rect"] <= th)
        print(f"    <= {th:>3}px : {n:>3} / {len(R)}  ({n/max(1,len(R))*100:.1f}%)")

    print("\n[2] 球心到最近球员框中心距离 d_center (px)")
    print("   ", q([r["d_center"] for r in R]))

    print("\n[3] 球心落在球员框内")
    n_in = sum(1 for r in R if r["inside"])
    print(f"    inside : {n_in} / {len(R)}  ({n_in/max(1,len(R))*100:.1f}%)")

    print("\n[4] poss_track_id 已解出（现口径 d_rect <= 0.04*diag）")
    n_p = sum(1 for r in R if r["poss"] is not None)
    print(f"    poss != None : {n_p} / {len(R)}  ({n_p/max(1,len(R))*100:.1f}%)")

    print("\n[5] 球点 y_rel（0=画面顶端 / 1=底端）")
    print("   ", q([r["y_rel"] for r in R]))
    for lo, hi, tag in ((0.0, 0.18, "顶端 0-18%（观众席区）"),
                        (0.18, 0.85, "中段"), (0.85, 1.01, "底端")):
        n = sum(1 for r in R if lo <= r["y_rel"] < hi)
        print(f"    {tag:<22}: {n:>3} / {len(R)}  ({n/max(1,len(R))*100:.1f}%)")

    print("\n[6] 球框边长 size (px)")
    print("   ", q([r["size"] for r in R]))

    print("\n[7] 交叉：顶端区 × 孤立（d_rect>88）")
    n_bad = sum(1 for r in R if r["y_rel"] < 0.18 and r["d_rect"] is not None and r["d_rect"] > 88)
    print(f"    同时满足 : {n_bad} / {len(R)}  ({n_bad/max(1,len(R))*100:.1f}%)")
    n_iso = sum(1 for r in R if r["d_rect"] is not None and r["d_rect"] > 88)
    print(f"    仅孤立   : {n_iso} / {len(R)}  ({n_iso/max(1,len(R))*100:.1f}%)")

    print("\n[8] 孤立点明细（d_rect>88，按距离降序）")
    for r in sorted([x for x in R if x["d_rect"] is not None and x["d_rect"] > 88],
                    key=lambda z: -z["d_rect"]):
        print(f"    f{r['frame']:>4} {r['file']}  d={r['d_rect']:>6.1f}  "
              f"y_rel={r['y_rel']:.2f}  size={r['size']:.0f}  conf={r['conf']:.2f}  "
              f"poss={r['poss']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default="sas_hou,sas_nop,sas_det")
    args = ap.parse_args()

    out = {}
    for c in args.clips.split(","):
        c = c.strip()
        if not c:
            continue
        res = diag_clip(c)
        if res is None:
            print(f"[跳过] 无 ball_tracks.json: {c}")
            continue
        report(res)
        out[c] = res

    od = ROOT / "reports" / "milestone_05" / "measure"
    od.mkdir(parents=True, exist_ok=True)
    fp = od / "ball_fp_diag.json"
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n[写盘] {fp}")


if __name__ == "__main__":
    main()
