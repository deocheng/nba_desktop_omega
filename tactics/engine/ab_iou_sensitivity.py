#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_iou_sensitivity.py — A/B「一致/变化」判据的敏感性检验。

隐患
----
`ball_head_v2.py` 用 `IoU >= 0.5` 判断"新旧 top-1 是否同一个框"。
但球框只有 ~25–35px：两个 30px 的框，IoU=0.5 只允许**框心差 ≈ 9px**。
同一个球被模型框得稍偏一点，IoU 就会掉到 0.5 以下 ⇒ 被误记成"变化帧"。
后果：变化数虚高、下行风险（原TP变化帧）被夸大、上界被撑大。

正解
----
小目标的一致性应优先用**中心距**（相对球径归一化），IoU 只作参考。
本脚本在多个判据下重算一致/变化，并给出"仅因判据变化而被算作变化"的帧数。

用法:
  python engine/ab_iou_sensitivity.py
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import math
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW, MS = ROOT / "action_work", ROOT / "reports/milestone_05/measure"


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2-x1) * max(0, y2-y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i/ua if ua > 0 else 0.0


def cdist(a, b):
    return math.hypot((a[0]+a[2])/2-(b[0]+b[2])/2, (a[1]+a[3])/2-(b[1]+b[3])/2)


def size(a):
    return ((a[2]-a[0]) + (a[3]-a[1])) / 2.0


def main():
    scores = json.load(open(AW / "ball_cand_scores_v2.json"))
    cands = json.load(open(AW / "ball_cands_all.json"))   # 含 conf1/conf2
    bank = [r for r in json.load(open(MS / "labels_bank.json"))
            if r["label"] in ("TP", "FP")]
    n = len(bank)

    # 旧 top-1（conf1 最高，来自检测器）与新 top-1（prob 最高，来自验证头）
    # ⚠️ ball_cand_scores_v2.json 只存 bbox+prob；conf1 需从 ball_cands_all.json 按索引对齐
    #    （ball_head_v2.py 逐帧按原顺序写出，索引一一对应）
    rows = []
    for r in bank:
        w, f = r["window"], r["frame"]
        cs = scores.get(w, {}).get(f, [])
        raw = cands.get(w, {}).get(f, [])
        if not cs:
            continue
        new = max(cs, key=lambda c: c["prob"])
        # 用 conf1（若有）作旧选择器；索引对齐
        best_old, bc = None, -1.0
        for i, c in enumerate(cs):
            c1 = raw[i].get("conf1", 0.0) if i < len(raw) else 0.0
            if c1 > bc:
                bc, best_old = c1, c
        if best_old is None:
            best_old = cs[0]
        rows.append({"label": r["label"], "win": w, "frame": f,
                     "label_box": r["bbox"], "new_box": new["bbox"],
                     "old_box": best_old["bbox"], "new_p": new["prob"], "old_c": bc})
    print(f"可比对帧 {len(rows)} / 标注库 {n}")
    # 自洽校验：旧选择器（conf1 top-1）应与标注框高度一致（标注就是对旧 top-1 做的）
    agree = sum(1 for r in rows if iou(r["old_box"], r["label_box"]) >= 0.5)
    print(f"自洽校验：conf1 top-1 与标注框 IoU>=0.5 的帧 {agree}/{len(rows)} = "
          f"{agree/len(rows)*100:.1f}%（应接近 100%，否则索引对齐有问题）")

    # 判据表
    crits = [("IoU>=0.5（现用）", lambda a, b: iou(a, b) >= 0.5),
             ("IoU>=0.3", lambda a, b: iou(a, b) >= 0.3),
             ("IoU>=0.1", lambda a, b: iou(a, b) >= 0.1),
             ("中心距<=10px", lambda a, b: cdist(a, b) <= 10),
             ("中心距<=15px", lambda a, b: cdist(a, b) <= 15),
             ("中心距<=20px", lambda a, b: cdist(a, b) <= 20),
             ("中心距<=0.5*max(边)", lambda a, b: cdist(a, b) <= 0.5*max(size(a), size(b)))]
    # 新 top-1 与「标注框」比（A/B 实际用的比较）
    print("\n--- 新 top-1 vs 标注框（= A/B 的原判据）---")
    print(f"{'判据':<22}{'一致':>6}{'变化':>6}{'变化中原TP':>11}{'变化中原FP':>11}"
          f"{'下界P':>9}{'上界P':>9}")
    base = None
    table = {}
    for name, f in crits:
        same = [r for r in rows if f(r["new_box"], r["label_box"])]
        chg = [r for r in rows if not f(r["new_box"], r["label_box"])]
        stp = sum(1 for r in same if r["label"] == "TP")
        ctp = sum(1 for r in chg if r["label"] == "TP")
        cfp = sum(1 for r in chg if r["label"] == "FP")
        lo, hi = stp/n*100, (stp+len(chg))/n*100
        table[name] = {"same": len(same), "changed": len(chg), "same_TP": stp,
                       "changed_TP": ctp, "changed_FP": cfp, "lo": lo, "hi": hi}
        print(f"{name:<22}{len(same):>6}{len(chg):>6}{ctp:>11}{cfp:>11}{lo:>9.1f}{hi:>9.1f}")
        if base is None:
            base = table[name]

    # 反向：新 top-1 vs 旧 conf top-1（"新旧是否选了同一个框"，与标注无关）
    print("\n--- 新 top-1 vs 旧 conf top-1（不看标注，纯比较两种选择器）---")
    for name, f in crits:
        k = sum(1 for r in rows if f(r["new_box"], r["old_box"]))
        print(f"{name:<22} 相同 {k:>4} / {len(rows)} = {k/len(rows)*100:.1f}%")

    # 关键定量：若判据放宽，有多少"变化"其实是**同一个球的框抖动**？
    strict = table["IoU>=0.5（现用）"]
    loose = table["中心距<=15px"]
    print(f"\n🔴 判据敏感性：IoU>=0.5 认为变化 {strict['changed']} 帧；"
          f"改中心距<=15px 后只剩 {loose['changed']} 帧")
    print(f"   ⇒ {strict['changed']-loose['changed']} 帧（{(strict['changed']-loose['changed'])/max(1,strict['changed'])*100:.0f}%）"
          f"属于**同一物体的框抖动**，不是真正的重选。")
    print(f"   上下界随判据移动：IoU0.5 [{strict['lo']:.1f}%,{strict['hi']:.1f}%] → "
          f"中心距15px [{loose['lo']:.1f}%,{loose['hi']:.1f}%]")

    json.dump({"n": len(rows), "table": table,
               "jitter_frames": strict["changed"] - loose["changed"]},
              open(MS / "ab_iou_sensitivity.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n→ {MS/'ab_iou_sensitivity.json'}")


if __name__ == "__main__":
    main()
