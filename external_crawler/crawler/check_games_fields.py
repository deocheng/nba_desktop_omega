#!/usr/bin/env python3
"""
检查games表的投篮相关字段
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def check_games_shooting_fields():
    """检查games表的投篮相关字段"""
    conn = psycopg2.connect(
        host='localhost',
        port=5433,
        dbname='nba',
        user='postgres',
        password=os.environ.get('DB_PASSWORD')
    )
    cur = conn.cursor()
    
    print("=== 检查games表的投篮相关字段 ===\n")
    
    # 检查所有包含fg/ft的字段
    cur.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'games' 
          AND (column_name LIKE '%fg%' OR column_name LIKE '%ft%')
        ORDER BY ordinal_position
    """)
    
    print("投篮相关字段:")
    for row in cur.fetchall():
        print(f"   {row[0]:30s} {row[1]}")
    
    # 检查是否有home_fg, home_fga等字段
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns 
        WHERE table_name = 'games' 
          AND column_name IN ('home_fg', 'home_fga', 'away_fg', 'away_fga')
    """)
    
    missing_fields = [row[0] for row in cur.fetchall()]
    if missing_fields:
        print(f"\n缺失字段: {missing_fields}")
        print("需要添加这些字段才能存储FG/FGA数据")
    else:
        print("\n✓ 所有必要的投篮字段都存在")
    
    conn.close()
    print("\n✓ 检查完成")

if __name__ == '__main__':
    check_games_shooting_fields()
