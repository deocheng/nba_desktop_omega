"""Independent QA verification of migration #46. READ-ONLY. SELECT only."""
import psycopg2
from backend.core.config import db_dsn

DSN = db_dsn()
print("DSN:", DSN)

def q(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()

with psycopg2.connect(DSN) as conn:
    # Schema introspection for play_by_play columns
    cols = [r[0] for r in q(conn, """
        SELECT column_name FROM information_schema.columns
        WHERE table_name='play_by_play' ORDER BY ordinal_position
    """)]
    print("play_by_play columns:", cols)
    id_col = 'id'
    gameid_col = 'gameid'
    dup_cols = [c for c in cols if c not in (id_col, gameid_col)]
    print("dup-compare columns (excl id,gameid):", dup_cols)

    # ---- Backup intact (Invariant 5) ----
    bak_count = q(conn, "SELECT COUNT(*) FROM dim_games_br_id_fix_bak")[0][0]
    print("\n[5] backup row count =", bak_count)

    # Get the 241 original 11-bit ids
    orig_ids = [r[0] for r in q(conn, "SELECT game_id FROM dim_games_br_id_fix_bak")]
    print("bak distinct game_id count =", len(set(orig_ids)))
    # Compute expected 12-bit ids independently
    expected = [o[:8] + '0' + o[8:] for o in orig_ids]
    exp_set = set(expected)
    print("sample orig->expected:", list(zip(orig_ids[:3], expected[:3])))

    # ---- Invariant 1 ----
    # (a) exactly one dim_games row per expected 12-bit id
    placeholders = ",".join(["%s"] * len(expected))
    per_id_counts = q(conn, f"""
        SELECT game_id, COUNT(*) FROM dim_games
        WHERE game_id IN ({placeholders})
        GROUP BY game_id
    """, expected)
    counts_map = {r[0]: r[1] for r in per_id_counts}
    matched = len(counts_map)
    maxc = max(counts_map.values()) if counts_map else 0
    minc = min(counts_map.values()) if counts_map else 0
    print("\n[1] expected 12-bit ids present in dim_games:", matched, "of", len(exp_set))
    print("    per-id count min/max:", minc, maxc)
    missing_12 = exp_set - set(counts_map.keys())
    multi_12 = {k: v for k, v in counts_map.items() if v != 1}
    # (b) zero leftover 11-bit rows (original ids still in dim_games)
    leftover_11 = q(conn, f"""
        SELECT COUNT(*) FROM dim_games WHERE game_id IN ({placeholders})
    """, orig_ids)[0][0]
    print("    leftover 11-bit rows in dim_games:", leftover_11)
    print("    missing 12-bit ids:", list(missing_12)[:10], "..." if len(missing_12) > 10 else "")
    print("    multi-row 12-bit ids:", multi_12)

    # ---- Invariant 2 ---- no orphan PBP under old 11-bit ids
    orphan_old = q(conn, f"""
        SELECT COUNT(*) FROM play_by_play WHERE gameid IN ({placeholders})
    """, orig_ids)[0][0]
    print("\n[2] PBP rows with old 11-bit gameid:", orphan_old)

    # ---- Invariant 3 ----
    pbp_total = q(conn, f"""
        SELECT COUNT(*) FROM play_by_play WHERE gameid IN ({placeholders})
    """, expected)[0][0]
    pbp_joined = q(conn, f"""
        SELECT COUNT(*) FROM play_by_play p
        JOIN dim_games g ON p.gameid = g.game_id
        WHERE p.gameid IN ({placeholders})
    """, expected)[0][0]
    print("\n[3] PBP rows (12-bit ids):", pbp_total, " expected 114287")
    print("    PBP rows that JOIN dim_games:", pbp_joined)
    print("    orphans (total-joined):", pbp_total - pbp_joined)

    # ---- Invariant 4 ---- no full-row dups (excl id, gameid)
    col_list = ", ".join(dup_cols)
    dup_sql = f"""
        SELECT gameid, COUNT(*) AS cnt FROM play_by_play
        WHERE gameid IN ({placeholders})
        GROUP BY gameid, {col_list}
        HAVING COUNT(*) > 1
    """
    dup_rows = q(conn, dup_sql, expected)
    agg_dups = len(dup_rows)
    dup_total_rows = sum(r[1] for r in dup_rows)
    print("\n[4] duplicate groups (excl id,gameid):", agg_dups, " rows involved:", dup_total_rows)
    if agg_dups:
        print("    sample dup groups:", dup_rows[:5])

    # ---- Sample games char-length check ----
    print("\n[SAMPLE] dim_games.game_id len & br_crawled_id len for samples:")
    samples = expected[:3]
    ph3 = ",".join(["%s"] * len(samples))
    samp = q(conn, f"""
        SELECT game_id, br_crawled_id, char_length(game_id), char_length(br_crawled_id)
        FROM dim_games WHERE game_id IN ({ph3})
    """, samples)
    for r in samp:
        print("    ", r)

# ---- Verdict ----
print("\n==== VERDICT ====")
r1 = (matched == len(exp_set) and maxc == 1 and leftover_11 == 0)
r2 = orphan_old == 0
r3 = (pbp_total == 114287 and pbp_joined == pbp_total)
r4 = agg_dups == 0
r5 = (bak_count == 241)
print("1 Canonical 12-bit rows:", "PASS" if r1 else "FAIL")
print("2 No orphan PBP old ids:", "PASS" if r2 else "FAIL")
print("3 PBP integrity 114287 & join:", "PASS" if r3 else "FAIL")
print("4 No full-row dups:", "PASS" if r4 else "FAIL")
print("5 Backup intact 241:", "PASS" if r5 else "FAIL")
print("OVERALL:", "ACCEPTED" if all([r1,r2,r3,r4,r5]) else "REJECTED")
