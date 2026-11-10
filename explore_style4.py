import psycopg2
from dotenv import dotenv_values

env = dotenv_values("/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env")
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

# dim_teams 列 + 样本
run("""SELECT column_name, data_type FROM information_schema.columns
       WHERE table_name='dim_teams' ORDER BY ordinal_position""", "dim_teams 全列")
run("""SELECT * FROM dim_teams LIMIT 3""", "dim_teams 样本")

# fact_team_season_stats 列
run("""SELECT column_name, data_type FROM information_schema.columns
       WHERE table_name='fact_team_season_stats' ORDER BY ordinal_position""",
    "fact_team_season_stats 全列")

# x3pa 1980起抽样(修正 round)
run("""SELECT season, count(*) n,
              round(avg(x3pa)::numeric,1) avg_3pa,
              round(avg(fga)::numeric,0) avg_fga
       FROM team_totals WHERE season BETWEEN 1980 AND 2026
       GROUP BY season ORDER BY season LIMIT 6""", "x3pa 1980起抽样(前6)")

# 位置方法 join 验证
run("""SELECT ppg.team, p.pos, round(sum(ppg.pts)::numeric,1) pts
       FROM player_per_game ppg
       JOIN dim_players p ON p.player_id=ppg.player_id
       WHERE ppg.season=2000 AND ppg.player_id<>'' AND ppg.g>20
       GROUP BY ppg.team, p.pos
       ORDER BY ppg.team, pts DESC LIMIT 6""", "2000 季得分手位置(join)")
run("""SELECT ppg.season, ppg.team, p.pos, round(sum(ppg.pts)::numeric,1) pts
       FROM player_per_game ppg
       JOIN dim_players p ON p.player_id=ppg.player_id
       WHERE ppg.season IN (1985,2020) AND ppg.player_id<>'' AND ppg.g>20
       GROUP BY ppg.season, ppg.team, p.pos
       ORDER BY ppg.season, ppg.team, pts DESC LIMIT 8""", "1985/2020 位置 join")

conn.close()
print("\nDONE")
