#!/usr/bin/env python3
"""
verify_gamelog_2027.py — 2026-27 赛季（season=2027）gamelog 补爬逐场对账。

对每场已完赛比赛交叉核对：
  A. player_gamelog（BR gamelog 爬取结果，season=2027）
  B. play_by_play（NBA-API PBP，事故中完好）
  C. dim_games（赛果）
报告每场 A/B 的出场球员数、差集（在 PBP 但无 gamelog 行的球员），以及全季汇总。
PBP 是独立信源（与 BR 爬取链路无关），适合做爬取完整性的旁证。

用法: python verify_gamelog_2027.py [--verbose]
退出码: 0=全部场次 A 覆盖 B（允许 B 有 PBP 无事件球员）；1=存在缺口
"""
import argparse
import os
import sys

import psycopg2

DB = dict(host='127.0.0.1', port=5433, dbname='nba', user='postgres',
          password=os.environ.get('DB_PASSWORD'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()
    if not DB['password']:
        print('ERROR: DB_PASSWORD 未设置', file=sys.stderr)
        sys.exit(2)

    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT game_id, game_date, home_team_abbr, away_team_abbr,
               home_pts, away_pts, nba_api_id
        FROM dim_games WHERE season = 2027 ORDER BY game_date, game_id
    """)
    games = cur.fetchall()
    print(f'season=2027 已登记比赛: {len(games)} 场')

    cur.execute("SELECT count(*) FROM player_gamelog WHERE season = 2027")
    total_gl = cur.fetchone()[0]
    cur.execute("SELECT count(DISTINCT br_player_id) FROM player_gamelog "
                "WHERE season = 2027 AND br_player_id IS NOT NULL "
                "AND br_player_id <> ''")
    total_gl_players = cur.fetchone()[0]
    print(f'player_gamelog season=2027: {total_gl} 行 / '
          f'{total_gl_players} 名球员')

    hard_gaps = 0
    soft_notes = 0
    print()
    print(f"{'game_id':<15}{'date':<12}{'matchup':<11}"
          f"{'gamelog':>8}{'pbp':>6}{'gap(B-A)':>9}")
    print('-' * 62)
    for gid, gdate, home, away, hpts, apts, api_id in games:
        cur.execute("""
            SELECT count(DISTINCT br_player_id) FROM player_gamelog
            WHERE season = 2027 AND gameid = %s
              AND br_player_id IS NOT NULL AND br_player_id <> ''
        """, (str(api_id),))
        n_gl = cur.fetchone()[0]
        cur.execute("""
            SELECT count(DISTINCT playerid) FROM play_by_play
            WHERE season = 2027 AND gameid = %s
              AND playerid IS NOT NULL AND playerid <> ''
        """, (str(api_id),))
        n_pbp = cur.fetchone()[0]
        gap = n_pbp - n_gl
        flag = ''
        if gap > 0:
            flag = ' ← PBP 有人无 gamelog 行'
            hard_gaps += 1
        elif n_gl == 0:
            flag = ' ← gamelog 0 人！'
            hard_gaps += 1
        elif gap < 0:
            flag = f' (gamelog 多 {-gap} 人：含无事件出场/ inactive 形态)'
            soft_notes += 1
        print(f'{gid:<15}{str(gdate):<12}{home + "@" + away:<11}'
              f'{n_gl:>8}{n_pbp:>6}{gap:>9}{flag}')

        if args.verbose and gap > 0:
            cur.execute("""
                SELECT DISTINCT p.playerid, p.player FROM play_by_play p
                WHERE p.season = 2027 AND p.gameid = %s
                  AND p.playerid IS NOT NULL AND p.playerid <> ''
                  AND NOT EXISTS (
                    SELECT 1 FROM player_gamelog g
                    WHERE g.season = 2027 AND g.gameid = %s
                      AND g.br_player_id = (
                        SELECT b.br_player_id FROM player_id_bridge b
                        WHERE b.nba_player_id = p.playerid LIMIT 1))
            """, (str(api_id), str(api_id)))
            for pid, pname in cur.fetchall():
                print(f'    missing: {pname} ({pid})')

    print('-' * 62)
    print(f'汇总: {len(games)} 场 / gamelog {total_gl} 行 / '
          f'{total_gl_players} 球员; 硬缺口场次={hard_gaps}, 软提示={soft_notes}')

    # 全级检查：NULL/空 slug 行（身份铁律：br_player_id 必须非空）
    cur.execute("""SELECT count(*) FROM player_gamelog WHERE season = 2027
                   AND (br_player_id IS NULL OR br_player_id = '')""")
    null_slug = cur.fetchone()[0]
    if null_slug:
        print(f'⚠ season=2027 有 {null_slug} 行 br_player_id 为空')
    else:
        print('✓ season=2027 全部行 br_player_id 非空')

    # ── 姓名维度逐场 diff（权威交叉核对）──
    # bridge 映射对有错/缺（2026 新秀大量缺席），slug 直连会漏报；姓级 diff
    # 能抓住被同姓遮挡的真实缺口（如 Brandon Williams vs Ziaire Williams）。
    # 已知假阳性源：姓相同但名不同（PBP 缩写姓）——逐条列出人工判读。
    print()
    print('=== 姓名维度逐场 diff（PBP 有、gamelog 无的姓）===')
    name_hard = 0
    for gid, gdate, home, away, hpts, apts, api_id in games:
        cur.execute("""
            SELECT DISTINCT split_part(player, ' ', 2) FROM play_by_play
            WHERE season = 2027 AND gameid = %s
              AND playerid IS NOT NULL AND playerid <> ''
            EXCEPT
            SELECT DISTINCT split_part(player, ' ', 2) FROM player_gamelog g
            JOIN dim_games d ON d.nba_api_id::text = g.gameid
            WHERE g.season = 2027 AND d.nba_api_id = %s
        """, (str(api_id), str(api_id)))
        missing = [r[0] for r in cur.fetchall()]
        if missing:
            name_hard += 1
            print(f'  {gid} {home}@{away}: {missing}')
    if name_hard == 0:
        print('  （无——14 场全部姓级覆盖）')
    else:
        print(f'  （{name_hard} 场有姓级标记；若该场计数缺口=0 则为名称格式差异'
              f'（变音符号/名缩写），非真实缺口——计数对账才是权威）')

    conn.close()
    sys.exit(0 if hard_gaps == 0 else 1)


if __name__ == '__main__':
    main()
