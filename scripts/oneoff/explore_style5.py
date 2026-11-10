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

# dim_players 含 position 的列
run("""SELECT column_name, data_type FROM information_schema.columns
       WHERE table_name='dim_players'
         AND (column_name ILIKE '%pos%' OR column_name ILIKE '%posi%')
       ORDER BY ordinal_position""", "dim_players position 列")
run("""SELECT column_name FROM information_schema.columns
       WHERE table_name='dim_players' ORDER BY ordinal_position LIMIT 1""", "dim_players 首列(确认表存在)")
# 直接看 dim_players 前2行所有列
run("""SELECT * FROM dim_players LIMIT 1""", "dim_players 样本(找position列名)")

# player_per_game position 列
run("""SELECT column_name FROM information_schema.columns
       WHERE table_name='player_per_game'
         AND (column_name ILIKE '%pos%' OR column_name ILIKE '%player_id%')
       ORDER BY ordinal_position""", "player_per_game pos/player_id 列")

# 位置 join 用正确列(dim_players 的 position 字段名待定, 先试 pos / position)
run("""SELECT ppg.team, dp.pos, round(sum(ppg.pts)::numeric,1) pts
       FROM player_per_game ppg
       JOIN dim_players dp ON dp.player_id=ppg.player_id
       WHERE ppg.season=2000 AND ppg.player_id<>'' AND ppg.g>20
       GROUP BY ppg.team, dp.pos
       ORDER BY ppg.team, pts DESC LIMIT 6""", "2000 位置 join (pos)")

# dim_teams 覆盖: 是否含历史队
run("""SELECT count(*) n_teams, count(DISTINCT team_abbr) n_abbr FROM dim_teams""",
    "dim_teams 队数")
run("""SELECT DISTINCT abbreviation FROM team_totals
       WHERE season BETWEEN 1980 AND 2026
       EXCEPT
       SELECT team_abbr FROM dim_teams""", "team_totals 有但 dim_teams 缺失的 abbr(历史队)")

conn.close()
print("\nDONE")
