#!/usr/bin/env python3
"""
检查PBP表的结构化字段，评估能否计算投篮命中率
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def check_pbp_structured_fields():
    """检查PBP表的结构化字段"""
    conn = psycopg2.connect(
        host='localhost',
        port=5433,
        dbname='nba',
        user='postgres',
        password=os.environ.get('DB_PASSWORD')
    )
    cur = conn.cursor()
    
    print("=== 检查PBP表结构化字段 ===\n")
    
    # 1. 检查event_type的可能值
    print("1. event_type的可能值:")
    cur.execute("""
        SELECT event_type, COUNT(*) as cnt
        FROM play_by_play
        WHERE event_type IS NOT NULL
        GROUP BY event_type
        ORDER BY 2 DESC
        LIMIT 20
    """)
    for row in cur.fetchall():
        print(f"   {row[0]}: {row[1]:,} 次")
    
    # 2. 检查subtype的可能值
    print("\n2. subtype的可能值（与投篮相关）:")
    cur.execute("""
        SELECT subtype, COUNT(*) as cnt
        FROM play_by_play
        WHERE subtype IS NOT NULL
          AND (subtype LIKE '%shot%' OR subtype LIKE '%jump%' OR subtype LIKE '%layup%' OR subtype LIKE '%dunk%')
        GROUP BY subtype
        ORDER BY 2 DESC
        LIMIT 20
    """)
    for row in cur.fetchall():
        print(f"   {row[0]}: {row[1]:,} 次")
    
    # 3. 检查result的可能值
    print("\n3. result的可能值:")
    cur.execute("""
        SELECT result, COUNT(*) as cnt
        FROM play_by_play
        WHERE result IS NOT NULL
        GROUP BY result
        ORDER BY 2 DESC
        LIMIT 20
    """)
    for row in cur.fetchall():
        print(f"   {row[0]}: {row[1]:,} 次")
    
    # 4. 检查是否有投篮事件（综合判断）
    print("\n4. 投篮事件统计:")
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN event_type = 'shot' THEN 1 ELSE 0 END) as shot_events,
            SUM(CASE WHEN subtype LIKE '%make%' OR result LIKE '%make%' THEN 1 ELSE 0 END) as make_events,
            SUM(CASE WHEN subtype LIKE '%miss%' OR result LIKE '%miss%' THEN 1 ELSE 0 END) as miss_events
        FROM play_by_play
        WHERE event_type IS NOT NULL OR subtype IS NOT NULL
    """)
    row = cur.fetchone()
    if row:
        print(f"   总事件: {row[0]:,}")
        print(f"   event_type='shot': {row[1]:,}")
        print(f"   包含'make': {row[2]:,}")
        print(f"   包含'miss': {row[3]:,}")
    
    conn.close()
    print("\n✓ 检查完成")

if __name__ == '__main__':
    check_pbp_structured_fields()
