#!/usr/bin/env python3
"""修正 player_gamelog 表的异常 season 值"""
import psycopg2

DB_CONFIG = {
    'host': 'localhost',
    'port': 5433,
    'dbname': 'nba',
    'user': 'postgres',
    'password': 'postgres'
}

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # 1. 检查异常 season 数量
    cur.execute('''
        SELECT COUNT(*) 
        FROM player_gamelog 
        WHERE season < 1947 OR season > 2026
    ''')
    abnormal_count = cur.fetchone()[0]
    print(f'异常 season 记录数: {abnormal_count:,}')
    
    if abnormal_count == 0:
        print('无需修正！')
        return
    
    # 2. 尝试通过 JOIN games 表修正
    print('\\n尝试通过 JOIN games 表修正...')
    cur.execute('''
        UPDATE player_gamelog pg
        SET season = g.season
        FROM games g
        WHERE pg.gameid::text = g.game_id::text
          AND (pg.season < 1947 OR pg.season > 2026)
    ''')
    join_fixed = cur.rowcount
    conn.commit()
    print(f'  通过 JOIN 修正: {join_fixed:,} 行')
    
    # 3. 剩余异常：尝试从 gameid 推导 season 
    cur.execute('''
        SELECT COUNT(*) 
        FROM player_gamelog 
        WHERE season < 1947 OR season > 2026
    ''')
    remaining = cur.fetchone()[0]
    print(f'\\nJOIN 修正后剩余异常: {remaining:,} 行')
    
    if remaining > 0:
        print('\\n尝试从 gameid 推导 season...')
        # 查看剩余异常的 gameid 格式
        cur.execute('''
            SELECT DISTINCT LEFT(gameid::text, 1) as first_char, 
                   COUNT(*) as cnt
            FROM player_gamelog
            WHERE season < 1947 OR season > 2026
            GROUP BY first_char
        ''')
        print('  剩余 gameid 格式:')
        for r in cur.fetchall():
            print(f'    {r[0]}: {r[1]:,} 行')
        
        # 从 gameid 推导 season (8位格式)
        cur.execute('''
            UPDATE player_gamelog
            SET season = (
                CASE 
                    WHEN SUBSTRING(gameid::text FROM 2 FOR 2)::int >= 50 
                    THEN 1900 + SUBSTRING(gameid::text FROM 2 FOR 2)::int + 1
                    ELSE 2000 + SUBSTRING(gameid::text FROM 2 FOR 2)::int + 1
                END
            )
            WHERE (season < 1947 OR season > 2026)
              AND LENGTH(gameid::text) = 8
              AND (gameid::text LIKE '2%' OR gameid::text LIKE '4%')
        ''')
        derive_fixed = cur.rowcount
        conn.commit()
        print(f'  从 gameid 推导修正 (8位): {derive_fixed:,} 行')
    
    # 4. 最终验证
    cur.execute('''
        SELECT COUNT(*) 
        FROM player_gamelog 
        WHERE season < 1947 OR season > 2026
    ''')
    final_remaining = cur.fetchone()[0]
    print(f'\\n最终剩余异常: {final_remaining:,} 行')
    
    if final_remaining > 0:
        cur.execute('''
            SELECT season, COUNT(*) 
            FROM player_gamelog 
            WHERE season < 1947 OR season > 2026
            GROUP BY season
        ''')
        print('  异常 season 分布:')
        for r in cur.fetchall():
            print(f'    season={r[0]}: {r[1]:,} 行')
    
    # 5. 显示修正后的 season 范围
    cur.execute('SELECT MIN(season), MAX(season), COUNT(DISTINCT season) FROM player_gamelog')
    r = cur.fetchone()
    print(f'\\n修正后 season 范围: {r[0]}-{r[1]} ({r[2]} 季)')
    
    conn.close()
    print('\\n修正完成！')

if __name__ == '__main__':
    main()
