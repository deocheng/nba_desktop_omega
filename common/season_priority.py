"""赛季抓取优先级（统一到一处，全爬虫共用，禁止副本漂移）。

用户于 2026-08-01 确立的全局爬取政策：
  - 最优先：2010 ~ 现在（season 结束年 >= 2010）
  - 其次  ：2000 ~ 2009（2000 <= season <= 2009）
  - 再次  ：1980 ~ 1999（1980 <= season <= 1999）
  - 最后  ：1980 以前（season < 1980）

约定：本平台 `season` 整型列存「赛季结束年」（如 2026 = 2025-26 赛季），
      故分层阈值按结束年判定，与 dim_games / player_shooting 等一致。

设计原则（对齐数据四性铁律与「判据统一」惯例）：
  所有按赛季枚举的爬虫都 import 本模块，不得各自硬编码阈值，
  以免改一处漏一处导致优先级语义漂移。

用法：
  from common.season_priority import season_tier, season_sort_key
  rows.sort(key=lambda r: season_sort_key(r.season))   # 升序：tier0 先、tier 内近季先
"""
from __future__ import annotations

# 优先级分层（数值越小越优先）
TIER_RECENT = 0    # 2010 ~ 现在
TIER_2000S = 1     # 2000 ~ 2009
TIER_1980S = 2     # 1980 ~ 1999
TIER_OLD   = 3     # 1980 以前

# 分层截止年（均为「赛季结束年」）
CUTOFF_RECENT = 2010   # >= 此值 → 最优先
CUTOFF_2000S = 2000    # [2000, 2009] → 其次
CUTOFF_1980S = 1980    # [1980, 1999] → 再次
# < 1980 → 最后


def season_tier(season: int) -> int:
    """返回赛季所属优先级分层：0(最优先) → 3(最后)。

    season 为「赛季结束年」整型。非法/None 视为最老层（最后处理）。
    """
    if season is None:
        return TIER_OLD
    try:
        s = int(season)
    except (TypeError, ValueError):
        return TIER_OLD
    if s >= CUTOFF_RECENT:
        return TIER_RECENT
    if s >= CUTOFF_2000S:
        return TIER_2000S
    if s >= CUTOFF_1980S:
        return TIER_1980S
    return TIER_OLD


def season_sort_key(season: int) -> tuple:
    """用于升序排序的键：(tier, -season)。

    - 先按分层（tier 0 最早处理）；
    - 同层内按 -season（即**近季优先**），符合「先拿最新数据」的直觉。
    """
    return (season_tier(season), -int(season or 0))


# 便于日志/调试打印分层名
TIER_NAMES = {
    TIER_RECENT: "2010~现在",
    TIER_2000S:  "2000~2009",
    TIER_1980S:  "1980~1999",
    TIER_OLD:    "1980以前",
}


def tier_name(season: int) -> str:
    return TIER_NAMES[season_tier(season)]
