#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tactical_glossary.py
==========================
纯文件名解析 -> 战术术语索引。

纪律约束（来自项目铁律）：
- 本脚本**只解析文件名**（集数 / 战术名原文 / 涉及球队 / 路径 / 大小），
  绝不解读战术含义、绝不猜测视频内容。
- 产出两份文件：
    action_work/tactical_glossary.json   (机读，供 tactical_annotate.py 做战术名 -> 讲解视频 反查)
    action_work/tactical_glossary.md     (人读目录，供老程检索)

战术名提取策略（保守、可复现）：
1. 优先抓被 「」 或 "" 或 ‘’ 包裹的子串（标题里的中文/英文战术代号）。
2. 兜底：对已知战术关键词表做不区分大小写匹配（仅用于辅助标注，不进入权威字段）。
3. 涉及球队/球员：仅当文件名**显式**出现时才记（文班亚马/马刺/SAS/波波维奇 等），
   不做推断。

不写入用户媒体库（<DATA_ROOT>/NBA战术笔记），只写到本项目 action_work/。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os
import re
import sys

from common.nba_paths import data_file, tactics_data_file

NOTES_DIR = str(data_file("NBA战术笔记"))
OUT_DIR = str(tactics_data_file("action_work"))
os.makedirs(OUT_DIR, exist_ok=True)

# 已知战术关键词（仅用于辅助标注 coverage，不进入权威 tactic 字段）
KNOWN_TACTICS = [
    "ZipperBackdoor", "Zipper", "Pistol5", "Pistol", "exitscreen", "ExitScreen",
    "Horns", "Staggerscreen", "wedgescreen", "Wedge", "短顺下", "提前顺下", "顺下",
    "Ghostscreen", "Ghost", "4POP", "Touchscreen", "DoubleHighScreen", "crossscreen",
    "反向挡拆", "Twirlaction", "drop", "Drop", "动态进攻", "Ram掩护", "Ram", "无球掩护",
    "切入", "BACKDOOR", "Backdoor", "ripscreen", "Rip", "Splitcut", "GatorPass",
    "Getaction", "Keep", "reject", "Reject", "Delay", "slice", "Slice", "三角进攻",
    "重新定位", "挡拆", "手递手", "边线球", "延时", "延误", "面框单打", "背身单打",
    "转换", "定点战术", "STS", "Through+Veer", "补篮", "筑墙式防守", "一五挡拆",
    "库追挡拆", "EOG", "无球", "普林斯顿", "Princeton", "拉链挡拆", "梯次掩护",
    "45度切入", "二次掩护", "上提", "分散挡拆", "交换", "Exchange",
    # 补：全角引号标题里出现或常见但原表漏的
    "牛角", "手枪", "拉链", "电梯门", "Spain", "Zoom", "Hammer", "Floppy",
    "Fist", "Hawk", "Elevator", "SLOB", "BLOB", "HORNS",
]

# 显式球队/球员提及（只在文件名出现时才记）
ENTITY_HINTS = {
    "SAS": ["马刺", "文班", "文班亚马", "Wembanyama", "波波维奇", "Popovich", "Spurs"],
    "LAL": ["湖人", "Lakers", "LAL", "东契奇", "布克", "里弗斯", "雷迪克", "克里斯蒂", "DFS"],
    "DEN": ["掘金", "约老师", "约基奇", "Jokic", "Murray", "布劳恩"],
    "MIA": ["热火", "Heat", "斯波", "Spo", "邓肯·罗宾逊", "罗宾逊"],
    "BOS": ["凯尔特人", "Celtics", "塔图姆", "Tatum", "布朗"],
    "MIL": ["雄鹿", "Bucks", "利拉德", "Lillard", "里弗斯"],
    "HOU": ["火箭", "Rockets", "乌度卡", "乌度卡"],
    "MIN": ["森林狼", "戈贝尔", "爱德华兹", "唐斯"],
    "DAL": ["独行侠", "东契奇", "欧文", "Irving"],
    "PHX": ["太阳", "Booker", "布克", "杜兰特", "Durant", "卡椒"],
    "LAC": ["快船", "哈登", "Harden", "卡椒", "伦纳德"],
    "GSW": ["勇士", "库里", "Curry", "格林", "Green", "汤普森", "追", "库追"],
    "NOP": ["鹈鹕", "英格拉姆"],
    "IND": ["步行者", "哈利伯顿", "Haliburton"],
    "OKC": ["雷霆", "亚历山大", "SGA"],
    "CHN": ["中国男篮", "李凯尔", "凯尔", "胡金秋", "崔永熙", "龙之队"],
}

QUOTE_RE = re.compile(r"[「“\"'‘]([^」“”\"'’]{1,40})[」“”\"'’]")
NUM_RE = re.compile(r"第\s*(\d+)\s*期")
WC_RE = re.compile(r"《世界杯战术笔记》\s*EP\s*(\d+)", re.I)
TERM_DIR = "NBA篮球术语"


def classify(path_rel, fname):
    if TERM_DIR in path_rel:
        return "term_video"          # 外文/术语短片
    if WC_RE.search(fname):
        return "world_cup"
    if NUM_RE.search(fname):
        return "series_episode"      # 第N期 系列
    if "赛季" in fname or "体系" in fname:
        return "team_system"
    return "other"


def parse(fpath):
    fname = os.path.basename(fpath)
    rel = os.path.relpath(fpath, NOTES_DIR)
    size_mb = round(os.path.getsize(fpath) / 1_048_576, 1)

    series = classify(rel, fname)
    ep_num = None
    m = NUM_RE.search(fname)
    if m:
        ep_num = int(m.group(1))
    m = WC_RE.search(fname)
    if m:
        ep_num = int(m.group(1))

    # 战术名：抓引号包裹
    quoted = QUOTE_RE.findall(fname)
    tactic_tokens = [q.strip() for q in quoted if q.strip()]

    # 兜底关键词（仅辅助 coverage）
    kw_hits = []
    low = fname.lower()
    for k in KNOWN_TACTICS:
        if k.lower() in low:
            kw_hits.append(k)

    # 实体提及（仅显式）
    entities = []
    for code, hints in ENTITY_HINTS.items():
        if any(h.lower() in fname.lower() for h in hints):
            entities.append(code)

    # 干净标题（去扩展名）
    title = re.sub(r"\.(mp4|mkv|mov)$", "", fname, flags=re.I)
    title = title.replace("_高清1080P在线观看平台_腾讯视频", "").replace("_720-ytshorts.savetube.me", "")
    title = re.sub(r"_\d+$", "", title)  # 尾巴 _2 之类

    return {
        "file": fpath,
        "rel": rel,
        "series": series,
        "episode": ep_num,
        "title": title,
        "tactic_quoted": tactic_tokens,
        "tactic_keywords": sorted(set(kw_hits)),
        "entities": sorted(set(entities)),
        "size_mb": size_mb,
    }


def main():
    rows = []
    for root, dirs, files in os.walk(NOTES_DIR):
        for f in files:
            if f.lower().endswith((".mp4", ".mkv", ".mov")):
                rows.append(parse(os.path.join(root, f)))
    rows.sort(key=lambda r: (r["series"], r["episode"] or 9999, r["rel"]))

    # 统计
    by_series = {}
    for r in rows:
        by_series[r["series"]] = by_series.get(r["series"], 0) + 1
    sas_rows = [r for r in rows if "SAS" in r["entities"]]

    out = {
        "source_dir": NOTES_DIR,
        "total_videos": len(rows),
        "by_series": by_series,
        "sas_related_count": len(sas_rows),
        "videos": rows,
    }
    jpath = os.path.join(OUT_DIR, "tactical_glossary.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Markdown 人读目录
    mpath = os.path.join(OUT_DIR, "tactical_glossary.md")
    lines = []
    lines.append("# NBA 战术笔记 — 视频术语索引\n")
    lines.append(f"> 自动生成自 `{NOTES_DIR}`（纯文件名解析，未解读视频内容）。\n")
    lines.append(f"> 总计 **{len(rows)}** 个视频；系列分布：{by_series}\n")
    lines.append(f"> 与马刺/SAS 显式相关：**{len(sas_rows)}** 个（见末尾）。\n")
    lines.append("\n## 按系列\n")
    cur = None
    for r in rows:
        if r["series"] != cur:
            cur = r["series"]
            lines.append(f"\n### {cur} （{by_series[cur]}）\n")
        tac = " / ".join(r["tactic_quoted"]) if r["tactic_quoted"] else (", ".join(r["tactic_keywords"][:3]) or "—")
        ent = " [" + ",".join(r["entities"]) + "]" if r["entities"] else ""
        ep = f"EP{r['episode']:02d}" if r["episode"] else "—"
        lines.append(f"- `{ep}` **{tac}**{ent} — {r['title']}  _({r['size_mb']}MB)_")
    lines.append("\n## 马刺/SAS 相关\n")
    for r in sas_rows:
        lines.append(f"- {r['rel']}  → 战术：{'/'.join(r['tactic_quoted']) or '—'}")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[OK] {len(rows)} videos indexed")
    print(f"  by_series={by_series}")
    print(f"  SAS-related={len(sas_rows)}")
    print(f"  -> {jpath}")
    print(f"  -> {mpath}")


if __name__ == "__main__":
    main()
