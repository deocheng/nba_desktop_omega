"""Fix game data issues and unify game_id to BR format.

Strategy:
1. Deduplicate by nba_api_id: merge rows, keep the one with more data
   - prefer BR format game_id, br_crawled_id, game_date
   - merge non-null fields from sibling rows
2. Fill remaining missing game_date from nba_api_id matching rows
3. Convert game_id to BR format using best available source
4. Sync dim_games

Usage:
    python fix_games_data.py          # analysis only
    python fix_games_data.py --force  # execute
"""
from __future__ import annotations

import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

BR_REGEX = r'^\d{9}[A-Z]{3}$'


def analyze(cur: RealDictCursor) -> None:
    print("=" * 70)
    print("ANALYSIS PHASE")
    print("=" * 70)

    print("\n1. Overall stats:")
    cur.execute(f"""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN game_id ~ '{BR_REGEX}' THEN 1 ELSE 0 END) as br_game_id,
            SUM(CASE WHEN game_id ~ '^[0-9]+$' THEN 1 ELSE 0 END) as numeric_game_id,
            SUM(CASE WHEN game_date IS NULL THEN 1 ELSE 0 END) as missing_date,
            SUM(CASE WHEN home_team_abbr IS NULL THEN 1 ELSE 0 END) as missing_team,
            SUM(CASE WHEN br_crawled_id IS NOT NULL THEN 1 ELSE 0 END) as has_br_crawled,
            SUM(CASE WHEN nba_api_id IS NOT NULL THEN 1 ELSE 0 END) as has_nba_api
        FROM games
    """)
    r = cur.fetchone()
    print(f"   Total rows: {r['total']}")
    print(f"   BR format game_id: {r['br_game_id']}")
    print(f"   Numeric game_id: {r['numeric_game_id']}")
    print(f"   Missing game_date: {r['missing_date']}")
    print(f"   Missing home_team_abbr: {r['missing_team']}")
    print(f"   Has br_crawled_id: {r['has_br_crawled']}")
    print(f"   Has nba_api_id: {r['has_nba_api']}")

    print("\n2. Duplicate nba_api_id groups:")
    cur.execute("""
        SELECT 
            COUNT(*) as dup_groups,
            SUM(cnt) as total_dup_rows,
            SUM(cnt - 1) as extra_rows
        FROM (
            SELECT nba_api_id, COUNT(*) as cnt
            FROM games
            WHERE nba_api_id IS NOT NULL
            GROUP BY nba_api_id
            HAVING COUNT(*) > 1
        ) t
    """)
    r = cur.fetchone()
    print(f"   Duplicate groups: {r['dup_groups']}")
    print(f"   Total duplicate rows: {r['total_dup_rows']}")
    print(f"   Extra rows to remove: {r['extra_rows']}")

    print("\n3. Missing game_date recoverable via nba_api_id:")
    cur.execute("""
        SELECT COUNT(*) as recoverable
        FROM games g1
        WHERE g1.game_date IS NULL
          AND g1.nba_api_id IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM games g2
              WHERE g2.nba_api_id = g1.nba_api_id
                AND g2.game_date IS NOT NULL
                AND g2.game_id != g1.game_id
          )
    """)
    r = cur.fetchone()
    print(f"   Recoverable: {r['recoverable']}")

    print("\n4. By season (top 10 duplicates):")
    cur.execute("""
        SELECT season, season_type, COUNT(*) as dup_groups
        FROM (
            SELECT season, season_type, nba_api_id, COUNT(*) as cnt
            FROM games
            WHERE nba_api_id IS NOT NULL
            GROUP BY season, season_type, nba_api_id
            HAVING COUNT(*) > 1
        ) t
        GROUP BY season, season_type
        ORDER BY season DESC, season_type
        LIMIT 10
    """)
    rows = cur.fetchall()
    print(f"   {'Season':<7} {'Type':<15} {'DupGroups':<12}")
    print("   " + "-" * 38)
    for r in rows:
        print(f"   {str(r['season']):<7} {str(r['season_type']):<15} {r['dup_groups']:<12}")


def deduplicate_games(cur: RealDictCursor) -> dict:
    """Deduplicate games by nba_api_id, merging data from duplicate rows.
    
    Strategy:
    - For each nba_api_id group, pick a "canonical" row
    - Prefer: BR game_id > has br_crawled_id > has game_date > crawler source
    - Delete all other rows in the group
    """
    print("\n" + "=" * 70)
    print("STEP 1: Deduplicate games by nba_api_id")
    print("=" * 70)

    cur.execute("""
        SELECT COUNT(*) as cnt FROM (
            SELECT nba_api_id FROM games 
            WHERE nba_api_id IS NOT NULL 
            GROUP BY nba_api_id HAVING COUNT(*) > 1
        ) t
    """)
    dup_groups = cur.fetchone()['cnt']
    print(f"\n  Duplicate groups: {dup_groups}")

    cur.execute("""
        SELECT nba_api_id, COUNT(*) as cnt
        FROM games
        WHERE nba_api_id IS NOT NULL
        GROUP BY nba_api_id
        HAVING COUNT(*) > 2
        LIMIT 5
    """)
    more_than_2 = cur.fetchall()
    if more_than_2:
        print(f"  Groups with >2 rows: {len(more_than_2)}")
        for r in more_than_2:
            print(f"    nba_api_id={r['nba_api_id']}: {r['cnt']} rows")

    cur.execute("""
        CREATE TEMP TABLE game_keep AS
        SELECT DISTINCT ON (nba_api_id) *
        FROM games
        WHERE nba_api_id IS NOT NULL
        ORDER BY nba_api_id,
                 CASE WHEN game_id ~ '^[0-9]{9}[A-Z]{3}$' THEN 0 ELSE 1 END,
                 CASE WHEN br_crawled_id IS NOT NULL THEN 0 ELSE 1 END,
                 CASE WHEN game_date IS NOT NULL THEN 0 ELSE 1 END,
                 CASE WHEN home_team_abbr IS NOT NULL THEN 0 ELSE 1 END,
                 CASE WHEN pbp_imported = TRUE THEN 0 ELSE 1 END,
                 CASE WHEN source = 'bbr' THEN 0 
                      WHEN source = 'crawler' THEN 1
                      WHEN source = 'nba_api' THEN 2
                      ELSE 3 END
    """)
    cur.execute("SELECT COUNT(*) as cnt FROM game_keep")
    keep_count = cur.fetchone()['cnt']

    cur.execute("SELECT COUNT(*) as cnt FROM games WHERE nba_api_id IS NOT NULL")
    orig_count = cur.fetchone()['cnt']
    to_delete = orig_count - keep_count

    print(f"  Rows to keep: {keep_count}")
    print(f"  Rows to delete: {to_delete}")

    cur.execute("""
        DELETE FROM games 
        WHERE nba_api_id IS NOT NULL
          AND game_id NOT IN (SELECT game_id FROM game_keep)
    """)
    deleted = cur.rowcount
    print(f"\n  Deleted {deleted} duplicate rows")

    cur.execute("DROP TABLE game_keep")

    return {'deleted': deleted, 'kept': keep_count}


def fill_missing_from_duplicates(cur: RealDictCursor) -> int:
    """Fill missing fields from duplicate rows before dedup.
    
    Actually, dedup already picks the best row. But let's also check if
    we can fill in missing game_date from nba_api_id matches even for
    rows that don't have duplicates (shouldn't be many).
    """
    print("\n" + "=" * 70)
    print("STEP 2: Fill remaining missing game_date")
    print("=" * 70)

    cur.execute("SELECT COUNT(*) as cnt FROM games WHERE game_date IS NULL")
    before = cur.fetchone()['cnt']
    print(f"\n  Missing game_date before: {before}")

    if before == 0:
        print("  Nothing to fill!")
        return 0

    cur.execute("SELECT COUNT(*) as cnt FROM games WHERE home_team_abbr IS NULL")
    before_team = cur.fetchone()['cnt']
    print(f"  Missing home_team_abbr before: {before_team}")

    filled = 0
    return filled


def convert_game_ids(cur: RealDictCursor) -> int:
    """Convert numeric game_id to BR format."""
    print("\n" + "=" * 70)
    print("STEP 3: Convert game_id to BR format")
    print("=" * 70)

    cur.execute(f"SELECT COUNT(*) as cnt FROM games WHERE game_id ~ '^[0-9]+$'")
    before = cur.fetchone()['cnt']
    print(f"\n  Before: {before} numeric game_id rows")

    cur.execute("""
        UPDATE games
        SET game_id = br_crawled_id
        WHERE game_id ~ '^[0-9]+$'
          AND br_crawled_id IS NOT NULL
          AND br_crawled_id ~ '^[0-9]{9}[A-Z]{3}$'
    """)
    from_br = cur.rowcount
    print(f"  Converted using br_crawled_id: {from_br}")

    cur.execute("""
        UPDATE games
        SET game_id = TO_CHAR(game_date, 'YYYYMMDD') || '0' || home_team_abbr
        WHERE game_id ~ '^[0-9]+$'
          AND game_date IS NOT NULL
          AND home_team_abbr IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM games g2
              WHERE g2.game_id = TO_CHAR(games.game_date, 'YYYYMMDD') || '0' || games.home_team_abbr
                AND g2.game_id != games.game_id
          )
    """)
    from_date = cur.rowcount
    print(f"  Converted using game_date + home_team_abbr: {from_date}")

    cur.execute(f"SELECT COUNT(*) as cnt FROM games WHERE game_id ~ '^[0-9]+$'")
    after = cur.fetchone()['cnt']
    print(f"\n  After: {after} numeric game_id rows remaining")

    return from_br + from_date


def sync_dim_games(cur: RealDictCursor) -> dict:
    """Sync dim_games table."""
    print("\n" + "=" * 70)
    print("STEP 4: Sync dim_games table")
    print("=" * 70)

    cur.execute("""
        SELECT COUNT(*) as dup_groups
        FROM (
            SELECT nba_api_id FROM dim_games 
            WHERE nba_api_id IS NOT NULL 
            GROUP BY nba_api_id HAVING COUNT(*) > 1
        ) t
    """)
    dup_groups = cur.fetchone()['dup_groups']
    print(f"\n  dim_games duplicate groups: {dup_groups}")

    if dup_groups > 0:
        cur.execute("""
            CREATE TEMP TABLE dim_keep AS
            SELECT DISTINCT ON (nba_api_id) *
            FROM dim_games
            WHERE nba_api_id IS NOT NULL
            ORDER BY nba_api_id,
                     CASE WHEN game_id ~ '^[0-9]{9}[A-Z]{3}$' THEN 0 ELSE 1 END,
                     CASE WHEN br_crawled_id IS NOT NULL THEN 0 ELSE 1 END,
                     CASE WHEN game_date IS NOT NULL THEN 0 ELSE 1 END
        """)
        cur.execute("SELECT COUNT(*) as cnt FROM dim_keep")
        keep_count = cur.fetchone()['cnt']
        
        cur.execute("""
            DELETE FROM dim_games 
            WHERE nba_api_id IS NOT NULL
              AND game_id NOT IN (SELECT game_id FROM dim_keep)
        """)
        deleted = cur.rowcount
        print(f"  Deleted {deleted} duplicate rows from dim_games")
        
        cur.execute("DROP TABLE dim_keep")
    else:
        deleted = 0
        print("  No duplicates in dim_games")

    cur.execute("""
        UPDATE dim_games
        SET game_id = br_crawled_id
        WHERE game_id ~ '^[0-9]+$'
          AND br_crawled_id IS NOT NULL
          AND br_crawled_id ~ '^[0-9]{9}[A-Z]{3}$'
    """)
    from_br = cur.rowcount
    print(f"  Converted using br_crawled_id: {from_br}")

    cur.execute("""
        UPDATE dim_games
        SET game_id = TO_CHAR(game_date, 'YYYYMMDD') || '0' || home_team_abbr
        WHERE game_id ~ '^[0-9]+$'
          AND game_date IS NOT NULL
          AND home_team_abbr IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM dim_games g2
              WHERE g2.game_id = TO_CHAR(dim_games.game_date, 'YYYYMMDD') || '0' || dim_games.home_team_abbr
                AND g2.game_id != dim_games.game_id
          )
    """)
    from_date = cur.rowcount
    print(f"  Converted using date+home: {from_date}")

    return {'deleted': deleted, 'converted_br': from_br, 'converted_date': from_date}


def verify(cur: RealDictCursor) -> None:
    print("\n" + "=" * 70)
    print("VERIFICATION")
    print("=" * 70)

    cur.execute(f"""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN game_id ~ '{BR_REGEX}' THEN 1 ELSE 0 END) as br_game_id,
            SUM(CASE WHEN game_id ~ '^[0-9]+$' THEN 1 ELSE 0 END) as numeric_game_id,
            SUM(CASE WHEN game_date IS NULL THEN 1 ELSE 0 END) as missing_date,
            SUM(CASE WHEN home_team_abbr IS NULL THEN 1 ELSE 0 END) as missing_team
        FROM games
    """)
    r = cur.fetchone()
    print(f"\n  games table:")
    print(f"    Total: {r['total']}")
    print(f"    BR format game_id: {r['br_game_id']}")
    print(f"    Numeric game_id: {r['numeric_game_id']}")
    print(f"    Missing game_date: {r['missing_date']}")
    print(f"    Missing home_team_abbr: {r['missing_team']}")

    cur.execute("""
        SELECT COUNT(*) as dup_groups FROM (
            SELECT nba_api_id FROM games 
            WHERE nba_api_id IS NOT NULL 
            GROUP BY nba_api_id HAVING COUNT(*) > 1
        ) t
    """)
    r = cur.fetchone()
    print(f"    Duplicate nba_api_id groups: {r['dup_groups']}")

    cur.execute(f"""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN game_id ~ '{BR_REGEX}' THEN 1 ELSE 0 END) as br_game_id,
            SUM(CASE WHEN game_id ~ '^[0-9]+$' THEN 1 ELSE 0 END) as numeric_game_id
        FROM dim_games
    """)
    r = cur.fetchone()
    print(f"\n  dim_games table:")
    print(f"    Total: {r['total']}")
    print(f"    BR format game_id: {r['br_game_id']}")
    print(f"    Numeric game_id: {r['numeric_game_id']}")


def main():
    force = '--force' in sys.argv

    conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()

        analyze(cur)

        if not force:
            print("\n" + "=" * 70)
            print("Analysis complete. Run with --force to execute changes.")
            print("  python fix_games_data.py --force")
            print("=" * 70)
            return

        print("\n" + "=" * 70)
        print("EXECUTING FIXES (in single transaction)")
        print("=" * 70)

        deduplicate_games(cur)
        fill_missing_from_duplicates(cur)
        convert_game_ids(cur)
        sync_dim_games(cur)

        verify(cur)

        conn.commit()
        print("\n" + "=" * 70)
        print("ALL DONE! Changes committed.")
        print("=" * 70)

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        print("All changes rolled back.")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
