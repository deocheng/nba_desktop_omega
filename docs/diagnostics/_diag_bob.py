"""Bob (Architect) on-site diagnostic for 3 data-quality issues.
Uses backend.core.db.batch_query (SELECT-only) — no writes.
Run from project root with venv python.
"""
import json
import sys
from backend.core.db import batch_query

def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

def show(rows, n=20):
    if not rows:
        print("  (no rows)")
        return
    cols = list(rows[0].keys())
    print(f"  cols({len(cols)}): {cols}")
    for r in rows[:n]:
        print("  ", {k: r[k] for k in cols})

# ───────────────────────── A1: draft_picks ─────────────────────────
section("A1a. draft_picks columns")
try:
    show(batch_query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='draft_picks' ORDER BY ordinal_position"), 50)
except Exception as e:
    print("  ERR:", e)

section("A1b. draft_picks row count")
try:
    print("  ", batch_query("SELECT COUNT(*) AS n FROM draft_picks"))
except Exception as e:
    print("  ERR:", e)

section("A1c. dim_players player_id format + sample")
try:
    show(batch_query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='dim_players' ORDER BY ordinal_position"), 50)
    show(batch_query("SELECT player_id, player_name, weight_lbs FROM dim_players LIMIT 8"), 8)
except Exception as e:
    print("  ERR:", e)

section("A1d. draft_picks sample (player linkage columns)")
try:
    show(batch_query(
        "SELECT * FROM draft_picks ORDER BY random() LIMIT 25"), 25)
except Exception as e:
    print("  ERR:", e)

section("A1e. draft_picks.player_id NOT IN dim_players.player_id (count)")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS bad_rows FROM draft_picks dp "
        "WHERE dp.player_id IS NOT NULL "
        "AND dp.player_id NOT IN (SELECT player_id FROM dim_players)"))
except Exception as e:
    print("  ERR:", e)

section("A1f. draft_picks.player_id NOT IN dim_players.player_id (sample 25)")
try:
    show(batch_query(
        "SELECT dp.player_id, dp.* FROM draft_picks dp "
        "WHERE dp.player_id IS NOT NULL "
        "AND dp.player_id NOT IN (SELECT player_id FROM dim_players) "
        "LIMIT 25"), 25)
except Exception as e:
    print("  ERR:", e)

# ───────────────────────── A2: weight tables ─────────────────────────
section("A2a. all tables + player-key detection (compute in python)")
tables = [r["table_name"] for r in batch_query(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema='public' ORDER BY table_name")]
cols_rows = batch_query(
    "SELECT table_name, column_name FROM information_schema.columns "
    "WHERE table_schema='public'")
colmap = {}
for r in cols_rows:
    colmap.setdefault(r["table_name"], []).append(r["column_name"])

player_tables = []
no_weight_player_tables = []
for t in tables:
    c = colmap.get(t, [])
    has_player_key = any(k in c for k in ("player_id", "br_player_id"))
    has_weight = any("weight" in k.lower() for k in c)
    if has_player_key:
        player_tables.append(t)
        if not has_weight:
            no_weight_player_tables.append(t)

print(f"  total tables: {len(tables)}")
print(f"  tables with player key (player_id/br_player_id): {len(player_tables)}")
print(f"  player-key tables WITHOUT a weight column: {len(no_weight_player_tables)}")
print("  -- list of player-key tables missing weight:")
for t in no_weight_player_tables:
    print("    -", t)

section("A2b. where does weight live now?")
for t in ["dim_players", "player_weight_history"]:
    print(f"  --- {t} ---")
    try:
        c = [r["column_name"] for r in batch_query(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s "
            "ORDER BY ordinal_position", (t,))]
        print("    cols:", c)
    except Exception as e:
        print("    ERR:", e)

section("A2c. dim_players weight coverage")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS total, "
        "COUNT(weight_lbs) AS with_lbs, COUNT(weight_kg) AS with_kg "
        "FROM dim_players"))
except Exception as e:
    print("  ERR:", e)

section("A2d. player_weight_history stats")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS rows, COUNT(DISTINCT player_id) AS distinct_players "
        "FROM player_weight_history"))
except Exception as e:
    print("  ERR:", e)

# ───────────────────────── A3: BR weight crawl ─────────────────────────
section("A3a. dim_players total vs weight-populated (BR crawl progress)")
try:
    print("  ", batch_query(
        "SELECT COUNT(*) AS total_players, "
        "COUNT(*) FILTER (WHERE weight_lbs IS NOT NULL) AS have_weight "
        "FROM dim_players"))
except Exception as e:
    print("  ERR:", e)

section("A3b. player_weight_history: distinct players with any weight row")
try:
    print("  ", batch_query(
        "SELECT COUNT(DISTINCT player_id) AS players_with_history "
        "FROM player_weight_history"))
except Exception as e:
    print("  ERR:", e)

section("A3c. draft_picks player_id values sample (first 15) to judge BR-id format")
try:
    show(batch_query("SELECT DISTINCT player_id FROM draft_picks LIMIT 15"), 15)
except Exception as e:
    print("  ERR:", e)

print("\nDONE.")
