#!/usr/bin/env python3
"""
重新聚合team_game_splits表（减少NULL值）
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def rebuild_team_game_splits():
    """重新聚合球队主客场拆分数据"""
    conn = psycopg2.connect(
        host='localhost',
        port=5433,
        dbname='nba',
        user='postgres',
        password=os.environ.get('DB_PASSWORD')
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    print("=== 重新聚合team_game_splits表 ===\n")
    
    # 1. 检查当前状态
    print("1. 当前状态:")
    cur.execute("SELECT COUNT(*) FROM team_game_splits")
    before = cur.fetchone()[0]
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN fg_pct IS NULL THEN 1 ELSE 0 END) as null_fg_pct
        FROM team_game_splits
    """)
    row = cur.fetchone()
    print(f"   当前记录数: {before:,}")
    print(f"   NULL值: {row[1]:,} / {row[0]:,} ({row[1]*100/row[0]:.1f}%)")
    
    # 2. 清空并重新插入
    print("\n2. 清空并重新聚合...")
    cur.execute("TRUNCATE team_game_splits RESTART IDENTITY")
    
    cur.execute("""
        INSERT INTO team_game_splits (season, team_abbr, split_type, games, pts, fg, fga, fg_pct, fg3, fga3, fg3_pct, ft, fta, ft_pct)
        SELECT 
            CASE 
                WHEN home_team_abbr IS NOT NULL THEN season
                ELSE NULL
            END as season,
            COALESCE(home_team_abbr, away_team_abbr) as team_abbr,
            CASE 
                WHEN home_team_abbr IS NOT NULL THEN 'home'
                ELSE 'away'
            END as split_type,
            COUNT(*) as games,
            ROUND(AVG(CASE WHEN home_team_abbr IS NOT NULL THEN home_pts ELSE away_pts END), 2) as pts,
            SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fgm ELSE away_fgm END) as fg,
            SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fga ELSE away_fga END) as fga,
            CASE 
                WHEN SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fga ELSE away_fga END) > 0 
                THEN ROUND(SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fgm ELSE away_fgm END)::NUMERIC / SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fga ELSE away_fga END), 3)
                ELSE NULL 
            END as fg_pct,
            SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fg3m ELSE away_fg3m END) as fg3,
            SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fga3 ELSE away_fga3 END) as fga3,
            CASE 
                WHEN SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fga3 ELSE away_fga3 END) > 0 
                THEN ROUND(SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fg3m ELSE away_fg3m END)::NUMERIC / SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fga3 ELSE away_fga3 END), 3)
                ELSE NULL 
            END as fg3_pct,
            SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_ftm ELSE away_ftm END) as ft,
            SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fta ELSE away_fta END) as fta,
            CASE 
                WHEN SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fta ELSE away_fta END) > 0 
                THEN ROUND(SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_ftm ELSE away_ftm END)::NUMERIC / SUM(CASE WHEN home_team_abbr IS NOT NULL THEN home_fta ELSE away_fta END), 3)
                ELSE NULL 
            END as ft_pct
        FROM games
        WHERE season BETWEEN 1947 AND 2026
          AND (home_team_abbr IS NOT NULL OR away_team_abbr IS NOT NULL)
          AND (home_pts IS NOT NULL OR away_pts IS NOT NULL)
        GROUP BY 
            CASE WHEN home_team_abbr IS NOT NULL THEN season ELSE NULL END,
            COALESCE(home_team_abbr, away_team_abbr),
            CASE WHEN home_team_abbr IS NOT NULL THEN 'home' ELSE 'away' END
    """)
    print(f"   插入了 {cur.rowcount:,} 行")
    
    # 3. 验证结果
    print("\n3. 验证结果:")
    cur.execute("SELECT COUNT(*) FROM team_game_splits")
    after = cur.fetchone()[0]
    print(f"   重新聚合后记录数: {after:,}")
    
    # 4. 检查NULL值
    print("\n4. 检查NULL值:")
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN fg_pct IS NULL THEN 1 ELSE 0 END) as null_fg_pct,
            SUM(CASE WHEN fg3_pct IS NULL THEN 1 ELSE 0 END) as null_fg3_pct,
            SUM(CASE WHEN ft_pct IS NULL THEN 1 ELSE 0 END) as null_ft_pct
        FROM team_game_splits
    """)
    row = cur.fetchone()
    print(f"   总行数: {row[0]:,}")
    print(f"   fg_pct为NULL: {row[1]:,} ({row[1]*100/row[0]:.1f}%)")
    print(f"   fg3_pct为NULL: {row[2]:,} ({row[2]*100/row[0]:.1f}%)")
    print(f"   ft_pct为NULL: {row[3]:,} ({row[3]*100/row[0]:.1f}%)")
    
    conn.close()
    print("\n✓ team_game_splits重新聚合完成")

if __name__ == '__main__':
    rebuild_team_game_splits()
