#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, unicodedata, json
BASE = "/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13"
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
cur.execute("""SELECT d.player_name, d.nickname, b.career_honors_text
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

def score(honors):
    if not honors:
        return 0, ""
    text = " | ".join(honors) if isinstance(honors, (list, tuple)) else str(honors)
    sc = 0
    if 'MVP' in text: sc += 12
    if '75th' in text: sc += 8
    if 'Hall' in text: sc += 6
    sc += text.count('NBA Champ') * 2
    sc += text.count('ABA Champ') * 2
    sc += text.count('All Star') * 1
    if 'Scoring Champ' in text: sc += 1
    if 'ROY' in text: sc += 1
    if 'Defensive' in text: sc += 1
    return sc, text

cands = []
for name, nk, honors in rows:
    if not name or name[0].upper() not in "BCDEFGHIJKLMNOPQRSTUVWXYZ":
        continue
    sc, text = score(honors)
    if sc >= 2:
        cands.append({"name": name, "nickname": nk, "key": norm(name), "score": sc, "honors": text})

# print count and list
print(f"候选总数(score>=2, B-Z) = {len(cands)}")
for c in cands:
    print(f"  {c['score']:>3}  {c['name']:<28} | {c['nickname']}")

with open(os.path.join(BASE, "candidates.json"), "w", encoding="utf-8") as f:
    json.dump(cands, f, ensure_ascii=False, indent=2)
print("已写入 candidates.json")
