#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 play_by_play 回填 player_gamelog 在 2014–2021 八个 BR-500 缺口季的缺失行。

背景 / 为什么用 PBP 而非爬取：
  这 8 季的缺口是 BR 球员页 HTTP 500（结构失败，爬取必然再 500），而 play_by_play
  对 2014–2021 全覆盖（各季 56–69 万事件）。故 PBP 回填是「成本更低且唯一可行」的方式：
  0 外部请求、0 CF 风险、纯 DB 聚合。

目标球员：logs/gamelog_500_bypass.txt 中的 BR-500 球员（clarkjo01 / mooreet01），
他们就是 2014–2021 全部缺口的来源（其余球员已由爬虫正常入库）。

机制（沿用已验证的 backfill_houstca01_from_pbp.py）：
  - 仅 INSERT 缺口场：PBP 有事件 + dim_games.season_type='Regular Season' + player_gamelog 无对应行。
  - 绝不覆盖已存在的准确 BR 行。
  - 字段来源：
      fg/fga/fg3/fga3/ft/fta/pts/trb(orb/drb)/tov/pf : event_type 聚合（可靠）
      stl/blk                              : description 正则（按球员名动态构造）
      ast / plus_minus                     : 本 PBP 数据集未抓 -> 留 NULL（不伪造）
      minutes / seconds_played             : 事件时钟跨度近似（PBP-estimated，精度有限）
  - 连接键遵循项目铁律：pbp.gameid(varchar) = dim_games.nba_api_id::bigint（非 BR game_id）。

用法：
  python backfill_gamelog_from_pbp_2014_2021.py --dry-run     # 仅统计不写
  python backfill_gamelog_from_pbp_2014_2021.py               # 正式回填
"""
import os
import re
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SEASONS = [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021]


def get_conn():
    return psycopg2.connect(
        host='127.0.0.1', port=5433, dbname='nba',
        user='postgres', password=os.environ.get('DB_PASSWORD'),
    )


def name_pattern(player_name, br_id):
    """构造 PBP description 中的 'c. houstan' 形式正则片段（小写、转义）。"""
    base = (player_name or br_id).replace("'", "").replace(".", " ")
    parts = base.split()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
    else:
        first = last = parts[0] if parts else br_id
    initial = re.escape(first[0].lower())
    last_esc = re.escape(last.lower())
    return f"{initial}\\. {last_esc}"


def find_missing_games(conn, season, br_id):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT pbp.gameid
        FROM play_by_play_p_{season} pbp
        JOIN dim_games d ON d.nba_api_id = pbp.gameid::bigint
        LEFT JOIN player_gamelog pg
            ON pg.gameid = pbp.gameid AND pg.br_player_id = '{br_id}' AND pg.season = {season}
        WHERE pbp.br_player_id = '{br_id}'
          AND d.season_type = 'Regular Season'
          AND pg.gameid IS NULL
        GROUP BY pbp.gameid ORDER BY pbp.gameid
    """)
    return [r[0] for r in cur.fetchall()]


def aggregate(conn, season, br_id, gameids, pat):
    if not gameids:
        return {}
    gid_list = ",".join(f"'{g}'" for g in gameids)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT pbp.gameid,
          MAX(pbp.team) AS team,
          count(*) FILTER (WHERE event_type='Made Shot' AND description !~* '3-pt|3pt') AS fg,
          count(*) FILTER (WHERE event_type IN ('Made Shot','Missed Shot') AND description !~* '3-pt|3pt') AS fga,
          count(*) FILTER (WHERE event_type='Made Shot' AND description ~* '3-pt|3pt') AS fg3,
          count(*) FILTER (WHERE event_type IN ('Made Shot','Missed Shot') AND description ~* '3-pt|3pt') AS fga3,
          count(*) FILTER (WHERE event_type='Free Throw' AND description ~* 'makes free throw') AS ft,
          count(*) FILTER (WHERE event_type='Free Throw') AS fta,
          SUM(CASE WHEN event_type='Made Shot' AND description ~* '3-pt|3pt' THEN 3
                   WHEN event_type='Made Shot' AND description !~* '3-pt|3pt' THEN 2
                   WHEN event_type='Free Throw' AND description ~* 'makes free throw' THEN 1 ELSE 0 END) AS pts,
          count(*) FILTER (WHERE event_type='Rebound' AND (subtype LIKE '%Off%' OR subtype LIKE '%ORB%')) AS orb,
          count(*) FILTER (WHERE event_type='Rebound' AND (subtype NOT LIKE '%Off%' AND subtype NOT LIKE '%ORB%')) AS drb,
          count(*) FILTER (WHERE event_type='Rebound') AS trb,
          count(*) FILTER (WHERE event_type='Turnover') AS tov,
          count(*) FILTER (WHERE event_type='Foul') AS pf,
          count(*) FILTER (WHERE description ~* 'steal by {pat}') AS stl,
          count(*) FILTER (WHERE description ~* '({pat} blocks|block by {pat})') AS blk
        FROM play_by_play_p_{season} pbp
        JOIN dim_games d ON d.nba_api_id = pbp.gameid::bigint
        WHERE pbp.br_player_id='{br_id}'
          AND d.season_type='Regular Season'
          AND pbp.gameid IN ({gid_list})
        GROUP BY pbp.gameid
        ORDER BY pbp.gameid
    """)
    stats = {}
    for row in cur.fetchall():
        (gid, team, fg, fga, fg3, fga3, ft, fta, pts, orb, drb, trb, tov, pf, stl, blk) = row
        stats[gid] = dict(team=team, fg=fg, fga=fga, fg3=fg3, fga3=fga3, ft=ft, fta=fta,
                          pts=pts, orb=orb, drb=drb, trb=trb, tov=tov, pf=pf, stl=stl, blk=blk)
    cur.execute(f"""
        SELECT pbp.gameid, pbp.period, min(pbp.clock_seconds), max(pbp.clock_seconds)
        FROM play_by_play_p_{season} pbp
        WHERE pbp.br_player_id='{br_id}'
          AND pbp.gameid IN ({gid_list})
          AND pbp.clock_seconds IS NOT NULL
        GROUP BY pbp.gameid, pbp.period
    """)
    span = {}
    for gid, period, mn, mx in cur.fetchall():
        if mn is None or mx is None:
            continue
        span.setdefault(gid, 0.0)
        span[gid] += max(0.0, (mx - mn)) / 60.0
    for gid, mins in span.items():
        if gid in stats:
            secs = int(round(mins * 60))
            stats[gid]['seconds_played'] = secs
            stats[gid]['minutes'] = f"{secs // 60}:{secs % 60:02d}"
    return stats


def backfill_player_season(conn, br_id, season, dry_run):
    cur = conn.cursor()
    cur.execute("SELECT player_name FROM dim_players WHERE player_id=%s", (br_id,))
    rn = cur.fetchone()
    player_name = rn[0] if rn else br_id
    cur.execute("SELECT nba_player_id FROM player_id_bridge WHERE br_player_id=%s", (br_id,))
    rb = cur.fetchone()
    nba_pid = rb[0] if rb else None
    pat = name_pattern(player_name, br_id)

    gameids = find_missing_games(conn, season, br_id)
    if not gameids:
        return 0
    stats = aggregate(conn, season, br_id, gameids, pat)
    print(f"  [{season}] {br_id} ({player_name}): 缺口场 {len(gameids)}, 聚合得 {len(stats)} 场")
    total = 0
    for gid, s in stats.items():
        fg, fga = s['fg'] or 0, s['fga'] or 0
        fg3, fga3 = s['fg3'] or 0, s['fga3'] or 0
        ft, fta = s['ft'] or 0, s['fta'] or 0
        fg_pct = round(fg / fga, 3) if fga else None
        ft_pct = round(ft / fta, 3) if fta else None
        fg3_pct = round(fg3 / fga3, 3) if fga3 else None
        team = s['team'] or ''
        secs = s.get('seconds_played', 0)
        minutes = s.get('minutes', '0:00')
        if dry_run:
            continue
        cur.execute("SELECT game_id, home_team_abbr, away_team_abbr FROM dim_games WHERE nba_api_id=%s::bigint", (gid,))
        g = cur.fetchone()
        game_id_full = g[0] if g else None
        cur.execute("""
            INSERT INTO player_gamelog
            (gameid, player, team, season, fg, fga, fg3, fga3, ft, fta, pts,
             orb, drb, trb, ast, stl, blk, tov, pf, plus_minus,
             fg_pct, ft_pct, fg3_pct, br_player_id, player_id, player_name,
             game_id_full, minutes, seconds_played, nba_player_id, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
        """, (
            gid, player_name, team, season, fg, fga, fg3, fga3, ft, fta, s['pts'] or 0,
            s['orb'] or 0, s['drb'] or 0, s['trb'] or 0, None, s['stl'] or 0, s['blk'] or 0,
            s['tov'] or 0, s['pf'] or 0, None,
            fg_pct, ft_pct, fg3_pct, br_id, br_id, player_name,
            game_id_full, minutes, secs, nba_pid,
        ))
        total += 1
    if not dry_run:
        conn.commit()
    return total


def main():
    dry = '--dry-run' in sys.argv
    here = os.path.dirname(os.path.abspath(__file__))
    bypass = os.path.join(here, 'logs', 'gamelog_500_bypass.txt')
    targets = []
    if os.path.exists(bypass):
        with open(bypass) as f:
            for line in f:
                p = line.strip()
                if p and not p.startswith('#'):
                    targets.append(p)
    if not targets:
        targets = ['clarkjo01', 'mooreet01']
    print(f"目标 BR-500 缺口球员: {targets}")
    conn = get_conn()
    grand = 0
    for br_id in targets:
        for s in SEASONS:
            grand += backfill_player_season(conn, br_id, s, dry)
    conn.close()
    print(f"=== 总计回填 {grand} 行 (dry_run={dry}) ===")


if __name__ == '__main__':
    main()
