#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 game_metadata 表补充 games 表的 game_date 字段
两个表通过 game_id 关联
"""

import psycopg2
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
    """从game_metadata提取并补充game_date"""
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
                  SELECT 1 FROM game_metadata gm 
                  WHERE gm.game_id = g.game_id::text 
                    AND gm.game_date IS NOT NULL
              )
        """)
        need_fill = cur.fetchone()[0]
        logger.info(f"需要补充game_date的比赛数: {need_fill:,}")
        
        if need_fill == 0:
            logger.info("所有比赛都已有game_date，无需补充")
            return
        
        # 2. 从game_metadata补充game_date
        logger.info("开始补充game_date...")
        cur.execute("""
            UPDATE games g
            SET game_date = gm.game_date
            FROM game_metadata gm
            WHERE gm.game_id = g.game_id::text
              AND gm.game_date IS NOT NULL
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
        
        # 5. 检查还有多少缺失
        cur.execute("""
            SELECT COUNT(*) 
            FROM games 
            WHERE game_date IS NULL
        """)
        still_missing = cur.fetchone()[0]
        
        if still_missing > 0:
            logger.warning(f"⚠️  仍有 {still_missing:,} 场比赛缺少game_date")
            logger.warning("这些比赛在game_metadata中也没有记录")
        
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    fill_game_dates()
