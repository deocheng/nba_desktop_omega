#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_team_franchise_coverage.py — 球队 franchise 页爬取覆盖验证。

按「数据四性·完整性铁律」逐队×逐页核对：30 队 × 17 页 是否都有数据落库，
输出每张表覆盖的队数与缺失队清单。rc=0 表示 30 队全覆盖。
只读，零写库。
"""
import os
import sys

import psycopg2

#: 仓库根（脚本已收敛到 scripts/oneoff/，自身目录不再是仓库根）
#: 🔴 上溯**三层**：scripts/oneoff/x.py → oneoff → scripts → 仓库根
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT = REPO_DIR
sys.path.insert(0, PROJECT)
from common.br_team_page import DB_CONFIG  # noqa: E402

TEAMS = ["ATL", "BOS", "BRK", "CHI", "CHO", "CLE", "DAL", "DEN", "DET", "GSW",
         "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
         "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"]

STAT_PAGES = ["stats_basic_totals", "stats_per_game_totals",
              "opp_stats_basic_totals", "opp_stats_per_game_totals",
              "stats_basic_ranks", "stats_per_game_ranks",
              "opp_stats_basic_ranks", "opp_stats_per_game_ranks",
              "stats_basic_yr_yr", "stats_per_game_yr_yr",
              "opp_stats_basic_yr_yr", "opp_stats_per_game_yr_yr"]

# 每队需覆盖的「页 → 表」；(page, table, 额外过滤) 用于「按页」核对
LIST_TABLES = {
    "players": "team_franchise_players",
    "numbers": "team_franchise_numbers",
    "head2head": "team_franchise_head2head",
    "hof": "team_franchise_hof",
    "all_star": "team_franchise_all_star",
}



def main() -> int:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    ok = True

    # 1) stat 长表：按 (team, table_id) 核对 30×12
    print("== team_franchise_stats（12 stat 页）==")
    cur.execute("""
        SELECT team_abbr, table_id, count(*) FROM team_franchise_stats
        GROUP BY team_abbr, table_id
    """)
    present = {(t, tid) for t, tid, _ in cur.fetchall()}
    for page in STAT_PAGES:
        missing = [t for t in TEAMS if (t, page) not in present]
        if missing:
            ok = False
            print(f"  [缺] {page}: {len(missing)} 队 {missing}")
        else:
            print(f"  [ok] {page}: 30/30")

    # 2) list 表：按表核对 30 队
    for page, table in LIST_TABLES.items():
        cur.execute(f"SELECT DISTINCT team_abbr FROM {table}")
        teams = {r[0] for r in cur.fetchall()}
        missing = [t for t in TEAMS if t not in teams]
        print(f"== {table}（{page}）: {len(teams)}/30 队 ==")
        if missing:
            ok = False
            print(f"  [缺] {missing}")

    # 3) 汇总行数
    print("== 行数汇总 ==")
    for table in ["team_franchise_stats", "team_franchise_players",
                  "team_franchise_numbers", "team_franchise_head2head",
                  "team_franchise_hof", "team_franchise_all_star"]:
        cur.execute(f"SELECT count(*) FROM {table}")
        print(f"  {table}: {cur.fetchone()[0]} 行")

    cur.close()
    conn.close()
    print("RESULT:", "PASS(30队×17页全覆盖)" if ok else "FAIL(有缺失)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
