import psycopg2
from dotenv import dotenv_values

from common.nba_paths import ENV_FILE

env = dotenv_values(str(ENV_FILE))
PW = env["DB_PASSWORD"]
conn = psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba",
                        user="postgres", password=PW)
cur = conn.cursor()

def run(sql, title, head=12):
    print("\n" + "="*70); print(title); print("="*70)
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(" | ".join(cols))
        for r in rows[:head]:
            print(" | ".join(str(x) for x in r))
        if len(rows) > head:
            print(f"... ({len(rows)} rows)")
    except Exception as e:
        print("ERR:", e)

# 所有候选表的 schema
run("""SELECT table_schema, table_name, table_type FROM information_schema.tables
       WHERE table_name IN ('fct_pbp_shots','player_shooting','player_shot_chart',
         'v_player_shot_dist_metric','v_player_shot_profile','v_team_clutch_shooting',
         'player_adjusted_shooting','playoff_player_shooting')""", "候选表 schema/type")

# 含 team 的表
run("""SELECT table_schema, table_name FROM information_schema.tables
       WHERE table_name ILIKE '%team%' ORDER BY table_name""", "含 team 的表")

# abbreviation 覆盖
run("""SELECT season, count(*) n, count(abbreviation) n_abbr,
              count(DISTINCT abbreviation) n_uniq
       FROM team_totals WHERE season IN (1980,1990,2000,2010,2020,2026)
       GROUP BY season ORDER BY season""", "abbreviation 覆盖抽样")
run("""SELECT DISTINCT abbreviation FROM team_totals WHERE season=1980 ORDER BY abbreviation""",
    "1980 季 abbreviation 列表")

# 三分连续性 1980-2026
run("""SELECT count(*) seasons_total,
              count(*) FILTER (WHERE x3pa IS NOT NULL) seasons_with_3pa
       FROM (SELECT season, max(x3pa) x3pa FROM team_totals
             WHERE season BETWEEN 1980 AND 2026 GROUP BY season) s""",
    "1980-2026 各季 x3pa 非全NULL季数")
run("""SELECT season, count(*) n, round(avg(x3pa),1) avg_3pa, round(avg(fga),0) avg_fga
       FROM team_totals WHERE season BETWEEN 1980 AND 2026
       GROUP BY season ORDER BY season LIMIT 6""", "x3pa 1980起抽样(前6)")

# 位置方法抽查 2000/2020
run("""SELECT ppg.team, p.pos, round(sum(ppg.pts),1) pts
       FROM player_per_game ppg
       JOIN dim_players p ON p.player_id=ppg.player_id
       WHERE ppg.season=2000 AND ppg.player_id<>'' AND ppg.g>20
       GROUP BY ppg.team, p.pos
       ORDER BY ppg.team, pts DESC LIMIT 6""", "2000 季得分手位置(join 验证)")
run("""SELECT ppg.season, ppg.team, p.pos, round(sum(ppg.pts),1) pts
       FROM player_per_game ppg
       JOIN dim_players p ON p.player_id=ppg.player_id
       WHERE ppg.season IN (1985,2020) AND ppg.player_id<>'' AND ppg.g>20
       GROUP BY ppg.season, ppg.team, p.pos
       ORDER BY ppg.season, ppg.team, pts DESC LIMIT 8""", "1985/2020 位置 join 验证")

conn.close()
print("\nDONE")
