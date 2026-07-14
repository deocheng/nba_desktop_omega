#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核查 C) 权威源覆盖 + 口径解释（§6 合规：仅参数化 SQL）。
  C1) dim_players / player_weight_history 的 weight_lbs/weight_kg 非空计数
  C2) 验证"20 = 缺 weight 的 player 相关表"：
      (表名含 player OR 含 player_id 列) AND 不含任何 weight* 列 -> 计数+清单
  C3) 反向：含 player 相关但【已】有 weight* 列的表（解释为何被排除在 20 之外）
仅 SELECT，无落库。
"""
import os
import sys
import json
import psycopg2
from psycopg2 import sql

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)


def connect():
    c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                         user='postgres', password=os.environ.get('DB_PASSWORD'))
    c.autocommit = True
    return c


def main():
    conn = connect()
    cur = conn.cursor()
    out = {}

    # C1) 权威源覆盖
    print('=' * 70)
    print('C1) 权威源体重覆盖')
    print('=' * 70)
    cur.execute("SELECT COUNT(*), COUNT(weight_lbs), COUNT(weight_kg) FROM dim_players")
    dp = cur.fetchone()
    cur.execute("SELECT COUNT(*), COUNT(weight_lbs), COUNT(weight_kg) FROM player_weight_history")
    pwh = cur.fetchone()
    print(f'  dim_players:           total={dp[0]} weight_lbs非null={dp[1]} weight_kg非null={dp[2]}')
    print(f'  player_weight_history: total={pwh[0]} weight_lbs非null={pwh[1]} weight_kg非null={pwh[2]}')
    out['coverage'] = {
        'dim_players': {'total': dp[0], 'weight_lbs': dp[1], 'weight_kg': dp[2]},
        'player_weight_history': {'total': pwh[0], 'weight_lbs': pwh[1], 'weight_kg': pwh[2]},
    }

    # C2) 缺 weight 的 player 相关表
    print()
    print('=' * 70)
    print('C2) player 相关表且【不含】任何 weight* 列（应为 20 量级）')
    print('=' * 70)
    cur.execute(
        """
        SELECT t.table_name
        FROM information_schema.tables t
        WHERE t.table_schema='public'
          AND (t.table_name ILIKE '%player%'
               OR EXISTS (SELECT 1 FROM information_schema.columns c
                          WHERE c.table_schema='public' AND c.table_name=t.table_name
                            AND c.column_name='player_id'))
          AND NOT EXISTS (SELECT 1 FROM information_schema.columns c
                          WHERE c.table_schema='public' AND c.table_name=t.table_name
                            AND c.column_name ILIKE 'weight%')
        ORDER BY t.table_name
        """
    )
    missing = [r[0] for r in cur.fetchall()]
    print(f'  计数: {len(missing)}')
    for m in missing:
        print(f'    - {m}')
    out['missing_weight_tables'] = missing

    # C3) player 相关表且【已含】weight* 列
    print()
    print('=' * 70)
    print('C3) player 相关表且【已含】weight* 列（被排除在 20 之外的原因）')
    print('=' * 70)
    cur.execute(
        """
        SELECT DISTINCT t.table_name
        FROM information_schema.tables t
        JOIN information_schema.columns c ON c.table_schema='public' AND c.table_name=t.table_name
        WHERE t.table_schema='public'
          AND (t.table_name ILIKE '%player%'
               OR EXISTS (SELECT 1 FROM information_schema.columns c2
                          WHERE c2.table_schema='public' AND c2.table_name=t.table_name
                            AND c2.column_name='player_id'))
          AND c.column_name ILIKE 'weight%'
        ORDER BY t.table_name
        """
    )
    have = [r[0] for r in cur.fetchall()]
    print(f'  计数: {len(have)}')
    for h in have:
        print(f'    - {h}')
    out['already_have_weight_tables'] = have

    conn.close()
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '_investigate_weight_caliber.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print('\n[OK] 结构化结果已写入 _investigate_weight_caliber.json')


if __name__ == '__main__':
    main()
