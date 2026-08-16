#!/usr/bin/env python3
"""Enrich player_id_bridge + 2026 player_gamelog for holmeda01 (DaRon Holmes).

holmeda01 is the ONLY one of the 25 2026 player_id-missing slugs that has a
borrowable NBA numeric id in OTHER seasons of our DB (per list_missing_bridge_2026.py
section 3). All other 24 slugs have 0 matches anywhere in the DB and require an
EXTERNAL source -- this script does NOT touch them.

This is a pure DB operation (no crawler involved). It runs in a single
transaction and is reversible: the pre-backfill snapshot table
player_gamelog_bak_pid_20260807 still exists as a rollback point.
"""
import os
import psycopg2

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
SLUG = "holmeda01"


def main():
    val = None
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("DB_PASSWORD"):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

    conn = psycopg2.connect(
        host="127.0.0.1", port=5433, dbname="nba",
        user="postgres", password=val,
    )
    conn.autocommit = False
    cur = conn.cursor()

    # 1) Borrow the NBA numeric id from any other season in our DB.
    cur.execute(
        "SELECT DISTINCT player_id FROM player_gamelog "
        "WHERE br_player_id=%s AND player_id IS NOT NULL AND season<>2026 "
        "LIMIT 1", (SLUG,)
    )
    row = cur.fetchone()
    if not row:
        print(f"{SLUG}: 其他赛季无可用 nba id, 跳过 (本脚本只处理 DB 内可借的情况)")
        conn.rollback()
        conn.close()
        return

    nid = row[0]
    print(f"{SLUG} 借到 nba id = {nid}")

    # 2) Fix the bridge entry (nba_player_id is currently NULL for this slug).
    cur.execute(
        "UPDATE player_id_bridge SET nba_player_id=%s "
        "WHERE br_player_id=%s AND nba_player_id IS NULL", (nid, SLUG)
    )
    print(f"  player_id_bridge 更新行数: {cur.rowcount}")

    # 3) Fill the 2026 gamelog rows that are still NULL.
    cur.execute(
        "UPDATE player_gamelog SET player_id=%s "
        "WHERE br_player_id=%s AND season=2026 AND player_id IS NULL", (nid, SLUG)
    )
    print(f"  2026 player_gamelog 更新行数: {cur.rowcount}")

    conn.commit()
    print("已提交 (可逆: 备份表 player_gamelog_bak_pid_20260807 仍在)")
    conn.close()


if __name__ == "__main__":
    main()
