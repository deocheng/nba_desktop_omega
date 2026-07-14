import os
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))
conn.autocommit = True  # 自动提交
cur = conn.cursor()

# Step 1: 创建表
print("📋 Step 1: 创建 team_game_splits 表...")
cur.execute('DROP TABLE IF EXISTS team_game_splits CASCADE')
cur.execute('''
    CREATE TABLE team_game_splits (
        id SERIAL PRIMARY KEY,
        season INTEGER NOT NULL,
        team_abbr TEXT NOT NULL,
        split_type TEXT NOT NULL,
        games INTEGER,
        pts DECIMAL(6,2),
        fg_pct DECIMAL(5,3),
        fg3_pct DECIMAL(5,3),
        ft_pct DECIMAL(5,3),
        reb INTEGER,
        ast INTEGER,
        stl INTEGER,
        blk INTEGER,
        tov INTEGER,
        pf INTEGER,
        plus_minus DECIMAL(7,2),
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(season, team_abbr, split_type)
    )
''')
print("✅ team_game_splits 表已创建")

# Step 2: 填充主场数据
print("\n📊 Step 2: 填充主场数据...")
cur.execute('''
    INSERT INTO team_game_splits 
        (season, team_abbr, split_type, games, pts, fg_pct, fg3_pct, ft_pct, 
         reb, ast, stl, blk, tov, pf, plus_minus)
    SELECT 
        g.season,
        g.home_team_abbr as team_abbr,
        'home' as split_type,
        COUNT(*) as games,
        ROUND(AVG(g.home_pts), 2) as pts,
        ROUND(AVG(g.home_fg_pct)::numeric, 3) as fg_pct,
        ROUND(AVG(g.home_fg3_pct)::numeric, 3) as fg3_pct,
        ROUND(AVG(g.home_ft_pct)::numeric, 3) as ft_pct,
        ROUND(AVG(g.home_reb), 1) as reb,
        ROUND(AVG(g.home_ast), 1) as ast,
        ROUND(AVG(g.home_stl), 1) as stl,
        ROUND(AVG(g.home_blk), 1) as blk,
        ROUND(AVG(g.home_tov), 1) as tov,
        ROUND(AVG(g.home_pf), 1) as pf,
        ROUND(AVG(g.home_plus_minus), 2) as plus_minus
    FROM games g
    WHERE g.home_team_abbr IS NOT NULL 
      AND g.home_pts IS NOT NULL
      AND g.season BETWEEN 2004 AND 2026
    GROUP BY g.season, g.home_team_abbr
    ON CONFLICT (season, team_abbr, split_type) DO UPDATE SET
        games = EXCLUDED.games,
        pts = EXCLUDED.pts,
        fg_pct = EXCLUDED.fg_pct,
        fg3_pct = EXCLUDED.fg3_pct,
        ft_pct = EXCLUDED.ft_pct,
        reb = EXCLUDED.reb,
        ast = EXCLUDED.ast,
        stl = EXCLUDED.stl,
        blk = EXCLUDED.blk,
        tov = EXCLUDED.tov,
        pf = EXCLUDED.pf,
        plus_minus = EXCLUDED.plus_minus,
        created_at = NOW()
''')
home_rows = cur.rowcount
print(f"✅ 主场数据已填充: {home_rows:,} 行")

# Step 3: 填充客场数据
print("\n📊 Step 3: 填充客场数据...")
cur.execute('''
    INSERT INTO team_game_splits 
        (season, team_abbr, split_type, games, pts, fg_pct, fg3_pct, ft_pct, 
         reb, ast, stl, blk, tov, pf, plus_minus)
    SELECT 
        g.season,
        g.away_team_abbr as team_abbr,
        'away' as split_type,
        COUNT(*) as games,
        ROUND(AVG(g.away_pts), 2) as pts,
        ROUND(AVG(g.away_fg_pct)::numeric, 3) as fg_pct,
        ROUND(AVG(g.away_fg3_pct)::numeric, 3) as fg3_pct,
        ROUND(AVG(g.away_ft_pct)::numeric, 3) as ft_pct,
        ROUND(AVG(g.away_reb), 1) as reb,
        ROUND(AVG(g.away_ast), 1) as ast,
        ROUND(AVG(g.away_stl), 1) as stl,
        ROUND(AVG(g.away_blk), 1) as blk,
        ROUND(AVG(g.away_tov), 1) as tov,
        ROUND(AVG(g.away_pf), 1) as pf,
        ROUND(AVG(g.away_plus_minus), 2) as plus_minus
    FROM games g
    WHERE g.away_team_abbr IS NOT NULL 
      AND g.away_pts IS NOT NULL
      AND g.season BETWEEN 2004 AND 2026
    GROUP BY g.season, g.away_team_abbr
    ON CONFLICT (season, team_abbr, split_type) DO UPDATE SET
        games = EXCLUDED.games,
        pts = EXCLUDED.pts,
        fg_pct = EXCLUDED.fg_pct,
        fg3_pct = EXCLUDED.fg3_pct,
        ft_pct = EXCLUDED.ft_pct,
        reb = EXCLUDED.reb,
        ast = EXCLUDED.ast,
        stl = EXCLUDED.stl,
        blk = EXCLUDED.blk,
        tov = EXCLUDED.tov,
        pf = EXCLUDED.pf,
        plus_minus = EXCLUDED.plus_minus,
        created_at = NOW()
''')
away_rows = cur.rowcount
print(f"✅ 客场数据已填充: {away_rows:,} 行")

# Step 4: 验证
print("\n📊 Step 4: 验证结果...")
cur.execute('SELECT COUNT(*), MIN(season), MAX(season) FROM team_game_splits')
r = cur.fetchone()
print(f"📊 team_game_splits 总计: {r[0]:,} 行, 赛季 {r[1]}-{r[2]}")

# 样本
cur.execute('''
    SELECT * FROM team_game_splits 
    WHERE season = 2026 AND team_abbr = 'OKC'
''')
cols = [d[0] for d in cur.description]
print("\n📝 样本 (OKC 2026):")
for r in cur.fetchall():
    print(dict(zip(cols, r)))

conn.close()
print("\n✅ Phase 1 - Task 2 完成！")
