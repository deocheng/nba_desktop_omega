import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()

def q(title, sql, args=None):
    print("\n=== " + title + " ===")
    cur.execute(sql, args or ())
    rows = cur.fetchall()
    if not rows:
        print("(no rows)")
    for r in rows:
        print(r)

# 1) All NBA Cup rows
q("NBA Cup rows (all)",
  "SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type, home_pts, away_pts, source FROM dim_games WHERE season_type='NBA Cup' ORDER BY game_date")

# 2) SAS / NYK / ORL matchups (any season)
q("SAS/NYK/ORL matchups (all-time)",
  "SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type, home_pts, away_pts, source FROM dim_games WHERE (home_team_abbr, away_team_abbr) IN (('NYK','ORL'),('ORL','NYK'),('SAS','NYK'),('NYK','SAS')) ORDER BY game_date")

# 3) All games in Dec 2025
q("All games Dec 2025",
  "SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type, home_pts, away_pts, source FROM dim_games WHERE game_date >= '2025-12-01' AND game_date <= '2025-12-31' ORDER BY game_date")

# 4) Season_type counts for the three target seasons (derive season from game_date)
q("season_type counts by season (2024/2025/2026)",
  """SELECT EXTRACT(YEAR FROM game_date) AS yr, season_type, COUNT(*) 
     FROM dim_games WHERE game_date >= '2023-09-01' AND game_date <= '2026-08-31'
     GROUP BY yr, season_type ORDER BY yr, season_type""")

# 5) Does SAS@NYK exist anywhere (any date)?
q("Any SAS@NYK or NYK@SAS ever",
  "SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type, home_pts, away_pts, source FROM dim_games WHERE (home_team_abbr, away_team_abbr) IN (('SAS','NYK'),('NYK','SAS')) ORDER BY game_date")

conn.close()
print("\nDONE")
