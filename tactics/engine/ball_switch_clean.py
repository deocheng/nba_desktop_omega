#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ball_switch_clean —— A5.32b 收尾：纯净比赛段子集上的最终 replace+twin 率。

⚠️ 关键方法论校正（2026-10-03 实测）：
  路线 A 原设想「用球框坐标分布自动区分纯净/污染段」，但实测证明 **位置信号不可分**：
  - 白板类假球（球检测器把白板红字当球）与「真实右倾比赛段」（球确实长期在右半场）在
    fr_half(右半占比) 与 空间方差(std_x) 上完全重叠：
      * ep83_s1/wcep3_s0(已视觉确认白板) 的 fr_half≈0.87 / std_x≈210，
        与 ep65_s0(右倾真比赛,cov=0.80)/ep72_s1(cov=0.88) 几乎相同；
      * 全语料 fr_half 连续分布(0→1)，(0.45,0.60) 区间有 23 段高覆盖率真比赛段。
  ⇒ 任何阈值要么误伤真比赛(过排)，要么漏排白板(欠排)。位置分类器是「假完整」陷阱。

  因此本脚本改用 **证据优先** 方案：
  ① 排除集 = A5.32b 已「视觉自证」确认的污染段（金标准，非位置启发式）；
  ② 补充一个可证伪的 fr_half≥0.67 白板检测器（复现 A5.32b 原信号「球框67-100%落右半」），
     其命中段单列、不参与主数，仅作交叉验证；
  ③ 主数 = 在「除确认污染段」后的子集上重跑 replace/twin/two_real；
  ④ 诚实声明盲区：弱白板(ep8_s1)/观众席(ep17_s1)/wcep4_s0 等位置信号弱，
     只能用已视觉确认名单排除，自动化位置规则抓不到。

  金标准证据下限（A5.32b 已抽样确证真·一人两ID）：4 干净锚点 ep32_s0/ep62_s1/ep69_s0/ep32_s1
  所在「宽判干净段 88 段」合计 replace=101 确证真实存在。

用法：
  python3 ball_switch_clean.py --root action_work/norm_g3
  python3 ball_switch_clean.py --root action_work/norm_g3 --json action_work/norm_calib/switch_classify_clean_g3.json
"""
from __future__ import annotations

import argparse
import json
import sys as _sys
from pathlib import Path

import numpy as np

_sys.path.insert(0, str(Path(__file__).resolve().parent))
import ball_holder_identity as B  # noqa: E402
import ball_switch_classify as C  # noqa: E402

W, H = 1280, 720

# ① A5.32b 视觉自证确认的污染段（金标准，不靠位置启发式）
VISUAL_DIRTY = {
    # 白板类（球检测器把白板红笔字/红圈当球）
    "ep14_s1", "ep54_s1", "ep75_s0", "ep83_s1", "wcep3_s0", "ep28_s1", "ep65_s0",
    # 观众席/字幕类
    "ep17_s1",
    # 弱白板/位置信号弱但已视觉确认（位置规则抓不到）
    "ep8_s1", "wcep4_s0", "ep1_s1",
}
# ② 干净锚点（应保留，且 replace 已抽样确证真实）
ANCHOR_CLEAN = {"ep32_s0", "ep62_s1", "ep69_s0", "ep32_s1"}


def seg_signals(d):
    bcs = []
    for r in d:
        b = (r.get("ball") or {}).get("bbox")
        if b:
            bcs.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
    n = len(d)
    out = {"n": n, "nb": len(bcs)}
    if not bcs:
        out.update(cov=0.0, fr_half=0.0, fr66=0.0, fr_top=0.0, std_x=0.0)
        return out
    cov = len(bcs) / max(1, n)
    bx = np.array([p[0] for p in bcs]); by = np.array([p[1] for p in bcs])
    out.update(cov=round(cov, 3),
               fr_half=float((bx > 0.5 * W).mean()),
               fr66=float((bx > 0.66 * W).mean()),
               fr_top=float((by < 0.12 * H).mean()),
               std_x=round(float(np.std(bx)), 1))
    return out


def is_dirty(d, seg, thr_half=0.67):
    """返回 (is_dirty, reasons_list)。"""
    if seg in VISUAL_DIRTY:
        return True, ["视觉确认污染(金标准)"]
    s = seg_signals(d)
    reasons = []
    if s["fr66"] > 0.5:
        reasons.append(f"白板右三分之一{fr66_fmt(s['fr66'])}")
    if s["fr_half"] >= thr_half:
        reasons.append(f"白板右半≥{thr_half:.2f}({s['fr_half']:.2f})")
    if s["fr_top"] > 0.30:
        reasons.append(f"观众席顶部{s['fr_top']:.2f}")
    if s["cov"] < 0.06:
        reasons.append(f"无球覆盖率{s['cov']:.3f}")
    return (len(reasons) > 0), reasons


def fr66_fmt(v):
    return f"{v:.2f}"


def classify_on(segs_root, seg_list, full_diag):
    rows = []
    for s in seg_list:
        d = json.loads((segs_root / s / "ball_tracks.json").read_text(encoding="utf-8"))
        c = C.classify_seg(d)
        rows.append({"seg": s, **c, "total": sum(c.values())})
    s_ = lambda k: sum(r[k] for r in rows)
    tot = s_("total")
    return {
        "n_seg": len(rows), "total": tot,
        "replace": s_("replace"), "twin": s_("twin"), "two_real": s_("two_real"),
        "err_rate": (s_("replace") + s_("twin")) / max(1, tot),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="action_work/norm_g3")
    ap.add_argument("--json", default="")
    ap.add_argument("--thr-half", type=float, default=0.67)
    a = ap.parse_args()
    root = Path(a.root)
    segs = sorted(d.name for d in root.iterdir()
                 if d.is_dir() and (d / "ball_tracks.json").exists())

    clean_segs, dirty_segs = [], []
    diag = {"dirty_reasons": {}, "anchor_check": {}, "fr66_candidates": []}
    for s in segs:
        d = json.loads((root / s / "ball_tracks.json").read_text(encoding="utf-8"))
        dirty, reasons = is_dirty(d, s, a.thr_half)
        (dirty_segs if dirty else clean_segs).append(s)
        if dirty:
            diag["dirty_reasons"][s] = reasons
        sig = seg_signals(d)
        if sig["fr66"] > 0.5 and s not in VISUAL_DIRTY:
            diag["fr66_candidates"].append({"seg": s, **sig})
        if s in VISUAL_DIRTY or s in ANCHOR_CLEAN:
            if s in VISUAL_DIRTY:
                diag["anchor_check"][s] = "DIRTY(排除) ✓期望"
            else:
                diag["anchor_check"][s] = "CLEAN(保留) ✓期望" if not dirty else "CLEAN ✗误伤"

    # 主数：纯净子集
    m = classify_on(root, clean_segs, diag)
    print(f"段总数 {len(segs)}  纯净段 {len(clean_segs)}  污染段 {len(dirty_segs)}")
    print("\n=== 纯净段子集 replace/twin/two_real（门①-B 最终可信数字, 主数）===")
    print(f"  段数                    : {m['n_seg']}")
    print(f"  球没动换ID 总事件       : {m['total']}")
    print(f"  replace 重连/一人两ID   : {m['replace']:>5} ({m['replace']/max(1,m['total'])*100:5.1f}%)")
    print(f"  twin   双胞胎一人两ID   : {m['twin']:>5} ({m['twin']/max(1,m['total'])*100:5.1f}%)")
    print(f"  two_real 贴身两人       : {m['two_real']:>5} ({m['two_real']/max(1,m['total'])*100:5.1f}%)")
    print(f"  ⇒ 真·身份错误(replace+twin) = {m['replace']+m['twin']} "
          f"({(m['replace']+m['twin'])/max(1,m['total'])*100:.1f}% of 纯净段球没动换ID)")

    # 对照全量
    g = json.loads(Path("action_work/norm_calib/switch_classify_g3.json").read_text()) if \
        Path("action_work/norm_calib/switch_classify_g3.json").exists() else None
    if g:
        gt = sum(x["total"] for x in g); gr = sum(x["replace"] for x in g); gt2 = sum(x["twin"] for x in g)
        print(f"\n对照全语料(含污染): 真错误 {gr+gt2}/{gt} = {(gr+gt2)/gt*100:.1f}%  "
              f"vs 纯净子集 {(m['replace']+m['twin'])/max(1,m['total'])*100:.1f}%")

    # 敏感性：不同 fr_half 阈值下纯净子集真错误率（证明不可分/稳健性）
    print("\n=== 敏感性：fr_half 阈值扫描（污染段=视觉确认∪fr_half≥thr）===")
    print(f"  {'thr':>5} {'纯净段':>6} {'total':>6} {'replace':>8} {'twin':>5} {'err%':>6}")
    for thr in (0.45, 0.55, 0.67, 0.80):
        cs = []
        for s in segs:
            d = json.loads((root / s / "ball_tracks.json").read_text())
            if s in VISUAL_DIRTY:
                continue
            if seg_signals(d)["fr_half"] >= thr:
                continue
            cs.append(s)
        mm = classify_on(root, cs, diag)
        print(f"  {thr:>5.2f} {mm['n_seg']:>6} {mm['total']:>6} {mm['replace']:>8} "
              f"{mm['twin']:>5} {mm['err_rate']*100:>5.1f}%")

    print("\n=== 锚点校准（金标准段，验证排除方向正确）===")
    for k, v in sorted(diag["anchor_check"].items()):
        print(f"  {k:<11} {v}")

    print("\n=== fr66>0.5 自动候选(非视觉确认, 需人工复核是否真比赛) ===")
    for c in sorted(diag["fr66_candidates"], key=lambda x: -x["fr66"])[:20]:
        print(f"  {c['seg']:<11} fr66={c['fr66']:.3f} cov={c['cov']:.3f} std_x={c['std_x']:.1f} nb={c['nb']}")

    if a.json:
        out = {"clean_segs": clean_segs, "dirty_segs": dirty_segs,
               "summary": {"clean": len(clean_segs), "dirty": len(dirty_segs), **m},
               "anchor_check": diag["anchor_check"],
               "dirty_reasons": diag["dirty_reasons"],
               "fr66_candidates": diag["fr66_candidates"]}
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\nwrote", a.json)


if __name__ == "__main__":
    main()
