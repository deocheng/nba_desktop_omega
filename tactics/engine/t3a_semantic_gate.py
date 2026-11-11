#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t3a_semantic_gate (T3a) —— 语义层增强量化：死球否决 + 遮挡/漏检帧标注。

语义输入（全部独立于球头打分）:
  - T1 比赛钟读数 + T2 状态表: sas_det_frame_states.json（live/dead 逐帧）
  - 老程人工备注: 遮挡帧 f25/91/103（球被防守者挡住）, 候选云漏检帧 f1/7/127/355
  - 🔴 A4.25 修正: 原判「人脸特写 FP 簇 f225-253」经原始分辨率 crop 全量复核
    = 投篮弧线跟球段（真阳性, 36/36 候选均为球本体）—— FP 簇定性撤回, 无近景段。

量化:
  A) 基线门禁: 全 400 帧 th 扫描（复现 A4.25）
  B) 死球否决版: 移除 dead 帧(f366-400)全部候选 → th 扫描;
     覆盖率双分母（400 全帧 / 365 活球帧）—— 分母变化必须显式报告, 防自指美化。

产出: action_work/validate/sas_det_t3a_semantic.json（零 DB 写）
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
import track_ball as tb  # noqa: E402

SCORES = AW / "validate" / "ball_cand_scores_sas_human.json"
STATES = AW / "validate" / "sas_det_frame_states.json"
OUT = AW / "validate" / "sas_det_t3a_semantic.json"
MIN_TRK = 3
THS = (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 0.9)
# 老程人工备注（human_labels.json reviewer_notes, 2026-09-26）
OCCLUDED = {25, 91, 103}          # 球被防守者挡住
RECALL_MISS = {1, 7, 127, 355}    # 有球但候选云没抓到
RETRACTED_FACE_CLUSTER = (225, 253)   # A4.25 原判 FP 簇 → 已撤回（实为球）


def main():
    d = json.loads(SCORES.read_text())
    fr = d["sas_det"] if "sas_det" in d else d
    states = json.loads(STATES.read_text())
    live_of = {r["fid"]: r["live_state"] for r in states["rows"]}
    dead = {fk for fk, s in live_of.items() if s == "dead"}
    n_all = len(live_of)
    n_live = n_all - len(dead)
    print(f"帧语义: 全 {n_all} 帧, dead {len(dead)} 帧(f{min(dead)}-f{max(dead)}), "
          f"live {n_live}; 遮挡 {sorted(OCCLUDED)}, 漏检 {sorted(RECALL_MISS)}")

    # 死球否决: dead 帧候选清空
    fr_veto = {}
    for k, cands in fr.items():
        fk = int(k[1:6])
        fr_veto[k] = [] if fk in dead else cands

    def sweep(scores, denom):
        rows = []
        for th in THS:
            tracks = tb.track_clip(scores, th, birth=th, gap=8)
            m = tb.track_metrics(tracks, denom, MIN_TRK)
            rows.append({"th": th,
                         "cov_all_pct": round(m["frame_coverage"] * 100, 1),
                         "trackable": m["trackable_frac"],
                         "median_step_px": m["median_step_px"],
                         "n_steps": m["n_steps"],
                         "n_tracks": m["n_tracks"]})
        return rows

    base = sweep(fr, n_all)
    veto = sweep(fr_veto, n_all)
    for r in veto:
        r["cov_live_pct"] = round(r["cov_all_pct"] * n_all / n_live, 1)

    print("\n=== T3a 门禁对比（HUMAN 头）===")
    print(f"{'th':>5} | {'基线 cov%':>9} {'track':>6} | {'否决 cov%(全)':>12} {'cov%(活球)':>10} {'track':>6}")
    for b, v in zip(base, veto):
        print(f"{b['th']:>5.2f} | {b['cov_all_pct']:>9.1f} {str(b['trackable']):>6} | "
              f"{v['cov_all_pct']:>12.1f} {v['cov_live_pct']:>10.1f} {str(v['trackable']):>6}")
    # 工作点摘要
    def best(rs, key):
        ok = [r for r in rs if r["trackable"] is not None and r["trackable"] >= 0.80
              and (r["median_step_px"] is None or r["median_step_px"] < 80)]
        return max(ok, key=lambda r: r[key]) if ok else None
    bb, bv = best(base, "cov_all_pct"), best(veto, "cov_all_pct")
    print(f"\n基线最佳: th={bb['th']} cov={bb['cov_all_pct']}% track={bb['trackable']}")
    print(f"否决后最佳: th={bv['th']} cov_all={bv['cov_all_pct']}% "
          f"cov_live={bv['cov_live_pct']}% track={bv['trackable']}")

    # 语义标注逐帧
    annot = {}
    for fk in range(1, n_all + 1):
        a = {"live_state": live_of[fk]}
        if fk in dead:
            a["semantic"] = "dead_ball_veto"
            a["note"] = "罚球/死球段: 球位语义钉死(罚球线/裁判), 球信号无战术含义"
        elif fk in OCCLUDED:
            a["semantic"] = "occluded"
            a["note"] = "老程标注: 球被防守者挡住(无拾取, 头行为=正确弃权)"
        elif fk in RECALL_MISS:
            a["semantic"] = "candidate_miss"
            a["note"] = "老程标注: 有球但候选云未抓到(头无从拾取, 候选池召回问题)"
        else:
            a["semantic"] = "live_tactical"
        annot[fk] = a

    out = {"meta": {"scores": SCORES.name, "n_all": n_all, "n_dead": len(dead),
                    "occluded": sorted(OCCLUDED), "recall_miss": sorted(RECALL_MISS),
                    "retracted_face_cluster": list(RETRACTED_FACE_CLUSTER),
                    "retraction_note": "A4.25 判 f225-253 为人脸 FP 簇; T3a 原始分辨率全量复核 "
                                       "36/36 候选=球本体(投篮弧线), 定性撤回"},
           "gate_baseline_all400": base,
           "gate_deadball_veto": veto,
           "frame_annotations": annot}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"\n[out] {OUT}")


if __name__ == "__main__":
    main()
