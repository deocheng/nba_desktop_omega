#!/usr/bin/env python3
"""A5.7 把老程对 ep24_s1 全部 8 条裁定条目的人工裁定**落盘**，并算自动预判命中率。

裁定来源：老程 2026-10-01 逐条目视裁定（对话原文，未改）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
JD = ROOT / "action_work" / "track_judge"

# key: (老程裁定, 老程对内容的定性, 逐帧归属说明)
VERDICTS = {
    "ep24_s1#21": {
        "verdict": "换人",
        "subject": "观众",
        "note": "f26 是另一人；但这条轨迹本来就是观众（不是球员）",
        "groups": None,
    },
    "ep24_s1#190": {
        "verdict": "换人",
        "subject": "替补席+观众",
        "note": "103/111 是同一人；f135 有球员",
        "groups": {"A(替补席?)": [103, 111], "球员": [135]},
    },
    "ep24_s1#246": {
        "verdict": "换人",
        "subject": "替补席+观众",
        "note": "104/132/141 同一人(在替补席)；113/122 观众席同一人；150 是替补席的球员 ⇒ 一条轨里 3 个人",
        "groups": {"A(替补席)": [104, 132, 141], "B(观众席)": [113, 122], "C(球员)": [150]},
    },
    "ep24_s1#269": {
        "verdict": "同一人",
        "subject": "场上球员",
        "note": "f116 无法判断（疑似转场镜头的一帧）；其余都是同一人",
        "groups": None,
    },
    "ep24_s1#309": {
        "verdict": "换人",
        "subject": "替补席教练",
        "note": "148/149 是同一人；其余都是替补席里的教练",
        "groups": {"A": [148, 149], "教练": None},
    },
    "ep24_s1#336": {
        "verdict": "换人",
        "subject": "观众",
        "note": "160/165/167/171 都是同一名观众；173 那帧有球员但框里仍是该观众；177 是其他人",
        "groups": {"A(观众)": [160, 165, 167, 171, 173], "其他人": [177]},
    },
    "B:ep24_s1#88": {
        "verdict": "换人",
        "subject": "观众+球员",
        "note": "52/55/58/61 同一人(观众)；64 是球员；68 是观众",
        "groups": {"A(观众)": [52, 55, 58, 61], "B(球员)": [64], "C(观众)": [68]},
    },
    "B:ep24_s1#116": {
        "verdict": "换人",
        "subject": "观众",
        "note": "99 与 193 应该是同一个光头；其余都不是同一个人",
        "groups": {"A(光头)": [99, 193], "其余各帧": None},
    },
}


def load_items():
    import re
    h = (JD / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r"\[\{.*\}\]", h.split("\n")[31], re.S).group(0))


def seq_foot(src, tid):
    out = []
    for fr in src.get("frames") or []:
        for p in fr.get("players") or []:
            if p["id"] == tid:
                b = p["box"]
                out.append((fr["idx"], (b[0] + b[2]) / 2, b[3], b[3] - b[1]))
    out.sort()
    return out


def main():
    items = {x["key"]: x for x in load_items()}
    audit = json.load(open(JD / "jump_criterion_audit.json"))
    amap = {a["key"]: a for a in audit}
    cache = {}

    rows = []
    for key, v in VERDICTS.items():
        it = items[key]
        seg, tid = it["seg"], it["tid"]
        src_name = "tracks_b.json" if key.startswith("B:") else "tracks.json"
        if (seg, src_name) not in cache:
            cache[(seg, src_name)] = json.load(open(
                ROOT / "action_work" / "tactic_notes_batch_full" / "segments" / seg / src_name))
        seq = seq_foot(cache[(seg, src_name)], tid)
        a = amap[key]
        auto = "换人" if it["n_big"] > 0 else "同一人"
        hit = (auto == v["verdict"])
        raw_hit = ("换人" if a["n_big_raw"] > 0 else "同一人") == v["verdict"]
        rows.append({
            "key": key, "n": it["n"], "span": it["span"],
            "auto": auto, "auto_raw": "换人" if a["n_big_raw"] > 0 else "同一人",
            "verdict": v["verdict"], "hit": hit, "hit_raw": raw_hit,
            "subject": v["subject"], "note": v["note"],
            "raw_max": a["raw_max"], "rate_max": a["rate_max"],
            "mean_h": a["mean_h"],
            "frames": seq,
        })

    n = len(rows)
    print(f"{'key':<16}{'auto':<7}{'raw口径':<8}{'老程':<7}{'命中':<6}"
          f"{'rawmax':>8}{'mean_h':>7}  内容")
    for r in rows:
        print(f"{r['key']:<16}{r['auto']:<7}{r['auto_raw']:<8}{r['verdict']:<7}"
              f"{'✅' if r['hit'] else '❌':<6}{r['raw_max']:>8}{r['mean_h']:>7}  {r['subject']}")

    hit = sum(r["hit"] for r in rows)
    hit_raw = sum(r["hit_raw"] for r in rows)
    same = [r for r in rows if r["auto"] == "同一人"]
    chg = [r for r in rows if r["auto"] == "换人"]
    print(f"\n总命中率（工作台 rate 口径）: {hit}/{n} = {hit/n:.1%}")
    print(f"总命中率（raw 原始位移口径）: {hit_raw}/{n} = {hit_raw/n:.1%}")
    print(f"  预判「同一人」的 {len(same)} 条：老程判同一人 "
          f"{sum(r['verdict']=='同一人' for r in same)}/{len(same)} ⇒ 该判据准确率 "
          f"{sum(r['verdict']=='同一人' for r in same)/len(same):.1%}")
    print(f"  预判「换人」的 {len(chg)} 条：老程判换人 "
          f"{sum(r['verdict']=='换人' for r in chg)}/{len(chg)} ⇒ 该判据准确率 "
          f"{sum(r['verdict']=='换人' for r in chg)/len(chg):.1%}")

    oncourt = [r for r in rows if r["subject"] == "场上球员"]
    print(f"\n8 条里只有 {len(oncourt)} 条是场上球员（{', '.join(r['key'] for r in oncourt) or '无'}）；"
          f"其余 {n-len(oncourt)} 条是观众/替补席/教练")

    # 老程明确指出"同一人"的组内，切换时刻的位移量级
    print("\n换人切换点的位移量级（老程分组的相邻组之间）：")
    for r in rows:
        g = VERDICTS[r["key"]].get("groups")
        if not g:
            continue
        byf = {f[0]: f for f in r["frames"]}
        keys = list(g.keys())
        for i in range(len(keys) - 1):
            fa, fb = g[keys[i]], g[keys[i + 1]]
            if not fa or not fb:
                continue
            la, lb = fa[-1], fb[0]
            if la in byf and lb in byf:
                d = ((byf[lb][1] - byf[la][1]) ** 2 + (byf[lb][2] - byf[la][2]) ** 2) ** 0.5
                print(f"  {r['key']:<16} {keys[i]}→{keys[i+1]}: f{la}→f{lb} 位移 {d:.0f}px"
                      f"（df={lb-la}） 框高 {byf[la][3]:.0f}→{byf[lb][3]:.0f}")

    out = JD / "verdicts_ep24_s1.json"
    json.dump({"rows": rows,
               "hit_rate": hit / n,
               "hit_rate_raw": hit_raw / n,
               "n": n},
              open(out, "w"), ensure_ascii=False, indent=1)
    print("\n->", out)


if __name__ == "__main__":
    main()
