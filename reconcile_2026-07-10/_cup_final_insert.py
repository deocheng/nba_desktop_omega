import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()
gid = '202512160NYK'   # SAS 113 @ NYK 124, 2025-12-16, T-Mobile Arena (NBA Cup final)
cur.execute("SELECT 1 FROM dim_games WHERE game_id=%s", (gid,))
if cur.fetchone():
    print("ALREADY EXISTS:", gid, "-> skip insert")
else:
    cur.execute(
        """INSERT INTO dim_games
           (game_id, game_date, season, season_type, home_team_abbr, away_team_abbr,
            home_pts, away_pts, location, boxscore_url, source, arena_name, arena_city, arena_state)
           VALUES (%s, '2025-12-16', 2026, 'NBA Cup', 'NYK', 'SAS', 124, 113, 'Neutral',
                   '/boxscores/202512160NYK.html', 'BBRef', 'T-Mobile Arena', 'Las Vegas', 'NV')""",
        (gid,))
    conn.commit()
    print("INSERTED Cup final:", gid, "SAS 113 @ NYK 124")
cur.execute("""SELECT game_id, game_date, home_team_abbr, away_team_abbr, season_type, home_pts, away_pts, source
               FROM dim_games WHERE season_type='NBA Cup' ORDER BY game_date""")
print("NBA Cup rows now:", cur.fetchall())
conn.close()
