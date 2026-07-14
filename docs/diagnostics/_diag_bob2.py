"""Bob diagnostic part 2 — refinement of A1/A2/A3."""
from backend.core.db import batch_query

def section(t):
    print("\n" + "=" * 70); print(t); print("=" * 70)
def show(rows, n=15):
    if not rows:
        print("  (no rows)"); return
    cols = list(rows[0].keys())
    print(f"  cols({len(cols)}): {cols}")
    for r in rows[:n]:
        print("  ", {k: r[k] for k in cols})

# ── A1 refined: name-based correctability ──
section("A1g. draft_picks rows whose player_name MATCHES dim_players but id DIFFERS (wrong id, correctable)")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS correctable_wrong "
        "FROM draft_picks dp "
        "JOIN dim_players p ON p.player_name = dp.player_name "
        "WHERE dp.player_id <> p.player_id"))
except Exception as e:
    print("  ERR:", e)

section("A1h. sample of correctable wrong-id rows (dp.player_id -> correct p.player_id)")
try:
    show(batch_query(
        "SELECT dp.player_id AS wrong_id, p.player_id AS correct_id, "
        "dp.player_name, dp.season "
        "FROM draft_picks dp "
        "JOIN dim_players p ON p.player_name = dp.player_name "
        "WHERE dp.player_id <> p.player_id "
        "LIMIT 20"), 20)
except Exception as e:
    print("  ERR:", e)

section("A1i. draft_picks rows whose player_name NOT in dim_players (player absent from master)")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS name_not_found "
        "FROM draft_picks dp "
        "WHERE dp.player_name NOT IN (SELECT player_name FROM dim_players)"))
except Exception as e:
    print("  ERR:", e)

section("A1j. malformed BR-id check: player_id length distribution in draft_picks")
try:
    show(batch_query(
        "SELECT length(player_id) AS len, COUNT(*) AS n "
        "FROM draft_picks GROUP BY length(player_id) ORDER BY len"), 20)
except Exception as e:
    print("  ERR:", e)

section("A1k. how many of the 3998 NOT-IN-dim_players are name-matchable vs not")
try:
    print("  ", batch_query(
        "SELECT "
        "COUNT(*) FILTER (WHERE player_name IN (SELECT player_name FROM dim_players)) AS name_in_master, "
        "COUNT(*) FILTER (WHERE player_name NOT IN (SELECT player_name FROM dim_players)) AS name_not_in_master "
        "FROM draft_picks dp "
        "WHERE dp.player_id IS NOT NULL "
        "AND dp.player_id NOT IN (SELECT player_id FROM dim_players)"))
except Exception as e:
    print("  ERR:", e)

# ── A2 refined: player key per table + view/backup flag ──
section("A2e. per-table player key + kind for the 37 missing-weight tables")
cols_rows = batch_query(
    "SELECT table_name, column_name FROM information_schema.columns "
    "WHERE table_schema='public'")
colmap = {}
for r in cols_rows:
    colmap.setdefault(r["table_name"], []).append(r["column_name"])
ttype = {r["table_name"]: r["table_type"] for r in batch_query(
    "SELECT table_name, table_type FROM information_schema.tables "
    "WHERE table_schema='public'")}
missing = []
for t, c in colmap.items():
    has_key = any(k in c for k in ("player_id", "br_player_id"))
    has_w = any("weight" in k.lower() for k in c)
    if has_key and not has_w:
        missing.append(t)
for t in sorted(missing):
    c = colmap[t]
    key = "br_player_id" if "br_player_id" in c else ("player_id" if "player_id" in c else "?")
    kind = ttype.get(t, "?")
    flag = ""
    if "bak" in t or "dup" in t or "backup" in t:
        flag = " [BACKUP/DUP]"
    if t == "player_id_bridge":
        flag += " [BRIDGE]"
    print(f"  {t:32s} key={key:14s} kind={kind}{flag}")

# ── A3 refined: reconcile 40/4607 claim ──
section("A3c. does a plain `players` table exist (distinct from dim_players)?")
try:
    show(batch_query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name IN ('players','player')"), 10)
except Exception as e:
    print("  ERR:", e)

section("A3d. player_weight_history: weight population detail")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS rows, "
        "COUNT(weight_lbs) AS wt_lbs_nonnull, "
        "COUNT(weight_kg) AS wt_kg_nonnull, "
        "COUNT(height) AS height_nonnull, "
        "COUNT(born) AS born_nonnull, "
        "COUNT(DISTINCT player_id) AS distinct_players "
        "FROM player_weight_history"))
except Exception as e:
    print("  ERR:", e)

section("A3e. any table with ~4607 rows? (search for the 4607 denominator)")
try:
    show(batch_query(
        "SELECT relname AS table_name, n_live_tup AS est_rows "
        "FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 15"), 15)
except Exception as e:
    print("  ERR:", e)

section("A3f. dim_players weight_lbs NULL rows (the 3 missing)")
try:
    show(batch_query(
        "SELECT player_id, player_name FROM dim_players "
        "WHERE weight_lbs IS NULL"), 10)
except Exception as e:
    print("  ERR:", e)

print("\nDONE2.")
