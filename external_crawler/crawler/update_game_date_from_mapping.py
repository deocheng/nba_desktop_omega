#!/usr/bin/env python3
"""
从game_id_mapping推导game_date并更新games表
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def update_game_date_from_mapping():
    """从game_id_mapping的crawled_id推导game_date"""
    conn = psycopg2.connect(
        host='localhost',
        port=5433,
        dbname='nba',
        user='postgres',
        password=os.environ.get('DB_PASSWORD')
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    print("=== 从game_id_mapping推导game_date ===\n")
    
    # 1. 添加game_date字段到game_id_mapping
    print("1. 添加game_date字段到game_id_mapping...")
    try:
        cur.execute("""
            ALTER TABLE game_id_mapping 
            ADD COLUMN IF NOT EXISTS game_date date
        """)
        print("   ✓ 字段已添加（或已存在）")
    except Exception as e:
        conn.rollback()
        print(f"   警告: {e}")
    
    # 2. 从crawled_id推导game_date
    print("\n2. 从crawled_id推导game_date...")
    cur.execute("""
        UPDATE game_id_mapping
        SET game_date = TO_DATE(SUBSTRING(crawled_id FROM 1 FOR 8), 'YYYYMMDD')
        WHERE crawled_id ~ '^[0-9]{8}0[A-Z]{2,3}$'
          AND game_date IS NULL
    """)
    print(f"   更新了 {cur.rowcount:,} 行")
    
    # 3. 从game_id_mapping更新games的game_date
    print("\n3. 从game_id_mapping更新games的game_date...")
    cur.execute("""
        UPDATE games g
        SET game_date = m.game_date
        FROM game_id_mapping m
        WHERE g.game_id::bigint = m.nba_id
          AND g.game_date IS NULL
          AND m.game_date IS NOT NULL
    """)
    print(f"   更新了 {cur.rowcount:,} 行")
    
    # 4. 检查更新后缺失情况
    print("\n4. 检查更新后缺失情况:")
    cur.execute("SELECT COUNT(*) FROM games WHERE game_date IS NULL")
    missing = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM games")
    total = cur.fetchone()[0]
    print(f"   总记录: {total:,}")
    print(f"   缺失game_date: {missing:,} ({missing*100/total:.1f}%)")
    
    # 5. 检查哪些记录的game_date仍然缺失
    print("\n5. 缺失game_date的记录样本:")
    cur.execute("""
        SELECT game_id, season
        FROM games
        WHERE game_date IS NULL
        LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"   game_id={row[0]}, season={row[1]}")
    
    conn.close()
    print("\n✓ 完成")

if __name__ == '__main__':
    update_game_date_from_mapping()
