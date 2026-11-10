#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""import_playoff_gamelog_v2.py — 2026 季后赛 gamelog 导入 v2
（修复 2026-08-16 代码审查 P0-⑤）

相对 import_playoff_gamelog.py（原版保留不动）的修复：
  [P0-⑤] 原版 DELETE（清掉 2026 季后赛全部旧 gamelog）先 commit、INSERT
         另起事务 —— INSERT 一旦失败（类型不匹配/断连），已删旧数据
         **永久丢失**。v2 把 DELETE+INSERT 放进同一事务，失败整体回滚。
  [顺带] 删除前先备份到 player_gamelog_po2026_bak_<ts>（可回滚铁律）。
  [顺带] DB 密码改从项目 .env 读取（原版硬编码 "postgres" 连不上真库）。
  [顺带] 删除范围收窄为「本次导入将覆盖的 gameid 集合」（原版
         LIKE '425%'/'525%' 会波及其他来源的同前缀行）。

字段映射、验证、样例输出与原版一致。
"""
import re
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
import logging

import psycopg2
from psycopg2.extras import execute_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("PlayoffGamelogV2")

PROJECT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"


def db_password() -> str:
    for line in open(f"{PROJECT}/.env"):
        m = re.match(r"^\s*DB_PASSWORD\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1)
    raise RuntimeError("未在 .env 找到 DB_PASSWORD")


DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": db_password(),
}


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False        # v2：全程显式事务
    cur = conn.cursor()
    cur.execute("SET max_parallel_workers_per_gather = 0")

    # 1. Find playoff games and their 8-digit game_id
    cur.execute("""
        SELECT DISTINCT g.game_id, g.season_type
        FROM games g
        WHERE g.season = 2026 AND g.season_type IN ('Playoffs', 'Play-In')
        ORDER BY g.game_id
    """)
    games = cur.fetchall()
    logger.info(f"Found {len(games)} playoff/play-in games")

    gid_map = {}
    for gid_8, stype in games:
        gid_10 = gid_8.zfill(10)
        gid_map[gid_10] = (gid_8, stype)
    logger.info(f"Game ID mapping: {len(gid_map)} entries")

    # 2. Fetch all player_game_details for these games
    gid_10_list = list(gid_map.keys())
    cur.execute("""
        SELECT pgd.game_id, pgd.player_name, pgd.team_abbreviation,
               pgd.pts, pgd.fgm, pgd.fga, pgd.tpm, pgd.tpa,
               pgd.ftm, pgd.fta, pgd.oreb, pgd.dreb, pgd.reb,
               pgd.ast, pgd.stl, pgd.blk, pgd.tov, pgd.pf, pgd.plus_minus
        FROM player_game_details pgd
        WHERE pgd.game_id = ANY(%s)
          AND pgd.pts IS NOT NULL
        ORDER BY pgd.game_id, pgd.team_abbreviation, pgd.player_name
    """, (gid_10_list,))

    rows = cur.fetchall()
    logger.info(f"Found {len(rows)} player_game_details rows with stats")

    # 3. Convert to player_gamelog format
    gamelog_rows = []
    for r in rows:
        gid_10 = r[0]
        if gid_10 not in gid_map:
            continue
        gid_8, stype = gid_map[gid_10]

        pts = r[3] or 0
        fg = r[4] or 0
        fga = r[5] or 0
        fg3 = r[6] or 0
        fga3 = r[7] or 0
        ft = r[8] or 0
        fta = r[9] or 0
        orb = r[10] or 0
        drb = r[11] or 0
        trb = r[12] or 0
        ast = r[13] or 0
        stl = r[14] or 0
        blk = r[15] or 0
        tov = r[16] or 0
        pf = r[17] or 0
        plus_minus = r[18]

        fg_pct = round(fg / fga, 3) if fga > 0 else 0.0
        ft_pct = round(ft / fta, 3) if fta > 0 else 0.0
        fg3_pct = round(fg3 / fga3, 3) if fga3 > 0 else 0.0

        gamelog_rows.append({
            "gameid": gid_8,
            "player": r[1],
            "team": r[2],
            "season": 2026,
            "fg": fg, "fga": fga, "fg3": fg3, "fga3": fga3,
            "ft": ft, "fta": fta,
            "orb": orb, "drb": drb, "trb": trb,
            "ast": ast, "stl": stl, "blk": blk,
            "tov": tov, "pf": pf, "pts": pts,
            "plus_minus": plus_minus,
            "fg_pct": fg_pct, "ft_pct": ft_pct, "fg3_pct": fg3_pct,
        })

    logger.info(f"Converted {len(gamelog_rows)} rows for player_gamelog")
    incoming_gids = sorted({g["gameid"] for g in gamelog_rows})

    # 4. v2：备份旧数据 → DELETE+INSERT 同一事务（P0-⑤ 根修）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_table = f"player_gamelog_po2026_bak_{ts}"
    try:
        cur.execute(
            f"CREATE TABLE {bak_table} AS "
            f"SELECT * FROM player_gamelog WHERE season = 2026 "
            f"AND gameid = ANY(%s)", (incoming_gids,))
        cur.execute(f"SELECT count(*) FROM {bak_table}")
        bak_n = cur.fetchone()[0]
        logger.info(f"备份 {bak_n} 行旧数据 → {bak_table}")

        # 删除范围 = 本次将覆盖的 gameid 集合（不再 LIKE '425%' 波及无辜）
        cur.execute(
            "DELETE FROM player_gamelog WHERE season = 2026 AND gameid = ANY(%s)",
            (incoming_gids,))
        logger.info(f"Deleted {cur.rowcount} existing rows（同一事务内，失败即回滚）")

        if gamelog_rows:
            execute_batch(cur, """
                INSERT INTO player_gamelog (
                    gameid, player, team, season,
                    fg, fga, fg3, fga3, ft, fta,
                    orb, drb, trb, ast, stl, blk, tov, pf, pts,
                    plus_minus, fg_pct, ft_pct, fg3_pct
                ) VALUES (
                    %(gameid)s, %(player)s, %(team)s, %(season)s,
                    %(fg)s, %(fga)s, %(fg3)s, %(fga3)s, %(ft)s, %(fta)s,
                    %(orb)s, %(drb)s, %(trb)s, %(ast)s, %(stl)s, %(blk)s, %(tov)s, %(pf)s, %(pts)s,
                    %(plus_minus)s, %(fg_pct)s, %(ft_pct)s, %(fg3_pct)s
                )
            """, gamelog_rows, page_size=100)
            logger.info(f"Staged {len(gamelog_rows)} rows（未提交）")

        conn.commit()   # 单一事务边界：DELETE+INSERT 原子生效
        logger.info(f"✅ 已提交：删旧+插新 {len(gamelog_rows)} 行（原子）")
    except Exception as e:
        conn.rollback()
        logger.error(f"!! 事务失败已整体回滚（旧数据完好，备份表 {bak_table} 也已回滚消失）：{e}")
        raise

    # 5. Verify（提交后校验）
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT player) FROM player_gamelog "
                "WHERE season = 2026 AND gameid = ANY(%s)", (incoming_gids,))
    r = cur.fetchone()
    logger.info(f"Verification: {r[0]} rows, {r[1]} players in 2026 playoff gamelogs")

    cur.execute("""
        SELECT gameid, player, team, pts, trb, ast, fg_pct
        FROM player_gamelog
        WHERE season = 2026 AND gameid = ANY(%s)
        ORDER BY pts DESC LIMIT 5
    """, (incoming_gids,))
    logger.info("Top 5 playoff scoring games:")
    for r in cur.fetchall():
        logger.info(f"  {r[0]} | {r[1]:20s} {r[2]:4s} | {r[3]:3d} pts {r[4]:2d} reb {r[5]:2d} ast | FG% {r[6]}")

    conn.close()
    logger.info("Done!（回滚备份保留在 " + bak_table + "，确认无误后可手动 DROP）")


if __name__ == "__main__":
    main()
