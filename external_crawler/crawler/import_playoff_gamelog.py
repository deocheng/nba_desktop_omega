#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 Playoff Player GameLog Import
===================================
Converts player_game_details -> player_gamelog for 2026 playoffs + play-in.

Mapping:
  game_id (10-digit) -> gameid (8-digit, strip leading '00')
  player_name -> player
  team_abbreviation -> team
  fgm -> fg, fga -> fga, tpm -> fg3, tpa -> fga3
  ftm -> ft, fta -> fta
  oreb -> orb, dreb -> drb, reb -> trb
  plus computed fg_pct, ft_pct, fg3_pct
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import psycopg2
from psycopg2.extras import execute_batch
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("PlayoffGamelog")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 1. Find playoff games and their 8-digit game_id
    cur.execute("""
        SELECT DISTINCT g.game_id, g.season_type
        FROM games g
        WHERE g.season = 2026 AND g.season_type IN ('Playoffs', 'Play-In')
        ORDER BY g.game_id
    """)
    games = cur.fetchall()
    logger.info(f"Found {len(games)} playoff/play-in games")

    # Build mapping: 10-digit -> 8-digit
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
        fg = r[4] or 0    # fgm
        fga = r[5] or 0
        fg3 = r[6] or 0   # tpm
        fga3 = r[7] or 0
        ft = r[8] or 0    # ftm
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

    # 4. Check for existing playoff gamelogs (avoid duplicates)
    cur.execute("SELECT COUNT(*) FROM player_gamelog WHERE season = 2026 AND gameid LIKE '425%'")
    existing = cur.fetchone()[0]
    if existing > 0:
        logger.warning(f"Found {existing} existing playoff gamelogs, deleting first...")
        cur.execute("DELETE FROM player_gamelog WHERE season = 2026 AND (gameid LIKE '425%' OR gameid LIKE '525%')")
        conn.commit()
        logger.info(f"Deleted {cur.rowcount} existing rows")

    # 5. Insert
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
        conn.commit()
        logger.info(f"Inserted {len(gamelog_rows)} rows into player_gamelog")

    # 6. Verify
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT player) FROM player_gamelog WHERE season = 2026 AND (gameid LIKE '425%' OR gameid LIKE '525%')")
    r = cur.fetchone()
    logger.info(f"Verification: {r[0]} rows, {r[1]} players in 2026 playoff gamelogs")

    # Sample
    cur.execute("""
        SELECT gameid, player, team, pts, trb, ast, fg_pct
        FROM player_gamelog
        WHERE season = 2026 AND gameid LIKE '425%'
        ORDER BY pts DESC LIMIT 5
    """)
    logger.info("Top 5 playoff scoring games:")
    for r in cur.fetchall():
        logger.info(f"  {r[0]} | {r[1]:20s} {r[2]:4s} | {r[3]:3d} pts {r[4]:2d} reb {r[5]:2d} ast | FG% {r[6]}")

    conn.close()
    logger.info("Done!")


if __name__ == "__main__":
    main()
