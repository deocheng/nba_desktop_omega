import os
os.environ['NBA_PYTHON'] = 'c:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega'
from backend.core.db import batch_query

rows = batch_query('SELECT * FROM fact_team_season_stats LIMIT 1')
if rows:
    print('Columns:', list(rows[0].keys()))

rows = batch_query('SELECT * FROM fact_team_season_stats WHERE abbreviation = %s AND season = %s', ('LAL', 2023))
print('LAL 2023:', rows)

rows = batch_query('SELECT season, abbreviation, pts FROM fact_team_season_stats WHERE abbreviation = %s AND season BETWEEN 2004 AND 2026 ORDER BY season', ('LAL',))
print('LAL all seasons:')
for r in rows:
    print(f"  {r['season']}: pts={r['pts']}")
