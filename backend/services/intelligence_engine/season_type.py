"""NBACore v8.2 — Season Type normalization (read-boundary adapter).

🔴 口径统一（2026-11-10）
------------------------
本模块此前把规范值定义为 `'Regular' / 'Playoffs' / 'PlayIn'`，而库中物理值
是 `'Regular Season' / 'Playoffs' / 'Play-In'`（`fact_player_season_stats`、
`player_advanced`、`player_shooting`、`player_shot_chart`、`dim_games` 全部
一致）→ 所有 `WHERE season_type = 'Regular'` 的查询恒定返回 0 行。

仓库早已有唯一权威 `common.season_type_norm`（爬虫 12 处写侧已采用），
只是服务层读侧从未引用。现改为**全仓单一词汇表**：本模块只做适配，
把外部传入的任意写法归一为 dim_games 权威值。

对外 API 契约保持向后兼容：外部仍可传 `"Regular"` / `"REG"` / `"play-in"`
等任意别名（见 `common.season_type_norm` 别名表），归一后才落库查询。

读侧 fail-loud：未知取值直接抛 ValueError（v8 §2）—— 静默返回 0 行会被
误读成「该球员没有数据」，比抛错危险得多。
"""
from __future__ import annotations

from common.season_type_norm import (
    PLAYER_SEASON_TYPES,
    SEASON_TYPE_PLAY_IN,
    SEASON_TYPE_PLAYOFFS,
    SEASON_TYPE_REGULAR_SEASON,
    canon_season_type_strict,
)

#: 球员赛季统计口径允许的规范值（= dim_games 权威值的子集）
SEASON_TYPES = (
    SEASON_TYPE_REGULAR_SEASON,
    SEASON_TYPE_PLAYOFFS,
    SEASON_TYPE_PLAY_IN,
)

#: 缺省口径（常规赛）
DEFAULT_SEASON_TYPE = SEASON_TYPE_REGULAR_SEASON


def normalize_season_type(value) -> str:
    """Map any accepted spelling to the canonical (DB-stored) season_type.

    Args:
        value: 任意写法，如 ``"Regular"`` / ``"REG"`` / ``"regular season"`` /
               ``"Playoffs"`` / ``"play_in"``；``None`` 取默认常规赛。

    Returns:
        dim_games 权威取值之一：``'Regular Season'`` / ``'Playoffs'`` /
        ``'Play-In'``。

    Raises:
        ValueError: 取值无法归一，或归一后不在允许集合内（v8 §2: fail loud,
            no silent fallback to wrong data）。
    """
    if value is None:
        value = DEFAULT_SEASON_TYPE
    return canon_season_type_strict(value, allowed=PLAYER_SEASON_TYPES)


def validate_season_type(value) -> bool:
    """Raise if invalid, else return True. Convenience for callers."""
    normalize_season_type(value)
    return True
