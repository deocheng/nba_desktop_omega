#!/usr/bin/env python3
"""
修正games表的game_date缺失值
从8位格式的game_id推导game_date（格式：2YYMMDDxx或4YYMMDDxx）
"""

import psycopg2
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

def fix_games_game_date():
    """从game_id推导game_date"""
    conn = psycopg2.connect(
        host='localhost',
        port=5433,
        dbname='nba',
        user='postgres',
        password=os.environ.get('DB_PASSWORD')
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    print("=== 修正games表的game_date缺失值 ===\n")
    
    # 1. 统计缺失情况
    cur.execute("SELECT COUNT(*) FROM games WHERE game_date IS NULL")
    missing_before = cur.fetchone()[0]
    print(f"1. 缺失game_date的记录数: {missing_before:,}")
    
    # 2. 从8位game_id推导game_date（格式：2YYMMDDxx）
    print("\n2. 从8位game_id推导game_date...")
    cur.execute("""
        UPDATE games
        SET game_date = TO_DATE(SUBSTRING(game_id FROM 1 FOR 8), 'YYMMDD')
        WHERE game_date IS NULL 
          AND LENGTH(game_id) = 8 
          AND game_id ~ '^[0-9]+$'
          AND (game_id LIKE '2%' OR game_id LIKE '4%')
    """)
    fixed_8digit = cur.rowcount
    print(f"   修正了 {fixed_8digit:,} 行（8位格式）")
    
    # 3. 处理年份转换（YY>=50则为19YY，否则为20YY）
    print("\n3. 修正年份（YY>=50 → 19YY，否则 → 20YY）...")
    cur.execute("""
        UPDATE games
        SET game_date = 
            CASE 
                WHEN EXTRACT(YEAR FROM game_date) < 1950 
                THEN game_date + INTERVAL '100 years'
                ELSE game_date
            END
        WHERE game_date IS NOT NULL
          AND EXTRACT(YEAR FROM game_date) < 1950
    """)
    print(f"   修正了 {cur.rowcount:,} 行的年份")
    
    # 4. 统计修正后情况
    cur.execute("SELECT COUNT(*) FROM games WHERE game_date IS NULL")
    missing_after = cur.fetchone()[0]
    print(f"\n4. 修正后缺失game_date的记录数: {missing_after:,}")
    print(f"   共修正: {missing_before - missing_after:,} 行")
    
    # 5. 检查是否还有10位格式的game_id缺失game_date
    cur.execute("""
        SELECT COUNT(*) 
        FROM games 
        WHERE game_date IS NULL 
          AND LENGTH(game_id) = 10
    """)
    missing_10digit = cur.fetchone()[0]
    print(f"\n5. 10位格式game_id缺失game_date: {missing_10digit:,} 行")
    
    if missing_10digit > 0:
        print("   提示：10位格式game_id可能需要从play_by_play或game_metadata表推导")
    
    # 6. 验证修正结果（抽样检查）
    print("\n6. 验证修正结果（抽样10条）:")
    cur.execute("""
        SELECT game_id, game_date 
        FROM games 
        WHERE game_date IS NOT NULL 
        ORDER BY game_date DESC 
        LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"   {row[0]} → {row[1]}")
    
    conn.close()
    print("\n✓ game_date修正完成")

if __name__ == '__main__':
    fix_games_game_date()
