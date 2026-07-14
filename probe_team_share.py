import sys
sys.path.insert(0, ".")
from backend.core.db import batch_query

# Joinable rows without playoffs filter (regular player -> regular team)
rows = batch_query("""
    SELECT COUNT(*) AS n FROM fact_player_season_stats p
    JOIN fact_team_season_stats t
      ON p.season = t.season AND p.team = t.abbreviation
    WHERE p.season_type = 'Regular'
""")
print("joinable Regular rows (no playoffs filter):", rows[0]["n"])

rows = batch_query("""
    SELECT COUNT(*) AS n FROM fact_player_season_stats p
    WHERE p.season_type = 'Regular'
      AND p.team NOT IN (SELECT DISTINCT abbreviation FROM fact_team_season_stats)
""")
print("Regular rows w/ unmatched team:", rows[0]["n"])

# Sample team_scoring_share for LeBron 2025: player pts/g vs team pts/g
rows = batch_query("""
    SELECT p.player_id, p.pts AS ppts, p.g AS pg,
           t.pts AS tpts, t.g AS tg,
           ROUND((p.pts::numeric/p.g::numeric) / (t.pts::numeric/t.g::numeric), 4) AS share
    FROM fact_player_season_stats p
    JOIN fact_team_season_stats t ON p.season=t.season AND p.team=t.abbreviation
    WHERE p.player_id='jamesle01' AND p.season=2025 AND p.season_type='Regular'
""")
print("LeBron 2025 share:", rows)

# distribution sanity: min/max share for season 2025
rows = batch_query("""
    SELECT ROUND(MIN((p.pts::numeric/p.g::numeric)/(t.pts::numeric/t.g::numeric))::numeric,4) min_sh,
           ROUND(MAX((p.pts::numeric/p.g::numeric)/(t.pts::numeric/t.g::numeric))::numeric,4) max_sh,
           COUNT(*) n
    FROM fact_player_season_stats p
    JOIN fact_team_season_stats t ON p.season=t.season AND p.team=t.abbreviation
    WHERE p.season=2025 AND p.season_type='Regular'
""")
print("2025 share range:", rows)
