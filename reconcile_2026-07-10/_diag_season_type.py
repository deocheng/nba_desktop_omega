import os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)
import psycopg2

conn = psycopg2.connect(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
cur = conn.cursor()

for s in (2024, 2025, 2026):
    print(f"=== Season {s} : season_type x month ===")
    cur.execute("""SELECT season_type, EXTRACT(MONTH FROM game_date) AS m, COUNT(*)
                   FROM dim_games WHERE season=%s
                   GROUP BY season_type, m ORDER BY season_type, m""", (s,))
    for st, m, c in cur.fetchall():
        print(f"  {st:14} month={int(m):02d} count={c}")
    # RS games that fall in the playoff window (heuristic: on/after Apr 20 of the ending year)
    cur.execute("""SELECT COUNT(*) FROM dim_games
                   WHERE season=%s AND season_type='Regular Season'
                   AND game_date >= MAKE_DATE(%s, 4, 20)""", (s, s))
    late = cur.fetchone()[0]
    print(f"  >> RS games on/after Apr-20 ({s}): {late}")
    print()

conn.close()
