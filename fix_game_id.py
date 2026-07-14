import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.core import config

BR_REGEX = '^[0-9]{9}[A-Z]{3}$'

def main():
    force = '--force' in sys.argv

    print("=" * 70)
    print("Game ID Unification Script (BR Format)")
    print("=" * 70)
    print("\nBR format: YYYYMMDD0TEAM (e.g., 202510220BOS)")
    print("Pattern: 9 digits + 3 uppercase letters")
    print("This script will convert pure numeric game_id to BR format.")
    print("Already in BR format, missing data, or conflicts will be preserved.\n")

    conn = psycopg2.connect(**config.DB_CONFIG, cursor_factory=RealDictCursor)

    try:
        cur = conn.cursor()

        print("1. Analyzing games table...")
        cur.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN game_id ~ '{BR_REGEX}' THEN 1 ELSE 0 END) as br_format_count,
                SUM(CASE WHEN game_id ~ '^[0-9]+$' THEN 1 ELSE 0 END) as numeric_count,
                SUM(CASE WHEN game_id !~ '^[0-9]+$' AND game_id !~ '{BR_REGEX}' THEN 1 ELSE 0 END) as other_count
            FROM games
        """)
        result = cur.fetchone()
        total = result['total']
        br_format_count = result['br_format_count']
        numeric_count = result['numeric_count']
        other_count = result['other_count']
        
        print(f"   Total games: {total}")
        print(f"   Already BR format (YYYYMMDD0TEAM): {br_format_count}")
        print(f"   Pure numeric (need conversion): {numeric_count}")
        print(f"   Other format: {other_count}")

        print("\n2. Checking for conflicts...")
        cur.execute("""
            SELECT COUNT(*) as conflict_count
            FROM games g1
            WHERE g1.game_id ~ '^[0-9]+$'
              AND g1.game_date IS NOT NULL 
              AND g1.home_team_abbr IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM games g2
                  WHERE g2.game_id = TO_CHAR(g1.game_date, 'YYYYMMDD') || '0' || g1.home_team_abbr
              )
        """)
        id_conflict_count = cur.fetchone()['conflict_count']

        cur.execute("""
            SELECT COUNT(*) as dup_group_count
            FROM games g1
            WHERE g1.game_id ~ '^[0-9]+$'
              AND g1.game_date IS NOT NULL 
              AND g1.home_team_abbr IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM games g2
                  WHERE g2.game_date = g1.game_date 
                    AND g2.home_team_abbr = g1.home_team_abbr
                    AND g2.game_id != g1.game_id
              )
        """)
        dup_group_count = cur.fetchone()['dup_group_count']
        
        print(f"   Target BR ID already exists: {id_conflict_count}")
        print(f"   In duplicate date+home group: {dup_group_count}")

        print("\n3. Analyzing conversion feasibility...")
        cur.execute("""
            SELECT 
                COUNT(*) as total_numeric,
                SUM(CASE WHEN game_date IS NOT NULL AND home_team_abbr IS NOT NULL THEN 1 ELSE 0 END) as can_convert,
                SUM(CASE WHEN game_date IS NULL THEN 1 ELSE 0 END) as missing_date,
                SUM(CASE WHEN home_team_abbr IS NULL THEN 1 ELSE 0 END) as missing_team
            FROM games
            WHERE game_id ~ '^[0-9]+$'
        """)
        result = cur.fetchone()
        total_numeric = result['total_numeric']
        can_convert = result['can_convert']
        missing_date = result['missing_date']
        missing_team = result['missing_team']

        cur.execute("""
            SELECT COUNT(*) as safe_count
            FROM games g1
            WHERE g1.game_id ~ '^[0-9]+$'
              AND g1.game_date IS NOT NULL 
              AND g1.home_team_abbr IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM games g2
                  WHERE g2.game_id = TO_CHAR(g1.game_date, 'YYYYMMDD') || '0' || g1.home_team_abbr
              )
              AND NOT EXISTS (
                  SELECT 1 FROM games g2
                  WHERE g2.game_date = g1.game_date 
                    AND g2.home_team_abbr = g1.home_team_abbr
                    AND g2.game_id != g1.game_id
              )
        """)
        safe_count = cur.fetchone()['safe_count']
        
        print(f"   Can be converted (has date + home_team_abbr): {can_convert}")
        print(f"   Missing game_date: {missing_date}")
        print(f"   Missing home_team_abbr: {missing_team}")
        print(f"   Safe to convert: {safe_count}")

        if safe_count > 0:
            print("\n   Sample conversions:")
            cur.execute("""
                SELECT game_id, game_date, home_team_abbr,
                       TO_CHAR(game_date, 'YYYYMMDD') || '0' || home_team_abbr as br_format
                FROM games g1
                WHERE g1.game_id ~ '^[0-9]+$'
                  AND g1.game_date IS NOT NULL 
                  AND g1.home_team_abbr IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM games g2
                      WHERE g2.game_id = TO_CHAR(g1.game_date, 'YYYYMMDD') || '0' || g1.home_team_abbr
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM games g2
                      WHERE g2.game_date = g1.game_date 
                        AND g2.home_team_abbr = g1.home_team_abbr
                        AND g2.game_id != g1.game_id
                  )
                LIMIT 5
            """)
            for row in cur.fetchall():
                print(f"     {row['game_id']} -> {row['br_format']}")

        print("\n4. Analyzing dim_games table...")
        cur.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN game_id ~ '{BR_REGEX}' THEN 1 ELSE 0 END) as br_format_count,
                SUM(CASE WHEN game_id ~ '^[0-9]+$' THEN 1 ELSE 0 END) as numeric_count
            FROM dim_games
        """)
        result = cur.fetchone()
        dim_total = result['total']
        dim_br_format_count = result['br_format_count']
        dim_numeric_count = result['numeric_count']
        
        print(f"   Total dim_games: {dim_total}")
        print(f"   Already BR format: {dim_br_format_count}")
        print(f"   Pure numeric (need conversion): {dim_numeric_count}")

        if not force:
            print("\n" + "=" * 70)
            print("Run with --force flag to execute the update.")
            print("Example: python fix_game_id.py --force")
            return

        print("\n" + "=" * 70)
        print("EXECUTING UPDATE...")
        print("=" * 70)

        print("\n5. Updating games table...")
        cur.execute("""
            UPDATE games 
            SET game_id = TO_CHAR(game_date, 'YYYYMMDD') || '0' || home_team_abbr 
            WHERE game_id ~ '^[0-9]+$'
              AND game_date IS NOT NULL 
              AND home_team_abbr IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM games g2
                  WHERE g2.game_id = TO_CHAR(games.game_date, 'YYYYMMDD') || '0' || games.home_team_abbr
              )
              AND NOT EXISTS (
                  SELECT 1 FROM games g2
                  WHERE g2.game_date = games.game_date 
                    AND g2.home_team_abbr = games.home_team_abbr
                    AND g2.game_id != games.game_id
              )
        """)
        updated = cur.rowcount
        print(f"   Updated {updated} rows to BR format")

        print("\n6. Updating dim_games table...")
        cur.execute("""
            UPDATE dim_games 
            SET game_id = TO_CHAR(game_date, 'YYYYMMDD') || '0' || home_team_abbr 
            WHERE game_id ~ '^[0-9]+$'
              AND game_date IS NOT NULL 
              AND home_team_abbr IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM dim_games g2
                  WHERE g2.game_id = TO_CHAR(dim_games.game_date, 'YYYYMMDD') || '0' || dim_games.home_team_abbr
              )
              AND NOT EXISTS (
                  SELECT 1 FROM dim_games g2
                  WHERE g2.game_date = dim_games.game_date 
                    AND g2.home_team_abbr = dim_games.home_team_abbr
                    AND g2.game_id != dim_games.game_id
              )
        """)
        updated = cur.rowcount
        print(f"   Updated {updated} rows to BR format")

        conn.commit()
        print("\n7. Verification...")
        
        cur.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN game_id ~ '{BR_REGEX}' THEN 1 ELSE 0 END) as br_format_count,
                SUM(CASE WHEN game_id ~ '^[0-9]+$' THEN 1 ELSE 0 END) as numeric_count
            FROM games
        """)
        result = cur.fetchone()
        print(f"   games table:")
        print(f"     Total: {result['total']}")
        print(f"     BR format: {result['br_format_count']}")
        print(f"     Numeric (unchanged): {result['numeric_count']}")
        
        cur.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN game_id ~ '{BR_REGEX}' THEN 1 ELSE 0 END) as br_format_count,
                SUM(CASE WHEN game_id ~ '^[0-9]+$' THEN 1 ELSE 0 END) as numeric_count
            FROM dim_games
        """)
        result = cur.fetchone()
        print(f"   dim_games table:")
        print(f"     Total: {result['total']}")
        print(f"     BR format: {result['br_format_count']}")
        print(f"     Numeric (unchanged): {result['numeric_count']}")

        print("\n✅ SUCCESS: Game ID unification completed.")

    finally:
        conn.close()

    print("\n" + "=" * 70)
    print("Script completed.")

if __name__ == "__main__":
    main()
