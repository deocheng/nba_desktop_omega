#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_migrate_add_weight_cols.py  —  给"应加 weight"的 player 事实/维度表补 `weight` 列并回填。

§6 合规：
  - 所有表名/列名用 psycopg2.sql.Identifier 参数化，绝无 f-string 拼表名/列名。
  - 无 eval / exec。
  - 回填用【批量 JOIN UPDATE】（FROM dim_players s ... WHERE t.<key>=s.player_id），
    杜绝"循环内单 player 逐行 DB 往返"。
  - 独立连接 + autocommit=True，避免事务悬挂。
  - 默认 --dry-run（只打印计划，绝不落库）；仅 --execute 才真正 ALTER + UPDATE。

权威源：dim_players（player_id 主键，weight_lbs 非空 5473/5476≈99.9%）。
       备选 player_weight_history（5473 行全非空）。本脚本默认用 dim_players。
join key：多数表 player_id 为 text/varchar，直接 join dim_players.player_id；
          player_gamelog 的 player_id 是 bigint(nba_api)，改用 br_player_id。
单位：默认 weight_lbs（与库内既有 weight_lbs/weight_kg 惯例一致）；
      kg 与否需主理人拍板（改 SOURCE_WEIGHT_COL 即可）。

范围（报告 A 判定"应加"的 12 张；dim_players / player_weight_history 自身、
2 张备份、2 张映射桥、2 张无 player_id 的事实表已排除）：
  all_star_selections, end_of_season_teams, fact_player_season_stats,
  player_award_shares, player_contracts, player_contracts_league,
  player_gamelog(br_player_id), player_play_by_play, player_season_info,
  player_season_splits, player_shooting, dim_draft_history

用法：
  python _migrate_add_weight_cols.py            # 默认 dry-run
  python _migrate_add_weight_cols.py --execute  # 真正 ALTER + UPDATE（逐表独立提交）
"""
import os
import sys
import psycopg2
from psycopg2 import sql

for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)

# ---- 配置（集中可改，便于主理人扩容/调单位）----
DB = dict(host='localhost', port=5433, dbname='nba',
          user='postgres', password=os.environ.get('DB_PASSWORD'))

NEW_COL = 'weight'            # 列名固定 weight（任务要求）
NEW_COL_TYPE = 'NUMERIC'      # 类型 NUMERIC

SOURCE_TABLE = 'dim_players'  # 权威源表
SOURCE_ID_COL = 'player_id'   # 权威源 join id（BBRef id）
SOURCE_WEIGHT_COL = 'weight_lbs'  # 取值列（默认 lbs；改 'weight_kg' 即 kg）

# 应加 weight 的表 -> 其 join key（连到 SOURCE_ID_COL）
# 注意 player_gamelog.player_id 是 bigint(nba_api)，必须用 br_player_id
TARGET_TABLES = {
    'all_star_selections': 'player_id',
    'end_of_season_teams': 'player_id',
    'fact_player_season_stats': 'player_id',
    'player_award_shares': 'player_id',
    'player_contracts': 'player_id',
    'player_contracts_league': 'player_id',
    'player_gamelog': 'br_player_id',   # 特殊：player_id 为 bigint，须用 br_player_id
    'player_play_by_play': 'player_id',
    'player_season_info': 'player_id',
    'player_season_splits': 'player_id',
    'player_shooting': 'player_id',
    'dim_draft_history': 'player_id',
}


def connect():
    c = psycopg2.connect(**DB)
    c.autocommit = True  # §6：独立连接 + autocommit，避免事务悬挂
    return c


def col_exists(cur, table, col):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s AND column_name=%s",
        (table, col),
    )
    return cur.fetchone() is not None


def table_exists(cur, table):
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    return cur.fetchone() is not None


def dry_run_table(cur, tbl, key):
    """打印该表 dry-run 计划：加列 / 可回填 N 行 / 无法回填 M 行。仅 SELECT。"""
    exists = table_exists(cur, tbl)
    if not exists:
        print(f'  [跳过] {tbl}: 表不存在')
        return
    has_col = col_exists(cur, tbl, NEW_COL)

    # 列尚不存在时，所有行都是回填候选（无需 t.weight IS NULL 过滤）
    null_filter = (sql.SQL("t.{newcol} IS NULL AND ").format(newcol=sql.Identifier(NEW_COL))
                   if has_col else sql.SQL(""))

    # 可回填：能 join 到权威源（且权威源 weight 非空）
    q_back = sql.SQL(
        "SELECT COUNT(*) FROM {tbl} t WHERE {nullf}EXISTS ("
        "SELECT 1 FROM {src} s WHERE s.{src_id} = t.{key} AND s.{src_w} IS NOT NULL)"
    ).format(tbl=sql.Identifier(tbl), nullf=null_filter,
             src=sql.Identifier(SOURCE_TABLE), src_id=sql.Identifier(SOURCE_ID_COL),
             key=sql.Identifier(key), src_w=sql.Identifier(SOURCE_WEIGHT_COL))
    cur.execute(q_back)
    n_back = cur.fetchone()[0]

    # 无法回填：join 不到 / 权威源为空
    q_un = sql.SQL(
        "SELECT COUNT(*) FROM {tbl} t WHERE {nullf}NOT EXISTS ("
        "SELECT 1 FROM {src} s WHERE s.{src_id} = t.{key} AND s.{src_w} IS NOT NULL)"
    ).format(tbl=sql.Identifier(tbl), nullf=null_filter,
             src=sql.Identifier(SOURCE_TABLE), src_id=sql.Identifier(SOURCE_ID_COL),
             key=sql.Identifier(key), src_w=sql.Identifier(SOURCE_WEIGHT_COL))
    cur.execute(q_un)
    n_un = cur.fetchone()[0]

    add_msg = f'将加列 {NEW_COL} {NEW_COL_TYPE}' if not has_col else f'{NEW_COL} 已存在(跳过加列)'
    print(f'  [计划] {tbl} (join key={key}): {add_msg} | 将回填 {n_back} 行 | '
          f'无法回填 {n_un} 行')


def execute_table(cur, tbl, key):
    """真正 ALTER + 批量 JOIN UPDATE（逐表独立提交，因 autocommit=True）。"""
    if not table_exists(cur, tbl):
        print(f'  [跳过] {tbl}: 表不存在')
        return
    has_col = col_exists(cur, tbl, NEW_COL)
    if not has_col:
        cur.execute(sql.SQL("ALTER TABLE {tbl} ADD COLUMN {col} {ctype}").format(
            tbl=sql.Identifier(tbl), col=sql.Identifier(NEW_COL),
            ctype=sql.SQL(NEW_COL_TYPE)))
        print(f'  [OK] {tbl}: 已加列 {NEW_COL} {NEW_COL_TYPE}')
    else:
        print(f'  [跳过] {tbl}: {NEW_COL} 已存在，仅回填')

    # 批量 JOIN UPDATE（幂等：WHERE t.<newcol> IS NULL）
    q_upd = sql.SQL(
        "UPDATE {tbl} t SET {newcol} = s.{src_w} FROM {src} s "
        "WHERE t.{key} = s.{src_id} AND s.{src_w} IS NOT NULL AND t.{newcol} IS NULL"
    ).format(tbl=sql.Identifier(tbl), newcol=sql.Identifier(NEW_COL),
             src=sql.Identifier(SOURCE_TABLE), src_id=sql.Identifier(SOURCE_ID_COL),
             key=sql.Identifier(key), src_w=sql.Identifier(SOURCE_WEIGHT_COL))
    cur.execute(q_upd)
    n = cur.rowcount
    print(f'  [OK] {tbl}: 回填 {n} 行（weight 仍 NULL 的为无法匹配权威源的行）')


def main():
    execute = '--execute' in sys.argv
    mode = 'EXECUTE(落库)' if execute else 'DRY-RUN(不落库)'
    print(f'=== _migrate_add_weight_cols | 模式: {mode} ===')
    print(f'    权威源={SOURCE_TABLE}.{SOURCE_ID_COL} -> {SOURCE_WEIGHT_COL} | '
          f'新列={NEW_COL} {NEW_COL_TYPE} | 目标表数={len(TARGET_TABLES)}')

    conn = connect()
    cur = conn.cursor()
    for tbl, key in TARGET_TABLES.items():
        if execute:
            execute_table(cur, tbl, key)
        else:
            dry_run_table(cur, tbl, key)
    conn.close()
    print('=== 完成 ===')
    if not execute:
        print('（默认 dry-run，未做任何改动。加 --execute 才真正 ALTER+UPDATE）')


if __name__ == '__main__':
    main()
