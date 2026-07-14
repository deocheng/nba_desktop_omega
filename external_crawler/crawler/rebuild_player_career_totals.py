#!/usr/bin/env python3
"""
重新聚合player_career_totals（修正字段名）
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def rebuild_player_career_totals():
    """重新聚合所有球员的生涯总计"""
    conn = psycopg2.connect(
        host='localhost',
        port=5433,
        dbname='nba',
        user='postgres',
        password=os.environ.get('DB_PASSWORD')
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    print("=== 重新聚合player_career_totals ===\n")
    
    # 1. 检查当前状态
    print("1. 当前状态:")
    cur.execute("SELECT COUNT(*) FROM player_career_totals")
    before = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(DISTINCT player) FROM player_gamelog")
    total_players = cur.fetchone()[0]
    
    print(f"   当前记录数: {before:,}")
    print(f"   gamelog中球员数: {total_players:,}")
    
    # 2. 清空并重新插入
    print("\n2. 清空并重新聚合...")
    cur.execute("TRUNCATE player_career_totals RESTART IDENTITY")
    
    cur.execute("""
        INSERT INTO player_career_totals (
            player_name, games, pts_total, trb_total, ast_total,
            stl_total, blk_total, tov_total, pf_total,
            fg_total, fga_total, fg3_total, fga3_total,
            ft_total, fta_total, orb_total, drb_total
        )
        SELECT 
            player,
            COUNT(DISTINCT gameid)::INTEGER as games,
            SUM(pts)::INTEGER as pts_total,
            SUM(trb)::INTEGER as trb_total,
            SUM(ast)::INTEGER as ast_total,
            SUM(stl)::INTEGER as stl_total,
            SUM(blk)::INTEGER as blk_total,
            SUM(tov)::INTEGER as tov_total,
            SUM(pf)::INTEGER as pf_total,
            SUM(fg)::INTEGER as fg_total,
            SUM(fga)::INTEGER as fga_total,
            SUM(fg3)::INTEGER as fg3_total,
            SUM(fga3)::INTEGER as fga3_total,
            SUM(ft)::INTEGER as ft_total,
            SUM(fta)::INTEGER as fta_total,
            SUM(orb)::INTEGER as orb_total,
            SUM(drb)::INTEGER as drb_total
        FROM player_gamelog
        WHERE season BETWEEN 1947 AND 2026
          AND player IS NOT NULL
        GROUP BY player
    """)
    print(f"   插入了 {cur.rowcount:,} 名球员")
    
    # 3. 更新百分比和场均字段
    print("\n3. 更新百分比和场均字段...")
    cur.execute("""
        UPDATE player_career_totals
        SET 
            pts_per_game = CASE WHEN games > 0 THEN ROUND(pts_total::NUMERIC / games, 2) ELSE NULL END,
            trb_per_game = CASE WHEN games > 0 THEN ROUND(trb_total::NUMERIC / games, 2) ELSE NULL END,
            ast_per_game = CASE WHEN games > 0 THEN ROUND(ast_total::NUMERIC / games, 2) ELSE NULL END,
            stl_per_game = CASE WHEN games > 0 THEN ROUND(stl_total::NUMERIC / games, 2) ELSE NULL END,
            blk_per_game = CASE WHEN games > 0 THEN ROUND(blk_total::NUMERIC / games, 2) ELSE NULL END,
            fg_pct = CASE WHEN fga_total > 0 THEN ROUND(fg_total::NUMERIC / fga_total, 3) ELSE NULL END,
            fg3_pct = CASE WHEN fga3_total > 0 THEN ROUND(fg3_total::NUMERIC / fga3_total, 3) ELSE NULL END,
            ft_pct = CASE WHEN fta_total > 0 THEN ROUND(ft_total::NUMERIC / fta_total, 3) ELSE NULL END
    """)
    print(f"   更新了 {cur.rowcount:,} 行")
    
    # 4. 验证结果
    print("\n4. 验证结果:")
    cur.execute("SELECT COUNT(*) FROM player_career_totals")
    after = cur.fetchone()[0]
    print(f"   重新聚合后记录数: {after:,}")
    print(f"   修正了 {after - before:,} 名缺失球员")
    
    # 5. 检查是否有异常值
    print("\n5. 检查异常值:")
    cur.execute("""
        SELECT player_name, games, pts_per_game
        FROM player_career_totals
        WHERE games > 0 AND pts_per_game > 50
        LIMIT 10
    """)
    anomalies = cur.fetchall()
    if anomalies:
        print(f"   发现 {len(anomalies)} 个异常值（场均得分>50）:")
        for row in anomalies:
            print(f"     - {row[0]}: {row[1]} 场比赛, 场均{row[2]}分")
    else:
        print("   ✓ 无异常值")
    
    conn.close()
    print("\n✓ player_career_totals重新聚合完成")

if __name__ == '__main__':
    rebuild_player_career_totals()
