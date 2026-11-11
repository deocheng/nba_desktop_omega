#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""id_stability_corpus_summary —— 全语料的门 ①-A 汇总（两种口径一起出数）。

背景（承 A5.31 / 本轮实测）：
  · 带净化过滤(conf0.40/h80)跑通后，18 段样本实测 **保真率 =
    稳定化并发 / 输入框中位 = 1.00（18/18 精确相等）**。
    ⇒ 稳定化没有制造任何 ID 碎片（也不是错并），
    ⇒ 但同时暴露：门①-A 的「并发中位」在过滤后**退化成"数输入"**，
      它测的是上游检测密度，不是稳定化质量。
  · 于是 10/18 的 FAIL 全部来自**输入的镜头景别**（广角 17~18 人、
    特写 4~5 人），不是稳定化。

本脚本对全部段同时给两套判据，避免"只报好看的那个"：
  口径甲（老口径，绝对带）：并发中位 ∈[8,16] 且 中位寿命 ≥30
  口径乙（相对保真）：保真率 ∈[0.80,1.25] 且 中位寿命 ≥30
                      —— 保真率=并发中位/输入框中位（1.00=每个可见人恰好一 ID）
  并报告「并发~输入框」的差值（差值>0=碎片倾向，<0=错并倾向）。

用法:
  python3 id_stability_corpus_summary.py --root action_work/norm_g3
  python3 id_stability_corpus_summary.py --root action_work/norm_g3 --json out.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import statistics
from pathlib import Path

from common.nba_paths import tactics_data_file

SEGDIR = Path(str(tactics_data_file("action_work/tactic_notes_batch_full/segments")))
BAND_LO, BAND_HI = 8, 16
LIFE_THR = 30
FID_LO, FID_HI = 0.80, 1.25


def raw_med_count(seg, conf=0.40, topn=12):
    """输入框中位人数。口径必须和 stabilize 的 --conf-min/--topn 完全一致：
    conf>=0.40 过滤后，每帧再取**框最高的 topn 个**。（h_min 已弃用，见 --h-min 注释：
    绝对像素高度对景别不鲁棒，会把宽景镜头里的真球员砍光。）"""
    p = SEGDIR / seg / "ball_tracks.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    c = []
    for r in d:
        ps = [pp for pp in (r.get("players") or []) if (pp.get("conf") or 0.0) >= conf]
        if topn and len(ps) > topn:
            ps = sorted(ps, key=lambda pp: -(pp["bbox"][3] - pp["bbox"][1]))[:topn]
        c.append(len(ps))
    return statistics.median(c) if c else None


def audit_tracks(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(d, dict):
        for k in ("tracks", "records", "frames"):
            if k in d:
                d = d[k]
                break
    conc, life = [], {}
    for r in d:
        ids = {p.get("track_id") for p in (r.get("players") or [])
               if p.get("track_id") is not None}
        conc.append(len(ids))
        for t in ids:
            life[t] = life.get(t, 0) + 1
    return (statistics.median(conc) if conc else 0.0,
            statistics.median(life.values()) if life else 0.0,
            sum(1 for v in conc if v) and len(d))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="action_work/norm_g3")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    root = Path(a.root)
    segs = sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / "ball_tracks.json").exists())
    rows = []
    for s in segs:
        inp = raw_med_count(s)
        c, ml, nf = audit_tracks(root / s / "ball_tracks.json")
        fid = c / inp if inp else 0.0
        rows.append({"seg": s, "input": inp, "conc": c, "med_life": ml,
                     "fidelity": round(fid, 3), "delta": round(c - inp, 1) if inp else 0.0,
                     "gate_abs": 8 <= c <= 16 and ml >= 30,
                     "gate_fid": FID_LO <= fid <= FID_HI and ml >= 30})

    rows.sort(key=lambda r: r["seg"])
    hdr = (f"{'段':<11}{'输入框':>7}{'并发':>7}{'Δ':>7}{'保真':>7}"
           f"{'中位寿命':>9}{'甲绝对':>7}{'乙保真':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['seg']:<11}{r['input']:>7.0f}{r['conc']:>7.1f}{r['delta']:>7.1f}"
              f"{r['fidelity']:>7.2f}{r['med_life']:>9.0f}"
              f"{'PASS' if r['gate_abs'] else 'FAIL':>8}{'PASS' if r['gate_fid'] else 'FAIL':>8}")

    n = len(rows)
    na = sum(r["gate_abs"] for r in rows)
    nb = sum(r["gate_fid"] for r in rows)
    print(f"\n段数 {n}")
    print(f"  甲(绝对带 [8,16]+寿命≥30) 通过 {na}/{n}  ({na/max(1,n)*100:.0f}%)")
    print(f"  乙(保真率 [0.80,1.25]+寿命≥30) 通过 {nb}/{n}  ({nb/max(1,n)*100:.0f}%)")
    print(f"  保真率 中位 {statistics.median([r['fidelity'] for r in rows]):.3f}"
          f"  | Δ(并发-输入) 中位 {statistics.median([r['delta'] for r in rows]):+.2f}")
    import collections
    b = collections.Counter(int(r["input"]) for r in rows if r["input"])
    print("  输入框中位分布(段数):", dict(sorted(b.items())))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print("wrote", a.json)


if __name__ == "__main__":
    main()
