#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_8_dimensions.py — 校验 8 张核心数据表覆盖，标缺口季。只读。"""
import re, psycopg2
PROJECT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
pw = None
for line in open(f"{PROJECT}/.env"):
    m = re.match(r"^\s*DB_PASSWORD\s*=(.+?)\s*$", line)
    if m: pw = m.group(1); break

conn = psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba",
                        user="postgres", password=pw)
cur = conn.cursor()
cur.execute("SET max_parallel_workers_per_gather=0")

SEASONS = list(range(1997, 2027))

def q(sql, params=()):
    cur.execute(sql, params)
    return cur.fetchall()

print("="*110)
print("维度1 · dim_games（赛程/比分/胜负）  — RS 场数 / W-L填充 / 球队数")
print("="*110)
hdr = f"{'季':>6} {'RS场':>7} {'W-L填%':>7} {'队':>4}  判定"
print(hdr)
for s in SEASONS:
    rows = q("""SELECT count(*),
                       count(*) FILTER (WHERE home_wl IS NOT NULL),
                       count(DISTINCT home_team_abbr)
                FROM dim_games WHERE season=%s AND season_type='Regular Season'""", (s,))
    g, wl, teams = rows[0]
    wl_pct = f"{100*wl/g:.0f}" if g else "  -"
    gap = "⚠缺场" if (s>=2005 and g<1100) else ("⚠W/L缺" if (g and wl<g) else "")
    print(f"{s:>6} {g:>7} {wl_pct:>6}% {teams:>4}  {gap}")

print()
print("="*110)
print("维度2 · player_gamelog（球员逐场） — 逐季 distinct 比赛数 vs dim_games RS 场数")
print("="*110)
# dim_games RS 场数映射
dg = {s: q("SELECT count(*) FROM dim_games WHERE season=%s AND season_type='Regular Season'",(s,))[0][0] for s in SEASONS}
print(f"{'季':>6} {'gamelog赛':>9} {'dim_rs赛':>9} {'覆盖%':>7}  判定")
for s in SEASONS:
    gl = q("SELECT count(DISTINCT gameid) FROM player_gamelog WHERE season=%s", (s,))[0][0]
    base = dg[s]
    cov = f"{100*gl/base:.0f}" if base else "  -"
    gap = "⚠缺口" if (base and gl < 0.9*base) else ""
    print(f"{s:>6} {gl:>9} {base:>9} {cov:>6}%  {gap}")

print()
print("="*110)
print("维度3 · team_stats_per_game（球队逐场效率） — 逐季 RS 队数（应~30）")
print("="*110)
print(f"{'季':>6} {'RS队':>6}  判定")
for s in SEASONS:
    n = q("SELECT count(DISTINCT abbreviation) FROM team_stats_per_game WHERE season=%s AND playoffs=FALSE", (s,))[0][0]
    gap = "⚠缺队" if n < 28 else ""
    print(f"{s:>6} {n:>6}  {gap}")

print()
print("="*110)
print("维度4 · player_per_game（球员赛季聚合） — 逐季 RS 球员数")
print("="*110)
print(f"{'季':>6} {'球员':>6}  判定")
prev = None
for s in SEASONS:
    n = q("SELECT count(*) FROM player_per_game WHERE season=%s AND player_id IS NOT NULL AND player_id<>''", (s,))[0][0]
    gap = "⚠骤降" if (prev and prev>500 and n < 0.6*prev) else ""
    print(f"{s:>6} {n:>6}  {gap}")
    prev = n

print()
print("="*110)
print("维度5 · player_epm（EPM 高阶） — 2002+ 逐季行数")
print("="*110)
print(f"{'季':>6} {'EPM行':>7}  判定")
for s in SEASONS:
    if s < 2002:
        print(f"{s:>6}   n/a  (2002前无EPM)"); continue
    n = q("SELECT count(*) FROM player_epm WHERE season=%s", (s,))[0][0]
    gap = "⚠缺" if n == 0 else ""
    print(f"{s:>6} {n:>7}  {gap}")

print()
print("="*110)
print("维度6 · 薪资（2026=player_contracts / 其余=player_salaries_historical） — 逐季有薪人数")
print("="*110)
print(f"{'季':>6} {'有薪':>6}  判定")
for s in SEASONS:
    if s == 2026:
        n = q("SELECT count(*) FROM player_contracts WHERE season='2025-26' AND salary_2025_26 IS NOT NULL", )[0][0]
    else:
        n = q("SELECT count(*) FROM player_salaries_historical WHERE season=%s AND salary IS NOT NULL", (s,))[0][0]
    gap = "⚠缺薪" if n < 300 else ""
    print(f"{s:>6} {n:>6}  {gap}")

print()
print("="*110)
print("维度7 · player_onoff（on-off 净效率） — 逐季 RS distinct 球员数")
print("="*110)
print(f"{'季':>6} {'球员':>6}  判定")
for s in SEASONS:
    n = q("SELECT count(DISTINCT player_id) FROM player_onoff WHERE season=%s AND season_type='Regular Season'", (s,))[0][0]
    gap = "⚠缺" if n < 200 else ""
    print(f"{s:>6} {n:>6}  {gap}")

print()
print("="*110)
print("维度8 · player_lineups（最佳阵容） — 逐季 RS 行数")
print("="*110)
print(f"{'季':>6} {'行数':>8}  判定")
for s in SEASONS:
    n = q("SELECT count(*) FROM player_lineups WHERE season=%s AND season_type='Regular Season'", (s,))[0][0]
    gap = "⚠缺" if n < 5000 else ""
    print(f"{s:>6} {n:>8}  {gap}")

conn.close()
print("\n校验完成（只读）。")
