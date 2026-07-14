"""Bob diagnostic part 4 — A1 precision + player_id_orig diff."""
from backend.core.db import batch_query

def section(t):
    print("\n" + "=" * 70); print(t); print("=" * 70)
def show(rows, n=12):
    if not rows:
        print("  (no rows)"); return
    cols = list(rows[0].keys())
    print(f"  cols({len(cols)}): {cols}")
    for r in rows[:n]:
        print("  ", {k: r[k] for k in cols})

section("A1q. draft rows where player_name IN dim_players BUT player_id NOT IN dim_players (collision-possible wrong set)")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS name_exists_id_wrong "
        "FROM draft_picks dp "
        "WHERE dp.player_name IN (SELECT player_name FROM dim_players) "
        "AND dp.player_id NOT IN (SELECT player_id FROM dim_players)"))
except Exception as e:
    print("  ERR:", e)

section("A1r. does player_id differ from player_id_orig in dim_draft_history? (prior-correction signal)")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS diff_count, COUNT(*) FILTER (WHERE player_id IS NULL) AS null_pid "
        "FROM dim_draft_history WHERE player_id IS DISTINCT FROM player_id_orig"))
except Exception as e:
    print("  ERR:", e)

section("A1s. composite high-precision candidate: name+college exact match to dim_players, id wrong")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS composite_candidates "
        "FROM dim_draft_history d "
        "WHERE d.player_id NOT IN (SELECT player_id FROM dim_players) "
        "AND d.player_name IN (SELECT player_name FROM dim_players) "
        "AND d.college IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM dim_players p "
        "            WHERE p.player_name=d.player_name AND p.college=d.college "
        "            AND p.player_id <> d.player_id)"))
except Exception as e:
    print("  ERR:", e)

section("A1t. sample composite candidates (d.player_id -> suggested p.player_id)")
try:
    show(batch_query(
        "SELECT d.player_id AS cur, p.player_id AS suggested, d.player_name, d.college, d.season "
        "FROM dim_draft_history d "
        "JOIN dim_players p ON p.player_name=d.player_name AND p.college=d.college "
        "WHERE d.player_id NOT IN (SELECT player_id FROM dim_players) "
        "AND d.college IS NOT NULL AND p.player_id <> d.player_id "
        "LIMIT 15"), 15)
except Exception as e:
    print("  ERR:", e)

section("A1u. how many of the 3998 have college populated (composite match feasibility)")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS with_college "
        "FROM draft_picks dp "
        "WHERE dp.player_id NOT IN (SELECT player_id FROM dim_players) "
        "AND dp.college IS NOT NULL AND dp.college <> ''"))
except Exception as e:
    print("  ERR:", e)

print("\nDONE4.")
