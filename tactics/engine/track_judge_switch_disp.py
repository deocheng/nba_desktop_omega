#!/usr/bin/env python3
"""A5.7b 换人切换点的**位移量级**量化（按帧序重排老程的逐帧归属）。

要回答：跟踪器在"换人"的那一刻，脚点到底跳了多远？
若切换位移与"同一人"的正常位移**同量级** ⇒ 任何位移阈值都分不开 ⇒ 运动学判据作废。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import re
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
JD = ROOT / "action_work" / "track_judge"
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"

# 老程 2026-10-01 逐帧归属（按裁剪条上显示的帧；'?'=老程未单独点名）
GROUP = {
    "ep24_s1#21":  {26: "B", 21: "A", 16: "A", 10: "A", 5: "A", 0: "A"},
    "ep24_s1#190": {103: "A", 111: "A", 135: "球员"},
    "ep24_s1#246": {104: "A", 113: "B", 122: "B", 132: "A", 141: "A", 150: "C球员"},
    "ep24_s1#269": {116: "?", 118: "A", 119: "A", 121: "A", 122: "A", 128: "A"},
    "ep24_s1#309": {148: "A", 149: "A", 150: "教练", 152: "教练", 153: "教练", 154: "教练"},
    "ep24_s1#336": {160: "A", 165: "A", 167: "A", 171: "A", 173: "A", 177: "B"},
    "B:ep24_s1#88": {52: "A", 55: "A", 58: "A", 61: "A", 64: "B球员", 68: "C"},
    "B:ep24_s1#116": {99: "A", 112: "B", 123: "C", 161: "D", 181: "E", 193: "A"},
}


def load_items():
    h = (JD / "index.html").read_text(encoding="utf-8")
    return {x["key"]: x for x in
            json.loads(re.search(r"\[\{.*\}\]", h.split("\n")[31], re.S).group(0))}


def seq_of(src, tid):
    out = []
    for fr in src.get("frames") or []:
        for p in fr.get("players") or []:
            if p["id"] == tid:
                b = p["box"]
                out.append((fr["idx"], (b[0] + b[2]) / 2, b[3], b[3] - b[1]))
    out.sort()
    return out


def main():
    items = load_items()
    cache = {}
    same_d, sw_d = [], []
    print("逐条：标注帧之间的位移（SW=老程判为换人处）")
    for key, g in GROUP.items():
        it = items[key]
        seg, tid = it["seg"], it["tid"]
        src_name = "tracks_b.json" if key.startswith("B:") else "tracks.json"
        if (seg, src_name) not in cache:
            cache[(seg, src_name)] = json.load(open(SEGD / seg / src_name))
        seq = seq_of(cache[(seg, src_name)], tid)
        byf = {f[0]: f for f in seq}
        fs = sorted(g.keys())
        line = [f"  {key}:"]
        for i in range(len(fs) - 1):
            fa, fb = fs[i], fs[i + 1]
            if fa not in byf or fb not in byf:
                continue
            d = ((byf[fb][1] - byf[fa][1]) ** 2 + (byf[fb][2] - byf[fa][2]) ** 2) ** 0.5
            df = fb - fa
            sw = (g[fa] != g[fb]) and ("?" not in (g[fa], g[fb]))
            tag = "SW" if sw else "  "
            line.append(f" f{fa}→f{fb}{tag}={d:.0f}px/{df}f({d/df:.0f}px每帧)")
            (sw_d if sw else same_d).append(d)
        print("".join(line))

    def st(a):
        a = sorted(a)
        return (f"n={len(a)} min={a[0]:.0f} p25={a[len(a)//4]:.0f} "
                f"med={a[len(a)//2]:.0f} p75={a[3*len(a)//4]:.0f} max={a[-1]:.0f}")
    print("\n【换人切换点】的总位移 :", st(sw_d))
    print("【同一人相邻帧】的总位移:", st(same_d))
    print("\n⇒ 若两者分位数重叠，就证明位移阈值分不开换人/不换人。")

    out = JD / "switch_displacement.json"
    json.dump({"switch": sorted(sw_d), "same": sorted(same_d)},
              open(out, "w"), indent=1)
    print("->", out)


if __name__ == "__main__":
    main()
