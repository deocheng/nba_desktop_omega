#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调查 player 相关表缺 `weight` 列的根因（§6 合规：仅参数化 SQL）。

查询范围（只读 SELECT，绝不 ALTER/UPDATE）：
  1. dim_players 全列 -> 是否含体重相关列（weight / weight_lbs / weight_kg / wght 等）
  2. player_weight_history 结构 + 行数 + 样本行（确认体重权威源）
  3. 全库 weight* 列分布
  4. 20 张候选表的结构（重点：是否有 player_id / br_player_id 列、行数）

执行：
  env -u http_proxy ... python _investigate_weight_cols_run.py
仅 SELECT，无落库。
"""
import os
import sys
import json
import psycopg2
from psycopg2 import sql

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)

# 20 张候选表（主理人按"表名含 player 或含 player_id 列"找到）
CANDIDATE_TABLES = [
    'all_star_selections',
    'dim_draft_history',
    'dim_draft_history_bak_20260712',
    'dim_players',
    'end_of_season_teams',
    'fact_player_season_stats',
    'player_award_shares',
    'player_career_totals',
    'player_contracts',
    'player_contracts_league',
    'player_gamelog',
    'player_gamelog_dup2026_bak',
    'player_id_bridge',
    'player_name_unified',
    'player_play_by_play',
    'player_salaries_historical',
    'player_season_info',
    'player_season_splits',
    'player_shooting',
    'player_weight_history',
]


def connect():
    c = psycopg2.connect(host='localhost', port=5433, dbname='nba',
                         user='postgres', password=os.environ.get('DB_PASSWORD'))
    c.autocommit = True  # §6：独立连接 + autocommit，避免事务悬挂
    return c


def get_columns(cur, table_name):
    """返回 (列名, 类型) 列表，按列序。"""
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    return cur.fetchall()


def table_exists(cur, table_name):
    cur.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    )
    return cur.fetchone() is not None


def row_count(cur, table_name):
    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name)))
    return cur.fetchone()[0]


def main():
    conn = connect()
    cur = conn.cursor()

    out = {}

    # ---- 1) dim_players 全列 ----
    print('=' * 70)
    print('1) dim_players 全列')
    print('=' * 70)
    dim_cols = get_columns(cur, 'dim_players')
    for cn, ct in dim_cols:
        print(f'  {cn:30s} {ct}')
    weight_related = [cn for cn, _ in dim_cols if 'weight' in cn.lower() or cn.lower() in ('wght', 'wt')]
    print(f'  -> 含体重相关列?: {bool(weight_related)} {weight_related}')
    out['dim_players_columns'] = [(cn, ct) for cn, ct in dim_cols]
    out['dim_players_weight_related'] = weight_related

    # ---- 2) player_weight_history 结构 ----
    print()
    print('=' * 70)
    print('2) player_weight_history 结构 + 行数 + 样本行')
    print('=' * 70)
    if table_exists(cur, 'player_weight_history'):
        pwh_cols = get_columns(cur, 'player_weight_history')
        for cn, ct in pwh_cols:
            print(f'  {cn:30s} {ct}')
        n = row_count(cur, 'player_weight_history')
        print(f'  -> 行数: {n}')
        cur.execute(
            sql.SQL("SELECT * FROM {} LIMIT 5").format(sql.Identifier('player_weight_history'))
        )
        sample_cols = [d[0] for d in cur.description]
        samples = cur.fetchall()
        print(f'  -> 样本列: {sample_cols}')
        for r in samples:
            print(f'  -> {r}')
        out['player_weight_history_columns'] = [(cn, ct) for cn, ct in pwh_cols]
        out['player_weight_history_rowcount'] = n
        out['player_weight_history_sample'] = [sample_cols, [list(r) for r in samples]]
    else:
        print('  -> 表不存在!')
        out['player_weight_history_columns'] = None

    # ---- 3) 全库 weight* 列分布 ----
    print()
    print('=' * 70)
    print('3) 全库 weight* 列分布')
    print('=' * 70)
    cur.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name ILIKE 'weight%'
        ORDER BY table_name, column_name
        """
    )
    weight_cols = cur.fetchall()
    for t, c, ct in weight_cols:
        print(f'  {t:35s} {c:20s} {ct}')
    if not weight_cols:
        print('  (无任何 weight* 列)')
    out['all_weight_columns'] = [(t, c, ct) for t, c, ct in weight_cols]

    # ---- 4) 20 张候选表结构 ----
    print()
    print('=' * 70)
    print('4) 20 张候选表结构（player_id / br_player_id / 行数）')
    print('=' * 70)
    candidate_info = {}
    for t in CANDIDATE_TABLES:
        if not table_exists(cur, t):
            print(f'  [缺失] {t}  -> 表不存在')
            candidate_info[t] = {'exists': False}
            continue
        cols = get_columns(cur, t)
        col_names = [cn for cn, _ in cols]
        has_player_id = 'player_id' in col_names
        has_br_player_id = 'br_player_id' in col_names
        # 其它可能的 player 关联列
        player_like = [cn for cn in col_names if 'player' in cn.lower()]
        n = row_count(cur, t)
        print(f'  {t:35s} rows={n:<8} player_id={has_player_id} br_player_id={has_br_player_id} '
              f'player_like={player_like}')
        candidate_info[t] = {
            'exists': True,
            'rowcount': n,
            'columns': col_names,
            'has_player_id': has_player_id,
            'has_br_player_id': has_br_player_id,
            'player_like_columns': player_like,
        }
    out['candidate_tables'] = candidate_info

    # ---- 5) 口径核对：验证 20 的来源 ----
    print()
    print('=' * 70)
    print('5) 口径核对：为何是 20 张')
    print('=' * 70)
    # 5a) 表名含 player
    cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema='public' AND table_name ILIKE '%player%'
        """
    )
    n_name_like = cur.fetchone()[0]
    # 5b) 含 player_id 列的表
    cur.execute(
        """
        SELECT COUNT(DISTINCT table_name) FROM information_schema.columns
        WHERE table_schema='public' AND column_name = 'player_id'
        """
    )
    n_has_player_id_col = cur.fetchone()[0]
    # 5c) 表名含 player OR 含 player_id 列（并集）
    cur.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_name ILIKE '%player%'
            UNION
            SELECT table_name FROM information_schema.columns
            WHERE table_schema='public' AND column_name = 'player_id'
        ) s
        """
    )
    n_union = cur.fetchone()[0]
    # 5d) 仅 base 表（排除 _bak / _dup 备份表）
    base_candidates = [t for t in CANDIDATE_TABLES
                       if not (t.endswith('_bak') or '_bak_' in t or '_dup' in t or t.endswith('_dup2026_bak'))]
    print(f'  a) 表名 ILIKE %player% 的表数: {n_name_like}')
    print(f'  b) 含 player_id 列的表数: {n_has_player_id_col}')
    print(f'  c) 表名含 player OR 含 player_id 列（并集）: {n_union}')
    print(f'  d) 20 候选中排除备份后的 base 表数: {len(base_candidates)}')
    print(f'     base 表: {base_candidates}')
    out['caliber_check'] = {
        'name_like_player': n_name_like,
        'has_player_id_col': n_has_player_id_col,
        'union_name_or_player_id': n_union,
        'base_candidate_count': len(base_candidates),
        'base_candidates': base_candidates,
    }

    conn.close()

    # 落盘结构化 JSON 供报告引用
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '_investigate_weight_cols.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print('\n[OK] 结构化结果已写入 _investigate_weight_cols.json')


if __name__ == '__main__':
    main()
