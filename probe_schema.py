"""One-off schema probe for entity_loader implementation (temporary)."""
from backend.core.db import batch_query


def cols(tbl: str) -> list[str]:
    try:
        rows = batch_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            (tbl,),
        )
        return [r["column_name"] for r in rows]
    except Exception as e:
        return [f"ERROR: {e}"]


def sample(tbl: str, limit: int = 1) -> list[dict]:
    try:
        return batch_query(f"SELECT * FROM {tbl} LIMIT %s", (limit,))
    except Exception as e:
        return [{"ERROR": str(e)}]


for t in [
    "team_stats_per_game",
    "games",
    "dim_games",
    "player_gamelog",
    "fact_player_season_stats",
    "dim_players",
    "team_summaries",
]:
    print("=" * 70)
    print(f"TABLE: {t}")
    c = cols(t)
    print(f"  cols({len(c)}): {c}")

# player linkage: does jamesle01 exist in both?
print("=" * 70)
print("player_gamelog sample for season 2025 (first row cols):")
gl = sample("player_gamelog", 1)
if gl and "ERROR" not in gl[0]:
    r = gl[0]
    print("  player_gamelog keys:", list(r.keys()))
    for k in ("br_player_id", "player_id", "gameid", "game_id", "pts", "season"):
        if k in r:
            print(f"    {k} = {r[k]}")

print("=" * 70)
print("fact_player_season_stats sample (first row):")
fs = sample("fact_player_season_stats", 1)
if fs and "ERROR" not in fs[0]:
    r = fs[0]
    print("  keys:", list(r.keys()))
    for k in ("player_id", "br_player_id", "season"):
        if k in r:
            print(f"    {k} = {r[k]}")

print("=" * 70)
print("Does jamesle01 exist?")
try:
    j = batch_query(
        "SELECT player_id FROM dim_players WHERE player_id = %s LIMIT 1", ("jamesle01",)
    )
    print("  dim_players jamesle01:", j)
except Exception as e:
    print("  err:", e)
try:
    jg = batch_query(
        "SELECT br_player_id, season FROM player_gamelog WHERE br_player_id = %s AND season=2025 LIMIT 2",
        ("jamesle01",),
    )
    print("  player_gamelog jamesle01 2025:", jg)
except Exception as e:
    print("  err:", e)

print("=" * 70)
print("team_stats_per_game sample row:")
ts = sample("team_stats_per_game", 1)
if ts and "ERROR" not in ts[0]:
    print("  row:", dict(ts[0]))

print("=" * 70)
print("games sample row (cols):")
g = sample("games", 1)
if g and "ERROR" not in g[0]:
    print("  row:", dict(g[0]))
