"""Find 2026 games labeled 'Regular Season' but played in the playoff window.

The 2025-26 NBA regular season ends mid-April 2026; playoffs run mid-April
through June. Any 2026 game dated after the RS cutoff that still carries
season_type='Regular Season' (and has an nba_api_id) is mislabeled and should
be 'Playoffs'.
"""
from __future__ import annotations
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()

# Latest RS game date, to understand the boundary
cur.execute("""
    SELECT MIN(game_date) min_d, MAX(game_date) max_d, COUNT(*) c
    FROM games WHERE season=2026 AND season_type='Regular Season'
""")
print("2026 RS date range:", cur.fetchone())

# Candidate mislabels: RS games on/after the playoff start window
cur.execute("""
    SELECT game_id, br_crawled_id, game_date, away_team_abbr, home_team_abbr,
           season_type, nba_api_id
    FROM games
    WHERE season=2026 AND season_type='Regular Season' AND game_date >= '2026-04-18'
    ORDER BY game_date, game_id
""")
rows = cur.fetchall()
print(f"\n2026 RS games on/after 2026-04-18: {len(rows)}")
for r in rows:
    print(f"  {r['game_date']}  {r['away_team_abbr']}@{r['home_team_abbr']}  "
          f"game_id={r['game_id']} br={r['br_crawled_id']} nba_api_id={r['nba_api_id']}")

# Also show how many Playoffs games exist for 2026 and their date range
cur.execute("""
    SELECT MIN(game_date) min_d, MAX(game_date) max_d, COUNT(*) c
    FROM games WHERE season=2026 AND season_type='Playoffs'
""")
print("\n2026 Playoffs date range:", cur.fetchone())

conn.close()
