#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义对齐层：RelateAnything 原生谓词 → 篮球战术语义。

来源：老程《半场端到端处理与词表映射规范》§二（2026-10-02）。
在原稿基础上补两处（不改老程的映射表本身）：

  M1  translate_relation() 额外回传 strength / blocker。
      理由：本词表里 watching(weak) 与 beside(weak, 且掩护判定已被 A4.61–63 证伪)
      若只回传 tactical_action，下游会当成等权信号直接用，等于把已知弱信号洗白。
      ⇒ 调用方**必须**按 strength 分层消费；core 可入事件，WEAK 只能入候选。

  M2  提供 usable_actions(strengths) 过滤助手，默认排除 WEAK。
      「默认排除」是可改参数，但改动必须显式写出，禁止静默放行。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
DEFAULT_JSON = ROOT / "vocab" / "basketball_tactics_mapping.json"

CORE = "core"
WEAK = "WEAK"
AUX = "aux"


class TacticalMapper:
    def __init__(self, mapping_json_path=None):
        p = Path(mapping_json_path) if mapping_json_path else DEFAULT_JSON
        if p.exists():
            self.config = json.loads(p.read_text(encoding="utf-8"))
            self.native_words = self.config["native_vocabulary_bundle"]
            self.mapping = self.config.get("tactical_mapping", {})
            self.source = str(p)
        else:
            # 兜底默认配置（老程原稿的最小集，无证据层）
            self.config = {}
            self.native_words = ["defending", "tackling", "hitting", "watching", "beside"]
            self.mapping = {}
            self.source = "FALLBACK(no-file)"

    def translate_relation(self, native_predicate, subject, target, score):
        """将模型原生输出翻译为战术语意。回传 strength/blocker，供下游分层消费。"""
        info = self.mapping.get(native_predicate, {
            "target_action": "unknown_spatial_relation",
            "description": "通用几何关系",
            "strength": AUX,
            "blocker": "未收录谓词",
        })
        return {
            "subject": subject,
            "target": target,
            "native_term": native_predicate,
            "tactical_action": info.get("target_action", "unknown_spatial_relation"),
            "description": info.get("description", ""),
            "strength": info.get("strength", AUX),
            "blocker": info.get("blocker", ""),
            "score": score,
        }

    def usable_actions(self, strengths=(CORE,)):
        """返回可作为战术事件消费的 target_action 集合（默认只取 core）。"""
        return sorted({v.get("target_action") for v in self.mapping.values()
                       if v.get("strength") in strengths and v.get("target_action")})

    def translate_many(self, raw_relate_results):
        """批量翻译。raw 项需含 predicate / subject_id / target_id / score。"""
        out = []
        for rel in raw_relate_results:
            w = rel.get("predicate")
            if w not in self.native_words:
                continue
            out.append(self.translate_relation(
                native_predicate=w,
                subject=rel.get("subject_id"),
                target=rel.get("target_id"),
                score=rel.get("score"),
            ))
        return out


if __name__ == "__main__":
    m = TacticalMapper()
    print("source:", m.source)
    print("core 可用动作:", m.usable_actions())
    print("全部动作:", m.usable_actions((CORE, WEAK, AUX)))
    demo = [{"predicate": "defending", "subject_id": 3, "target_id": 7, "score": 0.3643},
            {"predicate": "beside", "subject_id": 2, "target_id": 5, "score": 0.181},
            {"predicate": "watching", "subject_id": 1, "target_id": 4, "score": 0.3224}]
    for t in m.translate_many(demo):
        print(f"  {t['native_term']:18s} -> {t['tactical_action']:26s} "
              f"[{t['strength']}] score={t['score']}")
