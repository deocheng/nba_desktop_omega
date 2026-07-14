#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 boxscore_url 提取 game_date
适用于从 Basketball-Reference 爬取的数据
boxscore_url 格式: https://www.basketball-reference.com/boxscores/202510210OKC.html
"""

import psycopg2
import re
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ExtractDateFromURL")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

def extract_date_from_url():
    """从boxscore_url提取game_date"""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()
    
    try:
        # 1. 检查是否有boxscore_url字段
        cur.execute("""
            SELECT COUNT(*) 
            FROM information_schema.columns 
            WHERE table_name = 'games' 
              AND column_name = 'boxscore_url'
        """)
        
        has_url_field = cur.fetchone()[0] > 0
        
        if not has_url_field:
            logger.warning("games表没有boxscore_url字段，无法从URL提取日期")
            return
        
        # 2. 检查需要补充的记录数
        cur.execute("""
            SELECT COUNT(*) 
            FROM games
            WHERE game_date IS NULL
              AND boxscore_url IS NOT NULL
              AND boxscore_url ~ 'boxscores/[0-9]{8}'
        """)
        need_fill = cur.fetchone()[0]
        logger.info(f"可以从URL提取日期的比赛数: {need_fill:,}")
        
        if need_fill == 0:
            logger.info("没有可以从URL提取日期的比赛")
            return
        
        # 3. 从URL提取日期并更新
        logger.info("开始从URL提取日期...")
        
        # 先查询需要更新的数据
        cur.execute("""
            SELECT id, game_id, boxscore_url
            FROM games
            WHERE game_date IS NULL
              AND boxscore_url IS NOT NULL
              AND boxscore_url ~ 'boxscores/[0-9]{8}'
            LIMIT 10000
        """)
        
        rows = cur.fetchall()
        logger.info(f"找到 {len(rows):,} 条待更新记录")
        
        # 提取日期并更新
        update_count = 0
        for row in rows:
            record_id, game_id, url = row
            
            # 从URL提取日期: https://.../boxscores/202510210OKC.html
            match = re.search(r'/boxscores/([0-9]{8})', url)
            if match:
                date_str = match.group(1)  # 20251021
                try:
                    # 转换为日期类型
                    year = int(date_str[:4])
                    month = int(date_str[4:6])
                    day = int(date_str[6:8])
                    game_date = f"{year:04d}-{month:02d}-{day:02d}"
                    
                    # 更新数据库
                    cur.execute("""
                        UPDATE games
                        SET game_date = %s
                        WHERE id = %s
                    """, (game_date, record_id))
                    
                    update_count += 1
                except Exception as e:
                    logger.warning(f"无法解析日期 {date_str}: {e}")
        
        conn.commit()
        logger.info(f"✅ 成功更新 {update_count:,} 条记录的game_date")
        
        # 4. 再次检查覆盖率
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN game_date IS NOT NULL THEN 1 END) as has_date,
                ROUND(COUNT(CASE WHEN game_date IS NOT NULL THEN 1 END)::numeric / COUNT(*) * 100, 1) as pct
            FROM games
        """)
        row = cur.fetchone()
        logger.info(f"总体覆盖率: {row[1]:,}/{row[0]:,} ({row[2]}%)")
        
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    extract_date_from_url()
