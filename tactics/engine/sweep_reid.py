#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep_reid —— 路线A 实证扫描：在 5 段干净段上扫 τ 与合并策略，量化可达降幅。

不写盘（用缓存 gallery/emb，纯内存计算），输出事实表供裁定：
  - replace/twin/two_real（球没动换ID 三类）
  - Δ10 均值 + 外观审计 PASS 数（双指标护栏：错并会被 Δ10 下跌抓住）
组合：
  A_clean        : 仅合并「A 死→B 生」遮挡分裂（路线A原设计）
  B_overlap_same : 允许合并重叠高相似碎片 + 强团队约束
  C_overlap_noteam: 允许合并重叠高相似碎片 + 忽略团队标签
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ENG = Path(__file__).resolve().parent
sys.path.insert(0, str(ENG))
import ball_switch_classify as C  # noqa: E402
import id_identity_audit as AUD  # noqa: E402
import reid_relink as R  # noqa: E402

SEGS = ["ep15_s0", "ep32_s0", "ep62_s1", "ep69_s0", "ep32_s1"]
COMBOS = [
    ("baseline", dict(allow_overlap=False, team_strict=True, tau_dummy=True)),
    ("A_clean", dict(allow_overlap=False, team_strict=True)),
    ("B_overlap_same", dict(allow_overlap=True, team_strict=True)),
    ("C_overlap_noteam", dict(allow_overlap=True, team_strict=False)),
]
TAUS = [0.6, 0.7, 0.8, 0.85, 0.9]


def main():
    data = {}
    for seg in SEGS:
        od = Path("action_work/norm_g3_reid") / seg
        G = json.loads((od / "gallery.json").read_text(encoding="utf-8"))
        G = {int(k): v for k, v in G.items()}
        emb = json.loads((od / "emb_dump.json").read_text(encoding="utf-8"))
        base = json.loads((od / "ball_tracks_base.json").read_text(encoding="utf-8"))
        data[seg] = (G, emb, base)

    print(f"{'combo':18}{'tau':>5}{'replace':>9}{'twin':>6}{'two_real':>9}{'err%':>7}"
          f"{'Δ10':>8}{'PASS':>7}")
    print("-" * 70)
    for cname, cfg in COMBOS:
        team_strict = cfg.get("team_strict", True)
        allow_overlap = cfg.get("allow_overlap", False)
        for tau in ([99.0] if cname == "baseline" else TAUS):
            tot_rep = tot_twin = tot_tr = 0
            d10s, passn, nseg = [], 0, 0
            for seg in SEGS:
                G, emb, base = data[seg]
                mapping, _ = R.relink(G, tau, max_gap=2000, min_frames=3,
                                      allow_overlap=allow_overlap, team_strict=team_strict)
                relinked = []
                for rec in base:
                    players = []
                    for p in rec.get("players", []) or []:
                        t = p.get("track_id")
                        if isinstance(t, int) and t > 0 and t in mapping and mapping[t] != t:
                            np_ = dict(p)
                            np_["track_id"] = mapping[t]
                            players.append(np_)
                        else:
                            players.append(p)
                    relinked.append({**rec, "players": players})
                cls = C.classify_seg(relinked)
                tot_rep += cls["replace"]
                tot_twin += cls["twin"]
                tot_tr += cls["two_real"]
                with tempfile.TemporaryDirectory() as td:
                    tp = Path(td) / "bt.json"
                    ep = Path(td) / "emb.json"
                    tp.write_text(json.dumps(relinked))
                    ep.write_text(json.dumps(emb))
                    au = AUD.audit(str(tp), str(ep))
                if au["delta10"] is not None:
                    d10s.append(au["delta10"])
                if au["VERDICT"] == "PASS":
                    passn += 1
                nseg += 1
            tot = tot_rep + tot_twin + tot_tr
            tau_s = "base" if cname == "baseline" else f"{tau:.2f}"
            print(f"{cname:18}{tau_s:>5}{tot_rep:>9}{tot_twin:>6}{tot_tr:>9}"
                  f"{(tot_rep+tot_twin)/max(1,tot)*100:>6.1f}%"
                  f"{np.mean(d10s):>8.4f}{passn:>5}/{nseg}")


if __name__ == "__main__":
    main()
