#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并 BASE_NOTES 与 5 个批次小注，复用 build_nicknames_bz.py 的纯函数，
生成更丰富版本的 analysis_nicknames_bz.md，并导出合并后的 notes_enriched.json。
"""
import os, re, html, unicodedata, json

BASE = "/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13"
OUT_MD  = os.path.join(BASE, "analysis_nicknames_bz.md")
OUT_JSON = os.path.join(BASE, "notes_enriched.json")

# ---------- 1. 读取 .env 取 DB_PASSWORD ----------
cfg = {}
with open(os.path.join(BASE, ".env")) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
DSN = f"host=localhost port=5433 dbname=nba user=postgres password={cfg['DB_PASSWORD']}"

# ---------- 2a. 复用 build_nicknames_bz.py 中的纯函数 ----------
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

# ---------- 2b. 提取 BASE_NOTES（~94 条手写小注）----------
src = open(os.path.join(BASE, 'build_nicknames_bz.py'), encoding='utf-8').read()
i = src.index('NOTES = {')
j = src.index('\nblocks = []', i)
exec('BASE_NOTES = ' + src[i+len('NOTES = '):j])

# ---------- 3. 合并 NOTES ----------
NOTES = dict(BASE_NOTES)
batch_files = ['notes_batch_BD.json','notes_batch_EH.json','notes_batch_IL.json',
               'notes_batch_MP.json','notes_batch_QZ.json']
for f in batch_files:
    NOTES.update(json.load(open(os.path.join(BASE, f), encoding='utf-8')))

# ---------- 4. 跑与原脚本相同的查询 ----------
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

# ---------- 5. 生成文档（与原脚本相同格式）----------
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
# 每 5000 字插入分割线
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

with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write(doc)

# ---------- 6. 导出合并后的 NOTES ----------
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(NOTES, f, ensure_ascii=False, indent=2)

# ---------- 7. 汇报 ----------
print(f"OK -> {OUT_MD}")
print(f"OK -> {OUT_JSON}")
print(f"球员数(B-Z)={total}  含小注={matched_notes}  NOTES总数={len(NOTES)}")
print(f"BASE_NOTES={len(BASE_NOTES)}  批次合计={sum(len(json.load(open(os.path.join(BASE,f),encoding='utf-8'))) for f in batch_files)}")
print(f"文档字节≈{len(doc.encode('utf-8'))}")
