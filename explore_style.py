import psycopg2, os, sys
from dotenv import dotenv_values

env = dotenv_values("/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env")
PW = env["DB_PASSWORD"]

conn = psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba",
                        user="postgres", password=PW)
cur = conn.cursor()

def run(sql, title):
    print("\n" + "="*70)
    print(title)
    print("="*70)
    print(sql)
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(x) for x in r))
    return cols, rows

# 1. team_totals 全列
run("""SELECT column_name, data_type FROM information_schema.columns
       WHERE table_name='team_totals' ORDER BY ordinal_position""",
    "1) team_totals 全列 (column_name | data_type)")

# 2. 搜投篮分布表
run("""SELECT table_name FROM information_schema.tables
       WHERE table_name ILIKE '%shoot%' OR table_name ILIKE '%shot%'
          OR table_name ILIKE '%location%' OR table_name ILIKE '%zone%'
          OR table_name ILIKE '%pct%' ORDER BY table_name""",
    "2) 含 shooting/shot/location/zone/pct 的表")

# 3. team_totals 赛季范围
run("""SELECT min(season), max(season), count(DISTINCT season)
       FROM team_totals""",
    "3) team_totals season 范围")

# 4. season=1980 是否存在 + 3pa/3p 列
run("""SELECT season, fga, "3pa", "3p" FROM team_totals WHERE season=1980 LIMIT 5""",
    "4) season=1980 抽样 (确认 3pa/3p 列存在且有值)")

# 5. season=1980 该季总行数 & NULL 检查
run("""SELECT count(*) AS n_rows,
              count("3pa") AS n_3pa,
              count("3p")  AS n_3p,
              count(fga)  AS n_fga,
              count(orb)  AS n_orb,
              count(tov)  AS n_tov,
              count(fta)  AS n_fta,
              count(ast)  AS n_ast,
              count(pts)  AS n_pts,
              count(mp)   AS n_mp
       FROM team_totals WHERE season=1980""",
    "5) 1980 季空值覆盖检查")

conn.close()
print("\nDONE")
