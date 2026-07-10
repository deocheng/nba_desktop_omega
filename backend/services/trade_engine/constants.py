"""NBACore v8 — Trade Engine Constants & helpers (T02).

纯函数 / 常量，无 DB、无规则逻辑：
    - 赛季解析与 6 季列名映射（决策②：全程 season 参数，禁止硬编码）
    - two-way 识别口径（决策④，与 sql/003 保持一致）
    - 聚合底薪阈值（≤ 2025-26 最低薪资，约 $1,200,000，见 architecture §九）
    - 方案生成深度上限（默认口径）

遵循 Google 风格 + 适度中英文注释。
"""
from __future__ import annotations

from typing import List, Optional

# ── 赛季范围（6 季：2025-26 → 2030-31，与 DB 列对齐） ──
SEASON_START_YEARS: List[int] = [2025, 2026, 2027, 2028, 2029, 2030]


def all_seasons() -> List[str]:
    """返回全部 6 个赛季标签，如 ['2025-26', '2026-27', ... '2030-31']。"""
    return [f"{y}-{str(y + 1)[2:]}" for y in SEASON_START_YEARS]


def parse_season(season: str) -> tuple[int, int]:
    """将 '2025-26' 解析为 (start_year=2025, end_year=2026)。

    Raises:
        ValueError: 格式非法。
    """
    if not isinstance(season, str) or "-" not in season:
        raise ValueError(f"invalid season format: {season!r} (expected 'YYYY-YY')")
    start_s, end_s = season.split("-", 1)
    if len(start_s) != 4 or len(end_s) != 2:
        raise ValueError(f"invalid season format: {season!r}")
    start = int(start_s)
    end = 2000 + int(end_s)
    if end != start + 1:
        raise ValueError(f"season end year must be start+1: {season!r}")
    return start, end


def season_to_prefix(season: str) -> str:
    """由 season 推导 DB 列前缀，如 '2025-26' -> '2025_26'。"""
    start, end = parse_season(season)
    return f"{start}_{end % 100:02d}"


def salary_column(season: str) -> str:
    """当前季薪资列名，如 'salary_2025_26'。"""
    return f"salary_{season_to_prefix(season)}"


def guaranteed_column(season: str) -> str:
    """当前季保障额列名，如 'guaranteed_2025_26'。"""
    return f"guaranteed_{season_to_prefix(season)}"


def opt_column(season: str) -> str:
    """当前季选项列名，如 'opt_2025_26'。"""
    return f"opt_{season_to_prefix(season)}"


# ── two-way 识别口径（决策④，与 sql/003_backfill_two_way_flag.sql 一致） ──
# 关键词（notes JSONB 文本化后匹配）
TWO_WAY_KEYWORDS = ("two-way", "two_way")
# 底薪阈值：salary <= 该值且所在队合同数 > 15 视为 two-way
TWO_WAY_SALARY_THRESHOLD = 600_000
TWO_WAY_TEAM_SIZE_FLOOR = 15


def is_two_way_candidate(
    notes_text: Optional[str],
    salary: Optional[int],
    team_contract_count: int,
) -> bool:
    """判定一名球员是否应标记为 two-way（纯函数，供预处理/校验复用）。

    口径（architecture.md §九）：
        1) notes 含 'two-way' / 'two_way' 关键词
        OR 2) salary <= 600000 且该队合同数 > 15
    """
    if notes_text:
        low = notes_text.lower()
        if any(kw in low for kw in TWO_WAY_KEYWORDS):
            return True
    if (
        salary is not None
        and salary <= TWO_WAY_SALARY_THRESHOLD
        and team_contract_count > TWO_WAY_TEAM_SIZE_FLOOR
    ):
        return True
    return False


# ── 聚合底薪阈值（anti-padding，7/1–12/15 仅含 1 名底薪，见 §九） ──
MIN_CONTRACT_THRESHOLD = 1_200_000

# ── 方案生成深度上限（默认口径，见 §九） ──
GEN_MAX_PARTNERS_PER_TEAM = 2       # 每队最多 2 名搭档
GEN_CANDIDATE_TOP_N = 20            # 候选 Top-20（按薪资相近度）
GEN_MAX_BRANCHES = 200              # 最大搜索分支 K
