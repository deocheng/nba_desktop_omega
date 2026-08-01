#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提取 B~Z 有绰号球员，按荣誉计算"特点鲜明度"分数，输出候选名单 JSON。"""
import os, re, json, unicodedata
import psycopg2

BASE = "/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13"
cfg = {}
with open(os.path.join(BASE, ".env")) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
DSN = f"host=localhost port=5433 dbname=nba user={cfg.get('DB_USER','postgres')} password={cfg['DB_PASSWORD']}"
conn = psycopg2.connect(DSN)
cur = conn.cursor()
cur.execute("""SELECT d.player_id, d.player_name, d.nickname,
                     b.career_honors_text
              FROM dim_players d
              LEFT JOIN player_bio b ON b.player_id = d.player_id
              WHERE d.nickname IS NOT NULL AND d.nickname<>''
              ORDER BY d.player_name""")
rows = cur.fetchall()
conn.close()

def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()

def nick_list(nk):
    return [p.strip() for p in (nk or "").replace(";", ",").split(",") if p.strip()]

def score(honors):
    if not honors:
        return 0
    txt = " | ".join(honors)
    s = 0
    s += 12 if 'MVP' in txt else 0
    s += 8 if '75th' in txt else 0
    s += 6 if 'Hall' in txt else 0
    s += 2 * txt.count('NBA Champ')
    s += 2 * txt.count('ABA Champ')
    s += 1 * txt.count('All Star')
    s += 1 if 'Scoring Champ' in txt else 0
    s += 1 if 'ROY' in txt else 0
    s += 1 if 'Defensive' in txt else 0
    return s

players = []
for pid, name, nk, honors in rows:
    if not name or name[0].upper() not in "BCDEFGHIJKLMNOPQRSTUVWXYZ":
        continue
    nk_list = nick_list(nk)
    sc = score(honors)
    players.append(dict(pid=pid, name=name, norm=norm(name), nicknames=nk_list,
                        honors=honors or [], score=sc))

# 排序：分数降序，分数相同按姓名
players.sort(key=lambda p: (-p["score"], p["name"]))

# 候选：score >= 3 视为"特点鲜明"（含全明星/冠军级）；外加所有 HOF/75th/MVP 必含
candidates = [p for p in players if p["score"] >= 3]
print(f"总 B-Z 有绰号球员={len(players)}")
print(f"候选(score>=3)={len(candidates)}")
print(f"分数分布:",
      {s: sum(1 for p in players if p['score']==s) for s in sorted({p['score'] for p in players}, reverse=True)[:12]})

with open(os.path.join(BASE, "bz_candidates.json"), "w", encoding="utf-8") as f:
    json.dump(candidates, f, ensure_ascii=False, indent=1)
# 同时输出全部（用于最终文档渲染时带 note 匹配）
with open(os.path.join(BASE, "bz_all.json"), "w", encoding="utf-8") as f:
    json.dump(players, f, ensure_ascii=False, indent=1)
print("written bz_candidates.json / bz_all.json")
