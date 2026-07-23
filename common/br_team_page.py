"""common/br_team_page.py — 共享基类 for BR 球队页数据补全（br_gapfill）爬虫。

封装 5 类 BR 球队页（Team Shooting / Lineups / On-Off / Depth Charts / Referees）
爬虫的共性逻辑：

  * CDP 抓取（复用 ``common.browser.get_driver``，走用户已手动过 CF 的 Chrome）
  * 本地缓存 MERGE 语义（移植 gamelog 的 ``merge_gamelog_cache``：读旧→按 key
    合并→整体回写，绝不 OVERWRITE 未重抓的球队）
  * 球队×赛季枚举（权威源 ``team_summaries``，BR slug 经 ``team_mapping`` 归一）
  * 限速 ≤15 请求/分钟（3-6s 间隔，复用 gamelog/headshots）
  * 失败登记（复用 ``crawl_failures``，token = ``{slug}|{season}|{domain}``）
  * 球员键桥接（``player_id_bridge`` + ``HAVING COUNT(DISTINCT)=1`` 歧义处理）
  * DB 批量 upsert（``psycopg2.extras.execute_values`` + ``ON CONFLICT``）

各域爬虫继承本类，仅实现三个钩子：``parse`` / ``build_rows`` / ``upsert``。
解析层是纯函数（无 DB/网络依赖），便于单测。

约定（对齐现有表与 ARCH）：
  * ``season`` 一律为**赛季结束年**（与 ``team_summaries``/``dim_games``/``team_depth_chart``
    口径一致，例如 2026 = 2025-26 季）。因此 BR 球队页 URL 年 = ``season``
    （注意：ARCH §8 写为 ``season+1``，但实测 DB 中 season 已是结束年，此处按真实
    数据修正，详见回报中的「架构偏差」项）。
  * BR 球队页 URL：``/teams/{slug}/{year}/{page}/``。
  * 缓存目录：``<cache_dir>/<domain>_<season>.json``，结构
    ``{season, domain, teams:{slug:{season_type:[records]}}}``。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from bs4 import BeautifulSoup

# 确保仓库根（本文件向上一级即 common/ 的父目录 = 仓库根）在 sys.path，
# 使 ``import common.*`` 与 ``from common.browser import ...`` 可解析。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("br_team_page")

# 进程级日志配置：若调用方尚未配置 handler，则挂一个基础 handler，
# 使 crawler 的进度/失败日志可见（INFO 级别，默认 lastResort 仅 WARNING）。
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

# ── 限速常量（≤15 请求/分钟，复用 gamelog/headshots 的 3-6s 间隔）──────────
RATE_LIMIT_BASE_S = 3.0
RATE_LIMIT_JITTER_S = 3.0

# ── DB 连接（口令从环境变量读，禁止硬编码；兜底 PGPASSWORD）────────────────
DB_CONFIG = dict(
    host="localhost",
    port=5433,
    dbname="nba",
    user="postgres",
    password=os.environ.get("DB_PASSWORD") or os.environ.get("PGPASSWORD", ""),
)

# BR 球队页 URL 模板；year = 赛季结束年（见模块 docstring 约定）。
BR_TEAM_URL = "https://www.basketball-reference.com/teams/{slug}/{year}/{page}/"

# Cloudflare 挑战特征串（命中则视为页面未就绪，跳过+登记失败，不写 NULL）。
CF_MARKERS = ("Just a moment", "Checking your browser", "Verify you are human",
              "请稍候", "正在进行安全验证")

# BR 404 特征串（命中则视为页面不存在，跳过+隔离，不写 NULL、不存档）。
# 实测 404 页：<title>Page Not Found (404 error) | Basketball-Reference.com</title>
# 且 canonical：<link rel="canonical" href="https://www.basketball-reference.com/404.html">
NOT_FOUND_MARKERS = ("Page Not Found (404 error)", "/404.html")


# ── 通用解析辅助（纯函数，便于单测，无 DB/网络依赖）────────────────────────
def safe_int(val: Optional[str]) -> Optional[int]:
    """把 BR 文本值安全转为 int；空/*/None → None。"""
    if val is None or val == "" or val == "*":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def safe_float(val: Optional[str]) -> Optional[float]:
    """把 BR 文本值（如 '.625'）安全转为 float；空/None → None。"""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def extract_player_links(cell) -> List[Tuple[Optional[str], str]]:
    """从单元格抽取 ``(br_slug, display_name)`` 列表（BR 球员链接）。

    BR 球员链接形如 ``/players/{letter}/{slug}.html``；本函数只取 slug 与展示名，
    便于后续经 ``player_id_bridge`` 桥接。无链接时返回空列表。
    """
    if cell is None:
        return []
    out: List[Tuple[Optional[str], str]] = []
    for a in cell.find_all("a"):
        href = a.get("href", "") or ""
        m = re.search(r"/players/[a-z]/([a-z0-9]+)", href)
        slug = m.group(1) if m else None
        name = a.get_text(strip=True)
        if name:
            out.append((slug, name))
    return out


def _row_data_stats(row) -> Dict[str, str]:
    """读取一行的全部 ``data-stat`` → 文本 映射（跳过无 data-stat 的单元格）。"""
    vals: Dict[str, str] = {}
    for td in row.find_all(["th", "td"]):
        ds = td.get("data-stat", "")
        if ds:
            vals[ds] = td.get_text(strip=True)
    return vals


class BRTeamPageCrawler:
    """BR 球队页爬虫共享基类（模板方法）。

    子类必须设置类属性：``DOMAIN`` / ``TASK_TYPE`` / ``TABLE`` / ``PAGE`` /
    ``TABLE_ID`` / ``CONFLICT_COLS``，并实现钩子 ``parse`` / ``build_rows`` /
    ``upsert``。可选的 ``SEASON_TYPES``（默认 ``('Regular', 'Playoffs')``）与
    ``MIN_SEASON``（默认 1947）控制枚举与下界。

    BR 球队页默认在静态 HTML 中提供 **Regular Season** 数据；Playoffs 表常位于
    JS 切换视图（静态 ``page_source`` 未必含 ``_po`` 表）。因此本基类默认
    ``SEASON_TYPES = ('Regular',)``，避免对不存在的 PO 页大量登记失败；PO 解析
    逻辑已在各 ``parse`` 中预留（探测 ``{TABLE_ID}_po``），待实爬确认表 id 后开启。
    """

    # —— 子类必须覆盖 ——
    DOMAIN: str = ""
    TASK_TYPE: str = ""
    TABLE: str = ""
    PAGE: str = ""
    TABLE_ID: str = ""
    CONFLICT_COLS: Tuple[str, ...] = ()

    # —— 子类可选覆盖 ——
    SEASON_TYPES: Tuple[str, ...] = ("Regular",)
    MIN_SEASON: int = 1947

    def __init__(self, cache_dir: Optional[str] = None,
                 dry_run: bool = False, resume: bool = False) -> None:
        self.cache_dir = cache_dir or f"br_{self.DOMAIN}_cache"
        self.dry_run = dry_run
        self.resume = resume
        self._slug_map: Optional[Dict[str, str]] = None
        # 最近一次 fetch_team_page 是否命中风控(CF)挑战页。供调用方（如
        # br_player_page.run_players）区分「CF 拦截导致的 0 行」与「真无数据」，
        # 从而决定是暂停等用户清 CF 还是仅告警，避免缺口被静默清零。
        self._last_fetch_cf: bool = False
        # 最近一次 fetch_team_page 是否命中 404（页面不存在）。供调用方区分
        # 「404 永久失效」与「CF 拦截 / 空页」，从而隔离该 slug 而非死循环重试。
        self._last_fetch_404: bool = False

    # ── 浏览器 / 抓取 ──────────────────────────────────────────────────────
    @staticmethod
    def get_driver():
        """懒加载共享 CDP driver（进程级单例，复用 common.browser）。"""
        from common.browser import get_driver as _gd
        return _gd()

    def build_url(self, slug: str, season: int, page: str,
                  season_type: str = "Regular") -> str:
        """构造 BR 球队页 URL。year = 赛季结束年 = season。"""
        return BR_TEAM_URL.format(slug=slug, year=season, page=page)

    def fetch_team_page(self, driver, url: str) -> str:
        """导航并取回渲染 HTML；CF 挑战 / 空页 → ''（调用方据此跳过+登记）。

        命中 CF 挑战页时置 ``self._last_fetch_cf = True``，供上层区分「CF 拦截
        导致的 0 行」与「真无数据」，从而触发暂停等用户清 CF 而非静默清零缺口。
        """
        self._last_fetch_cf = False
        self._last_fetch_404 = False
        try:
            driver.get(url)
        except Exception as exc:  # noqa: BLE001 - 导航失败当作无页
            logger.warning("导航失败 %s: %s", url, exc)
            return ""
        html = driver.page_source
        if not html:
            return ""
        if any(marker in html for marker in CF_MARKERS):
            logger.warning("CF 挑战页，跳过: %s", url)
            self._last_fetch_cf = True
            return ""
        if any(marker in html for marker in NOT_FOUND_MARKERS):
            logger.warning("BR 404 页面，隔离: %s", url)
            self._last_fetch_404 = True
            return ""
        return html

    # ── 球队季枚举 ────────────────────────────────────────────────────────
    def _load_slug_map(self, conn) -> Dict[str, str]:
        """从 ``team_mapping`` 构建 历史缩写→当前 slug 映射（进程级缓存）。"""
        cur = conn.cursor()
        cur.execute("SELECT team_code, current_code FROM team_mapping")
        m: Dict[str, str] = {}
        for code, cur_code in cur.fetchall():
            if code:
                m[code] = cur_code
            if cur_code:
                m[cur_code] = cur_code
        cur.close()
        return m

    def _br_slug(self, conn, abbr: str) -> str:
        """把 team_summaries.abbreviation 归一到 BR franchise slug。

        命中 ``team_mapping`` 则取 current_code（处理搬迁队，如 WSB→WAS）；
        未命中（早期 BAA/NBA 队）原样返回，由抓取层判定是否有 BR 页。
        """
        if self._slug_map is None:
            self._slug_map = self._load_slug_map(conn)
        return self._slug_map.get(abbr, abbr)

    def enumerate_team_seasons(self, conn, season: int) -> List[Tuple[str, int, str]]:
        """枚举某季需抓取的 ``(slug, season, season_type)`` 列表。

        权威源 ``team_summaries(abbreviation, playoffs)``；``playoffs=True``
        映射为 ``'Playoffs'``。受 ``self.SEASON_TYPES`` 过滤，slug 去重。
        """
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT abbreviation, playoffs FROM team_summaries "
            "WHERE season = %s ORDER BY abbreviation",
            (season,),
        )
        rows = cur.fetchall()
        cur.close()

        out: List[Tuple[str, int, str]] = []
        seen = set()
        for abbr, playoffs in rows:
            st = "Playoffs" if playoffs else "Regular"
            if st not in self.SEASON_TYPES:
                continue
            slug = self._br_slug(conn, abbr)
            key = (slug, st)
            if key in seen:
                continue
            seen.add(key)
            out.append((slug, season, st))
        return out

    # ── 缓存 MERGE（移植 gamelog 语义，绝不 OVERWRITE）────────────────────
    def merge_cache(self, season: int, team: str, season_type: str,
                    records: list) -> str:
        """读旧缓存 + 按 (team, season_type) 合并新记录 + 整体回写。

        MERGE 语义：旧缓存中其它球队/其它 season_type 的记录**完整保留**；
        仅用本次新抓的 ``records`` 覆盖 ``(team, season_type)`` 这一项。
        三重容错（文件不存在 / JSON 损坏 / 结构异常 → 当空缓存），绝不让脚本崩溃。
        """
        os.makedirs(self.cache_dir, exist_ok=True)
        out_path = os.path.join(self.cache_dir, f"{self.DOMAIN}_{season}.json")

        old: Dict[str, dict] = {}
        if os.path.exists(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    old = data.get("teams") or {}
                if not isinstance(old, dict):
                    old = {}
            except (json.JSONDecodeError, ValueError, OSError):
                # 损坏/半截/无法读取 → 视为空缓存，绝不崩溃。
                old = {}

        team_entry = dict(old.get(team) or {})
        team_entry[season_type] = records
        old[team] = team_entry

        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(
                {"season": season, "domain": self.DOMAIN, "teams": old},
                fh, ensure_ascii=False, indent=1,
            )
        return out_path

    # ── 球员键桥接 ────────────────────────────────────────────────────────
    def resolve_player(self, conn, name: str) -> Tuple[Optional[str], Optional[int]]:
        """查 ``player_id_bridge`` 解析球员键。

        返回 ``(br_player_id, nba_player_id)``：
          * 同名仅映射到 1 个 ``nba_player_id`` → 取之（``HAVING COUNT(DISTINCT)=1``）；
          * 同名歧义 / 缺桥 → ``nba_player_id`` 留 NULL；
          * ``br_player_id`` 取一致的 BR slug（FK ``dim_players.player_id``），
            歧义时留 NULL。

        ``conn=None``（如单测）时直接返回 ``(None, None)``。
        """
        if conn is None:
            return (None, None)
        cur = conn.cursor()
        cur.execute(
            "SELECT br_player_id, nba_player_id FROM player_id_bridge "
            "WHERE player_name = %s",
            (name,),
        )
        rows = cur.fetchall()
        cur.close()
        if not rows:
            return (None, None)
        nba_ids = {r[1] for r in rows if r[1] is not None}
        br_ids = {r[0] for r in rows if r[0] is not None}
        nba_pid = next(iter(nba_ids)) if len(nba_ids) == 1 else None
        br_pid = next(iter(br_ids)) if len(br_ids) == 1 else None
        return (br_pid, nba_pid)

    # ── 失败登记 ──────────────────────────────────────────────────────────
    def register_failure(self, conn, token: str) -> None:
        """写 ``crawl_failures(game_id=token, task_type, resolved=False)``。"""
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO crawl_failures (game_id, task_type, resolved) "
            "VALUES (%s, %s, %s)",
            (token, self.TASK_TYPE, False),
        )
        cur.close()

    # ── 限速 ──────────────────────────────────────────────────────────────
    def rate_limit(self) -> None:
        """限速：3 + uniform(0,3) 秒（≈ ≤15 请求/分钟）。"""
        time.sleep(RATE_LIMIT_BASE_S + random.uniform(0, RATE_LIMIT_JITTER_S))

    # ── 通用 upsert ───────────────────────────────────────────────────────
    def _upsert_rows(self, conn, table: str, rows: list,
                     conflict_cols: Tuple[str, ...]) -> int:
        """批量 upsert（execute_values + ON CONFLICT DO UPDATE）。

        列集取所有行 key 的并集；冲突键 ``conflict_cols`` 之外的列在冲突时刷新为
        EXCLUDED 值；``created_at`` 等默认值列不入 rows，由 DB 默认值填充。
        """
        if not rows:
            return 0
        cols: List[str] = []
        for r in rows:
            for k in r.keys():
                if k not in cols:
                    cols.append(k)
        update_cols = [c for c in cols if c not in conflict_cols]
        col_sql = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        if update_cols:
            upd_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in update_cols])
            conflict_sql = (f"ON CONFLICT ({', '.join(conflict_cols)}) "
                            f"DO UPDATE SET {upd_sql}")
        else:
            conflict_sql = f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
        sql = (f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
               f"{conflict_sql}")
        data = [tuple(r.get(c) for c in cols) for r in rows]
        cur = conn.cursor()
        psycopg2.extras.execute_values(cur, sql, data, page_size=1000)
        cur.close()
        return len(data)

    # ── 子类钩子（必须由子类实现）─────────────────────────────────────────
    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> list:
        """解析 BR 页 HTML → 记录列表（纯函数，不含 team/season 维度）。"""
        raise NotImplementedError

    def build_rows(self, conn, team_abbr: str, season: int, season_type: str,
                   rec: dict) -> dict:
        """把一条解析记录补全为可落库行（注入 team/season 维度 + 球员桥接）。"""
        raise NotImplementedError

    def upsert(self, conn, rows: list) -> int:
        """子类实现：把行批量写入目标表。"""
        raise NotImplementedError

    # ── 已抓判定（--resume）───────────────────────────────────────────────
    def _already_done(self, conn, slug: str, season: int,
                      season_type: str) -> bool:
        """若目标表以 (team_abbr, season, season_type) 为键，探测是否已落库。"""
        cols = self.CONFLICT_COLS
        if "team_abbr" in cols and "season" in cols and "season_type" in cols:
            cur = conn.cursor()
            cur.execute(
                f"SELECT 1 FROM {self.TABLE} "
                f"WHERE team_abbr=%s AND season=%s AND season_type=%s LIMIT 1",
                (slug, season, season_type),
            )
            found = cur.fetchone() is not None
            cur.close()
            return found
        # 不以 team_abbr 为主键（如 game_referees 以 game_id 为主键）→ 不探测，
        # 依赖 upsert 幂等（同 game 从主客两队页各抓一次自动去重）。
        return False

    # ── 单队单季抓取 ──────────────────────────────────────────────────────
    def _crawl_one(self, conn, driver, slug: str, season: int,
                   season_type: str, cache_dir: Optional[str]) -> int:
        url = self.build_url(slug, season, self.PAGE, season_type)
        html = self.fetch_team_page(driver, url)
        if not html:
            self.register_failure(conn, f"{slug}|{season}|{self.DOMAIN}")
            return 0
        parsed = self.parse(html, season_type, slug)
        if not parsed:
            self.register_failure(conn, f"{slug}|{season}|{self.DOMAIN}")
            return 0
        rows = [self.build_rows(conn, slug, season, season_type, rec)
                for rec in parsed]
        if cache_dir:
            self.merge_cache(season, slug, season_type, parsed)
        n = self.upsert(conn, rows)
        conn.commit()
        return n

    # ── 主流程 ────────────────────────────────────────────────────────────
    def run_pipeline(self, season: int, resume: bool = False,
                     dry_run: bool = False,
                     cache_dir: Optional[str] = None) -> int:
        """某季全队抓取主循环。

        ``season`` 低于 ``MIN_SEASON`` 直接跳过（已知 BR 无数据，不登记失败以免
        污染 ``crawl_failures``）。``dry_run`` 只枚举+打印计划，不取浏览器/不写库。
        """
        if season < self.MIN_SEASON:
            logger.info("season %s < MIN_SEASON %s，跳过（已知 BR 无此域数据）",
                        season, self.MIN_SEASON)
            return 0
        self.cache_dir = cache_dir or self.cache_dir
        conn = psycopg2.connect(**DB_CONFIG)
        driver = None
        total = 0
        try:
            targets = self.enumerate_team_seasons(conn, season)
            logger.info("season %s: %d 个 (team, season_type) 目标",
                        season, len(targets))
            for i, (slug, season, season_type) in enumerate(targets):
                if resume and self._already_done(conn, slug, season, season_type):
                    logger.info("  [resume] 跳过 %s/%s/%s（已落库）",
                                slug, season, season_type)
                    continue
                if dry_run:
                    logger.info("  [dry-run] 计划抓取 %s/%s/%s",
                                slug, season, season_type)
                    continue
                if driver is None:
                    driver = self.get_driver()
                try:
                    n = self._crawl_one(conn, driver, slug, season,
                                        season_type, cache_dir)
                    total += n
                except Exception as exc:  # noqa: BLE001 - 单队异常不中断整季
                    logger.error("  抓取失败 %s/%s/%s: %s",
                                 slug, season, season_type, exc)
                    self.register_failure(conn, f"{slug}|{season}|{self.DOMAIN}")
                    conn.commit()
                # 限速（队间）
                if i < len(targets) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    from common.browser import quit_driver
                    quit_driver()
                except Exception:  # noqa: BLE001
                    pass
            conn.close()
        logger.info("season %s 完成：upsert %d 行", season, total)
        return total

    # ── 从缓存重放（免重爬，供返工/修正）──────────────────────────────────
    def rework_season(self, season: int,
                      cache_dir: Optional[str] = None) -> int:
        """读取 ``<cache_dir>/<domain>_<season>.json`` 重放落库（免爬）。"""
        cache_dir = cache_dir or self.cache_dir
        path = os.path.join(cache_dir, f"{self.DOMAIN}_{season}.json")
        if not os.path.exists(path):
            logger.warning("[rework] 缓存缺失: %s", path)
            return 0
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        teams = data.get("teams", {})
        conn = psycopg2.connect(**DB_CONFIG)
        total = 0
        try:
            for team, st_map in teams.items():
                for st, recs in st_map.items():
                    rows = [self.build_rows(conn, team, season, st, rec)
                            for rec in recs]
                    total += self.upsert(conn, rows)
            conn.commit()
        finally:
            conn.close()
        logger.info("[rework] 重放完成: %d 行 (season %s)", total, season)
        return total


# ── 共享 CLI 构造器（各爬虫 __main__ 复用）────────────────────────────────
def build_arg_parser(description: str) -> argparse.ArgumentParser:
    """构造统一的爬虫参数（--season/--dry-run/--resume/--cache-dir/--rework）。"""
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--season", type=int, default=None,
                   help="赛季结束年（如 2026 = 2025-26 季）")
    p.add_argument("--dry-run", action="store_true",
                   help="只枚举+打印计划，不取浏览器、不写库")
    p.add_argument("--resume", action="store_true",
                   help="跳过已落库 team×season（断点续传）")
    p.add_argument("--cache-dir", type=str, default=None,
                   help="本季缓存目录，落盘 JSON 供 --rework 重放")
    p.add_argument("--rework", type=int, default=None,
                   help="从缓存重放某季（免爬），需配合 --cache-dir")
    return p


def dispatch_cli(crawler_cls, description: str) -> None:
    """统一的 __main__ 入口：解析参数并驱动 crawler。"""
    args = build_arg_parser(description).parse_args()
    crawler = crawler_cls(cache_dir=args.cache_dir,
                          dry_run=args.dry_run, resume=args.resume)
    if args.rework is not None:
        crawler.rework_season(args.rework, args.cache_dir)
    elif args.season:
        crawler.run_pipeline(args.season, args.resume, args.dry_run,
                             args.cache_dir)
    else:
        print("需指定 --season <结束年> 或 --rework <结束年>")
