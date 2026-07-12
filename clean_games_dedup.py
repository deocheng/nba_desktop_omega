"""games 表安全清理（仅 Regular Season）：

1) 恢复 home_team_abbr=NULL 的行：game_id 后缀即 BR 主场缩写，100% 安全恢复，不删数据。
2) 删除同日同队「主客互换」重复：一场比赛不可能同日既 A@B 又 B@A，必有一行是幻影。
   保留规则（确定性）：优先有 nba_api_id -> 其次 source='BBRef' -> 再次 game_id 字典序最小。

dry_run=True 时只统计不修改。
"""
import psycopg2
import sys

DB = dict(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')
VALID = ('ATL','BOS','BRK','CHO','CLE','DAL','DEN','DET','GSW','HOU','IND','LAC','LAL',
         'MEM','MIA','MIL','MIN','NOP','NYK','OKC','ORL','PHI','PHO','POR','SAC','SAS','TOR','UTA','WAS')
DRY = '--dry' in sys.argv

def main():
    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    cur = conn.cursor()

    # ---- before counts ----
    cur.execute("SELECT count(*) FROM dim_games WHERE season_type='Regular Season'")
    before = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM dim_games
                   WHERE home_team_abbr IS NULL AND RIGHT(game_id,3) IN %s""", (VALID,))
    home_null = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM dim_games a JOIN dim_games b
                   ON a.game_date=b.game_date AND a.home_team_abbr=b.away_team_abbr
                      AND a.away_team_abbr=b.home_team_abbr AND a.season=b.season AND a.season_type=b.season_type
                   WHERE a.season_type='Regular Season' AND a.home_team_abbr<a.away_team_abbr AND a.ctid<>b.ctid""")
    swapped = cur.fetchone()[0]
    print(f"[before] RS rows={before}  home_null_recoverable={home_null}  swapped_dup_pairs={swapped}")

    if DRY:
        print("DRY RUN - no changes.")
        conn.close()
        return

    # ---- Phase A: recover home from game_id suffix ----
    cur.execute("""UPDATE dim_games
                   SET home_team_abbr = RIGHT(game_id,3)
                   WHERE home_team_abbr IS NULL AND RIGHT(game_id,3) IN %s""", (VALID,))
    a_n = cur.rowcount
    print(f"[A] recovered home_team_abbr for {a_n} rows")

    # ---- Phase B: delete one row per swapped pair ----
    cur.execute("""DELETE FROM dim_games
                   WHERE ctid = ANY(ARRAY(
                     SELECT ctid_to_delete FROM (
                       SELECT a.ctid AS ctid_to_delete,
                         ROW_NUMBER() OVER (
                           PARTITION BY a.game_date,
                             LEAST(a.home_team_abbr,a.away_team_abbr),
                             GREATEST(a.home_team_abbr,a.away_team_abbr), a.season
                           ORDER BY (CASE WHEN a.nba_api_id IS NOT NULL THEN 0 ELSE 1 END),
                                   (CASE WHEN a.source='BBRef' THEN 0 ELSE 1 END),
                                   a.game_id) AS rn
                       FROM dim_games a
                       JOIN dim_games b
                         ON a.game_date=b.game_date AND a.home_team_abbr=b.away_team_abbr
                            AND a.away_team_abbr=b.home_team_abbr AND a.season=b.season
                            AND a.season_type=b.season_type AND a.ctid<>b.ctid
                       WHERE a.season_type='Regular Season'
                     ) x WHERE rn > 1
                   ))""")
    b_n = cur.rowcount
    print(f"[B] deleted {b_n} swapped-duplicate rows")

    conn.commit()

    # ---- after counts ----
    cur.execute("SELECT count(*) FROM dim_games WHERE season_type='Regular Season'")
    after = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM dim_games
                   WHERE home_team_abbr IS NULL AND RIGHT(game_id,3) IN %s""", (VALID,))
    home_null_after = cur.fetchone()[0]
    print(f"[after ] RS rows={after}  (removed {before-after})  home_null_recoverable={home_null_after}")

    # per-team total sanity for the two affected seasons
    for s in (2024, 2026):
        cur.execute("""SELECT COUNT(*) FILTER (WHERE tot!=82) FROM (
                         SELECT COALESCE(h.home,0)+COALESCE(aw.away,0) AS tot FROM
                           (SELECT home_team_abbr t, count(*) home FROM dim_games
                            WHERE season=%s AND season_type='Regular Season' GROUP BY 1) h
                           FULL JOIN (SELECT away_team_abbr t, count(*) away FROM dim_games
                            WHERE season=%s AND season_type='Regular Season' GROUP BY 1) aw USING(t)
                       ) x""", (s, s))
        bad = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM dim_games WHERE season=%s AND season_type='Regular Season'", (s,))
        tot = cur.fetchone()[0]
        print(f"  season={s}: RS={tot}  teams_with_total!=82={bad}")
    conn.close()

if __name__ == '__main__':
    main()
