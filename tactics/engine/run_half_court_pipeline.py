#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""半场端到端流水线：空间清洗 → 战术板投射 → 裁判标注 → 原生谓词→战术语义映射。

来源：老程《半场端到端处理与词表映射规范》§三。

三处必须保留的门禁（否则会产出"看起来完整"的假结果）：
  G1 标定欠定即失败。src_points 必须由标定文件/直线交点现算；拿不到就 raise，
     绝不回退到任何示意值（C1 / A5.14「拿色块凑四边形」已封口）。
  G2 战术语义按 strength 分层。core 进 tactical_events，WEAK 只进 candidates
     （beside/watch 已被实测判弱；beside→掩护 与 A4.61–63 冲突）。
  G3 裁判只打 tag 不删除，且位置启发式默认关（会误删底角射手, F1）。

用法:
  python3 run_half_court_pipeline.py --calib <半场标定.json> \
      --det <detections.json> --rel <relate_raw.json> [--frame f.jpg] [--viz out.png]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
sys.path.insert(0, str(ROOT / "engine"))

from half_court_spatial_engine import HalfCourtSpatialEngine, estimate_virtual_expansion  # noqa: E402
from referee_filter import filter_referees  # noqa: E402
from tactical_mapper import AUX, CORE, WEAK, TacticalMapper  # noqa: E402


def run_half_court_pipeline(calib_path, frame_detections, raw_relate_results,
                            frame=None, expand_auto=True, viz_path=None,
                            use_ref_position=False):
    # ---- 1. 空间引擎（标定必须来自磁盘）----
    engine = HalfCourtSpatialEngine(calib_path=calib_path)
    if not engine.ready():
        raise RuntimeError("半场梯形未标定完备 —— 禁止继续（G1）")

    # 虚拟边线扩展（C4：只影响准入多边形，不影响 H）
    if expand_auto:
        exp_pts, exp_px = estimate_virtual_expansion(
            engine.src_points, engine.img_width, engine.img_height)
        engine.poly_admit = exp_pts
        engine.expand_px = exp_px
    else:
        exp_px = 0.0

    # ---- 2. 空间清洗 + 投射 ----
    cleaned, stats = engine.filter_and_project(frame_detections)

    # ---- 3. 裁判标注（只打 tag，不删）----
    cleaned, ref_report = filter_referees(cleaned, img=frame,
                                          use_position=use_ref_position)

    # ---- 4. 语义映射（按 strength 分层）----
    mapper = TacticalMapper()
    translated = mapper.translate_many(raw_relate_results)
    events = [t for t in translated if t["strength"] == CORE]
    candidates = [t for t in translated if t["strength"] in (WEAK, AUX)]

    # ---- 5. 可选可视化 ----
    if viz_path and frame is not None:
        engine.visualize(frame, cleaned, save_path=viz_path)

    return {
        "active_players_on_court": cleaned,
        "tactical_relations": events,          # G2: 只有 core 算事件
        "candidate_relations": candidates,     # G2: 弱信号只做候选
        "referee_report": ref_report,
        "spatial": {
            "stats": stats,
            "expand_px": exp_px,
            "selfcheck": engine.selfcheck(),
        },
        "gate": {
            "G1_calib_from_disk": str(calib_path),
            "G2_core_only_events": mapper.usable_actions((CORE,)),
            "G3_referee_tag_only": True,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", required=True)
    ap.add_argument("--det", required=True)
    ap.add_argument("--rel", required=True)
    ap.add_argument("--frame", default=None)
    ap.add_argument("--viz", default=None)
    ap.add_argument("--use-ref-position", action="store_true",
                    help="打开裁判位置启发式（默认关：会误删底角三分射手）")
    ap.add_argument("--no-auto-expand", action="store_true")
    a = ap.parse_args()

    frame = None
    if a.frame:
        import cv2
        frame = __import__("cv2").imread(a.frame)
    dets = json.loads(Path(a.det).read_text(encoding="utf-8"))
    rels = json.loads(Path(a.rel).read_text(encoding="utf-8"))

    out = run_half_court_pipeline(a.calib, dets, rels, frame=frame,
                                  expand_auto=not a.no_auto_expand,
                                  viz_path=a.viz,
                                  use_ref_position=a.use_ref_position)
    print(json.dumps({k: v for k, v in out.items() if k != "active_players_on_court"},
                     ensure_ascii=False, indent=2, default=str))
    print(f"\n场内球员 {len(out['active_players_on_court'])} 人 / "
          f"事件 {len(out['tactical_relations'])} 条 / "
          f"候选 {len(out['candidate_relations'])} 条")


if __name__ == "__main__":
    main()
