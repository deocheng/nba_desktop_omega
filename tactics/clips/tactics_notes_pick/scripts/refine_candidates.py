#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选精筛：在 shot_scale_seq 产出上施加 4 道门控，产出高置信「完整配合」。

五道硬门控 + 第6道标记门控（记分牌仅标记不自动排除）：
  ① 景别链 远→中→特（顺序成立，来自 shot_scale_seq）
  ② **无死球**：全程活跃度 > 死球阈（归零 = 进球/暂停/失误 ⇒ 回合已结束）
  ③ **时长 8~20s**：24 秒进攻窗口的合理跨度（跨回合会被 ②③ 杀掉）
  ④ 特写段 ≤4s：过长 = 回放/慢镜/庆祝，不是正常出手镜头
  ⑤ 特写框高 ∈ [600,760]：真特写（不是 500 的中近景，也不是误检）
  ⑥ **特写段记分牌(标记,非排除)**：特写段 ROI 静态差→sb_frac。实测活球特写也常带记分牌(cand932/1119/428 sb>0.5 但老程判一次进攻)，故仅标记供老程裁定；sb_frac=1.0 多为吹停转场(如cand1244)

用法：refine_candidates.py <shot_scale_full.json> [out_json]
"""
import json
import sys

import numpy as np


def refine(d, act_p10=2.0, dur_lo=8.0, dur_hi=20.0, close_max=4.0,
           h_close_lo=560.0, h_close_hi=800.0, sb_frac_max=0.5):
    ts = np.array(d["ts"]); h = np.array(d["hmax"]); act = np.array(d["act"])
    thr_lo, thr_hi = d["thr_lo"], d["thr_hi"]
    lab = []
    for v in h:
        lab.append("远" if v < thr_lo else ("特" if v > thr_hi else "中"))
    lab = np.array(lab)
    # 死球掩码
    dead = act < act_p10
    # 第6道门控信号：特写段记分牌 ROI 静态差（shot_scale_seq 产出，缺则跳过该门）
    sb = np.array(d["sb"]) if d.get("sb") else None

    # 景别段
    segs = []
    i = 0
    while i < len(lab):
        j = i
        while j + 1 < len(lab) and lab[j + 1] == lab[i]:
            j += 1
        segs.append({"lab": lab[i], "t0": float(ts[i]), "t1": float(ts[j]),
                     "hmed": float(np.median(h[i:j + 1])),
                     "i0": i, "i1": j})
        i = j + 1

    out = []
    for si, s in enumerate(segs):
        if s["lab"] != "特":
            continue
        if not (h_close_lo <= s["hmed"] <= h_close_hi):
            continue
        if s["t1"] - s["t0"] > close_max:
            continue
        # 第6道门控（⚠️ 仅标记不自动排除）：特写段记分牌 ROI 静态差
        # 实测活球特写也常带记分牌(cand932/1119/428 均 sb>0.5 但老程判为一次进攻)，
        # 故记分牌在≠吹停，仅记 sb_frac 供老程裁定；sb_frac≈1.0 多为吹停转场(cand1244)
        sb_frac = -1.0
        if sb is not None:
            m_s = (ts >= s["t0"]) & (ts <= s["t1"])
            if m_s.sum() > 0:
                sb_frac = round(float(sb[m_s].mean()), 2)
        far = None
        for sj in range(si - 1, -1, -1):
            if segs[sj]["lab"] == "远":
                far = segs[sj]; break
        if far is None:
            continue
        mids = [x for x in segs[:si] if x["lab"] == "中" and x["t1"] > far["t0"]]
        if not mids:
            continue
        mid_first, mid_last = mids[0], mids[-1]

        span0, span1 = far["t0"], s["t1"]
        dur = span1 - span0
        if not (dur_lo <= dur <= dur_hi):
            continue
        m = (ts >= span0) & (ts <= span1)
        n_dead = int(dead[m].sum())
        if n_dead > 0:
            continue
        act_win = act[m]
        # 形态：低谷→上升→峰（老程验证过的判据）
        if len(act_win) < 5:
            continue
        b = act_win[1:]
        pk = int(np.argmax(b)); tr = int(np.argmin(b[:pk + 1]))
        rise = float(b[pk] - b[tr])
        shape_ok = bool(tr < pk and rise > 2.0)

        out.append({
            "far": [round(far["t0"], 1), round(far["t1"], 1), round(far["hmed"])],
            "mid": [round(mid_first["t0"], 1), round(mid_last["t1"], 1)],
            "close": [round(s["t0"], 1), round(s["t1"], 1), round(s["hmed"])],
            "dur": round(dur, 1), "act_rise": round(rise, 1),
            "shape_ok": shape_ok, "sb_frac": sb_frac,
            "clip": [round(far["t0"] - 1.5, 1), round(s["t1"] + 3.0, 1)],
        })
    return out, segs, dead


if __name__ == "__main__":
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/candidates.json"
    d = json.load(open(src))
    cands, segs, dead = refine(d)
    print(f"景别阈值 远<{d['thr_lo']:.0f} 特>{d['thr_hi']:.0f}")
    print(f"采样 {len(d['ts'])} 点  跨度 {d['ts'][0]}~{d['ts'][-1]}s  "
          f"死球点 {int(dead.sum())}")
    print(f"\n=== 通过全部 6 道门控的候选：{len(cands)} ===")
    print(f"{'远景(框高)':<22}{'中景':<16}{'特写(框高)':<22}{'时长':<7}"
          f"{'升幅':<7}{'形态':<6}{'sb':<6}建议剪")
    for c in sorted(cands, key=lambda x: -x["dur"]):
        print(f"{str(c['far']):<22}{str(c['mid']):<16}{str(c['close']):<22}"
              f"{c['dur']:<7}{c['act_rise']:<7}{'✅' if c['shape_ok'] else '⚠️':<6}"
              f"{c.get('sb_frac','-'):<6}{c['clip']}")

    # 放宽一档：允许 1 个死球采样点（采样 1s 时可能是瞬时抖动）
    cands2, _, _ = refine(d)
    print(f"\n（严格门控命中 {len(cands2)} 个）")
    json.dump({"src": d["src"], "cands": cands}, open(out, "w"),
              ensure_ascii=False, indent=1)
    print(f"wrote {out}")
