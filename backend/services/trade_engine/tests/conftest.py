"""Shared fixtures & helpers for trade_engine tests.

纯逻辑测试（match_engine / schemas / nba_rules / trade_graph / tax_engine /
suggester）不需要 DB，直接用构造的 PlayerAsset / LeagueSalaryRules。
DB 相关测试（GSW/BRK 样例、时间线、API）通过 db.ping() 探测，DB 不可用时跳过。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# 确保项目根在 sys.path（以 `python -m pytest` 运行时已自动包含，这里兜底）
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest  # noqa: E402

from backend.core import db as core_db  # noqa: E402
from backend.services.trade_engine import nba_rules, schemas  # noqa: E402

# 共享规则集实例与 as_of（供纯逻辑测试复用，避免跨测试模块导入）
RULE_SET = nba_rules.NBARuleSet()
AS_OF = datetime(2026, 1, 15)

# ── 2025-26 官方核实阈值（PRD §3.1，与 league_salary_rules 回填值一致） ──
SECOND_APRON = 207_824_000
FIRST_APRON = 195_945_000
LUXURY_TAX = 187_895_000
SALARY_CAP = 154_647_000


@pytest.fixture
def rules_2025() -> schemas.LeagueSalaryRules:
    """2025-26 联盟薪资规则常量（纯逻辑测试用，无需连库）。"""
    return schemas.LeagueSalaryRules(
        season="2025-26",
        league="NBA",
        salary_cap=SALARY_CAP,
        luxury_tax=LUXURY_TAX,
        first_apron=FIRST_APRON,
        second_apron=SECOND_APRON,
        minimum_team_salary=139_182_000,
        mle_non_tax=14_104_000,
        mle_tax=5_685_000,
        mle_room=8_781_000,
    )


def make_asset(
    guaranteed: int,
    *,
    player_id: str = "p",
    player_name: str = "P",
    salary: int | None = None,
    is_two_way: bool = False,
    byc: bool = False,
    is_partial: bool = False,
    opt_type=None,
) -> schemas.PlayerAsset:
    """构造一个 PlayerAsset（默认 salary == guaranteed，便于 cap/guaranteed 联动）。"""
    return schemas.PlayerAsset(
        player_id=player_id,
        player_name=player_name,
        team_abbr="T",
        season="2025-26",
        salary=salary if salary is not None else guaranteed,
        guaranteed=guaranteed,
        is_partial=is_partial,
        is_two_way=is_two_way,
        byc=byc,
        opt_type=opt_type,
    )


# ── DB 可用性探测（DB 相关测试据此 skip） ──
try:
    DB_OK = bool(core_db.ping())
except Exception:  # noqa: BLE001
    DB_OK = False

skip_if_no_db = pytest.mark.skipif(not DB_OK, reason="PostgreSQL 不可用，跳过 DB 相关测试")
