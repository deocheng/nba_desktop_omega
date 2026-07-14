import os
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))
conn.autocommit = True
cur = conn.cursor()

# Step 1: 创建表
print("📋 Step 1: 创建 player_career_totals 表...")
cur.execute('DROP TABLE IF EXISTS player_career_totals CASCADE')
cur.execute('''
    CREATE TABLE player_career_totals (
        id SERIAL PRIMARY KEY,
        player_name TEXT NOT NULL,
        games INTEGER,
        pts_total INTEGER,
        trb_total INTEGER,
        ast_total INTEGER,
        stl_total INTEGER,
        blk_total INTEGER,
        tov_total INTEGER,
        pf_total INTEGER,
        fg_total INTEGER,
        fga_total INTEGER,
        fg3_total INTEGER,
        fga3_total INTEGER,
        ft_total INTEGER,
        fta_total INTEGER,
        orb_total INTEGER,
        drb_total INTEGER,
        pts_per_game DECIMAL(6,2),
        trb_per_game DECIMAL(6,2),
        ast_per_game DECIMAL(6,2),
        stl_per_game DECIMAL(6,2),
        blk_per_game DECIMAL(6,2),
        fg_pct DECIMAL(5,3),
        fg3_pct DECIMAL(5,3),
        ft_pct DECIMAL(5,3),
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(player_name)
    )
''')
print("✅ player_career_totals 表已创建")

# Step 2: 聚合数据
print("\n📊 Step 2: 聚合球员生涯总计...")
cur.execute('''
    INSERT INTO player_career_totals 
        (player_name, games, pts_total, trb_total, ast_total, stl_total, blk_total,
         tov_total, pf_total, fg_total, fga_total, fg3_total, fga3_total,
         ft_total, fta_total, orb_total, drb_total,
         pts_per_game, trb_per_game, ast_per_game, stl_per_game, blk_per_game,
         fg_pct, fg3_pct, ft_pct)
    SELECT 
        player,
        COUNT(*) as games,
        SUM(pts) as pts_total,
        SUM(trb) as trb_total,
        SUM(ast) as ast_total,
        SUM(stl) as stl_total,
        SUM(blk) as blk_total,
        SUM(tov) as tov_total,
        SUM(pf) as pf_total,
        SUM(fg) as fg_total,
        SUM(fga) as fga_total,
        SUM(fg3) as fg3_total,
        SUM(fga3) as fga3_total,
        SUM(ft) as ft_total,
        SUM(fta) as fta_total,
        SUM(orb) as orb_total,
        SUM(drb) as drb_total,
        ROUND(AVG(pts), 2) as pts_per_game,
        ROUND(AVG(trb), 2) as trb_per_game,
        ROUND(AVG(ast), 2) as ast_per_game,
        ROUND(AVG(stl), 2) as stl_per_game,
        ROUND(AVG(blk), 2) as blk_per_game,
        ROUND(CASE WHEN SUM(fga) > 0 THEN SUM(fg)::decimal / SUM(fga) ELSE NULL END, 3) as fg_pct,
        ROUND(CASE WHEN SUM(fga3) > 0 THEN SUM(fg3)::decimal / SUM(fga3) ELSE NULL END, 3) as fg3_pct,
        ROUND(CASE WHEN SUM(fta) > 0 THEN SUM(ft)::decimal / SUM(fta) ELSE NULL END, 3) as ft_pct
    FROM player_gamelog
    WHERE season BETWEEN 1947 AND 2026
      AND pts IS NOT NULL
    GROUP BY player
    ON CONFLICT (player_name) DO UPDATE SET
        games = EXCLUDED.games,
        pts_total = EXCLUDED.pts_total,
        trb_total = EXCLUDED.trb_total,
        ast_total = EXCLUDED.ast_total,
        stl_total = EXCLUDED.stl_total,
        blk_total = EXCLUDED.blk_total,
        tov_total = EXCLUDED.tov_total,
        pf_total = EXCLUDED.pf_total,
        fg_total = EXCLUDED.fg_total,
        fga_total = EXCLUDED.fga_total,
        fg3_total = EXCLUDED.fg3_total,
        fga3_total = EXCLUDED.fga3_total,
        ft_total = EXCLUDED.ft_total,
        fta_total = EXCLUDED.fta_total,
        orb_total = EXCLUDED.orb_total,
        drb_total = EXCLUDED.drb_total,
        pts_per_game = EXCLUDED.pts_per_game,
        trb_per_game = EXCLUDED.trb_per_game,
        ast_per_game = EXCLUDED.ast_per_game,
        stl_per_game = EXCLUDED.stl_per_game,
        blk_per_game = EXCLUDED.blk_per_game,
        fg_pct = EXCLUDED.fg_pct,
        fg3_pct = EXCLUDED.fg3_pct,
        ft_pct = EXCLUDED.ft_pct,
        created_at = NOW()
''')
print(f"✅ 已聚合 {cur.rowcount:,} 球员的生涯总计")

# Step 3: 验证
print("\n📊 Step 3: 验证结果...")
cur.execute('SELECT COUNT(*), MIN(pts_total), MAX(pts_total) FROM player_career_totals')
r = cur.fetchone()
print(f"📊 player_career_totals 总计: {r[0]:,} 行")
print(f"   最低生涯总得分: {r[1]}")
print(f"   最高生涯总得分: {r[2]:,}")

# 样本（历史得分王）
cur.execute('''
    SELECT player_name, games, pts_total, pts_per_game, fg_pct
    FROM player_career_totals
    ORDER BY pts_total DESC
    LIMIT 5
''')
cols = [d[0] for d in cur.description]
print("\n📝 样本 (生涯总得分 TOP 5):")
for r in cur.fetchall():
    print(dict(zip(cols, r)))

conn.close()
print("\n✅ Phase 1 - Task 3 完成！")
