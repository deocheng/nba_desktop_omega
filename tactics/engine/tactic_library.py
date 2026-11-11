#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tactic_library.py  —  战术库储备的加载/查询接口（分析时调用）
================================================================
战术库来源：`action_work/tactic_library.json`（由 build_semantic_glossary.py 生成，
语义全部来自《NBA战术笔记》人声讲解的 ASR 转写）。

分析一段比赛视频时，用本模块：
    from tactic_library import TacticLibrary
    lib = TacticLibrary()
    lib.topics()                      # 已储备的所有战术名
    lib.lookup("zipper backdoor")     # 取某战术条目（含人声讲解原文 + 来源片段）
    lib.search("无球掩护")             # 关键词检索讲解文本 -> 相关战术
    lib.explain("horns")              # 打印讲解原文（供标注/解说用）

纪律：本模块只检索/呈现**人声转写原文**，不生成也不改写战术含义；
      识别与裁定权仍归老程（工具给出候选，老程确认）。
"""
import json
import os
import re

LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "action_work", "tactic_library.json")


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


class TacticLibrary:
    def __init__(self, path=LIB_PATH):
        self.path = path
        self.data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"tactics": {}}
        self.tactics = self.data.get("tactics", {})
        # 别名 -> 规范键 反向表
        self._alias2key = {}
        for k, v in self.tactics.items():
            self._alias2key[_norm(k)] = k
            for a in v.get("aliases", []):
                self._alias2key[_norm(a)] = k

    def topics(self):
        return sorted(self.tactics.keys())

    def lookup(self, name):
        k = self._alias2key.get(_norm(name))
        return self.tactics.get(k) if k else None

    def search(self, query, limit=10):
        q = _norm(query)
        hits = []
        for k, v in self.tactics.items():
            teach = _norm(v.get("teaching", ""))
            score = 0
            if q in _norm(k):
                score += 3
            if q in teach:
                score += 1
            if score:
                hits.append((score, k, v))
        hits.sort(key=lambda x: -x[0])
        return [(k, v) for _, k, v in hits[:limit]]

    def explain(self, name):
        v = self.lookup(name)
        if not v:
            return f"[未储备] {name}"
        out = [f"■ 战术：{name}", f"  别名：{', '.join(v.get('aliases', []))}",
               f"  来源：{', '.join(v.get('source_clips', []))}",
               f"  涉及球队：{', '.join(v.get('entities', [])) or '—'}",
               f"  人声讲解原文：{v.get('teaching', '')[:400]}"]
        return "\n".join(out)


if __name__ == "__main__":
    import sys
    lib = TacticLibrary()
    print(f"战术库：{lib.path}")
    print(f"已储备战术数：{len(lib.topics())}")
    if len(sys.argv) > 1:
        print()
        print(lib.explain(sys.argv[1]))
    else:
        for t in lib.topics():
            print(" -", t)
