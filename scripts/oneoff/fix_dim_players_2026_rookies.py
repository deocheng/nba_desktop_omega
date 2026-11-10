#!/usr/bin/env python3
"""
fix_dim_players_2026_rookies.py — 补 3 名 2026 新秀进 dim_players（FK 前置修复）。

背景：2026-27 gamelog 补爬中，3 名球员 BR 页正常但 insert 撞
fk_gamelog_dim_players——dim_players 无其 BR slug 行。dim_players 仅
player_id/player_name 非空，其余列可空、scraped_at 默认 now()。

幂等：NOT EXISTS 守卫，重复跑不插重复行。参数化写入（%s），无动态 SQL。
"""
import os
import sys

import psycopg2

DB = dict(host='127.0.0.1', port=5433, dbname='nba', user='postgres',
          password=os.environ.get('DB_PASSWORD'))

# (br_player_id, player_name, source_url) —— 来自 BR 联赛页名单 + 爬取日志
ROOKIES = [
    ('ikegr01', 'Graham Ike',
     'https://www.basketball-reference.com/players/i/ikegr01.html'),
    ('selleja01', 'Jaylin Sellers',
     'https://www.basketball-reference.com/players/s/selleja01.html'),
    ('awakato01', 'Tobe Awaka',
     'https://www.basketball-reference.com/players/a/awakato01.html'),
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

    # post-check：3 个 slug 必须都在
    cur.execute(
        "SELECT player_id FROM dim_players WHERE player_id = ANY(%s)",
        ([r[0] for r in ROOKIES],))
    found = {r[0] for r in cur.fetchall()}
    missing = [r[0] for r in ROOKIES if r[0] not in found]
    if missing:
        print(f'ERROR: post-check 缺失 {missing}', file=sys.stderr)
        conn.close()
        sys.exit(1)
    print('post-check OK: 3/3 slugs in dim_players')
    conn.close()


if __name__ == '__main__':
    main()
