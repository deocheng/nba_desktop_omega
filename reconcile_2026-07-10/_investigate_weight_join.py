#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度核查（修正版）：迁移安全性（§6 合规：仅参数化 SQL）。
关键修正：player_id 在不同表里类型不同（BBRef character varying vs nba_api bigint）。
  - 若 player_id 为 character varying -> 直接 join dim_players.player_id
  - 若 player_id 为 bigint (nba_api) -> 用 br_player_id (若有) join dim_players.player_id
  - 否则标记无干净 join key
同时输出每表选中的 join key + 匹配率。
仅 SELECT，无落库。
"""
import os
import sys
import json
import psycopg2
from psycopg2 import sql

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)

FACT_TABLES = [
    'all_star_selections', 'dim_draft_history', 'end_of_season_teams',
    'fact_player_season_stats', 'player_award_shares', 'player_contracts',
    'player_contracts_league', 'player_gamelog', 'player_play_by_play',
    'player_season_info', 'player_season_splits', 'player_shooting',
]


def connect():
    c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                         user='postgres', password=os.environ.get('DB_PASSWORD'))
    c.autocommit = True
    return c


def col_type(cur, table, col):
    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s AND column_name=%s",
        (table, col),
    )
    r = cur.fetchone()
    return r[0] if r else None


def has_col(cur, table, col):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s AND column_name=%s",
        (table, col),
    )
    return cur.fetchone() is not None


def main():
    conn = connect()
    cur = conn.cursor()
    out = {}

    print('=' * 70)
    print('B) 各事实表 join key 选择 + 匹配率（基于 player_id 真实类型）')
    print('=' * 70)
    match_info = {}
    for t in FACT_TABLES:
        pid_type = col_type(cur, t, 'player_id')
        has_br = has_col(cur, t, 'br_player_id')
        # 选 key：text/character varying 均可直接 join dim_players.player_id(varchar)
        #          仅 bigint(nba_api) 需改用 br_player_id
        if pid_type in ('character varying', 'text'):
            key = 'player_id'
        elif has_br:
            key = 'br_player_id'
        else:
            key = None
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(t)))
        total = cur.fetchone()[0]
        if key is None:
            matched = 0
            rate = 0.0
            print(f'  {t:30s} pid_type={str(pid_type):16s} key=NONE -> 无干净 join key!')
        else:
            q = sql.SQL(
                "SELECT COUNT(*) FROM {t} x WHERE EXISTS ("
                "SELECT 1 FROM dim_players d WHERE d.player_id = x.{k})"
            ).format(t=sql.Identifier(t), k=sql.Identifier(key))
            cur.execute(q)
            matched = cur.fetchone()[0]
            rate = (matched / total * 100) if total else 0.0
            print(f'  {t:30s} pid_type={str(pid_type):16s} key={key:12s} '
                  f'total={total:<9} matched={matched:<9} rate={rate:5.1f}%')
        match_info[t] = {'player_id_type': pid_type, 'has_br_player_id': has_br,
                         'join_key': key, 'total': total, 'matched': matched, 'rate': rate}
    out['pid_match'] = match_info

    # gamelog 双键抽样确认
    print()
    print('D) player_gamelog 双键抽样 + br_player_id 匹配率')
    cur.execute(
        "SELECT player_id, br_player_id, nba_player_id FROM player_gamelog "
        "WHERE br_player_id IS NOT NULL LIMIT 3"
    )
    for r in cur.fetchall():
        print(f'  player_id(bigint)={r[0]!r} br_player_id={r[1]!r} nba_player_id={r[2]!r}')
    cur.execute(
        "SELECT COUNT(*) FROM player_gamelog g WHERE EXISTS "
        "(SELECT 1 FROM dim_players d WHERE d.player_id = g.br_player_id)"
    )
    g_match = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM player_gamelog WHERE br_player_id IS NOT NULL")
    g_total = cur.fetchone()[0]
    print(f'  player_gamelog br_player_id 匹配 dim_players: {g_match}/{g_total} '
          f'({g_match/g_total*100:.1f}%)')
    out['gamelog_br_key'] = {'matched': g_match, 'total': g_total,
                             'rate': g_match / g_total * 100 if g_total else 0.0}

    conn.close()
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '_investigate_weight_join.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print('\n[OK] 结构化结果已写入 _investigate_weight_join.json')


if __name__ == '__main__':
    main()
