#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用「合并后的小注字典」重新生成 analysis_nicknames_bz.md 与 notes_enriched.json。
复用 build_nicknames_bz.py 的 DB 取值与 bio_line/honors_short/nick_text 逻辑，
仅把 NOTES 换成 enriched_notes.py 的 569 条 + 7 个补全候选 + 17 条未覆盖原 94/103 条。
"""
import os, re, html, unicodedata, json, importlib.util

BASE = "/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13"
OUT  = os.path.join(BASE, "analysis_nicknames_bz.md")
JSON_OUT = os.path.join(BASE, "notes_enriched.json")

cfg = {}
with open(os.path.join(BASE, ".env")) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
DSN = f"host=localhost port=5433 dbname=nba user={cfg.get('DB_USER','postgres')} password={cfg['DB_PASSWORD']}"

import psycopg2
conn = psycopg2.connect(DSN)
cur = conn.cursor()
cur.execute("""SELECT d.player_name, d.nickname,
                     b.position, b.height_display, b.draft_info, b.career_length_years,
                     b.nationality, b.career_honors_text
              FROM dim_players d
              LEFT JOIN player_bio b ON b.player_id = d.player_id
              WHERE d.nickname IS NOT NULL AND d.nickname<>''
              ORDER BY d.player_name""")
rows = cur.fetchall()
conn.close()

POS_MAP = {'Point Guard':'控卫','Shooting Guard':'分卫','Small Forward':'小前',
           'Power Forward':'大前','Center':'中锋','Forward':'前锋','Guard':'后卫'}

def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()

def bio_line(pos, hgt, draft, yrs, nat):
    parts = []
    if pos:
        first = re.split(r'[,、]|\band\b', pos)[0].strip()
        parts.append(POS_MAP.get(first, first))
    if hgt:
        parts.append(hgt)
    if draft:
        y = re.search(r'(\d{4})\s*NBA Draft', draft)
        p = re.search(r'(\d+)(?:st|nd|rd|th)\s+overall', draft)
        if y and p:
            parts.append(f"{y.group(1)}年NBA第{p.group(1)}顺位")
        elif y:
            parts.append(f"{y.group(1)}年NBA选秀")
    if yrs:
        parts.append(f"生涯{yrs}季")
    if nat and nat not in ('USA', 'United States', 'United States of America'):
        parts.append(nat)
    return " · ".join(parts)

KEYWORDS = ['MVP', 'Champ', '75th', 'All Star', 'Hall', 'ROY', 'Scoring', 'AST', 'Defensive', 'Rebound']
def honors_short(honors):
    if not honors:
        return []
    key = [h for h in honors if any(k in h for k in KEYWORDS)]
    return key[:4] if key else list(honors)[:3]

def nick_text(nk):
    return "、".join(p.strip() for p in (nk or "").replace(";", ",").split(",") if p.strip())

# ---------- 1) 载入 enriched_notes.py 的 569 条 ----------
spec = importlib.util.spec_from_file_location('en', os.path.join(BASE, 'enriched_notes.py'))
en_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(en_mod)
NOTES = dict(en_mod.NOTES)
print("载入 enriched_notes:", len(NOTES))

# ---------- 2) 补全 7 个缺失候选（丰富版小注）----------
EXTRA = {
 "billy donovan": "“Billy the Kid（小比利）”是对他名字的俏皮叫法。作为球员他只是 1987 年落选末段被选中的短命控卫，真正成名是在教练席——率领佛罗里达大学两夺 NCAA 冠军（2006、2007），后执掌多支 NBA 球队，并入选篮球名人堂。",
 "eddie johnson": "“Fast Eddie（快枪埃迪）”点出他第一步之快与 burst 式得分能力。作为老鹰/超音速的锋卫摇摆人，他是 70 年代末至 80 年代的两次全明星与两次最佳防守阵容成员。",
 "eddie jones": "“Steady Eddie（稳健埃迪）”概括了他攻防一体的可靠边翼属性——三届全明星、多次最佳防守阵容，并在 1999-2000 赛季荣膺联盟抢断王。",
 "eddie jordan": "“Fast Eddie（快枪埃迪）”形容他作为后卫的速度；资料中还列有 Ed、Steady Eddie、Monty 以及较冷门的 The Thief of Baghdad 等变体。作为 80 年代湖人后卫，他随队夺得 1982 年总冠军。",
 "jordan mcrae": "“Orange Mamba（橙色曼巴）”是借科比“Black Mamba（黑曼巴）”玩的谐音/意象，呼应其田纳西“Vols（橙色）”底色与得分型后卫的风格；他曾位列 2016 年克利夫兰冠军阵容、获一枚总冠军戒指。",
 "kristaps porzingis": "“Unicorn（独角兽）”由凯文·杜兰特在 2015 年的一档播客中大名鼎鼎地喊出——一个 7 尺 3 寸却能像后卫一样投三分、护框的七尺长人，彼时如“独角兽”般稀有；“Zinger”则取自其姓氏。他是 2024 年 NBA 总冠军成员。",
 "shawn marion": "“The Matrix（矩阵/黑客帝国）”成名于他生涯早期——那种古怪、超 athletic、一抖一抖的打法看起来几乎像被“数字渲染”出来，令人联想到电影；其姓氏 Marion 也与 Matrix 谐音。他是四届全明星，并在 2011 年随达拉斯夺冠。",
}
added = 0
for k, v in EXTRA.items():
    if k not in NOTES:
        NOTES[k] = v
        added += 1
print("补全缺失候选:", added)

# ---------- 3) 合并「未被覆盖」的原 103 条（保留原文）----------
src = open(os.path.join(BASE, "build_nicknames_bz.py"), encoding="utf-8").read()
start = src.index("NOTES = {")
depth = 0
for j in range(start, len(src)):
    if src[j] == '{': depth += 1
    elif src[j] == '}':
        depth -= 1
        if depth == 0:
            end = j + 1; break
ns = {}; exec(src[start:end], ns)
ORIG = ns["NOTES"]
merged_orig = 0
for k, v in ORIG.items():
    nk = norm(k)
    if nk not in NOTES:
        NOTES[nk] = v
        merged_orig += 1
print("合并未覆盖原 103 条:", merged_orig)

print("合并后小注总数:", len(NOTES))

# ---------- 4) 生成文档 ----------
blocks = []
matched_notes = 0
for name, nk, pos, hgt, draft, yrs, nat, honors in rows:
    if not name or name[0].upper() not in "BCDEFGHIJKLMNOPQRSTUVWXYZ":
        continue  # 仅 B~Z
    bio = bio_line(pos, hgt, draft, yrs, nat)
    hon = honors_short(honors)
    b = [f"## {name}", f"绰号：{nick_text(nk)}"]
    if bio:
        b.append(bio)
    if hon:
        b.append(" · ".join(hon))
    note = NOTES.get(norm(name))
    if note:
        b.append(note)
        matched_notes += 1
    blocks.append("\n".join(b))

total = len(blocks)
out_parts = []
cum = 0
last_div = 0
for blk in blocks:
    if cum - last_div >= 5000:
        out_parts.append("\n---\n")
        last_div = cum
    out_parts.append("\n\n" + blk)
    cum += len(blk) + 2

doc = f"""# NBA 球员绰号大全（B–Z，含绰号由来小注）

> 本表收录姓名以 B–Z 开头、且在库中有绰号记录的球员，共 {total:,} 人。
> 每人段落：姓名 / 绰号 / 简介（位置·身高·选秀·生涯·国籍）/ 核心荣誉。
> 段落末的「绰号由来小注」仅对绰号来源可可靠考证的知名球员填写（共 {matched_notes} 人）；普通球员按示例格式不附小注。
> A 开头球员的小注由用户另行整理。数据来自 dim_players.nickname + player_bio。

{"".join(out_parts)}
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(doc)

# ---------- 5) 导出 JSON ----------
with open(JSON_OUT, "w", encoding="utf-8") as f:
    json.dump(NOTES, f, ensure_ascii=False, indent=2)

print(f"OK -> {OUT}")
print(f"球员数={total} 含小注={matched_notes} 文档行数≈{len(doc.splitlines())} 字节≈{len(doc.encode('utf-8'))}")
