import psycopg2
from dotenv import dotenv_values

env = dotenv_values("/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env")
PW = env["DB_PASSWORD"]
conn = psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba",
                        user="postgres", password=PW)
cur = conn.cursor()

def run(sql, title):
    print("\n" + "="*70); print(title); print("="*70)
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(" | ".join(cols))
    for r in rows[:15]:
        print(" | ".join(str(x) for x in r))
    if len(rows) > 15:
        print(f"... ({len(rows)} rows total)")
    return cols, rows

# 4b. season=1980 抽样 (用真列名 x3pa/x3p)
run("""SELECT season, fga, x3pa, x3p, x3p_percent, pts, orb, tov, fta, ast, mp
       FROM team_totals WHERE season=1980 LIMIT 6""",
    "4) season=1980 抽样 (x3pa/x3p 真列名)")

# 5b. 1980 季空值覆盖
run("""SELECT count(*) n_rows,
       count(x3pa) n_x3pa, count(x3p) n_x3p, count(fga) n_fga,
       count(orb) n_orb, count(tov) n_tov, count(fta) n_fta,
       count(ast) n_ast, count(pts) n_pts, count(mp) n_mp,
       count(trb) n_trb, count(drb) n_drb
       FROM team_totals WHERE season=1980""",
    "5) 1980 季空值覆盖")

# 各维度覆盖: x3pa 从哪季起开始非全 NULL
run("""SELECT season, count(*) n, count(x3pa) n_x3pa
       FROM team_totals GROUP BY season ORDER BY season
       LIMIT 1""", "x3pa 最早季")
run("""SELECT min(season) first_3pt FROM team_totals WHERE x3pa IS NOT NULL AND x3pa>0""",
    "x3pa>0 的最早赛季")

# 投篮分布相关表列探查
for t in ["player_shooting","player_shot_chart","fct_pbp_shots",
          "v_player_shot_dist_metric","v_player_shot_profile","v_team_clutch_shooting"]:
    run(f"""SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name='{t}' ORDER BY ordinal_position""",
        f"列: {t}")

conn.close()
print("\nDONE")
