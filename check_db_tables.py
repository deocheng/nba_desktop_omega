import os
os.environ['NBA_PYTHON'] = 'c:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega'
from backend.core.db import batch_query

rows = batch_query("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    ORDER BY table_name
""")
print("Tables:")
for r in rows:
    print(f"  {r['table_name']}")

print("\n--- Player-season team info ---")
rows = batch_query("SELECT * FROM fact_player_season_stats LIMIT 1")
if rows:
    print("fact_player_season_stats columns:", list(rows[0].keys()))

print("\n--- Team info ---")
rows = batch_query("SELECT * FROM dim_teams LIMIT 1")
if rows:
    print("dim_teams columns:", list(rows[0].keys()))

print("\n--- Player bio ---")
rows = batch_query("SELECT * FROM dim_players LIMIT 1")
if rows:
    print("dim_players columns:", list(rows[0].keys()))

print("\n--- Team season stats ---")
rows = batch_query("SELECT * FROM fact_team_season_stats LIMIT 1")
if rows:
    print("fact_team_season_stats columns:", list(rows[0].keys()))
