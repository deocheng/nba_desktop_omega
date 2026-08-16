#!/usr/bin/env python3
"""
从 PBP 回填 houstca01 (Caleb Houstan) 缺失的 player_gamelog 行 (2023/2024 RS)。

仅 INSERT 缺口场:
  PBP 有事件 + dim_games.season_type='Regular Season' + player_gamelog 无对应行。
绝不覆盖已存在的准确 BR 行。

字段来源 / 精度:
- fg/fga/fg3/fga3/ft/fta/pts/trb(orb/drb)/tov/pf : event_type 聚合 (可靠)
- stl/blk                                       : description 正则 (steal by / blocks)
- ast / plus_minus                              : 本 PBP 数据集未抓 -> 留 NULL (不伪造)
- minutes / seconds_played                      : 事件时钟跨度近似 (PBP-estimated, 精度有限)
"""
import psycopg2
import os
import argparse
from dotenv import load_dotenv

load_dotenv()

BR_ID = 'houstca01'


def get_conn():
    return psycopg2.connect(
        host='127.0.0.1', port=5433, dbname='nba',
        user='postgres', password=os.environ.get('DB_PASSWORD'),
    )


def backfill(season: int, dry_run: bool) -> int:
    conn = get_conn()
    cur = conn.cursor()
    part = f'play_by_play_p_{season}'

    # 1) 找缺口场 (PBP 有 + RS + gamelog 无)
    cur.execute(f"""
        SELECT pbp.gameid
        FROM {part} pbp
        JOIN dim_games d ON d.nba_api_id = pbp.gameid::bigint
        LEFT JOIN player_gamelog pg
            ON pg.gameid = pbp.gameid
           AND pg.br_player_id = '{BR_ID}' AND pg.season = {season}
        WHERE pbp.br_player_id = '{BR_ID}'
          AND d.season_type = 'Regular Season'
          AND pg.gameid IS NULL
        GROUP BY pbp.gameid
        ORDER BY pbp.gameid
    """)
    missing = [r[0] for r in cur.fetchall()]
    print(f"[season {season}] PBP RS 缺口场: {len(missing)} 场")
    inserted = 0

    for gid in missing:
        # 2) 聚合 box score
        cur.execute(f"""
            SELECT
              count(*) FILTER (WHERE event_type='Made Shot' AND description !~* '3-pt|3pt') AS fg,
              count(*) FILTER (WHERE event_type IN ('Made Shot','Missed Shot') AND description !~* '3-pt|3pt') AS fga,
              count(*) FILTER (WHERE event_type='Made Shot' AND description ~* '3-pt|3pt') AS fg3,
              count(*) FILTER (WHERE event_type IN ('Made Shot','Missed Shot') AND description ~* '3-pt|3pt') AS fga3,
              count(*) FILTER (WHERE event_type='Free Throw' AND description ~* 'makes free throw') AS ft,
              count(*) FILTER (WHERE event_type='Free Throw') AS fta,
              SUM(CASE WHEN event_type='Made Shot' AND description ~* '3-pt|3pt' THEN 3
                       WHEN event_type='Made Shot' AND description !~* '3-pt|3pt' THEN 2
                       WHEN event_type='Free Throw' AND description ~* 'makes free throw' THEN 1 ELSE 0 END) AS pts,
              count(*) FILTER (WHERE event_type='Rebound' AND (subtype LIKE '%%Off%%' OR subtype LIKE '%%ORB%%')) AS orb,
              count(*) FILTER (WHERE event_type='Rebound' AND (subtype NOT LIKE '%%Off%%' AND subtype NOT LIKE '%%ORB%%')) AS drb,
              count(*) FILTER (WHERE event_type='Rebound') AS trb,
              count(*) FILTER (WHERE event_type='Turnover') AS tov,
              count(*) FILTER (WHERE event_type='Foul') AS pf,
              count(*) FILTER (WHERE description ~* 'steal by c\\. houstan') AS stl,
              count(*) FILTER (WHERE description ~* 'houstan blocks|block by c\\. houstan') AS blk,
              (SELECT team FROM {part} WHERE br_player_id='{BR_ID}' AND gameid=%s AND team IS NOT NULL LIMIT 1) AS team
            FROM {part}
            WHERE br_player_id='{BR_ID}' AND gameid=%s
        """, (gid, gid))
        row = cur.fetchone()
        fg, fga, fg3, fga3, ft, fta, pts, orb, drb, trb, tov, pf, stl, blk, team = row

        # 3) minutes 估算: 每节事件时钟跨度 (clock_seconds = 该节剩余秒)
        cur.execute(f"""
            SELECT period, min(clock_seconds), max(clock_seconds)
            FROM {part}
            WHERE br_player_id='{BR_ID}' AND gameid=%s AND clock_seconds IS NOT NULL
            GROUP BY period
        """, (gid,))
        span_min = 0.0
        for _period, mn, mx in cur.fetchall():
            if mn is not None and mx is not None:
                span_min += max(0.0, (mx - mn)) / 60.0
        secs = int(round(span_min * 60))
        minutes = f"{secs // 60}:{secs % 60:02d}"

        # 4) 辅助信息
        cur.execute(
            "SELECT game_id, home_team_abbr, away_team_abbr FROM dim_games WHERE nba_api_id=%s::bigint",
            (gid,),
        )
        g = cur.fetchone()
        game_id_full = g[0] if g else None
        if not team:
            team = 'ORL'
        cur.execute("SELECT player_name FROM dim_players WHERE player_id=%s", (BR_ID,))
        pn = cur.fetchone()
        player_name = pn[0] if pn else 'Caleb Houstan'
        cur.execute("SELECT nba_player_id FROM player_id_bridge WHERE br_player_id=%s", (BR_ID,))
        nb = cur.fetchone()
        nba_pid = nb[0] if nb else None

        fg_pct = round(fg / fga, 3) if fga else None
        ft_pct = round(ft / fta, 3) if fta else None
        fg3_pct = round(fg3 / fga3, 3) if fga3 else None

        if dry_run:
            print(f"  [dry] {gid} {game_id_full} {team} min={minutes}(est) "
                  f"fg{fg}/{fga} 3p{fg3}/{fga3} ft{ft}/{fta} reb{trb}(o{orb}/d{drb}) "
                  f"tov{tov} pf{pf} stl{stl} blk{blk} pts{pts} (ast/pm=NULL)")
            continue

        cur.execute("""
            INSERT INTO player_gamelog
            (gameid, player, team, season, fg, fga, fg3, fga3, ft, fta, pts,
             orb, drb, trb, ast, stl, blk, tov, pf, plus_minus,
             fg_pct, ft_pct, fg3_pct, br_player_id, player_id, player_name,
             game_id_full, minutes, seconds_played, nba_player_id, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
        """, (
            gid, player_name, team, season, fg, fga, fg3, fga3, ft, fta, pts,
            orb, drb, trb, None, stl, blk, tov, pf, None,
            fg_pct, ft_pct, fg3_pct, BR_ID, BR_ID, player_name,
            game_id_full, minutes, secs, nba_pid,
        ))
        inserted += 1

    if not dry_run:
        conn.commit()
    conn.close()
    print(f"[season {season}] 回填完成: {inserted} 行 (dry_run={dry_run})")
    return inserted


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, nargs='+', default=[2023, 2024])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    total = 0
    for s in args.season:
        total += backfill(s, args.dry_run)
    print(f"总计回填 {total} 行")
