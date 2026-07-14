#!/usr/bin/env python3
"""
检查PBP表事件格式，评估能否计算投篮命中率
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def check_pbp_events():
    """检查PBP表事件格式"""
    conn = psycopg2.connect(
        host='localhost',
        port=5433,
        dbname='nba',
        user='postgres',
        password=os.environ.get('DB_PASSWORD')
    )
    cur = conn.cursor()
    
    print("=== 检查PBP表事件格式 ===\n")
    
    # 1. 检查play_by_play表的字段
    print("1. play_by_play表字段（样本）:")
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'play_by_play' 
        ORDER BY ordinal_position
        LIMIT 20
    """)
    for row in cur.fetchall():
        print(f"   {row[0]}")
    
    # 2. 检查事件描述格式
    print("\n2. 事件描述样本:")
    cur.execute("""
        SELECT description 
        FROM play_by_play 
        WHERE description IS NOT NULL 
        LIMIT 20
    """)
    for i, row in enumerate(cur.fetchall()):
        print(f"   {i+1}. {row[0]}")
    
    # 3. 检查是否有投篮相关事件
    print("\n3. 投篮相关事件统计（前100个事件）:")
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN description LIKE '%shot%' THEN 1 ELSE 0 END) as shot_events,
            SUM(CASE WHEN description LIKE '%miss%' THEN 1 ELSE 0 END) as miss_events,
            SUM(CASE WHEN description LIKE '%makes%' THEN 1 ELSE 0 END) as make_events
        FROM (
            SELECT description 
            FROM play_by_play 
            WHERE description IS NOT NULL 
            LIMIT 100
        ) t
    """)
    row = cur.fetchone()
    if row:
        print(f"   总事件: {row[0]:,}")
        print(f"   包含\"shot\"的事件: {row[1]:,}")
        print(f"   包含\"miss\"的事件: {row[2]:,}")
        print(f"   包含\"makes\"的事件: {row[3]:,}")
    
    # 4. 检查是否有结构化的投篮字段
    print("\n4. 检查是否有结构化的投篮字段:")
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'play_by_play' 
          AND (column_name LIKE '%shot%' OR column_name LIKE '%fg%' OR column_name LIKE '%make%')
        ORDER BY ordinal_position
    """)
    shot_fields = [row[0] for row in cur.fetchall()]
    if shot_fields:
        print(f"   发现投篮相关字段: {shot_fields}")
    else:
        print("   未发现结构化的投篮字段")
        print("   结论: 需要从事件描述中解析投篮事件")
    
    conn.close()
    print("\n✓ 检查完成")

if __name__ == '__main__':
    check_pbp_events()
