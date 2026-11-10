#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fusion_report.py — 融合覆盖度报告（只读汇总，零写入）。

"融合数据"按钮的真实落点：跨源数据最终都汇入 player_gamelog（以 gameid 对齐
dim_games.nba_api_id 为权威键）。本脚本做**覆盖度可见化**：
  - 总行数 / 去重比赛数
  - dim_games 常规赛场次数（分母）
  - 已覆盖的常规赛场次数与覆盖率%
  - NULL minutes 行数（数据完整性的直接信号）

诚实说明：当前 player_gamelog **无 source 列**（v2 适配器设计写入但 DDL 缺失），
故无法做"逐源明细融合"。真正的跨源回填待 ESPN / nba_api 适配器落地 + 补 source 列。

输出：人类可读摘要 + JSON（--json）。
用法：
  python fusion_report.py
  python fusion_report.py --season 2026
  python fusion_report.py --json
"""
import argparse
import json
import os
import sys

import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
CRAWLER_V2 = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(CRAWLER_V2))
for p in (CRAWLER_V2, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.config import get_db_config  # noqa: E402


def _conn():
    return psycopg2.connect(connect_timeout=10, **get_db_config())


def _clause(season):
    if season:
        return "WHERE season=%s", [season]
    return "", []


def build_report(season: int | None) -> dict:
    clause, params = _clause(season)
    rep = {
        "season": season,
        "total_rows": None,
        "distinct_games": None,
        "dim_games_rs": None,
        "covered_rs_games": None,
        "coverage_pct": None,
        "null_minutes": None,
        "note": ("player_gamelog 无 source 列：跨源明细融合需先补 source 列"
                 "（v2 适配器已设计写入，但当前 DDL 缺失）。本报表仅做覆盖度可见化。"),
    }
    with _conn() as c:
        cur = c.cursor()
        cur.execute(f"SELECT count(*), count(DISTINCT gameid) FROM player_gamelog {clause}", params)
        rep["total_rows"], rep["distinct_games"] = cur.fetchone()

        if season:
            cur.execute("SELECT count(*) FROM dim_games WHERE season=%s AND season_type='Regular Season'",
                        (season,))
        else:
            cur.execute("SELECT count(*) FROM dim_games WHERE season_type='Regular Season'")
        rep["dim_games_rs"] = cur.fetchone()[0] or 0

        if season:
            cur.execute(
                "SELECT count(DISTINCT g.gameid) FROM player_gamelog g "
                "WHERE g.season=%s AND EXISTS (SELECT 1 FROM dim_games d "
                "WHERE d.season=%s AND d.season_type='Regular Season' "
                "AND d.nba_api_id = g.gameid::bigint)", (season, season))
        else:
            cur.execute(
                "SELECT count(DISTINCT g.gameid) FROM player_gamelog g "
                "WHERE EXISTS (SELECT 1 FROM dim_games d "
                "WHERE d.season_type='Regular Season' AND d.nba_api_id = g.gameid::bigint)")
        covered = cur.fetchone()[0] or 0
        rep["covered_rs_games"] = covered
        denom = rep["dim_games_rs"] or 1
        rep["coverage_pct"] = round(100.0 * covered / denom, 2)

        try:
            cur.execute(f"SELECT count(*) FROM player_gamelog {clause} AND minutes IS NULL", params)
            rep["null_minutes"] = cur.fetchone()[0]
        except Exception:
            rep["null_minutes"] = None
    return rep


def render(rep: dict) -> str:
    lines = []
    lines.append(f"=== 融合覆盖度报告 (season={rep['season'] or 'ALL'}) ===")
    lines.append(f"player_gamelog 总行数      : {rep['total_rows']}")
    lines.append(f"去重比赛数 (gameid)        : {rep['distinct_games']}")
    lines.append(f"dim_games 常规赛场次数(分母): {rep['dim_games_rs']}")
    lines.append(f"已覆盖常规赛场次           : {rep['covered_rs_games']}")
    lines.append(f"覆盖率                    : {rep['coverage_pct']}%")
    lines.append(f"NULL minutes 行数         : {rep['null_minutes']}")
    lines.append(f"说明: {rep['note']}")
    if not rep["total_rows"]:
        lines.append("(无 player_gamelog 数据 — 请先爬取 BR Gamelog)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = build_report(args.season)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else render(rep))


if __name__ == "__main__":
    main()
