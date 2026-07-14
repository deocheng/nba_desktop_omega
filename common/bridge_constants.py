# common/bridge_constants.py
# ============================================================================
# 跨源桥接与双爬虫回补 —— 共享常量与队名归一化（照 ARCH §3.6）
# 所有匹配 / 回填 / 落盘逻辑统一引用本模块的锚点字段名、归档模板与 canon_abbr。
# ============================================================================
from __future__ import annotations

import os
from typing import Optional, Union

# 锚点字段名（与 dim_games 列名一致，所有匹配/回填逻辑引用 ANCHOR_COLS）
ANCHOR_COLS = ("game_date", "home_team_abbr", "away_team_abbr",
               "home_pts", "away_pts")

# 归档根目录与模板（照 OQ-a：严格用此路径布局）
ARCHIVE_ROOT = "raw_archive"
BR_ARCHIVE_TMPL = "raw_archive/br/{season}/{gid}.html"
ESPN_ARCHIVE_TMPL = "raw_archive/espn/{date}/{event}.json"

# PostgreSQL 连接串（PG 5433 / nba / postgres，口令从环境变量 DB_PASSWORD 注入，禁止硬编码）
PG_DSN = "dbname=nba user=postgres host=localhost port=5433 password=" + os.environ.get("DB_PASSWORD", "")

# 项目根目录（common/ 的父目录）
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(COMMON_DIR)

# 三源队名归一化（2023-26 实测三源一致；下表为安全网，命中即映射）
# 键为「源标识」-> {源缩写: 规范缩写}
BR_TO_CANON = {}    # e.g. {}  （空=无需映射）
NBAPI_TO_CANON = {}
ESPN_TO_CANON = {}

# 标准 3 字母规范缩写集合，用于兜底校验
_CANON = {
    'BOS', 'BKN', 'NYK', 'PHI', 'TOR', 'CHI', 'CLE', 'DET', 'IND', 'MIL',
    'ATL', 'CHA', 'MIA', 'ORL', 'WAS', 'DEN', 'MIN', 'OKC', 'POR', 'UTA',
    'GSW', 'LAC', 'LAL', 'PHX', 'SAC', 'DAL', 'HOU', 'MEM', 'NOP', 'SAS',
}


def canon_abbr(src: str, abbr: str) -> str:
    """把任意源 (br / nba_api / espn) 的队名缩写归一化到规范 3 字母集合。

    先按源查安全网映射表（2023-26 实测三源一致，表暂空），再归一到
    _CANON 规范缩写集合；匹配与落盘前必须调用，避免大小写/空格/历史 code 失配。
    """
    a = (abbr or "").strip().upper()
    a = {'br': BR_TO_CANON, 'nba_api': NBAPI_TO_CANON,
         'espn': ESPN_TO_CANON}.get(src, {}).get(a, a)
    # _CANON 为规范缩写集合；成员校验通过则原样返回，未知缩写亦原样返回（无法猜测）。
    return a if a in _CANON else a


def season_start_year(gdate: Union[str, "object"]) -> int:
    """由比赛日期求「赛季起始年」。7 月及以后属当年起始赛季，否则上一年。

    例：2024-01-15 -> 2023（属 2023-24 赛季）；2024-10-22 -> 2024（属 2024-25）。
    与 dim_games.season 口径一致（赛季起始年）。
    """
    if isinstance(gdate, str):
        parts = gdate.split("-")
        y, m = int(parts[0]), int(parts[1])
    else:  # datetime.date / datetime.datetime
        y, m = gdate.year, gdate.month
    return y if m >= 7 else y - 1


# 便利：构建归档绝对路径
def br_archive_path(season: Union[int, str], gid: str) -> str:
    return os.path.join(PROJECT_ROOT, BR_ARCHIVE_TMPL.format(season=season, gid=gid))


def espn_archive_path(date_str: str, event: str) -> str:
    return os.path.join(PROJECT_ROOT, ESPN_ARCHIVE_TMPL.format(date=date_str, event=event))


def get_pg_conn():
    """获取一个 psycopg2 连接（口令来自环境变量 DB_PASSWORD，需先 source .env）。"""
    import psycopg2
    return psycopg2.connect(PG_DSN)
