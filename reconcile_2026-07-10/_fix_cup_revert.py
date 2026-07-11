import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type, home_pts, away_pts FROM dim_games WHERE game_id='202512130ORL'")
print("BEFORE:", cur.fetchone())
cur.execute("UPDATE dim_games SET season_type='Regular Season' WHERE game_id='202512130ORL' AND season_type='NBA Cup'")
print("rows updated:", cur.rowcount)
conn.commit()
cur.execute("SELECT game_id, season_type FROM dim_games WHERE game_id='202512130ORL'")
print("AFTER:", cur.fetchone())
# also confirm NBA Cup now only has the 2 legit rows
cur.execute("SELECT game_id, game_date, home_team_abbr, away_team_abbr, home_pts, away_pts FROM dim_games WHERE season_type='NBA Cup' ORDER BY game_date")
print("NBA Cup rows now:", cur.fetchall())
conn.close()
