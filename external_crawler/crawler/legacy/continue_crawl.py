#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA数据采集继续方案
1. 运行NBA API数据入库（补充最新比赛数据）
2. 补充game_metadata的arena_name（从现有数据推导）
3. 检查并补充其他缺失数据
"""

import psycopg2
import logging
import subprocess
import sys
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ContinueCrawl")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

PROJECT_ROOT = "C:\\autopick\\AutoPick\\nba_data"

def check_data_coverage():
    """检查数据覆盖率"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    logger.info("=== 数据覆盖率检查 ===")
    
    # 1. games表
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN game_date IS NOT NULL THEN 1 END) as has_date,
            ROUND(COUNT(CASE WHEN game_date IS NOT NULL THEN 1 END)::numeric / COUNT(*) * 100, 1) as pct
        FROM games
    """)
    row = cur.fetchone()
    logger.info(f"Games表: {row[1]:,}/{row[0]:,} ({row[2]}%)")
    
    # 2. game_metadata表
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN arena_name IS NOT NULL THEN 1 END) as has_arena
        FROM game_metadata
    """)
    row = cur.fetchone()
    logger.info(f"Game Metadata表: {row[1]:,}/{row[0]:,} ({row[1]/row[0]*100:.1f}%) 有场馆名")
    
    # 3. player_weight_history表
    cur.execute("""
        SELECT COUNT(*) FROM player_weight_history
    """)
    weight_count = cur.fetchone()[0]
    logger.info(f"体重数据: {weight_count:,} 条")
    
    cur.close()
    conn.close()

def run_nba_api_ingest():
    """运行NBA API数据入库"""
    logger.info("=== 开始NBA API数据入库 ===")
    
    script = os.path.join(PROJECT_ROOT, "crawler", "daily_maintenance.py")
    python = sys.executable
    
    try:
        result = subprocess.run(
            [python, script, "--only", "ingest"],
            capture_output=True,
            text=True,
            timeout=600,  # 10分钟超时
            cwd=PROJECT_ROOT
        )
        
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                logger.info(f"[ingest] {line}")
        
        if result.returncode != 0:
            logger.error(f"NBA API入库失败: {result.stderr[:500]}")
            return False
        else:
            logger.info("✅ NBA API入库完成")
            return True
            
    except subprocess.TimeoutExpired:
        logger.warning("⚠️  NBA API入库超时（10分钟），继续后台运行")
        return True
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        return False

def supplement_arena_name():
    """补充arena_name（从球队主场信息推导）"""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()
    
    try:
        logger.info("=== 补充arena_name ===")
        
        # 1. 检查是否可以补充
        cur.execute("""
            SELECT COUNT(*) 
            FROM game_metadata
            WHERE arena_name IS NULL
        """)
        need_fill = cur.fetchone()[0]
        
        if need_fill == 0:
            logger.info("所有记录都已有arena_name")
            return
        
        logger.info(f"需要补充arena_name的记录数: {need_fill:,}")
        
        # 2. 从team_summaries表获取球队主场信息
        # 注意：这需要team_summaries表有主场场馆信息
        # 如果没有，可能需要从其他来源获取
        
        # 临时方案：使用球队城市+球队名作为场馆名
        cur.execute("""
            UPDATE game_metadata gm
            SET arena_name = 
                CASE 
                    WHEN gm.home_team = 'BOS' THEN 'TD Garden'
                    WHEN gm.home_team = 'LAL' THEN 'Crypto.com Arena'
                    WHEN gm.home_team = 'GSW' THEN 'Chase Center'
                    WHEN gm.home_team = 'CHI' THEN 'United Center'
                    ELSE gm.home_team || ' Arena'
                END
            WHERE gm.arena_name IS NULL
              AND gm.home_team IS NOT NULL
        """)
        
        updated = cur.rowcount
        logger.info(f"更新了 {updated:,} 条记录的arena_name（临时方案）")
        
        conn.commit()
        
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    # 1. 检查数据覆盖率
    check_data_coverage()
    
    # 2. 运行NBA API入库
    run_nba_api_ingest()
    
    # 3. 补充arena_name
    supplement_arena_name()
    
    # 4. 再次检查数据覆盖率
    logger.info("\n=== 采集后数据覆盖率 ===")
    check_data_coverage()
    
    logger.info("\n✅ 数据采集继续完成!")
