#!/usr/bin/env python3
"""A5.8d 老程判据的**正确实现**：用「帧差运动量」判一个框里的人**是不是在动**。

老程：「球员和裁判是场上移动距离最大的目标，其他都是无价值的啊」
⇒ 观众/替补席/教练**坐着不动** ⇒ 框内几乎无运动像素；球员/裁判**持续跑动** ⇒ 框内大量运动像素。

与 med_step 的区别：med_step 受**检测框抖动**污染（静止的人框也会抖几 px/帧），
本判据直接用**像素级运动**，与框的定位抖动无关。

方法：|gray[i]-gray[i-1]| > TH 的像素占比（限缩到框内，且取框的**主体区**避免背景混入）。
验证集：老程裁定的 ep24_s1 8 条（#269=球员有价值，其余 7 条=无价值）
        + ep1_s0#116 老程精确分组（126=球员 / 141-194=观众A / 207,220=邻座B）
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import re
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
JD = ROOT / "action_work" / "track_judge"
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
TH = 12          # 帧差灰度阈值
SHRINK = 0.12    # 框向内缩比例(避开边缘背景)

VALUE = {
    "ep24_s1#21": "无价值", "ep24_s1#190": "无价值", "ep24_s1#246": "无价值",
    "ep24_s1#269": "有价值", "ep24_s1#309": "无价值", "ep24_s1#336": "无价值",
    "B:ep24_s1#88": "无价值", "B:ep24_s1#116": "无价值",
}
GROUP_116 = {126: "球员", 141: "观众A", 154: "观众A", 167: "观众A",
             181: "观众A", 194: "观众A", 207: "邻座B", 220: "邻座B"}


def load_items():
    h = (JD / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r"\[\{.*\}\]", h.split("\n")[31], re.S).group(0))


def motion_ratio(prev_gray, gray, box):
    """框内运动像素占比（框内缩 SHRINK，避免背景/邻座混入）。"""
    H, W = gray.shape
    x1, y1, x2, y2 = [int(v) for v in box]
    dx = int((x2 - x1) * SHRINK)
    dy = int((y2 - y1) * SHRINK)
    x1, y1 = max(0, x1 + dx), max(0, y1 + dy)
    x2, y2 = min(W, x2 - dx), min(H, y2 - dy)
    if x2 - x1 < 3 or y2 - y1 < 3:
        return None
    d = cv2.absdiff(gray[y1:y2, x1:x2], prev_gray[y1:y2, x1:x2])
    return float((d > TH).mean())


def scan(seg, tid, src_name):
    d = SEGD / seg
    tr = json.load(open(d / src_name))
    files = sorted((d / "frames").glob("f*.jpg"))
    out = []
    prev = None
    for fr in tr["frames"]:
        idx = fr["idx"]
        if idx >= len(files) or idx == 0:
            continue
        img = cv2.imread(str(files[idx]))
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        g = cv2.GaussianBlur(g, (5, 5), 0)
        for p in fr.get("players", []):
            if p["id"] != tid:
                continue
            if prev is None or prev[0] != idx - 1:
                pf = files[idx - 1]
                pg = cv2.cvtColor(cv2.imread(str(pf)), cv2.COLOR_BGR2GRAY)
                pg = cv2.GaussianBlur(pg, (5, 5), 0)
            else:
                pg = prev[1]
            r = motion_ratio(pg, g, p["box"])
            if r is not None:
                out.append((idx, r))
        prev = (idx, g)
    return out


def main():
    items = load_items()
    res = {}
    print(f"{'key':<16}{'value':<8}{'n':>3} {'motion_ratio 中位':>16}{'均值':>8}")
    sub = [it for it in items if it["key"] in VALUE]
    for it in sub:
        seg, tid = it["seg"], it["tid"]
        src = "tracks_b.json" if it["key"].startswith("B:") else "tracks.json"
        rs = scan(seg, tid, src)
        res[it["key"]] = rs
        if not rs:
            continue
        v = sorted(r for _, r in rs)
        print(f"{it['key']:<16}{VALUE[it['key']]:<8}{len(v):>3} "
              f"{v[len(v)//2]:>16.3f}{np.mean(v):>8.3f}")

    vals = [np.median([r for _, r in res[k]]) for k in res if VALUE.get(k) == "有价值"]
    novs = [np.median([r for _, r in res[k]]) for k in res if VALUE.get(k) == "无价值"]
    print(f"\n有价值(球员) motion_ratio 中位 = {[round(x,3) for x in vals]}")
    print(f"无价值 motion_ratio 中位      = {sorted(round(x,3) for x in novs)}")
    if vals and novs:
        print(f"⇒ 最小有价值 {min(vals):.3f} vs 最大无价值 {max(novs):.3f}  "
              f"gap={min(vals)-max(novs):+.3f}")

    print("\n=== ep1_s0#116 老程精确分组 ===")
    rs = scan("ep1_s0", 116, "tracks.json")
    byf = dict(rs)
    grp = {}
    for f, g in GROUP_116.items():
        grp.setdefault(g, []).append(byf.get(f))
    for g, vs in grp.items():
        vs = [v for v in vs if v is not None]
        if vs:
            print(f"  {g}({len(vs)}帧): motion_ratio 中位={np.median(vs):.3f}  "
                  f"各帧={[round(v,3) for v in vs]}")

    out = JD / "motion_ratio.json"
    json.dump({k: v for k, v in res.items()}, open(out, "w"), indent=1)
    print("\n->", out)


if __name__ == "__main__":
    main()
