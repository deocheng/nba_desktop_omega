#!/usr/bin/env python3
"""A5.8c 老程判据验证：**「移动距离」筛掉无价值目标**（球员/裁判 = 场上移动距离最大的目标）。

老程原话：「球员和裁判是场上移动距离最大的目标，其他都是无价值的啊」
⇒ 判据不靠地板掩膜，靠**运动量**：观众/替补席/教练坐着不动，球员/裁判持续跑动。

指标（每个轨迹/每帧算）：
- med_step  : 每帧脚点位移的**中位数**（典型运动量；混串的观众串大部分帧静止 ⇒ 小）
- move_frac : 位移 > MOVE_PX 的帧占比（"动帧"比例）
- total_disp: 总位移（会被长轨放大，仅参考）
验证集：老程裁定的 ep24_s1 8 条（#269=球员有价值；其余 7 条=观众/替补席/教练=无价值）
        + 全 38 条（看分布是否双峰）
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
MOVE_PX = 3.0          # "算在动"的每帧位移阈值(px/帧)

# 老程 2026-10-01 08:00 补充裁定（ep1_s0#116 精确分组）
GROUP_116 = {126: "球员", 141: "观众A", 154: "观众A", 167: "观众A",
             181: "观众A", 194: "观众A", 207: "邻座B", 220: "邻座B"}

# 老程裁定的 ep24_s1 8 条：value = 有价值(场上) / 无价值
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


def metrics(seq):
    st = []
    for i in range(1, len(seq)):
        df = seq[i][0] - seq[i - 1][0]
        if df <= 0:
            continue
        d = ((seq[i][1] - seq[i - 1][1]) ** 2 + (seq[i][2] - seq[i - 1][2]) ** 2) ** 0.5
        st.append(d / df)
    if not st:
        return 0.0, 0.0, 0.0
    s = sorted(st)
    med = s[len(s) // 2]
    frac = sum(1 for v in st if v > MOVE_PX) / len(st)
    return med, frac, sum(st) * 0 + sum(s)


def main():
    items = load_items()
    cache = {}
    rows = []
    for it in items:
        seg, tid = it["seg"], it["tid"]
        src_name = "tracks_b.json" if it["key"].startswith("B:") else "tracks.json"
        k = (seg, src_name)
        if k not in cache:
            cache[k] = json.load(open(SEGD / seg / src_name))
        seq = seq_of(cache[k], tid)
        med, frac, tot = metrics(seq)
        rows.append({"key": it["key"], "n": it["n"], "span": it["span"],
                     "med_step": round(med, 2), "move_frac": round(frac, 3),
                     "total_disp": round(tot, 1),
                     "value": VALUE.get(it["key"], "未知")})

    print("=== 老程裁定的 ep24_s1 8 条 ===")
    print(f"{'key':<16}{'value':<8}{'n':>4} {'med_step':>9}{'move_frac':>10}  判定")
    sub = [r for r in rows if r["key"] in VALUE]
    sub.sort(key=lambda r: -r["med_step"])
    for r in sub:
        keep = r["med_step"] >= 5.0
        ok = "✅" if (keep and r["value"] == "有价值") or \
             ((not keep) and r["value"] == "无价值") else "❌"
        print(f"{r['key']:<16}{r['value']:<8}{r['n']:>4} {r['med_step']:>9}"
              f"{r['move_frac']:>10}  {ok}")
    val = [r for r in sub if r["value"] == "有价值"]
    nov = [r for r in sub if r["value"] == "无价值"]
    print(f"\n有价值(球员) med_step = {[r['med_step'] for r in val]}")
    print(f"无价值 med_step      = {sorted(r['med_step'] for r in nov)}")
    if val and nov:
        print(f"⇒ 最小有价值 {min(r['med_step'] for r in val):.2f} vs "
              f"最大无价值 {max(r['med_step'] for r in nov):.2f}")

    print("\n=== 全 38 条 med_step 分布（升序）===")
    allr = sorted(rows, key=lambda r: r["med_step"])
    for r in allr:
        tag = r["value"]
        print(f"  {r['key']:<16} med_step={r['med_step']:>6}  move_frac={r['move_frac']:>5}  {tag}")
    ms = sorted(r["med_step"] for r in rows)
    print(f"\nmed_step 分位: p10={ms[len(ms)//10]:.2f} p25={ms[len(ms)//4]:.2f} "
          f"med={ms[len(ms)//2]:.2f} p75={ms[3*len(ms)//4]:.2f} p90={ms[9*len(ms)//10]:.2f}")

    # ep1_s0#116 老程精确分组：各组内的运动量
    print("\n=== ep1_s0#116 老程精确分组后的组内运动量 ===")
    tr = cache[("ep1_s0", "tracks.json")]
    seq = seq_of(tr, 116)
    byf = {s[0]: s for s in seq}
    grp = {}
    for f, g in GROUP_116.items():
        grp.setdefault(g, []).append(f)
    for g, fs in grp.items():
        sub_seq = [byf[f] for f in sorted(fs) if f in byf]
        m, fr, _ = metrics(sub_seq)
        print(f"  {g}({len(sub_seq)}帧): med_step={m:.2f} px/帧  move_frac={fr:.2f}")

    out = JD / "motion_gate_38.json"
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=1)
    print("\n->", out)


if __name__ == "__main__":
    main()
