"""NBACore v8 §2 Layer 1 (Data Layer) — Crawler overview read access.

This module belongs to Layer 1 (Data Layer) and is the SOLE place where the
``/crawler`` router's table-overview data is read from PostgreSQL. It follows
the v8 §2 / §6 hard rules:

    - SELECT-only. All ordinary reads go through ``backend.core.db.batch_query``
      (validated by ``validate_batch_sql``).
    - No dynamic SQL anywhere: table identifiers are interpolated with
      ``psycopg2.sql.Identifier`` — never via f-string / string concatenation
      (v8 §6 explicitly forbids f-string table names / injection-prone SQL).
    - The API router (``backend.api.routers.crawler``) must NOT touch the DB
      directly; it only calls :func:`get_crawlable_tables` here, i.e. it
      orchestrates a lower layer and never executes SQL itself.

The per-table ``COUNT(*)`` is executed on a short-lived dedicated connection
because ``backend.core.db.batch_query`` only accepts a plain ``str`` (it runs
``validate_batch_sql`` on a ``str``). This is a bounded, sanctioned exception
for Layer 1: the identifier is ALWAYS a ``sql.Identifier`` (never an
f-string), so there is zero injection surface, and the table name originates
from ``information_schema.tables`` (a trusted system catalog), not from user
input.
"""
from __future__ import annotations

import logging

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from backend.core import config
from backend.core.db import batch_query

logger = logging.getLogger("nbacore.data_layer.crawler_overview")

# ── Table descriptions for data overview (display-only metadata, NOT SQL) ──
_TABLE_DESCRIPTIONS: dict[str, str] = {
    "all_star_selections": "全明星入选记录，按球员、赛季、票数",
    "coach_stats": "教练执教战绩：任期、胜场、负场、胜率",
    "coaches": "教练基本信息：姓名、球队、执教年份",
    "dim_draft_history": "选秀历史：顺位、球队、球员、年份",
    "dim_games": "比赛主表：日期、主客队、比分、加时",
    "dim_players": "球员主表：姓名、身高、体重、生年、国籍",
    "dim_teams": "球队主表：简称、全名、城市、赛区",
    "draft_combine": "选秀体测数据：身高、臂展、弹跳、敏捷性",
    "draft_summary": "选秀汇总：每年选秀人数、球队数",
    "end_of_season_teams": "赛季末球队阵容快照",
    "fact_player_season_stats": "球员赛季总数据：得分、篮板、助攻、命中率等",
    "fact_team_season_stats": "球队赛季总数据",
    "injuries": "伤病记录：球员、伤势、状态、日期",
    "league_averages": "联盟平均数据：每赛季平均得分、节奏、效率等",
    "play_by_play": "逐回合数据（1800万行）：每场比赛每个事件",
    "player_award_shares": "球员奖项投票：MVP、DPOY、ROY等",
    "player_career_totals": "球员职业生涯累计数据",
    "player_contracts": "球员合同：金额、年限、选项",
    "player_contracts_league": "联盟整体合同统计",
    "player_gamelog": "球员比赛日志（191万行）：每场得分、篮板等",
    "player_id_bridge": "球员ID映射：不同数据源的ID对应关系",
    "player_name_unified": "球员名称统一表：别名映射",
    "player_play_by_play": "球员逐回合统计摘要",
    "player_salaries_historical": "球员历史薪资",
    "player_season_info": "球员赛季基本信息：球队、年龄、合同年",
    "player_season_splits": "球员赛季分段数据（103万行）：主场/客场/各月份",
    "player_shooting": "球员投篮细分：距离、区域、命中率",
    "player_weight_history": "球员体重历史变化",
    "starting_lineups": "首发阵容：五人组合、效率",
    "team_depth_chart": "球队深度图：位置、轮换顺序",
    "team_game_splits": "球队比赛分段统计：主客场、背靠背等",
    "team_payroll": "球队薪资总额",
    "team_stats_per_100_poss": "球队每百回合数据：攻防效率",
    "team_stats_per_game": "球队场均数据：得分、篮板、助攻、命中率",
    "team_summaries": "球队赛季汇总：战绩、排名、季后赛标识",
    "transactions": "交易记录：日期、类型、涉及球员",
}


def _connect() -> "psycopg2.extensions.connection":
    """Open a short-lived connection for identifier-safe queries.

    Uses the same credentials from ``backend.core.config.DB_CONFIG`` and a
    RealDictCursor so callers get dict-like rows.
    """
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        cursor_factory=RealDictCursor,
    )


def _count_rows(table_name: str) -> int:
    """Count rows in a table using a SAFE, parameterized identifier.

    The table name is quoted via ``psycopg2.sql.Identifier`` — never an
    f-string or string concatenation — so there is no injection surface.
    Returns 0 on any error (e.g. table concurrently dropped) so a single
    failure never breaks the whole overview.
    """
    composed = sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier(table_name))
    conn: "psycopg2.extensions.connection | None" = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(composed)
            row = cur.fetchone()
        return int(row["n"]) if row is not None else 0
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to count rows for table %s: %s", table_name, exc)
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass


def get_crawlable_tables() -> list[dict]:
    """Return overview of all crawlable tables.

    Each entry is a dict with keys: ``name``, ``columns``, ``rows``,
    ``description`` — matching the API contract consumed by the frontend.

    Read path (Layer 1, SELECT-only):
        * table listing  -> ``batch_query`` over ``information_schema.tables``
        * column counts  -> ``batch_query`` over ``information_schema.columns``
        * row counts     -> :func:`_count_rows` (identifier-safe ``COUNT(*)``)

    Returns:
        list[dict]: one dict per public, non-workspace base table, ordered by name.
    """
    info_rows = batch_query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
        "AND table_name NOT LIKE 'workspace%%' ORDER BY table_name",
        (),
    )
    result: list[dict] = []
    for r in info_rows:
        tn = r["table_name"]
        col_cnt = batch_query(
            "SELECT COUNT(*) AS n FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (tn,),
        )[0]["n"]
        row_cnt = _count_rows(tn)
        desc = _TABLE_DESCRIPTIONS.get(tn, "")
        result.append({
            "name": tn,
            "columns": col_cnt,
            "rows": row_cnt,
            "description": desc,
        })
    return result
