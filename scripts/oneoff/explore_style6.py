import psycopg2
from dotenv import dotenv_values

from common.nba_paths import ENV_FILE

env = dotenv_values(str(ENV_FILE))
PW = env["DB_PASSWORD"]
conn = psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba",
                        user="postgres", password=PW)
cur = conn.cursor()

def run(sql, title, head=14):
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

# 位置方法: 直接用 ppg.pos
run("""SELECT ppg.team, ppg.pos, round(sum(ppg.pts)::numeric,1) pts
       FROM player_per_game ppg
       WHERE ppg.season=2000 AND ppg.player_id<>'' AND ppg.g>20
       GROUP BY ppg.team, ppg.pos
       ORDER BY ppg.team, pts DESC LIMIT 8""", "2000 位置(ppg.pos, 不join)")
run("""SELECT ppg.season, ppg.team, ppg.pos, round(sum(ppg.pts)::numeric,1) pts
       FROM player_per_game ppg
       WHERE ppg.season IN (1985,2020) AND ppg.player_id<>'' AND ppg.g>20
       GROUP BY ppg.season, ppg.team, ppg.pos
       ORDER BY ppg.season, ppg.team, pts DESC LIMIT 8""", "1985/2020 位置(ppg.pos)")
run("""SELECT season, count(DISTINCT pos) npos,
              string_agg(DISTINCT pos, ',' ORDER BY pos) positions
       FROM player_per_game WHERE season BETWEEN 1980 AND 2026 AND player_id<>''
       GROUP BY season ORDER BY season LIMIT 5""", "pos 取值(前5季)")

# dim_teams 覆盖
run("""SELECT count(*) n_teams, count(DISTINCT team_abbr) n_abbr FROM dim_teams""",
    "dim_teams 队数")
run("""SELECT DISTINCT abbreviation FROM team_totals
       WHERE season BETWEEN 1980 AND 2026
       EXCEPT SELECT team_abbr FROM dim_teams
       ORDER BY abbreviation""", "team_totals 有但 dim_teams 缺失的 abbr")

# 顺带确认 fact_team_season_stats 与 team_totals 是否同表(行数)
run("""SELECT (SELECT count(*) FROM team_totals) tt,
              (SELECT count(*) FROM fact_team_season_stats) ftts""",
    "team_totals vs fact_team_season_stats 行数")

conn.close()
print("\nDONE")
