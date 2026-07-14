"""NBACore v8 — Human-review helper for the games.game_id -> BR migration.

Prints a distribution of game_id formats and join-key integrity for the two
recent seasons (and, optionally, all seasons) so a reviewer can eyeball the
result of scripts/migrate_games_gameid_to_br.py.

Usage:
    python scripts/verify_migration.py
"""
from __future__ import annotations

import re

import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG: dict = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

SEASONS: tuple[int, int] = (2025, 2026)
BR_RE: str = r"^\d{8,}[A-Z]{3}$"
NUMERIC_RE: str = r"^\d+$"


def _dist(cur: RealDictCursor, where: str, params: tuple) -> dict:
    cur.execute(
        f"""
        SELECT
            count(*)                                            AS total,
            count(*) FILTER (WHERE game_id ~ %s)                AS br_format,
            count(*) FILTER (WHERE game_id ~ %s)                AS numeric,
            count(*) FILTER (WHERE game_id !~ %s AND game_id !~ %s) AS other,
            count(*) FILTER (WHERE nba_api_id IS NULL)          AS nba_api_null
        FROM games
        {where}
        """,
        (BR_RE, NUMERIC_RE, BR_RE, NUMERIC_RE) + params,
    )
    return dict(cur.fetchone())


def _dup_groups(cur: RealDictCursor, where: str, params: tuple) -> int:
    cur.execute(
        f"""
        SELECT count(*) AS c FROM (
            SELECT game_id FROM games {where}
            GROUP BY game_id HAVING count(*) > 1
        ) d
        """,
        params,
    )
    return cur.fetchone()["c"]


def main() -> None:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        print("=" * 64)
        print("games.game_id MIGRATION VERIFICATION")
        print("=" * 64)

        recent = _dist(cur, "WHERE season IN %s", (SEASONS,))
        recent_dup = _dup_groups(cur, "WHERE season IN %s", (SEASONS,))
        print(f"\nRECENT SEASONS {SEASONS}")
        print(f"  total rows      : {recent['total']}")
        print(f"  BR-format id    : {recent['br_format']}")
        print(f"  numeric id      : {recent['numeric']}")
        print(f"  other (non-std) : {recent['other']}")
        print(f"  nba_api_id NULL : {recent['nba_api_null']}")
        print(f"  duplicate groups: {recent_dup}")

        overall = _dist(cur, "", ())
        overall_dup = _dup_groups(cur, "", ())
        print(f"\nALL SEASONS")
        print(f"  total rows      : {overall['total']}")
        print(f"  BR-format id    : {overall['br_format']}")
        print(f"  numeric id      : {overall['numeric']}")
        print(f"  other (non-std) : {overall['other']}")
        print(f"  nba_api_id NULL : {overall['nba_api_null']}")
        print(f"  duplicate groups: {overall_dup}")

        # samples
        cur.execute(
            "SELECT game_id FROM games WHERE season IN %s AND game_id ~ %s LIMIT 3",
            (SEASONS, BR_RE),
        )
        br_samples = [r["game_id"] for r in cur.fetchall()]
        cur.execute(
            "SELECT game_id FROM games WHERE season IN %s AND game_id ~ %s LIMIT 3",
            (SEASONS, NUMERIC_RE),
        )
        num_samples = [r["game_id"] for r in cur.fetchall()]
        print(f"\n  sample BR ids   : {br_samples}")
        print(f"  sample numeric  : {num_samples}")

        # backup table presence
        cur.execute(
            "SELECT count(*) AS c FROM information_schema.tables "
            "WHERE table_name = 'games_bak_pre_br'"
        )
        bak_exists = cur.fetchone()["c"] == 1
        if bak_exists:
            cur.execute("SELECT count(*) AS c FROM games_bak_pre_br")
            print(f"  backup table    : games_bak_pre_br ({cur.fetchone()['c']} rows)")
        else:
            print("  backup table    : (not found)")

        print("\nVERDICT:")
        ok = (
            recent["other"] == 0
            and recent_dup == 0
            and recent["nba_api_null"] == 0
            and recent["br_format"] > 0
        )
        print("  PASS" if ok else "  CHECK NEEDED")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
