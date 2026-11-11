#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_reid —— 门①-B 双指标验收（路线A 重连前后对比）。

复用既有验收口径，禁止事后调线：
  - 外观一致性：id_identity_audit.audit() => delta10 / adj_break(<0.5) / VERDICT(PASS 需 P1&P2&P3)
  - 身份错误率：ball_switch_classify.classify_seg() => replace / twin / two_real（真错误=replace+twin）
  emb_dump.json 在基线/重连间共用（顺序对齐，仅 track_id 变），保证对照公平。

硬约束（不得回退）：门①-A 不退化；本报告只读数不写，所有权在 reid_relink。

用法：
  python3 eval_reid.py --out action_work/norm_g3_reid --clean-json action_work/norm_calib/switch_classify_clean_g3.json
  python3 eval_reid.py --out action_work/norm_g3_reid --seg ep15_s0 ep32_s0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ENG = Path(__file__).resolve().parent
sys.path.insert(0, str(ENG))
import ball_switch_classify as C  # noqa: E402
import id_identity_audit as AUD  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="action_work/norm_g3")
    ap.add_argument("--out", default="action_work/norm_g3_reid")
    ap.add_argument("--clean-json", default="action_work/norm_calib/switch_classify_clean_g3.json")
    ap.add_argument("--seg", nargs="*", default=[])
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    out = Path(a.out)
    if a.seg:
        segs = a.seg
    else:
        cj = json.loads(Path(a.clean_json).read_text(encoding="utf-8"))
        segs = cj.get("clean_segs", [])

    rows = []
    for seg in segs:
        odir = out / seg
        base_bt = odir / "ball_tracks_base.json"
        rel_bt = odir / "ball_tracks.json"
        emb = odir / "emb_dump.json"
        if not (rel_bt.exists() and emb.exists()):
            print(f"[{seg}] 缺重连产物，跳过（先跑 reid_relink）")
            continue
        if not base_bt.exists():
            base_bt = Path(a.root) / seg / "ball_tracks.json"

        base_aud = AUD.audit(str(base_bt), str(emb))
        rel_aud = AUD.audit(str(rel_bt), str(emb))
        base_cls = C.classify_seg(json.loads(base_bt.read_text(encoding="utf-8")))
        rel_cls = C.classify_seg(json.loads(rel_bt.read_text(encoding="utf-8")))

        rows.append({
            "seg": seg,
            "delta10_base": base_aud.get("delta10"),
            "delta10_rel": rel_aud.get("delta10"),
            "adj_brk_base": base_aud.get("adj_break_ratio(<0.5)"),
            "adj_brk_rel": rel_aud.get("adj_break_ratio(<0.5)"),
            "verdict_base": base_aud["VERDICT"],
            "verdict_rel": rel_aud["VERDICT"],
            "rep_b": base_cls["replace"], "twin_b": base_cls["twin"], "tr_b": base_cls["two_real"],
            "rep_r": rel_cls["replace"], "twin_r": rel_cls["twin"], "tr_r": rel_cls["two_real"],
            "tot_b": sum(base_cls.values()), "tot_r": sum(rel_cls.values()),
        })

    if not rows:
        print("无可用段")
        return

    def s(k):
        return sum(r[k] for r in rows)

    tot_b, tot_r = s("tot_b"), s("tot_r")
    err_b = s("rep_b") + s("twin_b")
    err_r = s("rep_r") + s("twin_r")
    dd10 = np.mean([r["delta10_rel"] - r["delta10_base"] for r in rows
                    if r["delta10_base"] is not None and r["delta10_rel"] is not None])
    n_pass_b = sum(1 for r in rows if r["verdict_base"] == "PASS")
    n_pass_r = sum(1 for r in rows if r["verdict_rel"] == "PASS")

    print(f"{'段':<12}{'Δ10基':>8}{'Δ10重':>8}{'adj基':>7}{'adj重':>7}"
          f"{'rep基':>6}{'rep重':>6}{'twin基':>7}{'twin重':>7}{'Verdict':>14}")
    print("-" * 88)
    for r in rows:
        print(f"{r['seg']:<12}{str(r['delta10_base']):>8}{str(r['delta10_rel']):>8}"
              f"{str(r['adj_brk_base']):>7}{str(r['adj_brk_rel']):>7}"
              f"{r['rep_b']:>6}{r['rep_r']:>6}{r['twin_b']:>7}{r['twin_r']:>7}"
              f"{'  '+r['verdict_base']+'->'+r['verdict_rel']:>14}")

    print("\n=== 汇总（门①-B 双指标，重连前→后）===")
    print(f"  段数                 : {len(rows)}")
    print(f"  Δ10 均值变化         : {dd10:+.4f}  (基线→重连)")
    print(f"  adj_break(<0.5) 均值 : {np.mean([r['adj_brk_base'] for r in rows]):.4f} "
          f"→ {np.mean([r['adj_brk_rel'] for r in rows]):.4f}")
    print(f"  外观审计 PASS         : {n_pass_b}/{len(rows)} → {n_pass_r}/{len(rows)}")
    print(f"  球没动换ID 总事件     : {tot_b} → {tot_r}")
    print(f"  replace 重连/漂移     : {s('rep_b')} → {s('rep_r')}  "
          f"({(s('rep_b')/max(1,tot_b)*100):.1f}%→{s('rep_r')/max(1,tot_r)*100:.1f}%)")
    print(f"  twin   双胞胎         : {s('twin_b')} → {s('twin_r')}")
    print(f"  two_real 贴身两人     : {s('tr_b')} → {s('tr_r')}")
    print(f"  ⇒ 真·身份错误(replace+twin) = {err_b} → {err_r}  "
          f"({err_b/max(1,tot_b)*100:.1f}% → {err_r/max(1,tot_r)*100:.1f}%)")

    if a.json:
        Path(a.json).write_text(json.dumps(
            {"rows": rows,
             "summary": {"n_seg": len(rows), "tot_b": tot_b, "tot_r": tot_r,
                         "err_b": err_b, "err_r": err_r,
                         "dd10_mean": round(float(dd10), 4),
                         "pass_b": n_pass_b, "pass_r": n_pass_r}},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("\nwrote", a.json)


if __name__ == "__main__":
    main()
