#!/usr/bin/env python3
"""
从PBP表重新计算games表的投篮命中率
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def recalculate_fg_from_pbp():
    """从PBP聚合计算games表的投篮命中率字段"""
    conn = psycopg2.connect(
        host='localhost',
        port=5433,
        dbname='nba',
        user='postgres',
        password=os.environ.get('DB_PASSWORD')
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    print("=== 从PBP重新计算games表投篮命中率 ===\n")
    
    # 1. 创建临时表存储PBP聚合结果
    print("1. 创建临时表存储PBP聚合结果...")
    cur.execute("""
        DROP TABLE IF EXISTS tmp_pbp_shooting;
        CREATE TEMP TABLE tmp_pbp_shooting (
            gameid VARCHAR,
            team CHAR(3),
            fgm INTEGER,
            fga INTEGER,
            fg3m INTEGER,
            fga3 INTEGER,
            ftm INTEGER,
            fta INTEGER
        )
    """)
    
    # 2. 聚合PBP数据（按gameid和team）
    print("2. 聚合PBP数据...")
    cur.execute("""
        INSERT INTO tmp_pbp_shooting (gameid, team, fgm, fga, fg3m, fga3, ftm, fta)
        SELECT 
            gameid,
            team,
            SUM(CASE WHEN event_type = 'Made Shot' AND subtype NOT LIKE '%3PT%' THEN 1 ELSE 0 END) as fgm,
            SUM(CASE WHEN event_type IN ('Made Shot', 'Missed Shot') AND subtype NOT LIKE '%3PT%' THEN 1 ELSE 0 END) as fga,
            SUM(CASE WHEN event_type = 'Made Shot' AND subtype LIKE '%3PT%' THEN 1 ELSE 0 END) as fg3m,
            SUM(CASE WHEN event_type IN ('Made Shot', 'Missed Shot') AND subtype LIKE '%3PT%' THEN 1 ELSE 0 END) as fga3,
            SUM(CASE WHEN event_type = 'Free Throw' AND result = 'Made' THEN 1 ELSE 0 END) as ftm,
            SUM(CASE WHEN event_type = 'Free Throw' THEN 1 ELSE 0 END) as fta
        FROM play_by_play
        WHERE season BETWEEN 2001 AND 2026
          AND team IS NOT NULL
          AND event_type IN ('Made Shot', 'Missed Shot', 'Free Throw')
        GROUP BY gameid, team
    """)
    print(f"   插入了 {cur.rowcount:,} 行（gameid-team组合）")
    
    # 3. 更新games表（主场投篮数据）
    print("\n3. 更新games表（主场投篮数据）...")
    cur.execute("""
        UPDATE games g
        SET 
            home_fgm = p.fgm,
            home_fga = p.fga,
            home_fg_pct = CASE WHEN p.fga > 0 THEN ROUND(p.fgm::NUMERIC / p.fga, 3) ELSE NULL END,
            home_fg3m = p.fg3m,
            home_fga3 = p.fga3,
            home_fg3_pct = CASE WHEN p.fga3 > 0 THEN ROUND(p.fg3m::NUMERIC / p.fga3, 3) ELSE NULL END,
            home_ftm = p.ftm,
            home_fta = p.fta,
            home_ft_pct = CASE WHEN p.fta > 0 THEN ROUND(p.ftm::NUMERIC / p.fta, 3) ELSE NULL END
        FROM (
            SELECT 
                gameid,
                team,
                MAX(fgm) as fgm,
                MAX(fga) as fga,
                MAX(fg3m) as fg3m,
                MAX(fga3) as fga3,
                MAX(ftm) as ftm,
                MAX(fta) as fta
            FROM tmp_pbp_shooting t
            JOIN games g ON g.game_id::TEXT = t.gameid
            WHERE t.team = g.home_team_abbr
            GROUP BY gameid, team
        ) p
        WHERE g.game_id::TEXT = p.gameid
    """)
    print(f"   更新了 {cur.rowcount:,} 行（主场数据）")
    
    # 4. 更新games表（客场投篮数据）
    print("\n4. 更新games表（客场投篮数据）...")
    cur.execute("""
        UPDATE games g
        SET 
            away_fgm = p.fgm,
            away_fga = p.fga,
            away_fg_pct = CASE WHEN p.fga > 0 THEN ROUND(p.fgm::NUMERIC / p.fga, 3) ELSE NULL END,
            away_fg3m = p.fg3m,
            away_fga3 = p.fga3,
            away_fg3_pct = CASE WHEN p.fga3 > 0 THEN ROUND(p.fg3m::NUMERIC / p.fga3, 3) ELSE NULL END,
            away_ftm = p.ftm,
            away_fta = p.fta,
            away_ft_pct = CASE WHEN p.fta > 0 THEN ROUND(p.ftm::NUMERIC / p.fta, 3) ELSE NULL END
        FROM (
            SELECT 
                gameid,
                team,
                MAX(fgm) as fgm,
                MAX(fga) as fga,
                MAX(fg3m) as fg3m,
                MAX(fga3) as fga3,
                MAX(ftm) as ftm,
                MAX(fta) as fta
            FROM tmp_pbp_shooting t
            JOIN games g ON g.game_id::TEXT = t.gameid
            WHERE t.team = g.away_team_abbr
            GROUP BY gameid, team
        ) p
        WHERE g.game_id::TEXT = p.gameid
    """)
    print(f"   更新了 {cur.rowcount:,} 行（客场数据）")
    
    # 5. 检查更新结果
    print("\n5. 检查更新结果:")
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN home_fg_pct IS NOT NULL THEN 1 ELSE 0 END) as has_home_fg_pct,
            SUM(CASE WHEN away_fg_pct IS NOT NULL THEN 1 ELSE 0 END) as has_away_fg_pct
        FROM games
        WHERE home_pts IS NOT NULL
    """)
    row = cur.fetchone()
    print(f"   有比分数据的比赛: {row[0]:,}")
    print(f"   home_fg_pct填充: {row[1]:,} ({row[1]*100/row[0]:.1f}%)")
    print(f"   away_fg_pct填充: {row[2]:,} ({row[2]*100/row[0]:.1f}%)")
    
    # 6. 清理临时表
    print("\n6. 清理临时表...")
    cur.execute("DROP TABLE IF EXISTS tmp_pbp_shooting")
    print("   ✓ 临时表已删除")
    
    conn.close()
    print("\n✓ games表投篮命中率重新计算完成")

if __name__ == '__main__':
    recalculate_fg_from_pbp()
