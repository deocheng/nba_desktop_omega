#!/usr/bin/env python3
"""A5.9b Top-K 选池 × 老程裁定交叉验证。

老程裁定：ep24_s1 8 条里只有 #269 是场上球员(有价值)，其余 7 条是观众/替补席/教练(无价值)。
问：按「框内运动量」每帧取 Top13 后，#269 的检测有多少帧被保留？7 条无价值的呢？
期望：#269 保留率高，无价值保留率低。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
TH, FRAC, K = 12, 0.6, 13

VALUE = {
    21: ("无价值/观众", "tracks.json"), 190: ("无价值/替补席观众", "tracks.json"),
    246: ("无价值/替补席观众", "tracks.json"), 269: ("★有价值/球员", "tracks.json"),
    309: ("无价值/教练", "tracks.json"), 336: ("无价值/观众", "tracks.json"),
    88: ("无价值/观众", "tracks_b.json"), 116: ("无价值/观众", "tracks_b.json"),
}


def gray(f):
    im = cv2.imread(str(f))
    return None if im is None else cv2.GaussianBlur(
        cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (5, 5), 0)


def motion(da, box, frac):
    H, W = da.shape
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    a1 = max(0, int(cx - w * frac / 2)); a2 = min(W, int(cx + w * frac / 2))
    b1 = max(0, int(cy - h * frac / 2)); b2 = min(H, int(cy + h * frac / 2))
    if a2 - a1 < 3 or b2 - b1 < 3:
        return 0.0
    return float((da[b1:b2, a1:a2] > TH).mean())


def main():
    seg = "ep24_s1"
    d = SEGD / seg
    files = sorted((d / "frames").glob("f*.jpg"))
    srcs = {k[1]: json.load(open(d / k[1])) for k in VALUE.values()}
    tr = srcs["tracks.json"]

    # 每帧算 Top13（基于 base tracks.json 的全部检测）
    keep_tids = {i: {} for i in VALUE}       # tid -> {hit, tot}
    prev = None
    for fr in tr["frames"]:
        idx = fr["idx"]
        if idx == 0 or idx >= len(files):
            continue
        g = gray(files[idx])
        pg = gray(files[idx - 1]) if (prev is None or prev[0] != idx - 1) else prev[1]
        if g is None or pg is None:
            continue
        da = cv2.absdiff(g, pg)
        items = [{"m": motion(da, p["box"], FRAC), "tid": int(p["id"]), "box": p["box"]}
                 for p in fr.get("players", [])]
        items.sort(key=lambda x: -x["m"])
        for rank, it in enumerate(items):
            if it["tid"] in keep_tids:
                d_ = keep_tids[it["tid"]]
                d_.setdefault("tot", 0); d_.setdefault("hit", 0)
                d_["tot"] += 1
                if rank < K:
                    d_["hit"] += 1
        prev = (idx, g)

    # B 版的两条(88/116)需在 tracks_b.json 里同样统计"该检测是否在 Top13"
    for tid in (88, 116):
        tb = srcs["tracks_b.json"]
        prev = None
        for fr in tb["frames"]:
            idx = fr["idx"]
            if idx == 0 or idx >= len(files):
                continue
            g = gray(files[idx])
            pg = gray(files[idx - 1]) if (prev is None or prev[0] != idx - 1) else prev[1]
            if g is None or pg is None:
                continue
            da = cv2.absdiff(g, pg)
            items = [{"m": motion(da, p["box"], FRAC), "tid": int(p["id"]), "box": p["box"]}
                     for p in fr.get("players", [])]
            items.sort(key=lambda x: -x["m"])
            for rank, it in enumerate(items):
                if it["tid"] == tid:
                    d_ = keep_tids[tid]
                    d_.setdefault("tot", 0); d_.setdefault("hit", 0)
                    d_["tot"] += 1
                    if rank < K:
                        d_["hit"] += 1
            prev = (idx, g)

    print(f"{'tid':>5} {'老程定性':<18}{'帧数':>5}{'进Top13':>9}{'保留率':>9}")
    for tid in sorted(VALUE):
        d_ = keep_tids[tid]
        tot, hit = d_.get("tot", 0), d_.get("hit", 0)
        r = hit / tot if tot else 0
        print(f"{tid:>5} {VALUE[tid][0]:<18}{tot:>5}{hit:>9}{r:>9.1%}")
    val = keep_tids[269]
    nov = [keep_tids[t] for t in VALUE if t != 269]
    nov_r = [d_.get("hit", 0) / d_["tot"] for d_ in nov if d_.get("tot")]
    print(f"\n有价值(#269) 保留率 {val.get('hit',0)/val['tot']:.1%} vs "
          f"无价值 7 条 保留率 {np.mean(nov_r):.1%}（范围 {min(nov_r):.1%}–{max(nov_r):.1%}）")


if __name__ == "__main__":
    main()
