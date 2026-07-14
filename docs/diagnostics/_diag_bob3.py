"""Bob diagnostic part 3 — view defs, draft base tables, weight writer."""
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

section("A1l. VIEW definitions for draft_picks / draft_pick_history")
for v in ("draft_picks", "draft_pick_history"):
    try:
        r = batch_query(
            "SELECT view_definition FROM information_schema.views "
            "WHERE table_name=%s", (v,))
        print(f"  --- {v} ---")
        print(r[0]["view_definition"][:1500] if r else "  (not a view / not found)")
    except Exception as e:
        print(f"  {v} ERR:", e)

section("A1m. does base table dim_draft_history exist? columns + sample")
try:
    c = [r["column_name"] for r in batch_query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='dim_draft_history' ORDER BY ordinal_position")]
    print("  cols:", c)
    show(batch_query("SELECT * FROM dim_draft_history LIMIT 5"), 5)
except Exception as e:
    print("  ERR:", e)

section("A1n. dim_draft_history player_id coverage vs draft_picks 'wrong' ids")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS total FROM dim_draft_history"))
    print("  ", batch_query(
        "SELECT COUNT(*) AS in_dim_draft "
        "FROM draft_picks dp "
        "WHERE dp.player_id IN (SELECT player_id FROM dim_draft_history)"))
except Exception as e:
    print("  ERR:", e)

section("A1o. For 3 known-wrong draft_picks ids, is the correct id in dim_draft_history?")
try:
    show(batch_query(
        "SELECT player_id, player_name, season FROM dim_draft_history "
        "WHERE player_name IN ('Don Smith','Bob Duffy','Bill Bradley') "
        "ORDER BY player_name LIMIT 20"), 20)
except Exception as e:
    print("  ERR:", e)

section("A1p. unique-name exact match (no collision) correctable subset size")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS unique_name_correctable "
        "FROM draft_picks dp "
        "WHERE dp.player_id NOT IN (SELECT player_id FROM dim_players) "
        "AND dp.player_name IN ("
        "   SELECT player_name FROM dim_players GROUP BY player_name HAVING COUNT(*)=1)"
        "AND EXISTS (SELECT 1 FROM dim_players p WHERE p.player_name=dp.player_name "
        "            AND p.player_id <> dp.player_id)"))
except Exception as e:
    print("  ERR:", e)

print("\nDONE3.")
