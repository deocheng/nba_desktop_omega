#!/usr/bin/env python3
"""A5.6d 复核「大跳判据」口径：速率(÷帧差) vs 原始位移。

背景：`track_judge_app.py` 的 max_step / n_big 用 (位移 ÷ 帧差) = px/帧 速率。
对**有缺帧**的轨迹，一次跨 4 帧的 165px 瞬移会被稀释成 41px/帧
⇒ 低于 300px 门 ⇒ 误判"无大跳=同一人"。
本脚本对工作台 38 条逐条**两种口径都算**，输出差异表。
只读，不写任何工作台产物。
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
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
IDX = ROOT / "action_work" / "track_judge" / "index.html"
BIG = 300.0


def load_items():
    h = IDX.read_text(encoding="utf-8")
    line = h.split("\n")[31]
    return json.loads(re.search(r"\[\{.*\}\]", line, re.S).group(0))


def seq_foot(src, tid):
    out = []
    for fr in src.get("frames") or []:
        for p in fr.get("players") or []:
            if p["id"] == tid:
                b = p["box"]
                out.append((fr["idx"], (b[0] + b[2]) / 2, b[3], b[3] - b[1], b[2] - b[0]))
    out.sort()
    return out


def main():
    items = load_items()
    cache = {}
    rows = []
    for it in items:
        seg, tid = it["seg"], it["tid"]
        src_name = "tracks_b.json" if it["key"].startswith("B:") else "tracks.json"
        key = (seg, src_name)
        if key not in cache:
            cache[key] = json.load(open(SEGD / seg / src_name))
        seq = seq_foot(cache[key], tid)
        raw, rate = [], []
        for i in range(1, len(seq)):
            df = seq[i][0] - seq[i - 1][0]
            if df <= 0:
                continue
            d = ((seq[i][1] - seq[i - 1][1]) ** 2 + (seq[i][2] - seq[i - 1][2]) ** 2) ** 0.5
            raw.append(d)
            rate.append(d / df)
        rows.append({
            "key": it["key"], "n": it["n"], "span": it["span"],
            "raw_max": round(max(raw), 1) if raw else 0.0,
            "rate_max": round(max(rate), 1) if rate else 0.0,
            "n_big_raw": sum(1 for v in raw if v > BIG),
            "n_big_rate": sum(1 for v in rate if v > BIG),
            "app_n_big": it["n_big"], "app_auto": it["auto"],
            "mean_h": round(sum(s[3] for s in seq) / max(1, len(seq)), 1),
        })

    print(f"{'key':<18}{'n':>4} {'span':<10}{'rawmax':>8}{'ratemax':>8}"
          f"{'bigRaw':>7}{'bigRate':>8}{'appBig':>7}  {'mean_h':>7}  auto")
    flip_raw = flip_rate = 0
    for r in rows:
        print(f"{r['key']:<18}{r['n']:>4} {r['span']:<10}{r['raw_max']:>8}"
              f"{r['rate_max']:>8}{r['n_big_raw']:>7}{r['n_big_rate']:>8}"
              f"{r['app_n_big']:>7}  {r['mean_h']:>7}  {r['app_auto']}")
        if (r["n_big_raw"] > 0) != (r["app_n_big"] > 0):
            flip_raw += 1
        if (r["n_big_rate"] > 0) != (r["app_n_big"] > 0):
            flip_rate += 1

    print(f"\n口径差异：以 raw>300 判「有跳」⇒ {flip_raw}/38 条与工作台 auto 不同；"
          f"以 rate>300 判 ⇒ {flip_rate}/38 条不同")
    print("⚠ 工作台 app_n_big 应等于 rate 口径（同一套公式）；不等说明 app 生成后又改过 tracks。")
    out = ROOT / "action_work" / "track_judge" / "jump_criterion_audit.json"
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=1)
    print("->", out)


if __name__ == "__main__":
    main()
