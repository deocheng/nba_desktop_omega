import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()

print('=== games table: game_id format patterns ===')
cur.execute("""
    SELECT 
        CASE 
            WHEN game_id ~ '^[0-9]+$' THEN 'pure_numeric'
            WHEN game_id ~ '^[0-9]{10}[A-Z]{3}$' THEN 'br_format'
            ELSE 'other'
        END as format,
        COUNT(*) as cnt
    FROM games
    GROUP BY format
""")
for p in cur.fetchall():
    print(f"  {p['format']}: {p['cnt']} rows")

print('\n=== BR format samples (already in BR format) ===')
cur.execute("""
    SELECT game_id, nba_api_id, game_date, home_team_abbr, away_team_abbr 
    FROM games 
    WHERE game_id ~ '^[0-9]{10}[A-Z]{3}$'
    LIMIT 5
""")
for row in cur.fetchall():
    print(f"  game_id={row['game_id']}, nba_api_id={row['nba_api_id']}, date={row['game_date']}, home={row['home_team_abbr']}, away={row['away_team_abbr']}")

print('\n=== Pure numeric samples (need conversion) ===')
cur.execute("""
    SELECT game_id, nba_api_id, game_date, home_team_abbr, away_team_abbr 
    FROM games 
    WHERE game_id ~ '^[0-9]+$'
    LIMIT 5
""")
for row in cur.fetchall():
    print(f"  game_id={row['game_id']}, nba_api_id={row['nba_api_id']}, date={row['game_date']}, home={row['home_team_abbr']}, away={row['away_team_abbr']}")

print('\n=== player_gamelog gameid format ===')
cur.execute("""
    SELECT 
        CASE 
            WHEN gameid ~ '^[0-9]+$' THEN 'pure_numeric'
            WHEN gameid ~ '^[0-9]{10}[A-Z]{3}$' THEN 'br_format'
            ELSE 'other'
        END as format,
        COUNT(DISTINCT gameid) as cnt
    FROM player_gamelog
    GROUP BY format
""")
for p in cur.fetchall():
    print(f"  {p['format']}: {p['cnt']} unique gameids")

print('\n=== play_by_play gameid format ===')
cur.execute("""
    SELECT 
        CASE 
            WHEN gameid ~ '^[0-9]+$' THEN 'pure_numeric'
            WHEN gameid ~ '^[0-9]{10}[A-Z]{3}$' THEN 'br_format'
            ELSE 'other'
        END as format,
        COUNT(DISTINCT gameid) as cnt
    FROM play_by_play
    GROUP BY format
""")
for p in cur.fetchall():
    print(f"  {p['format']}: {p['cnt']} unique gameids")

print('\n=== Check if we can construct BR format from available data ===')
cur.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN game_date IS NOT NULL AND home_team_abbr IS NOT NULL THEN 1 ELSE 0 END) as has_date_and_team
    FROM games
    WHERE game_id ~ '^[0-9]+$'
""")
result = cur.fetchone()
print(f"  Pure numeric rows: {result['total']}")
print(f"  Have date and home_team_abbr: {result['has_date_and_team']}")

conn.close()
