"""common/team_names.py — 30 队英文全名 + BR slug 单一来源 (SINGLE SOURCE OF TRUTH).

经独立核验的关键事实（务必遵守，别踩坑）：
  * 英文全名 ``TEAM_FULL_NAME`` 来自**本代码字典**，是 30 队官方英文队名。
    **绝不**用 ``dim_teams.team_name`` 当英文名源 —— 那是**中文**队名
    （实测：夏洛特黄蜂 / 布鲁克林篮网 / 新奥尔良鹈鹕）。
  * BR URL slug 唯一来源是 ``BR_TEAM_SLUGS``（BKN→BRK, CHA→CHO，其余恒等）。
    ``dim_teams.current_code`` 是“历史队码 → 现用队码”的队史连续性映射，
    **不是** BR slug。
  * 本模块**单向**依赖 ``hof_exec.config``（叶子依赖）；
    ``hof_exec.config`` 不得反向 import 本模块，保持无环。

与 docs/team_crawl_design.md §3.3 / §8-Q2 对齐：选择“代码固化”而非运行时查表，
以避免离线/测试依赖 DB、避免 CF 高压下再开连接，且 slug 本就不在 DB 中。
"""

from __future__ import annotations

from hof_exec.config import BR_TEAM_SLUGS, TEAM_ABBRS  # noqa: F401  (re-export)

# 30-team abbreviation -> full ENGLISH franchise name.
# 原样搬自 transactions_crawl/parse.py:53-84（已泛化到全 30 队），请勿改写。
TEAM_FULL_NAME: dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


def get_full_name(abbr: str) -> str:
    """Return the English full franchise name for an abbreviation.

    Example: ``get_full_name("DET") -> "Detroit Pistons"``.

    Raises ``KeyError`` for an unknown abbreviation (callers pass a canon abbr
    from ``TEAM_ABBRS``).
    """
    return TEAM_FULL_NAME[abbr]


def get_slug(abbr: str) -> str:
    """Return the Basketball-Reference URL slug for an abbreviation.

    Uses ``BR_TEAM_SLUGS`` (BKN->BRK, CHA->CHO; identity otherwise).
    Falls back to the abbr itself if not present (defensive).
    """
    return BR_TEAM_SLUGS.get(abbr, abbr)
