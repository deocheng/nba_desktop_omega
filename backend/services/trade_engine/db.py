"""NBACore v8 — Trade Engine Data Layer (T02).

严格四层隔离（Frontend → API → Engine → Data）：
    - 读路径：复用 v8 现有的 ``backend.core.db.batch_query``（仅 SELECT，参数化）。
    - 写路径：专用 psycopg2 写连接池 + 参数化 SQL（v8 §6：无 eval/exec、无动态
      SQL、无每球员循环、无跨层泄漏）。用于 ``league_salary_rules`` 更新与
      two-way 预处理回填。

所有 SELECT 经 ``batch_query``；所有 DML/DDL 经专用写池。引擎其余模块只调用
本模块提供的函数，不直接碰 psycopg2（只读 API 走 core.db，写走本模块）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from psycopg2 import connect
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.core import config, db as core_db
from backend.services.trade_engine import constants, schemas

logger = logging.getLogger("nbacore.trade.db")

# ── 固定 SELECT（非动态，列名写死；值全部参数化） ──
_COLS_SALARY = ", ".join(
    f"salary_{constants.season_to_prefix(s)}" for s in constants.all_seasons()
)
_COLS_OPT = ", ".join(
    f"opt_{constants.season_to_prefix(s)}" for s in constants.all_seasons()
)
_COLS_TOTAL = ", ".join(
    f"total_{constants.season_to_prefix(s)}" for s in constants.all_seasons()
)

_SQL_PLAYERS = f"""
SELECT player_id, player_name, team_abbr, season, age,
       {_COLS_SALARY}, guaranteed, is_partial, is_two_way,
       {_COLS_OPT}
FROM player_contracts
WHERE season = %s AND player_id = ANY(%s)
"""

_SQL_TEAM_PLAYERS = f"""
SELECT player_id, player_name, team_abbr, season, age,
       {_COLS_SALARY}, guaranteed, is_partial, is_two_way,
       {_COLS_OPT}
FROM player_contracts
WHERE season = %s AND team_abbr = ANY(%s)
ORDER BY team_abbr, guaranteed DESC
"""

_SQL_RULES = """
SELECT league, season, salary_cap, luxury_tax, first_apron, second_apron,
       minimum_team_salary, mle_non_tax, mle_tax, mle_room, freeze_calendar, source_url
FROM league_salary_rules
WHERE league = %s AND season = %s
"""

_SQL_PAYROLL = f"""
SELECT team_abbr, team_name, season, salary_cap, player_count,
       {_COLS_TOTAL}, total_guaranteed
FROM team_payroll
WHERE season = %s AND team_abbr = ANY(%s)
"""

# 交易读取（transaction_type = 'Traded'，参数化；team_abbr 走 %s）
_SQL_TRADES_ALL = """
SELECT id, transaction_date, team_abbr, description
FROM transactions
WHERE transaction_type = 'Traded'
ORDER BY transaction_date
"""

_SQL_TRADES_TEAM = """
SELECT id, transaction_date, team_abbr, description
FROM transactions
WHERE transaction_type = 'Traded' AND team_abbr = %s
ORDER BY transaction_date
"""

# 球队目录（缩写 <-> 全名 白名单，供交易 counterparties 解析）
_SQL_TEAM_DIRECTORY = """
SELECT DISTINCT team_abbr, team_name
FROM team_payroll
ORDER BY team_abbr
"""

# ── 专用写连接池（与只读 batch_query 池隔离） ──
_write_pool: Optional[ThreadedConnectionPool] = None


def _get_write_pool() -> ThreadedConnectionPool:
    """惰性初始化专用写连接池（v8 §6 隔离要求）。"""
    global _write_pool
    if _write_pool is None:
        _write_pool = ThreadedConnectionPool(
            1, 5, **config.DB_CONFIG, cursor_factory=RealDictCursor
        )
        logger.info("trade write pool initialized")
    return _write_pool


def _execute_write(sql: str, params: Optional[tuple] = None) -> None:
    """在写连接上执行参数化 DML/DDL（固定 SQL 或带 %s 占位符的常量）。

    不接受任何由用户输入拼装的 SQL（v8 §6 禁则）。
    """
    pool = _get_write_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _as_dict(value) -> Optional[dict]:
    """将 psycopg2 返回的 JSONB（可能是 dict 或 str）规范化为 dict。"""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def _norm_opt(value) -> Optional[str]:
    if value in ("team_option", "player_option"):
        return value
    return None


def _row_to_asset(row: dict, season: str) -> schemas.PlayerAsset:
    """将 player_contracts 行转为 PlayerAsset（6 季 salary / opt，当前季 guaranteed）。"""
    salary_by_season: Dict[str, int] = {}
    opt_by_season: Dict[str, Optional[str]] = {}
    guaranteed_by_season: Dict[str, int] = {}
    for s in constants.all_seasons():
        pref = constants.season_to_prefix(s)
        salary_by_season[s] = int(row.get(f"salary_{pref}") or 0)
        opt_by_season[s] = _norm_opt(row.get(f"opt_{pref}"))
        # DB 仅存当前季 guaranteed 单列；其余季留 0（v1 未知未来保障额）
        guaranteed_by_season[s] = int(row.get("guaranteed") or 0) if s == season else 0

    cur_pref = constants.season_to_prefix(season)
    return schemas.PlayerAsset(
        player_id=str(row.get("player_id")),
        player_name=str(row.get("player_name") or ""),
        team_abbr=str(row.get("team_abbr") or ""),
        season=season,
        salary=int(row.get(f"salary_{cur_pref}") or 0),
        guaranteed=int(row.get("guaranteed") or 0),
        is_partial=bool(row.get("is_partial") or False),
        is_two_way=bool(row.get("is_two_way") or False),
        opt_type=_norm_opt(row.get(f"opt_{cur_pref}")),
        salary_by_season=salary_by_season,
        guaranteed_by_season=guaranteed_by_season,
        opt_by_season=opt_by_season,
    )


def load_rules(season: str, league: str = "NBA") -> Optional[schemas.LeagueSalaryRules]:
    """读取某赛季联盟薪资规则（TRADE-05）。读路径走 batch_query。"""
    rows = core_db.batch_query(_SQL_RULES, (league, season))
    if not rows:
        return None
    r = rows[0]
    return schemas.LeagueSalaryRules(
        season=season,
        league=league,
        salary_cap=int(r.get("salary_cap") or 0),
        luxury_tax=int(r.get("luxury_tax") or 0),
        first_apron=int(r.get("first_apron") or 0),
        second_apron=int(r.get("second_apron") or 0),
        minimum_team_salary=int(r.get("minimum_team_salary") or 0),
        mle_non_tax=int(r.get("mle_non_tax") or 0),
        mle_tax=int(r.get("mle_tax") or 0),
        mle_room=int(r.get("mle_room") or 0),
        freeze_calendar=_as_dict(r.get("freeze_calendar")),
        source_url=r.get("source_url"),
    )


def load_players_by_ids(
    player_ids: List[str], season: str
) -> Dict[str, schemas.PlayerAsset]:
    """按 player_id 批量加载球员资产（只读 batch_query，参数化 ANY）。"""
    if not player_ids:
        return {}
    rows = core_db.batch_query(_SQL_PLAYERS, (season, list(player_ids)))
    return {a.player_id: a for a in (_row_to_asset(r, season) for r in rows)}


def load_team_players(
    team_abbrs: List[str], season: str
) -> Dict[str, List[schemas.PlayerAsset]]:
    """按球队批量加载球员资产（候选池 / 方案生成用，只读 batch_query）。"""
    if not team_abbrs:
        return {}
    rows = core_db.batch_query(_SQL_TEAM_PLAYERS, (season, list(team_abbrs)))
    out: Dict[str, List[schemas.PlayerAsset]] = {t: [] for t in team_abbrs}
    for r in rows:
        a = _row_to_asset(r, season)
        out.setdefault(a.team_abbr, []).append(a)
    return out


def load_team_payrolls(
    team_abbrs: List[str], season: str
) -> Dict[str, dict]:
    """读取球队总薪资（team_payroll），用于税档 / apron 基准（只读 batch_query）。"""
    if not team_abbrs:
        return {}
    rows = core_db.batch_query(_SQL_PAYROLL, (season, list(team_abbrs)))
    out: Dict[str, dict] = {}
    for r in rows:
        abbr = str(r.get("team_abbr"))
        out[abbr] = {
            "team_abbr": abbr,
            "team_name": str(r.get("team_name") or abbr),
            "season": season,
            "salary_cap": int(r.get("salary_cap") or 0),
            "player_count": int(r.get("player_count") or 0),
            "total_guaranteed": int(r.get("total_guaranteed") or 0),
            "totals": {
                s: int(r.get(f"total_{constants.season_to_prefix(s)}") or 0)
                for s in constants.all_seasons()
            },
        }
    return out


def get_team_directory() -> List[dict]:
    """读取球队目录（team_abbr + team_name）去重集，作为交易解析白名单。

    只读 batch_query；无用户输入，SQL 常量写死。
    """
    return core_db.batch_query(_SQL_TEAM_DIRECTORY)


def get_team_player_rows(
    team_abbrs: List[str], season: str
) -> List[dict]:
    """按球队批量读取 player_contracts 原始行（含 age 与 salary_* 列）。

    复用 ``_SQL_TEAM_PLAYERS`` 常量，返回 RealDict 行（不转 PlayerAsset），
    供 cba_aux_db 做 age -> yos 映射。只读 batch_query，参数化 ANY。
    """
    if not team_abbrs:
        return []
    return core_db.batch_query(_SQL_TEAM_PLAYERS, (season, list(team_abbrs)))


def get_trades(team_abbr: Optional[str] = None) -> List[dict]:
    """读取交易记录（transaction_type = 'Traded'）。

    Args:
        team_abbr: 可选球队缩写过滤；为 None 时返回全部交易。

    Returns:
        每行 dict：id, transaction_date, team_abbr, description
        （按 transaction_date 升序）。只读 batch_query，team_abbr 走 %s 参数。
    """
    if team_abbr is None:
        return core_db.batch_query(_SQL_TRADES_ALL)
    return core_db.batch_query(_SQL_TRADES_TEAM, (team_abbr,))


# ── 写路径（专用写池 + 参数化 SQL） ──
def upsert_league_rules(rules: schemas.LeagueSalaryRules) -> schemas.LeagueSalaryRules:
    """受控更新 / 插入联盟薪资规则（TRADE-10 / T11）。参数化，无动态 SQL。"""
    sql = """
    INSERT INTO league_salary_rules
        (league, season, salary_cap, luxury_tax, first_apron, second_apron,
         minimum_team_salary, mle_non_tax, mle_tax, mle_room, freeze_calendar, source_url)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (league, season) DO UPDATE SET
        salary_cap = EXCLUDED.salary_cap,
        luxury_tax = EXCLUDED.luxury_tax,
        first_apron = EXCLUDED.first_apron,
        second_apron = EXCLUDED.second_apron,
        minimum_team_salary = EXCLUDED.minimum_team_salary,
        mle_non_tax = EXCLUDED.mle_non_tax,
        mle_tax = EXCLUDED.mle_tax,
        mle_room = EXCLUDED.mle_room,
        freeze_calendar = EXCLUDED.freeze_calendar,
        source_url = EXCLUDED.source_url,
        scraped_at = now()
    """
    params = (
        rules.league,
        rules.season,
        rules.salary_cap or None,
        rules.luxury_tax or None,
        rules.first_apron or None,
        rules.second_apron or None,
        rules.minimum_team_salary or None,
        rules.mle_non_tax or None,
        rules.mle_tax or None,
        rules.mle_room or None,
        json.dumps(rules.freeze_calendar) if rules.freeze_calendar else None,
        rules.source_url,
    )
    _execute_write(sql, params)
    # 回读保证返回最新持久化值
    refreshed = load_rules(rules.season, rules.league)
    return refreshed if refreshed else rules


def backfill_two_way_flag() -> int:
    """执行 sql/003 预处理回填（决策④）。固定常量 SQL，经专用写池。

    Returns:
        被标记为 two-way 的行数。
    """
    sql_path = Path(__file__).resolve().parents[3] / "sql" / "003_backfill_two_way_flag.sql"
    sql_text = sql_path.read_text(encoding="utf-8")
    _execute_write(sql_text)
    # 统计受影响行数
    pool = _get_write_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM player_contracts WHERE is_two_way = TRUE"
            )
            n = cur.fetchone()["n"]
        return int(n)
    finally:
        pool.putconn(conn)


def run_migration_file(path: str) -> None:
    """程序化执行固定迁移 SQL 文件（与 sql/run_migrations.py 等价，经专用写池）。"""
    sql_text = Path(path).read_text(encoding="utf-8")
    _execute_write(sql_text)
