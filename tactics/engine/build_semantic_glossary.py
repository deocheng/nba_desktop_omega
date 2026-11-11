#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_semantic_glossary.py  —  合并 ASR 转写 -> 语义战术术语库（侧车参考）
=============================================================================
输入：
  action_work/tactical_glossary.json        (文件名级索引)
  action_work/asr_transcripts/*_asr_*.json  (asr_batch.py 产出)
输出：
  action_work/tactical_glossary_semantic.json
  action_work/tactical_glossary_semantic.md
侧车结构：
  tactic_index[战术名] -> [ {video, segments:[{start,end,text}], match} ]

纪律：只合并/索引，不解读战术含义；ASR 文本原样保留（含可能的音近误识）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os
import re

from common.nba_paths import tactics_data_file

WORK = str(tactics_data_file("action_work"))
GLOSSARY = os.path.join(WORK, "tactical_glossary.json")
TRANS_DIR = os.path.join(WORK, "asr_transcripts")
OUT_JSON = os.path.join(WORK, "tactical_glossary_semantic.json")
OUT_MD = os.path.join(WORK, "tactical_glossary_semantic.md")
OUT_LIB = os.path.join(WORK, "tactic_library.json")  # 战术库储备（分析时调用）
OUT_OVERVIEW = os.path.join(WORK, "tactic_library_overview.md")  # 人读总表

# 战术名归一化别名（音近/中英混写 -> 规范键），仅用于侧车匹配，不改原文
ALIASES = {
    "zipperbackdoor": "zipper backdoor", "zipper backdoor": "zipper backdoor",
    "拉链挡拆": "拉链挡拆", "拉链": "拉链挡拆",
    "pistol5": "pistol 5", "手枪5": "pistol 5", "手枪": "pistol 5",
    "crossscreen": "cross screen", "cross screen": "cross screen",
    "ghostscreen": "ghost screen", "ghost": "ghost screen",
    "staggerscreen": "stagger screen",
    "horns": "horns", "牛角": "horns",
    "4pop": "4 pop",
    "wedgescreen": "wedge screen", "wedge": "wedge screen",
    "ram掩护": "ram screen", "ram": "ram screen",
    "twirlaction": "twirl action",
    "drop": "drop",
    "无球掩护": "off-ball screen", "ripscreen": "rip screen", "rip": "rip screen",
    "backdoor": "backdoor", "back door": "backdoor",
    "splitcut": "split cut",
    "gatorpass": "gator pass", "gator": "gator pass",
    "getaction": "get action",
    "doublehighscreen": "double high screen",
    "touchscreen": "touch screen",
    "动态进攻": "motion offense",
    "三角进攻": "triangle offense",
    "普林斯顿": "princeton offense", "princeton": "princeton offense",
    "挡拆": "pick and roll",
    "短顺下": "short roll", "提前顺下": "short roll", "顺下": "roll",
    "手递手": "handoff", "handoff": "handoff",
    "边线球": "sideline play", "eog": "eog",
    "sts": "sts", "through+veer": "through veer",
    "切入": "cut", "补篮": "putback", "转换": "transition",
    "delay": "delay", "slice": "slice", "reject": "reject",
    "keep": "keep", "定点战术": "spot action",
    "背身单打": "post up", "面框单打": "face up",
    "一五挡拆": "1-5 pick and roll", "库追挡拆": "curry-dray pick and roll",
    "筑墙式防守": "wall defense", "延误": "delay defense", "延误防守": "delay defense",
    "二次掩护": "second screen", "梯次掩护": "tiered screen",
    "45度切入": "45 cut", "上提": "lift", "分散挡拆": "spread pnr",
    "无球": "off-ball",
}


def norm(t):
    return re.sub(r"\s+", " ", t.strip().lower())


NUM_RE_OVERVIEW = re.compile(r"第\s*(\d+)\s*期")


# 标题引号里被误抽的非战术短语（噪声键，剔除）
STOP_KEYS = {"c", "大问题", "全靠自己", "独角兽", "约基奇化", "重新定位", "全靠自己了"}


def main():
    g = json.load(open(GLOSSARY, encoding="utf-8"))
    videos = g["videos"]
    out_videos = []
    transcribed = 0
    tactic_index = {}

    for v in videos:
        rec = dict(v)
        base = os.path.splitext(os.path.basename(v["file"]))[0]
        # 找该视频的 ASR 产物（任意 model）
        asr = None
        for mdl in ("small", "medium"):
            p = os.path.join(TRANS_DIR, f"{base}_asr_{mdl}.json")
            if os.path.exists(p):
                try:
                    asr = json.load(open(p, encoding="utf-8"))
                except Exception:
                    asr = None
                break
        if asr and asr.get("segments"):
            transcribed += 1
            segs = [{"start": s["start"], "end": s["end"], "text": s["text"]}
                    for s in asr["segments"]]
            rec["transcript"] = " ".join(s["text"] for s in asr["segments"])
            rec["segments"] = segs
            rec["transcript_meta"] = asr.get("meta")
        else:
            rec["transcript"] = None
            rec["segments"] = []
        out_videos.append(rec)

        # 建 tactic_index：用文件名 tactic_quoted + 规范化（同一视频同一键只入一次）
        terms = set()
        for q in v.get("tactic_quoted", []):
            terms.add(norm(q))
        for kw in v.get("tactic_keywords", []):
            terms.add(norm(kw))
        keys_used = set()
        for t in terms:
            key = ALIASES.get(t, t)
            if key in keys_used or key in STOP_KEYS:
                continue
            keys_used.add(key)
            if key not in tactic_index:
                tactic_index[key] = []
            tactic_index[key].append({
                "video": v["rel"], "episode": v.get("episode"),
                "segments": rec["segments"], "match": t,
            })

    out = {
        "source_dir": g["source_dir"],
        "total_videos": len(videos),
        "transcribed": transcribed,
        "tactic_index_keys": sorted(tactic_index.keys()),
        "videos": out_videos,
        "tactic_index": tactic_index,
    }
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 战术库储备：每个战术名 -> 结构化可查询条目（语义全部来自人声转写）
    library = {}
    for key, entries in tactic_index.items():
        aliases = sorted({e["match"] for e in entries})
        clips = []
        ts = []
        entities = set()
        chunks = []
        for e in entries:
            clips.append(e["video"])
            if e["segments"]:
                ts.append([e["segments"][0]["start"], e["segments"][-1]["end"]])
            # 该战术在源视频里的讲解文本（取含战术名或前几段作为 teaching）
            txt = " ".join(s["text"] for s in e["segments"])
            chunks.append(txt)
        # 反查该战术视频涉及的实体（从 videos 记录）
        for v in videos:
            if v["rel"] in clips:
                entities.update(v.get("entities", []))
        library[key] = {
            "aliases": aliases,
            "source_clips": clips,
            "timestamps": ts,
            "entities": sorted(entities),
            "teaching": " || ".join(c for c in chunks if c),  # 人声讲解原文拼接
        }
    json.dump({"tactics": library, "total_tactics": len(library)},
              open(OUT_LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 人读总表
    O = [f"# NBA 战术库总表（{len(library)} 条）\n",
         f"> 来源：《NBA战术笔记》101 个人声讲解视频的 ASR 转写（{transcribed}/101 成功）。",
         "> 讲解原文为语音转写，含少量音近误识（如 勇士→泳士、马刺→马斯）。\n"]
    for k in sorted(library.keys()):
        v = library[k]
        src = v["source_clips"][0] if v.get("source_clips") else "—"
        ep = "—"
        m = NUM_RE_OVERVIEW.search(src)
        if m:
            ep = "第" + m.group(1) + "期"
        ent = "".join(f"[{e}]" for e in v.get("entities", []))
        teach = (v.get("teaching") or "")[:60]
        O.append(f"- **{k}** {ent} — {ep} {teach}…")
    open(OUT_OVERVIEW, "w", encoding="utf-8").write("\n".join(O))
    print(f"  -> {OUT_OVERVIEW}")

    # Markdown
    L = []
    L.append("# NBA 战术笔记 — 语义术语库（ASR 侧车参考）\n")
    L.append(f"> 由 {transcribed}/{len(videos)} 个视频的 ASR 转写合并。原文保留（含音近误识）。\n")
    L.append("\n## 战术名 -> 讲解视频索引\n")
    for k in sorted(tactic_index.keys()):
        L.append(f"\n### {k}\n")
        for e in tactic_index[k]:
            segs = e["segments"]
            if segs:
                span = f"{segs[0]['start']:.0f}-{segs[-1]['end']:.0f}s"
                snippet = segs[0]["text"][:40]
                L.append(f"- `{e['video']}` [{span}] {snippet}…")
            else:
                L.append(f"- `{e['video']}` (未转写)")
    L.append("\n## 逐视频转写\n")
    for v in out_videos:
        ep = f"EP{v['episode']:02d}" if v.get("episode") else "—"
        L.append(f"\n### `{ep}` {v['title']}\n")
        if v["segments"]:
            for s in v["segments"]:
                L.append(f"- `[{s['start']:.1f}-{s['end']:.1f}]` {s['text']}")
        else:
            L.append("_(未转写)_")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L))

    print(f"[OK] transcribed={transcribed}/{len(videos)}")
    print(f"  tactic_index keys={len(tactic_index)}")
    print(f"  -> {OUT_JSON}")
    print(f"  -> {OUT_MD}")


if __name__ == "__main__":
    main()
