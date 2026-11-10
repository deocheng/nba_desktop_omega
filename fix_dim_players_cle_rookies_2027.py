#!/usr/bin/env python3
"""
fix_dim_players_cle_rookies_2027.py — 补 2 名 CLE 球员进 dim_players（FK 前置修复）。

背景：2026-27 CLE@PHI（game_id 202610220PHI）补爬探测中发现，CLE 阵容中
udehjer01 (Ernest Udeh Jr.)、diopkh01 (Khalifa Diop) 不在 dim_players。
一旦 BR 发布该场、自动补爬触发，fk_gamelog_dim_players 会拦截这 2 人的
gamelog 行（与 2026 新秀同款问题）。名字取自 BR /teams/CLE/2027.html roster。

幂等：NOT EXISTS 守卫；参数化写入（%s），无动态 SQL。
来源：本机已有全量备份 nba_full_20261023_013448.dump，无需另备。
"""
import os
import sys

import psycopg2

DB = dict(host='127.0.0.1', port=5433, dbname='nba', user='postgres',
          password=os.environ.get('DB_PASSWORD'))

ROOKIES = [
    ('udehjer01', 'Ernest Udeh Jr.',
     'https://www.basketball-reference.com/players/u/udehjer01.html'),
    ('diopkh01', 'Khalifa Diop',
     'https://www.basketball-reference.com/players/d/diopkh01.html'),
]


def main():
    if not DB['password']:
        print('ERROR: DB_PASSWORD 未设置', file=sys.stderr)
        sys.exit(2)
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    inserted = 0
    for pid, name, url in ROOKIES:
        cur.execute("SELECT 1 FROM dim_players WHERE player_id = %s", (pid,))
        if cur.fetchone():
            print(f'skip (exists): {pid} {name}')
            continue
        cur.execute(
            "INSERT INTO dim_players (player_id, player_name, source_url) "
            "VALUES (%s, %s, %s)",
            (pid, name, url))
        inserted += 1
        print(f'inserted: {pid} {name}')
    conn.commit()
    print(f'done: {inserted} inserted / {len(ROOKIES)} total')

    cur.execute(
        "SELECT player_id FROM dim_players WHERE player_id = ANY(%s)",
        ([r[0] for r in ROOKIES],))
    found = {r[0] for r in cur.fetchall()}
    missing = [r[0] for r in ROOKIES if r[0] not in found]
    if missing:
        print(f'ERROR: post-check 缺失 {missing}', file=sys.stderr)
        conn.close()
        sys.exit(1)
    print('post-check OK: 2/2 slugs in dim_players')
    conn.close()


if __name__ == '__main__':
    main()
