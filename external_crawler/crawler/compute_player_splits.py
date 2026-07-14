#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Player Season Splits — 从 player_gamelog + games 计算
=====================================================
从已有的逐场比赛数据聚合计算多种 split 类型，无需爬取 BR。

Split 类型:
  1. location  → home / away
  2. result    → wins / losses
  3. month     → October ~ June
  4. all_star  → pre_all_star / post_all_star
  5. day_of_week → Monday ~ Sunday
  6. opponent  → vs 每个对手球队

用法:
  python compute_player_splits.py [--season 2026] [--split-types all]
  python compute_player_splits.py --season 2026 --split-types location,result,month
  python compute_player_splits.py --all-seasons
"""

import argparse
import psycopg2
import sys
import time
from datetime import datetime

DB_CONFIG = {
    'host': 'localhost',
    'port': 5433,
    'database': 'nba',
    'user': 'postgres',
    'password': 'postgres',
}

# All-Star game dates (用于 pre/post All-Star split)
ALL_STAR_DATES = {
    2026: '2026-02-15',
    2025: '2025-02-16',
    2024: '2024-02-18',
    2023: '2023-02-19',
    2022: '2022-02-20',
    2021: '2021-03-07',  # COVID delayed
    2020: '2020-02-16',
    2019: '2019-02-17',
    2018: '2018-02-18',
    2017: '2017-02-19',
    2016: '2016-02-14',
    2015: '2015-02-15',
    2014: '2014-02-16',
    2013: '2013-02-17',
    2012: '2012-02-26',  # COVID shortened, ASG delayed
    2011: '2011-02-20',
    2010: '2010-02-14',
    2009: '2009-02-15',
    2008: '2008-02-17',
    2007: '2007-02-18',
    2006: '2006-02-19',
    2005: '2005-02-20',
    2004: '2004-02-15',
    2003: '2003-02-09',
    2002: '2002-02-10',
    2001: '2001-02-11',
    2000: '2000-02-13',
    1999: '1999-03-07',  # Lockout shortened
    1998: '1998-02-08',
    1997: '1997-02-09',
    1996: '1996-02-11',
    1995: '1995-02-12',
    1994: '1994-02-13',
    1993: '1993-02-21',
    1992: '1992-02-09',
    1991: '1991-02-10',
    1990: '1990-02-11',
    1989: '1989-02-12',
    1988: '1988-02-07',
    1987: '1987-02-08',
    1986: '1986-02-09',
    1985: '1985-02-10',
    1984: '1984-01-29',
    1983: '1983-01-30',
    1982: '1982-01-31',
    1981: '1981-02-01',
    1980: '1980-02-03',
    1979: '1979-02-04',
    1978: '1978-02-05',
    1977: '1977-02-06',
    1976: '1976-02-03',
    1975: '1975-01-14',
    1974: '1974-01-15',
    1973: '1973-01-16',
    1972: '1972-01-18',
    1971: '1971-01-12',
    1970: '1970-01-20',
    1969: '1969-01-14',
    1968: '1968-01-23',
    1967: '1967-01-10',
    1966: '1966-01-11',
}

ALL_SPLIT_TYPES = ['location', 'result', 'month', 'all_star', 'day_of_week', 'opponent']


def get_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn


def alter_table(cur):
    """扩展 player_season_splits 表结构"""
    print("[1/4] 检查并扩展表结构...")

    # 添加 split_category 列
    cur.execute("""
        ALTER TABLE player_season_splits 
        ADD COLUMN IF NOT EXISTS split_category TEXT DEFAULT 'location'
    """)

    # 添加更多统计列
    new_cols = [
        ('mp', 'DECIMAL(6,1)'),
        ('fg', 'INTEGER'),
        ('fga', 'INTEGER'),
        ('fg3', 'INTEGER'),
        ('fga3', 'INTEGER'),
        ('ft', 'INTEGER'),
        ('fta', 'INTEGER'),
        ('orb', 'INTEGER'),
        ('drb', 'INTEGER'),
        ('stl', 'INTEGER'),
        ('blk', 'INTEGER'),
        ('tov', 'INTEGER'),
        ('pf', 'INTEGER'),
    ]
    for col, dtype in new_cols:
        cur.execute(f"ALTER TABLE player_season_splits ADD COLUMN IF NOT EXISTS {col} {dtype}")

    # 更新现有 home/away 数据的 split_category
    cur.execute("""
        UPDATE player_season_splits 
        SET split_category = 'location' 
        WHERE split_category IS NULL
    """)

    print("  ✅ 表结构已扩展（+13 统计列 +split_category）")


def compute_splits(cur, seasons, split_types, batch_size=5000):
    """计算并插入 split 数据"""

    for season in seasons:
        print(f"\n[2/4] 计算 {season} 赛季 splits (类型: {', '.join(split_types)})...")

        # 先删除该赛季的旧数据（只删除要重新计算的 split 类型）
        categories_filter = "','".join(split_types)
        cur.execute(f"""
            DELETE FROM player_season_splits 
            WHERE season = {season} 
              AND split_category IN ('{categories_filter}')
        """)
        deleted = cur.rowcount
        if deleted > 0:
            print(f"  删除旧数据: {deleted:,} 行")

        total_inserted = 0

        for split_type in split_types:
            t0 = time.time()
            sql = build_split_sql(season, split_type)
            if sql is None:
                print(f"  ⏭️  {split_type}: 跳过（无 All-Star 日期）")
                continue

            cur.execute(sql)
            inserted = cur.rowcount
            elapsed = time.time() - t0
            total_inserted += inserted
            print(f"  ✅ {split_type:15s}: {inserted:>7,} 行  ({elapsed:.1f}s)")

        print(f"  📊 {season} 赛季合计: {total_inserted:,} 行")


def build_split_sql(season, split_type):
    """构建 split 聚合 SQL"""

    # JOIN 逻辑说明：
    # - 2024~2026: player_gamelog.gameid (8位) 直接等于 games.game_id (8位, 有date)
    # - 2015~2023: player_gamelog.gameid (8位, 如22200001) 对应 games.game_id 中
    #              有 date 的是 10位版本 (0022200001), 需要加 '00' 前缀来匹配
    # 用 COALESCE 双重 join 兼容两种情况，且只取有 game_date 的那条记录
    base_select = """
        SELECT
            {season}::INTEGER as season,
            pg.player as player_name,
            pg.team as team_abbr,
            '{category}' as split_category,
            '{split_value}' as split_type,
            COUNT(*) as games,
            ROUND(AVG(pg.pts)::numeric, 1) as pts,
            ROUND(AVG(pg.trb)::numeric, 1) as reb,
            ROUND(AVG(pg.ast)::numeric, 1) as ast,
            ROUND(AVG(pg.stl)::numeric, 1) as stl,
            ROUND(AVG(pg.blk)::numeric, 1) as blk,
            ROUND(AVG(pg.tov)::numeric, 1) as tov,
            ROUND(AVG(pg.pf)::numeric, 1) as pf,
            SUM(pg.fg) as fg,
            SUM(pg.fga) as fga,
            SUM(pg.fg3) as fg3,
            SUM(pg.fga3) as fga3,
            SUM(pg.ft) as ft,
            SUM(pg.fta) as fta,
            SUM(pg.orb) as orb,
            SUM(pg.drb) as drb,
            CASE WHEN SUM(pg.fga) > 0 
                THEN ROUND(SUM(pg.fg)::numeric / SUM(pg.fga), 3) ELSE NULL END as fg_pct,
            CASE WHEN SUM(pg.fga3) > 0 
                THEN ROUND(SUM(pg.fg3)::numeric / SUM(pg.fga3), 3) ELSE NULL END as fg3_pct,
            CASE WHEN SUM(pg.fta) > 0 
                THEN ROUND(SUM(pg.ft)::numeric / SUM(pg.fta), 3) ELSE NULL END as ft_pct,
            ROUND(AVG(pg.plus_minus)::numeric, 1) as plus_minus,
            NOW() as created_at
        FROM player_gamelog pg
        JOIN games g ON (
            g.game_id = pg.gameid
            OR g.game_id = '00' || pg.gameid
        )
        WHERE pg.season = {season}
          AND g.season = {season}
          AND g.game_date IS NOT NULL
    """

    insert_cols = """
        (season, player_name, team_abbr, split_category, split_type, games,
         pts, reb, ast, stl, blk, tov, pf, fg, fga, fg3, fga3, ft, fta, orb, drb,
         fg_pct, fg3_pct, ft_pct, plus_minus, created_at)
    """

    if split_type == 'location':
        # Home/Away
        return f"""
        INSERT INTO player_season_splits {insert_cols}
        {base_select.format(season=season, category='location', split_value='home')}
          AND pg.team = g.home_team_abbr
        GROUP BY pg.player, pg.team
        ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
            split_category = EXCLUDED.split_category,
            games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
            ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
            tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
            fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
            orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
            fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
            plus_minus = EXCLUDED.plus_minus, created_at = NOW();

        INSERT INTO player_season_splits {insert_cols}
        {base_select.format(season=season, category='location', split_value='away')}
          AND pg.team = g.away_team_abbr
        GROUP BY pg.player, pg.team
        ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
            split_category = EXCLUDED.split_category,
            games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
            ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
            tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
            fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
            orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
            fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
            plus_minus = EXCLUDED.plus_minus, created_at = NOW();
        """

    elif split_type == 'result':
        # Wins/Losses
        return f"""
        INSERT INTO player_season_splits {insert_cols}
        {base_select.format(season=season, category='result', split_value='wins')}
          AND (
            (pg.team = g.home_team_abbr AND g.home_pts > g.away_pts)
            OR
            (pg.team = g.away_team_abbr AND g.away_pts > g.home_pts)
          )
        GROUP BY pg.player, pg.team
        ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
            split_category = EXCLUDED.split_category,
            games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
            ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
            tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
            fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
            orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
            fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
            plus_minus = EXCLUDED.plus_minus, created_at = NOW();

        INSERT INTO player_season_splits {insert_cols}
        {base_select.format(season=season, category='result', split_value='losses')}
          AND (
            (pg.team = g.home_team_abbr AND g.home_pts < g.away_pts)
            OR
            (pg.team = g.away_team_abbr AND g.away_pts < g.home_pts)
          )
        GROUP BY pg.player, pg.team
        ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
            split_category = EXCLUDED.split_category,
            games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
            ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
            tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
            fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
            orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
            fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
            plus_minus = EXCLUDED.plus_minus, created_at = NOW();
        """

    elif split_type == 'month':
        # By month (Oct through Jun)
        months = [
            (10, 'October'), (11, 'November'), (12, 'December'),
            (1, 'January'), (2, 'February'), (3, 'March'),
            (4, 'April'), (5, 'May'), (6, 'June'),
        ]
        statements = []
        for month_num, month_name in months:
            sql = f"""
            INSERT INTO player_season_splits {insert_cols}
            {base_select.format(season=season, category='month', split_value=month_name.lower())}
              AND EXTRACT(MONTH FROM g.game_date) = {month_num}
            GROUP BY pg.player, pg.team
            ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
                split_category = EXCLUDED.split_category,
                games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
                ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
                tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
                fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
                orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
                fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
                plus_minus = EXCLUDED.plus_minus, created_at = NOW();
            """
            statements.append(sql)
        return '\n'.join(statements)

    elif split_type == 'all_star':
        as_date = ALL_STAR_DATES.get(season)
        if not as_date:
            return None

        return f"""
        INSERT INTO player_season_splits {insert_cols}
        {base_select.format(season=season, category='all_star', split_value='pre_all_star')}
          AND g.game_date < '{as_date}'
        GROUP BY pg.player, pg.team
        ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
            split_category = EXCLUDED.split_category,
            games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
            ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
            tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
            fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
            orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
            fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
            plus_minus = EXCLUDED.plus_minus, created_at = NOW();

        INSERT INTO player_season_splits {insert_cols}
        {base_select.format(season=season, category='all_star', split_value='post_all_star')}
          AND g.game_date >= '{as_date}'
        GROUP BY pg.player, pg.team
        ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
            split_category = EXCLUDED.split_category,
            games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
            ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
            tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
            fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
            orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
            fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
            plus_minus = EXCLUDED.plus_minus, created_at = NOW();
        """

    elif split_type == 'day_of_week':
        # By day of week
        days = [
            (0, 'sunday'), (1, 'monday'), (2, 'tuesday'), (3, 'wednesday'),
            (4, 'thursday'), (5, 'friday'), (6, 'saturday'),
        ]
        statements = []
        for dow_num, dow_name in days:
            sql = f"""
            INSERT INTO player_season_splits {insert_cols}
            {base_select.format(season=season, category='day_of_week', split_value=dow_name)}
              AND EXTRACT(DOW FROM g.game_date) = {dow_num}
            GROUP BY pg.player, pg.team
            ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
                split_category = EXCLUDED.split_category,
                games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
                ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
                tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
                fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
                orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
                fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
                plus_minus = EXCLUDED.plus_minus, created_at = NOW();
            """
            statements.append(sql)
        return '\n'.join(statements)

    elif split_type == 'opponent':
        # By opponent
        return f"""
        INSERT INTO player_season_splits {insert_cols}
        SELECT
            {season}::INTEGER as season,
            pg.player as player_name,
            pg.team as team_abbr,
            'opponent' as split_category,
            'vs_' || opp.abbr as split_type,
            COUNT(*) as games,
            ROUND(AVG(pg.pts)::numeric, 1) as pts,
            ROUND(AVG(pg.trb)::numeric, 1) as reb,
            ROUND(AVG(pg.ast)::numeric, 1) as ast,
            ROUND(AVG(pg.stl)::numeric, 1) as stl,
            ROUND(AVG(pg.blk)::numeric, 1) as blk,
            ROUND(AVG(pg.tov)::numeric, 1) as tov,
            ROUND(AVG(pg.pf)::numeric, 1) as pf,
            SUM(pg.fg) as fg, SUM(pg.fga) as fga,
            SUM(pg.fg3) as fg3, SUM(pg.fga3) as fga3,
            SUM(pg.ft) as ft, SUM(pg.fta) as fta,
            SUM(pg.orb) as orb, SUM(pg.drb) as drb,
            CASE WHEN SUM(pg.fga) > 0 
                THEN ROUND(SUM(pg.fg)::numeric / SUM(pg.fga), 3) ELSE NULL END as fg_pct,
            CASE WHEN SUM(pg.fga3) > 0 
                THEN ROUND(SUM(pg.fg3)::numeric / SUM(pg.fga3), 3) ELSE NULL END as fg3_pct,
            CASE WHEN SUM(pg.fta) > 0 
                THEN ROUND(SUM(pg.ft)::numeric / SUM(pg.fta), 3) ELSE NULL END as ft_pct,
            ROUND(AVG(pg.plus_minus)::numeric, 1) as plus_minus,
            NOW() as created_at
        FROM player_gamelog pg
        JOIN games g ON (
            g.game_id = pg.gameid
            OR g.game_id = '00' || pg.gameid
        )
        CROSS JOIN LATERAL (
            SELECT CASE 
                WHEN pg.team = g.home_team_abbr THEN g.away_team_abbr
                ELSE g.home_team_abbr
            END as abbr
        ) opp
        WHERE pg.season = {season}
          AND g.season = {season}
          AND g.game_date IS NOT NULL
          AND opp.abbr IS NOT NULL
        GROUP BY pg.player, pg.team, opp.abbr
        ON CONFLICT (season, player_name, team_abbr, split_type) DO UPDATE SET
            split_category = EXCLUDED.split_category,
            games = EXCLUDED.games, pts = EXCLUDED.pts, reb = EXCLUDED.reb,
            ast = EXCLUDED.ast, stl = EXCLUDED.stl, blk = EXCLUDED.blk,
            tov = EXCLUDED.tov, pf = EXCLUDED.pf, fg = EXCLUDED.fg, fga = EXCLUDED.fga,
            fg3 = EXCLUDED.fg3, fga3 = EXCLUDED.fga3, ft = EXCLUDED.ft, fta = EXCLUDED.fta,
            orb = EXCLUDED.orb, drb = EXCLUDED.drb, fg_pct = EXCLUDED.fg_pct,
            fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
            plus_minus = EXCLUDED.plus_minus, created_at = NOW();
        """

    return None


def verify(cur, season=None):
    """验证结果"""
    print(f"\n[3/4] 验证数据...")

    if season:
        cur.execute("""
            SELECT split_category, split_type, COUNT(*), 
                   COUNT(DISTINCT player_name), MIN(games), MAX(games)
            FROM player_season_splits 
            WHERE season = %s
            GROUP BY split_category, split_type 
            ORDER BY split_category, split_type
        """, [season])
    else:
        cur.execute("""
            SELECT split_category, split_type, COUNT(*),
                   COUNT(DISTINCT player_name), MIN(games), MAX(games)
            FROM player_season_splits
            GROUP BY split_category, split_type
            ORDER BY split_category, split_type
        """)

    print(f"  {'Category':15s} {'Split Type':15s} {'Rows':>8s} {'Players':>8s} {'Min G':>6s} {'Max G':>6s}")
    print(f"  {'-'*65}")
    for r in cur.fetchall():
        print(f"  {r[0]:15s} {r[1]:15s} {r[2]:>8,} {r[3]:>8,} {r[4]:>6} {r[5]:>6}")

    # Total
    cur.execute("SELECT COUNT(*) FROM player_season_splits")
    total = cur.fetchone()[0]
    print(f"\n  总行数: {total:,}")

    # Sample: LeBron James 2026
    cur.execute("""
        SELECT split_category, split_type, games, pts, reb, ast, fg_pct, fg3_pct, plus_minus
        FROM player_season_splits
        WHERE player_name = 'LeBron James' AND season = 2026
        ORDER BY split_category, split_type
    """)
    rows = cur.fetchall()
    if rows:
        print(f"\n  📝 样本: LeBron James 2026")
        print(f"  {'Category':15s} {'Split':15s} {'G':>4s} {'PTS':>6s} {'REB':>5s} {'AST':>5s} {'FG%':>6s} {'3P%':>6s} {'+/-':>6s}")
        for r in rows:
            print(f"  {r[0]:15s} {r[1]:15s} {r[2]:>4} {r[3]:>6} {r[4]:>5} {r[5]:>5} {r[6]!s:>6} {r[7]!s:>6} {r[8]!s:>6}")


def main():
    parser = argparse.ArgumentParser(description='Compute player season splits from gamelog data')
    parser.add_argument('--season', type=int, nargs='*', help='Season(s) to compute (e.g., --season 2026 2025)')
    parser.add_argument('--all-seasons', action='store_true', help='Compute all available seasons')
    parser.add_argument('--split-types', type=str, default='all',
                        help=f'Comma-separated split types (default: all). Options: {",".join(ALL_SPLIT_TYPES)}')
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Determine seasons
    if args.all_seasons:
        cur.execute("SELECT DISTINCT season FROM player_gamelog ORDER BY season")
        seasons = [r[0] for r in cur.fetchall()]
    elif args.season:
        seasons = args.season
    else:
        # Default: latest 3 seasons
        cur.execute("SELECT DISTINCT season FROM player_gamelog ORDER BY season DESC LIMIT 3")
        seasons = [r[0] for r in cur.fetchall()]

    # Determine split types
    if args.split_types == 'all':
        split_types = ALL_SPLIT_TYPES
    else:
        split_types = args.split_types.split(',')
        for st in split_types:
            if st not in ALL_SPLIT_TYPES:
                print(f"ERROR: Unknown split type '{st}'. Options: {','.join(ALL_SPLIT_TYPES)}")
                sys.exit(1)

    print("=" * 70)
    print(f"  Player Season Splits — 从数据库计算")
    print(f"  赛季: {seasons}")
    print(f"  Split 类型: {split_types}")
    print("=" * 70)

    # Step 1: Alter table
    alter_table(cur)

    # Step 2: Compute splits
    compute_splits(cur, seasons, split_types)

    # Step 3: Verify
    verify(cur, seasons[0] if len(seasons) == 1 else None)

    # Step 4: Create index if not exists
    print(f"\n[4/4] 创建索引...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pss_season_category 
        ON player_season_splits (season, split_category)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pss_player_season 
        ON player_season_splits (player_name, season)
    """)
    print("  ✅ 索引已就绪")

    cur.close()
    conn.close()
    print("\n✅ 全部完成！")


if __name__ == '__main__':
    main()
