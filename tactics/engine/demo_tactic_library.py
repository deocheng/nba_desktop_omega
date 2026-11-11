#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_tactic_library.py  —  演示「分析视频时调用战术库」
=====================================================
两件事：
1) 打印战术库概览（储备了多少战术、覆盖哪些球队）。
2) 给定一段"分析上下文"（如 sas_det 的战术目的关键词 / 或直接战术名），
   从库里检索对应的人声讲解，证明分析时可直接取用。

用法：
  python engine/demo_tactic_library.py                 # 概览 + 内置样例
  python engine/demo_tactic_library.py zipper backdoor # 查某战术
  python engine/demo_tactic_library.py --search 无球掩护
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os
import sys

from common.nba_paths import tactics_data_file

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tactic_library import TacticLibrary

WORK = str(tactics_data_file("action_work"))


def overview(lib):
    print(f"■ 战术库：{lib.path}")
    print(f"  已储备战术：{len(lib.topics())} 个")
    ents = {}
    for t in lib.topics():
        for e in lib.lookup(t).get("entities", []):
            ents[e] = ents.get(e, 0) + 1
    print(f"  涉及球队/球员：{dict(sorted(ents.items(), key=lambda x:-x[1]))}")
    print(f"  战术名样例：{lib.topics()[:15]}")


def demo_analysis(lib):
    """模拟分析 sas_det 时，从库中取用。"""
    print("\n■ 模拟：分析 sas_det 时按战术名取讲解（人声转写原文）")
    for name in ["zipper backdoor", "cross screen", "horns", "无球掩护", "ghost screen"]:
        v = lib.lookup(name)
        if not v:
            print(f"\n  [{name}] —— 未储备（可补录对应期视频）")
            continue
        print(f"\n  [{name}]  来源={v.get('source_clips')}  时间戳={v.get('timestamps')}")
        print(f"    讲解原文：{v.get('teaching','')[:220]}")


def main():
    lib = TacticLibrary()
    args = sys.argv[1:]
    if args and args[0] == "--search":
        for k, v in lib.search(" ".join(args[1:])):
            print(f"- {k}  ← {v.get('source_clips')}")
        return
    if args:
        print(lib.explain(" ".join(args)))
        return
    overview(lib)
    demo_analysis(lib)


if __name__ == "__main__":
    main()
