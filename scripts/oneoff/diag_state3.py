"""Diagnostic v3: efficient coverage via Python sets (avoids slow correlated subqueries)."""
from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
cur = conn.cursor()


def q(sql):
    cur.execute(sql)
    return cur.fetchall()


# 1) 2026 RS nba_api_ids (bigint) -- only not null
cur.execute("SELECT nba_api_id FROM games WHERE season=2026 AND season_type='Regular Season' AND nba_api_id IS NOT NULL")
rs_ids = set(int(r['nba_api_id']) for r in cur.fetchall())
print(f"2026 RS games with nba_api_id: {len(rs_ids)}")

# 2) distinct PBP gameids -> int set
cur.execute("SELECT DISTINCT gameid FROM play_by_play WHERE gameid ~ '^[0-9]+$'")
pbp_ids = set(int(r['gameid']) for r in cur.fetchall())
print(f"PBP distinct numeric gameids: {len(pbp_ids)}")

# 3) distinct gamelog gameids -> int set
cur.execute("SELECT DISTINCT gameid FROM player_gamelog WHERE gameid ~ '^[0-9]+$'")
log_ids = set(int(r['gameid']) for r in cur.fetchall())
print(f"gamelog distinct numeric gameids: {len(log_ids)}")

# 4) coverage
has_pbp = rs_ids & pbp_ids
has_log = rs_ids & log_ids
print(f"\n=== 2026 RS coverage (of {len(rs_ids)} games with nba_api_id) ===")
print(f"  with PBP:     {len(has_pbp)}  ({len(rs_ids)-len(has_pbp)} missing)")
print(f"  with gamelog: {len(has_log)}  ({len(rs_ids)-len(has_log)} missing)")

# 5) duplicates by (date,home,away)
print("\n=== Duplicate (date,home,away) in 2026 RS ===")
for r in q("""
SELECT game_date, home_team_abbr, away_team_abbr, COUNT(*) c,
       COUNT(DISTINCT game_id) dg, COUNT(DISTINCT nba_api_id) dn
FROM games WHERE season=2026 AND season_type='Regular Season'
GROUP BY game_date, home_team_abbr, away_team_abbr HAVING COUNT(*) > 1
ORDER BY c DESC LIMIT 20
"""):
    print(f"  {r['game_date']} {r['away_team_abbr']}@{r['home_team_abbr']}: rows={r['c']} game_id={r['dg']} nba_api={r['dn']}")

# 6) missing nba_api_id count
cur.execute("SELECT COUNT(*) c FROM games WHERE season=2026 AND season_type='Regular Season' AND nba_api_id IS NULL")
print(f"\n2026 RS games missing nba_api_id: {cur.fetchone()['c']}")

# 7) season_type for 2026
print("\n=== season=2026 season_type counts ===")
for r in q("SELECT season_type, COUNT(*) c FROM games WHERE season=2026 GROUP BY season_type ORDER BY c DESC"):
    print(f"  {r['season_type']}: {r['c']}")

conn.close()
