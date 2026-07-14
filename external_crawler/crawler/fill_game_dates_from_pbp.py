#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 play_by_play 表补充 games 表的 game_date 字段
PBP数据中包含时间戳，可以提取比赛日期
"""

import psycopg2
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FillGameDate")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

def fill_game_dates():
    """从PBP数据提取并补充game_date"""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()
    
    try:
        # 1. 检查需要补充的记录数
        cur.execute("""
            SELECT COUNT(*) 
            FROM games g
            WHERE g.game_date IS NULL
              AND EXISTS (
                  SELECT 1 FROM play_by_play pbp 
                  WHERE pbp.gameid = g.game_id::text 
                     OR pbp.gameid = g.game_id::text || '.0'
              )
        """)
        need_fill = cur.fetchone()[0]
        logger.info(f"需要补充game_date的比赛数: {need_fill:,}")
        
        if need_fill == 0:
            logger.info("所有比赛都已有game_date，无需补充")
            return
        
        # 2. 从PBP提取game_date（使用最小时间戳作为比赛日期）
        logger.info("开始补充game_date...")
        cur.execute("""
            UPDATE games g
            SET game_date = sub.min_date::date
            FROM (
                SELECT 
                    gameid as pbp_game_id,
                    MIN(datetime) as min_date
                FROM play_by_play
                WHERE datetime IS NOT NULL
                GROUP BY gameid
            ) sub
            WHERE (g.game_id::text = sub.pbp_game_id 
                   OR g.game_id::text || '.0' = sub.pbp_game_id)
              AND g.game_date IS NULL
        """)
        
        updated = cur.rowcount
        logger.info(f"更新了 {updated:,} 条记录的game_date")
        
        # 3. 再次检查覆盖率
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN game_date IS NOT NULL THEN 1 END) as has_date,
                ROUND(COUNT(CASE WHEN game_date IS NOT NULL THEN 1 END)::numeric / COUNT(*) * 100, 1) as pct
            FROM games
            WHERE season BETWEEN 2015 AND 2026
        """)
        row = cur.fetchone()
        logger.info(f"2015-2026赛季总体覆盖率: {row[1]:,}/{row[0]:,} ({row[2]}%)")
        
        # 4. 按赛季检查
        cur.execute("""
            SELECT season,
                   COUNT(*) as total,
                   COUNT(CASE WHEN game_date IS NOT NULL THEN 1 END) as has_date,
                   ROUND(COUNT(CASE WHEN game_date IS NOT NULL THEN 1 END)::numeric / COUNT(*) * 100, 1) as pct
            FROM games
            WHERE season BETWEEN 2015 AND 2026
            GROUP BY season
            ORDER BY season DESC
        """)
        logger.info("各赛季覆盖率:")
        for row in cur.fetchall():
            logger.info(f"  Season {row[0]}: {row[2]:,}/{row[1]:,} ({row[3]}%)")
        
        conn.commit()
        logger.info("✅ game_date补充完成!")
        
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    fill_game_dates()
