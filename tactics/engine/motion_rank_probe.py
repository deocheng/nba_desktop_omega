#!/usr/bin/env python3
"""A5.8g 老程判据的**正解形态**：不算阈值、不分类，直接**按移动距离排序取前 N**。

老程：「球员和裁判是场上移动距离最大的目标，其他都是无价值的啊」
⇒ 场上目标(球员+裁判)**移动距离最大** ⇒ 按移动量降序排，取前 N（≈场上目标数）即可；
   剩下的**一律丢弃**，根本不需要知道"它是不是观众"（这正是老程批评我"在观众上花力气"的原因）。

移动量的三个候选定义（都算，看哪个把球员排最前）：
  path_len  : 累计位移（会被长轨迹放大 ⇒ 偏向静止但被连续跟踪的观众）
  net_disp  : 首末净位移（原地徘徊 ⇒ 小；跑遍全场 ⇒ 大）
  span_diag : 脚点包围盒对角线（"活动范围"，最抗抖动）
检验：老程裁定的 ep24_s1 8 条（#269=球员有价值 / 其余 7 条无价值）
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import re
from pathlib import Path

import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
JD = ROOT / "action_work" / "track_judge"
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"

VALUE = {
    "ep24_s1#21": "无价值", "ep24_s1#190": "无价值", "ep24_s1#246": "无价值",
    "ep24_s1#269": "有价值", "ep24_s1#309": "无价值", "ep24_s1#336": "无价值",
    "B:ep24_s1#88": "无价值", "B:ep24_s1#116": "无价值",
}


def load_items():
    h = (JD / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r"\[\{.*\}\]", h.split("\n")[31], re.S).group(0))


def seq_of(src, tid):
    out = []
    for fr in src.get("frames") or []:
        for p in fr.get("players") or []:
            if p["id"] == tid:
                b = p["box"]
                out.append((fr["idx"], (b[0] + b[2]) / 2, b[3]))
    out.sort()
    return out


def m3(seq):
    if len(seq) < 2:
        return 0.0, 0.0, 0.0
    pts = np.array([[s[1], s[2]] for s in seq])
    path = float(np.abs(np.diff(pts, axis=0)).sum())
    net = float(np.linalg.norm(pts[-1] - pts[0]))
    span = float(np.linalg.norm(pts.max(0) - pts.min(0)))
    return path, net, span


def main():
    items = load_items()
    cache = {}
    rows = []
    for it in items:
        seg, tid = it["seg"], it["tid"]
        src = "tracks_b.json" if it["key"].startswith("B:") else "tracks.json"
        k = (seg, src)
        if k not in cache:
            cache[k] = json.load(open(SEGD / seg / src))
        seq = seq_of(cache[k], tid)
        p, n, s = m3(seq)
        rows.append({"key": it["key"], "seg": seg, "n": len(seq),
                     "path_len": round(p, 1), "net_disp": round(n, 1),
                     "span_diag": round(s, 1), "value": VALUE.get(it["key"], "未知")})

    for metric in ["path_len", "net_disp", "span_diag"]:
        print(f"\n=== 按 {metric} 降序（ep24_s1 的 8 条内部排名）===")
        sub = sorted([r for r in rows if r["key"] in VALUE],
                     key=lambda r: -r[metric])
        for i, r in enumerate(sub, 1):
            mark = "★有价值" if r["value"] == "有价值" else " 无价值"
            print(f"  {i:>2}. {r['key']:<16}{metric}={r[metric]:>8}  "
                  f"path={r['path_len']:>7} net={r['net_disp']:>7} "
                  f"span={r['span_diag']:>7}  n={r['n']:>3}  {mark}")
        # 有价值那条排第几
        pos = next(i for i, r in enumerate(sub, 1) if r["value"] == "有价值")
        print(f"  ⇒ 「有价值」的 #269 在 {metric} 排名 = 第 {pos}/{len(sub)}")

    print("\n=== 各段内按 span_diag 取前 6，看命中率（需老程裁定，先看构成）===")
    for seg in sorted({r["seg"] for r in rows}):
        sr = sorted([r for r in rows if r["seg"] == seg], key=lambda r: -r["span_diag"])
        print(f"  {seg}: " + ", ".join(f"{r['key'].split('#')[1]}={r['span_diag']:.0f}"
                                        for r in sr[:6]))

    json.dump(rows, open(JD / "motion_rank_38.json", "w"), ensure_ascii=False, indent=1)
    print("\n->", JD / "motion_rank_38.json")


if __name__ == "__main__":
    main()
