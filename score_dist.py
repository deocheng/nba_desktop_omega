#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, unicodedata
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
cur.execute("""SELECT d.player_name, b.career_honors_text
              FROM dim_players d LEFT JOIN player_bio b ON b.player_id = d.player_id
              WHERE d.nickname IS NOT NULL AND d.nickname<>'' ORDER BY d.player_name""")
rows = cur.fetchall(); conn.close()

def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).strip().lower()

def score_per(honors):
    if not honors: return 0
    text = " | ".join(honors) if isinstance(honors,(list,tuple)) else str(honors)
    sc=0
    if 'MVP' in text: sc+=12
    if '75th' in text: sc+=8
    if 'Hall' in text: sc+=6
    sc+=text.count('NBA Champ')*2
    sc+=text.count('ABA Champ')*2
    sc+=text.count('All Star')*1
    if 'Scoring Champ' in text: sc+=1
    if 'ROY' in text: sc+=1
    if 'Defensive' in text: sc+=1
    return sc

def score_once(honors):
    if not honors: return 0
    text = " | ".join(honors) if isinstance(honors,(list,tuple)) else str(honors)
    sc=0
    if 'MVP' in text: sc+=12
    if '75th' in text: sc+=8
    if 'Hall' in text: sc+=6
    if 'NBA Champ' in text: sc+=2
    if 'ABA Champ' in text: sc+=2
    if 'All Star' in text: sc+=1
    if 'Scoring Champ' in text: sc+=1
    if 'ROY' in text: sc+=1
    if 'Defensive' in text: sc+=1
    return sc

for label, fn in [("per",score_per),("once",score_once)]:
    cands=[]
    for name,h in rows:
        if not name or name[0].upper() not in "BCDEFGHIJKLMNOPQRSTUVWXYZ": continue
        if fn(h)>=2: cands.append(name)
    print(f"[{label}] B-Z score>=2 人数 = {len(cands)}")
