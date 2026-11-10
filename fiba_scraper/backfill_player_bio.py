"""GAP-3 backfill: enrich the `players` dimension with position_code /
date_of_birth / uniform_number, recovered from game_player_stats.raw_stats
(the boxscore player object already stored for all 168 games). No re-download.

Idempotent + rollback-safe:
  * ALTER COLUMN IF NOT EXISTS (no-op on re-run)
  * snapshot players -> players_bak_gap3_20260828 before UPDATE
"""
from __future__ import annotations

import fiba_db as D

BACKUP = "players_bak_gap3_20260828"

def main() -> None:
    conn = D.get_conn()
    try:
        cur = conn.cursor()
        # 1) ensure schema migration
        for col, typ in (("position_code", "TEXT"), ("date_of_birth", "TIMESTAMPTZ"),
                         ("uniform_number", "INT")):
            cur.execute(f"ALTER TABLE players ADD COLUMN IF NOT EXISTS {col} {typ}")
        conn.commit()

        # 2) pre-backfill coverage snapshot (from source)
        cur.execute("""
            SELECT
                COUNT(DISTINCT player_id) FILTER (
                    WHERE raw_stats->'player'->>'positionCode' IS NOT NULL),
                COUNT(DISTINCT player_id) FILTER (
                    WHERE raw_stats->'player'->>'dateOfBirth' IS NOT NULL),
                COUNT(DISTINCT player_id) FILTER (
                    WHERE raw_stats->'player'->>'uniformNumber' IS NOT NULL)
            FROM game_player_stats
            WHERE raw_stats->'player' IS NOT NULL AND player_id IS NOT NULL
        """)
        src_pos, src_dob, src_uni = cur.fetchone()
        print("SOURCE coverage (distinct players w/ field in raw_stats):")
        print(f"  position_code : {src_pos}")
        print(f"  date_of_birth : {src_dob}")
        print(f"  uniform_number: {src_uni}")

        # 3) rollback snapshot
        cur.execute(f"DROP TABLE IF EXISTS {BACKUP}")
        cur.execute(f"CREATE TABLE {BACKUP} AS SELECT * FROM players")
        conn.commit()
        print(f"rollback snapshot: {BACKUP} created")

        # 4) backfill from most-recent game per player
        cur.execute("""
            WITH bio AS (
                SELECT DISTINCT ON (player_id) player_id,
                    raw_stats->'player'->>'positionCode'        AS position_code,
                    (raw_stats->'player'->>'dateOfBirth')::timestamptz AS date_of_birth,
                    (raw_stats->'player'->>'uniformNumber')::int        AS uniform_number,
                    raw_stats->'player'->>'nationality'          AS nationality
                FROM game_player_stats
                WHERE raw_stats->'player' IS NOT NULL AND player_id IS NOT NULL
                ORDER BY player_id, game_id DESC
            )
            UPDATE players p
            SET position_code  = b.position_code,
                date_of_birth  = b.date_of_birth,
                uniform_number = b.uniform_number,
                nationality    = COALESCE(p.nationality, b.nationality)
            FROM bio b
            WHERE b.player_id = p.player_id
        """)
        conn.commit()
        n = cur.rowcount
        print(f"UPDATE rows affected: {n}")

        # 5) post-backfill verification
        cur.execute("""
            SELECT
                COUNT(*)                                              AS total,
                COUNT(*) FILTER (WHERE position_code IS NOT NULL)    AS pos,
                COUNT(*) FILTER (WHERE date_of_birth IS NOT NULL)    AS dob,
                COUNT(*) FILTER (WHERE uniform_number IS NOT NULL)   AS uni
            FROM players
        """)
        total, pos, dob, uni = cur.fetchone()
        print(f"PLAYERS dimension after backfill (total={total}):")
        print(f"  position_code : {pos} ({100*pos/total:.1f}%)")
        print(f"  date_of_birth : {dob} ({100*dob/total:.1f}%)")
        print(f"  uniform_number: {uni} ({100*uni/total:.1f}%)")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
