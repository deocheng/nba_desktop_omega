#!/usr/bin/env python3
"""历史薪资残留 NULL team_abbr 归属清理（1997-2005）。

背景：
  player_salaries_historical 的原始 CSV 装载把 team_abbr 全部写成 NULL（全季共数千行）。
  本轮补爬(scrape_historical_salaries.py)对能抓到 BR 队页的队，用 UPSERT (player_name,season)
  把对应 legacy NULL 行补上了正确队属；但 PHX / CHA / WAS-1997 等队在 BR 上薪资页 404，
  永远抓不到，其 legacy NULL 行仍挂着 NULL。

本脚本：用 player_per_game（Regular Season）按 (player_name=player, season) 反查该球员当季主队，
  把剩余 NULL team_abbr 补上。仅作用于 1997-2005（用户「补历史薪资」范围），不动 2006+。

安全：执行前先整表快照到 player_salaries_historical_bak_<日期>_preattr，可回滚。
"""
from __future__ import annotations
import psycopg2, datetime, sys

DB = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
          password="R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1")

def main():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    today = datetime.date.today().strftime("%Y%m%d")
    snap = f"player_salaries_historical_bak_{today}_preattr"

    # 0) 快照（可回滚）
    cur.execute(f"DROP TABLE IF EXISTS {snap}")
    cur.execute(f"CREATE TABLE {snap} AS SELECT * FROM player_salaries_historical")
    conn.commit()
    print(f"[snapshot] 已快照整表 -> {snap}")

    # 1) 归属前计数
    cur.execute("SELECT COUNT(*) FROM player_salaries_historical WHERE team_abbr IS NULL AND season BETWEEN 1997 AND 2005")
    before = cur.fetchone()[0]
    print(f"[before] 1997-2005 NULL team 行数: {before}")

    # 2) 精确匹配更新：player_per_game RS 主队（同季多队取出场最多）
    cur.execute("""
        UPDATE player_salaries_historical t
        SET team_abbr = sub.team
        FROM (
            SELECT DISTINCT ON (p.player, p.season)
                   p.player, p.season, p.team
            FROM player_per_game p
            WHERE p.season_type = 'Regular Season'
              AND p.player IS NOT NULL AND p.player <> ''
              AND p.team IS NOT NULL AND p.team <> ''
            ORDER BY p.player, p.season, p.g DESC
        ) sub
        WHERE t.team_abbr IS NULL
          AND t.season BETWEEN 1997 AND 2005
          AND t.player_name = sub.player
          AND t.season = sub.season
    """)
    upd = cur.rowcount
    conn.commit()
    print(f"[update] 精确匹配更新行数: {upd}")

    # 3) 宽松匹配（小写去标点）补漏
    cur.execute("""
        UPDATE player_salaries_historical t
        SET team_abbr = sub.team
        FROM (
            SELECT DISTINCT ON (lower(regexp_replace(p.player,'[^a-zA-Z ]','')), p.season)
                   p.player, p.season, p.team
            FROM player_per_game p
            WHERE p.season_type = 'Regular Season'
              AND p.player IS NOT NULL AND p.player <> ''
              AND p.team IS NOT NULL AND p.team <> ''
            ORDER BY lower(regexp_replace(p.player,'[^a-zA-Z ]','')), p.season, p.g DESC
        ) sub
        WHERE t.team_abbr IS NULL
          AND t.season BETWEEN 1997 AND 2005
          AND lower(regexp_replace(t.player_name,'[^a-zA-Z ]','')) = lower(regexp_replace(sub.player,'[^a-zA-Z ]',''))
          AND length(lower(regexp_replace(t.player_name,'[^a-zA-Z ]',''))) > 3
          AND t.season = sub.season
    """)
    upd2 = cur.rowcount
    conn.commit()
    print(f"[update-fuzzy] 宽松匹配更新行数: {upd2}")

    # 4) 归属后计数 + 仍剩 NULL 样例
    cur.execute("SELECT COUNT(*) FROM player_salaries_historical WHERE team_abbr IS NULL AND season BETWEEN 1997 AND 2005")
    after = cur.fetchone()[0]
    print(f"[after] 1997-2005 NULL team 行数: {after}  (减少 {before-after})")
    cur.execute("SELECT season, COUNT(*) FROM player_salaries_historical WHERE team_abbr IS NULL AND season BETWEEN 1997 AND 2005 GROUP BY season ORDER BY season")
    print("[remaining by season]", cur.fetchall())
    if after > 0:
        cur.execute("SELECT player_name, season, salary FROM player_salaries_historical WHERE team_abbr IS NULL AND season BETWEEN 1997 AND 2005 LIMIT 10")
        print("[sample remaining]", cur.fetchall())
    cur.close(); conn.close()
    print("DONE")

if __name__ == "__main__":
    main()
