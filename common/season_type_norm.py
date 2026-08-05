"""season_type 归一化——爬虫写入约定统一对齐 dim_games 字典。

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
"""
from typing import Optional

# dim_games 权威值的「小写键 → 规范写法」
_CANON = {
    "regular": "Regular Season",
    "regular season": "Regular Season",
    "playoffs": "Playoffs",
    "playoff": "Playoffs",
    "play-in": "Play-In",
    "playin": "Play-In",
    "all-star": "All-Star",
    "all star": "All-Star",
    "pre season": "Pre Season",
    "preseason": "Pre Season",
    "nba cup": "NBA Cup",
    "nbacup": "NBA Cup",
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
