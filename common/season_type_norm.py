"""season_type 归一化——全仓唯一权威词汇表（读+写双侧统一）。

问题背景
--------
`dim_games.season_type` 的权威取值只有 6 个：
    'Regular Season' / 'Playoffs' / 'Pre Season' / 'All-Star' / 'Play-In' / 'NBA Cup'

但各爬虫历史上自行写 'Regular' / 'Playoffs' 等散落写法（如
`SEASON_TYPES = ("Regular", "Playoffs")` 字面量直写、或 psc 在 `_resolve_game`
里把 dim_games 的 'Regular Season' 又强行 remap 成 'Regular'）。这导致：
  1. 与 dim_games 字典不一致；
  2. 每轮 re-upsert 会把已统一的 'Regular Season' 顶回 'Regular'（反复污染）。

正本清源
--------
所有爬虫在「落库写边界」统一调用 `canon_season_type()`，把任意来源/别名的
season_type 归一为 dim_games 权威值。内部控制标签（如 'Regular'）仍用于选 BR
页面 id（如 `if season_type == "Playoffs"`），**只有落库值被归一**，二者解耦。

读侧同样必须归一（2026-11-10 新增）
------------------------------------
历史上**只有爬虫写侧**调用本模块，服务层（v8.2 智能层 / career_engine /
data_layer）自行定义了 `'Regular'` 规范值，而库里物理值是 `'Regular Season'` →
服务层所有 `WHERE season_type = 'Regular'` 的查询恒定返回 0 行。

因此本模块现为**读+写双侧唯一权威**：
  - 写侧（爬虫）：`canon_season_type()` —— 宽松，未知值原样返回（不破坏数据）
  - 读侧（服务层）：`canon_season_type_strict()` —— fail-loud，未知值抛 ValueError

服务层不得再自行定义 season_type 词汇，一律引用本模块。
"""
from typing import Optional

# ── dim_games 权威取值（常量形式，避免散落字面量）──────────────────────────
SEASON_TYPE_REGULAR_SEASON = "Regular Season"
SEASON_TYPE_PLAYOFFS = "Playoffs"
SEASON_TYPE_PLAY_IN = "Play-In"
SEASON_TYPE_PRE_SEASON = "Pre Season"
SEASON_TYPE_ALL_STAR = "All-Star"
SEASON_TYPE_NBA_CUP = "NBA Cup"

#: dim_games 权威值全集（6 个）
CANON_SEASON_TYPES = frozenset({
    SEASON_TYPE_REGULAR_SEASON,
    SEASON_TYPE_PLAYOFFS,
    SEASON_TYPE_PLAY_IN,
    SEASON_TYPE_PRE_SEASON,
    SEASON_TYPE_ALL_STAR,
    SEASON_TYPE_NBA_CUP,
})

#: 球员赛季统计口径的三个子集（服务层读侧允许的取值）
PLAYER_SEASON_TYPES = frozenset({
    SEASON_TYPE_REGULAR_SEASON,
    SEASON_TYPE_PLAYOFFS,
    SEASON_TYPE_PLAY_IN,
})

# dim_games 权威值的「小写键 → 规范写法」
_CANON = {
    "regular": SEASON_TYPE_REGULAR_SEASON,
    "regular season": SEASON_TYPE_REGULAR_SEASON,
    "reg": SEASON_TYPE_REGULAR_SEASON,
    "rs": SEASON_TYPE_REGULAR_SEASON,
    "playoffs": SEASON_TYPE_PLAYOFFS,
    "playoff": SEASON_TYPE_PLAYOFFS,
    "postseason": SEASON_TYPE_PLAYOFFS,
    "post": SEASON_TYPE_PLAYOFFS,
    "po": SEASON_TYPE_PLAYOFFS,
    "play-in": SEASON_TYPE_PLAY_IN,
    "playin": SEASON_TYPE_PLAY_IN,
    "play_in": SEASON_TYPE_PLAY_IN,
    "all-star": SEASON_TYPE_ALL_STAR,
    "all star": SEASON_TYPE_ALL_STAR,
    "allstar": SEASON_TYPE_ALL_STAR,
    "pre season": SEASON_TYPE_PRE_SEASON,
    "preseason": SEASON_TYPE_PRE_SEASON,
    "nba cup": SEASON_TYPE_NBA_CUP,
    "nbacup": SEASON_TYPE_NBA_CUP,
}

# 已经是规范值 → 直接直通，避免无谓 lowercase 比较
_CANON_EXACT = frozenset(_CANON.values())


def canon_season_type(value: Optional[str]) -> Optional[str]:
    """把任意 season_type 写法归一为 dim_games 权威值。

    - None            → None（不臆造）
    - 已是规范值       → 原样返回
    - 已知别名         → 规范值（'Regular'→'Regular Season' 等）
    - 未知字符串       → 原样返回（不破坏既有数据）
    """
    if value is None:
        return None
    v = value.strip()
    if v in _CANON_EXACT:
        return v
    return _CANON.get(v.lower(), v)


def canon_season_type_strict(
    value: Optional[str],
    allowed: Optional[frozenset] = None,
) -> str:
    """严格版归一化：未知取值直接抛 ValueError（读侧 fail-loud）。

    与宽松版 `canon_season_type()` 的区别：
        - 宽松版用于**写边界**：未知值原样返回，宁可不归一也不破坏既有数据；
        - 严格版用于**读边界**：未知值必须暴露（v8 §2「fail loud, no silent
          fallback to wrong data」），否则查询会静默返回 0 行、被误读成
          「该球员没有数据」。

    Args:
        value: 任意来源的 season_type 写法（大小写、别名均可）。
        allowed: 允许的规范值集合，默认 ``PLAYER_SEASON_TYPES``
                （Regular Season / Playoffs / Play-In）。

    Raises:
        ValueError: 取值无法归一，或归一后不在 ``allowed`` 内。
    """
    if allowed is None:
        allowed = PLAYER_SEASON_TYPES
    if value is None:
        raise ValueError(
            f"season_type must not be None; expected one of {sorted(allowed)}"
        )
    if not isinstance(value, str):
        raise ValueError(
            f"season_type must be a string, got {type(value).__name__}; "
            f"expected one of {sorted(allowed)}"
        )
    v = value.strip()
    canon = v if v in _CANON_EXACT else _CANON.get(v.lower())
    if canon is None:
        raise ValueError(
            f"Unknown season_type {value!r}; expected one of {sorted(allowed)} "
            f"(or aliases: regular/reg/rs/playoffs/postseason/play_in)"
        )
    if canon not in allowed:
        raise ValueError(
            f"season_type {value!r} normalizes to {canon!r}, which is outside "
            f"the allowed set {sorted(allowed)}"
        )
    return canon
