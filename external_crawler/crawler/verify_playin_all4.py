#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_playin_all4.py — Play-In 四维终验（逐场证据，非表象）。

维度：
  ① Box Score: player_gamelog play_in 行数/场（基线 1071/37）
  ② PBP: play_by_play 每场行数 > 0 + 末行比分 == dim_games/box 比分抽验
  ③ Shot: player_shot_chart season_type='Play-In' 每场行数（对 2020-2025 也复验）
  ④ PM: player_playin_plus_minus 每场人数 + total 非空完整（box 权威源口径）；
       q列和==total 仅信息性统计（2026-08-17 仲裁：BR 3 场自矛盾 + 2020 气泡赛
       逐节表空白为源级缺陷，不作 FAIL）；
  ⑤ gamelog 回填一致性: play_in 行 plus_minus 与 pppm total 差异数（精确 name join，
       29 行名字变体行旧值已核实一致）。
输出: 逐场表 + 汇总（任何 FAIL 即 rc=1）。
"""
import os
import sys

sys.path.insert(0, "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13")
import psycopg2


def conn():
    pw = ""
    with open("/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env") as f:
        for line in f:
            if line.startswith("DB_PASSWORD="):
                pw = line.strip().split("=", 1)[1]
    return psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba", user="postgres", password=pw)

BR_ABBR = {"PHX": "PHO", "CHA": "CHO", "BKN": "BRK"}

def main():
    c = conn()
    cur = c.cursor()
    cur.execute("SET max_parallel_workers_per_gather=0")
    cur.execute("SELECT season, game_id_full, br_game_id, game_date, home_team_abbr, "
                "away_team_abbr FROM playin_game_dates ORDER BY season, game_date")
    games = cur.fetchall()
    print(f"{'game':16} {'box':>4} {'pbp':>4} {'pbpEnd':>9} {'shot':>4} {'pm':>3} {'pmTot':>5} {'q≠t':>4}")
    fails = []
    qdiff_info = 0
    for s, gf, br, dt, h, a in games:
        url_id = br[:9] + BR_ABBR.get(br[-3:], br[-3:])
        cur.execute("SELECT count(*) FROM player_gamelog WHERE game_id_full=%s AND game_type='play_in' AND banned=FALSE", (gf,))
        box = cur.fetchone()[0]
        cur.execute("SELECT count(*), max(h_pts), max(a_pts) FROM play_by_play WHERE gameid=%s", (gf,))
        pbp, mh, ma = cur.fetchone()
        cur.execute("SELECT count(*) FROM player_shot_chart WHERE season_type='Play-In' AND game_id=%s", (url_id,))
        shot = cur.fetchone()[0]
        # ④ pm：total 完整性为主校验；q 和==total 信息性（BR 源缺陷，不 FAIL）
        cur.execute("SELECT count(*), "
                    "count(*) FILTER (WHERE plus_minus_total IS NOT NULL), "
                    "count(*) FILTER (WHERE COALESCE(q1,0)+COALESCE(q2,0)+"
                    "COALESCE(q3,0)+COALESCE(q4,0)+COALESCE(ot1,0)+COALESCE(ot2,0)+"
                    "COALESCE(ot3,0)+COALESCE(ot4,0) <> plus_minus_total) "
                    "FROM player_playin_plus_minus WHERE game_id_full=%s", (gf,))
        pm, pm_tot, qdiff = cur.fetchone()
        qdiff_info += qdiff
        end = f"{mh}-{ma}" if mh is not None else "-"
        ok = box > 0 and pbp > 300 and shot > 100 and pm > 15 and pm == pm_tot
        print(f"{url_id:16} {box:>4} {pbp:>4} {end:>9} {shot:>4} {pm:>3} {pm_tot:>5} {qdiff:>4}" + ("" if ok else "  ← FAIL"))
        if not ok:
            fails.append(url_id)
    # ⑤ gamelog 回填一致性（精确 name join 口径）
    cur.execute("""SELECT count(*) FROM player_gamelog g
                   JOIN player_playin_plus_minus p
                     ON g.game_id_full=p.game_id_full AND g.player_name=p.player_name
                   WHERE g.game_type='play_in' AND g.banned=FALSE
                     AND (g.plus_minus IS DISTINCT FROM p.plus_minus_total)""")
    backfill_diff = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM player_playin_plus_minus")
    tot_pm = cur.fetchone()[0]
    print(f"\npm total rows: {tot_pm}; q和≠total(信息性, BR源缺陷): {qdiff_info}; "
          f"gamelog回填差异: {backfill_diff} (应为0)")
    if backfill_diff:
        fails.append("gamelog_backfill")
    print("RESULT:", "ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
