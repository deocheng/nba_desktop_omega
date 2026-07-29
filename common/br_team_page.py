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
import datetime
import json
import logging
import os
import random
import re
import shutil
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

from common.browser import ensure_cf_cleared, reset_driver  # noqa: E402

logger = logging.getLogger("br_team_page")

# 进程级日志配置：若调用方尚未配置 handler，则挂一个基础 handler，
# 使 crawler 的进度/失败日志可见（INFO 级别，默认 lastResort 仅 WARNING）。
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

# ── 限速常量 ────────────────────────────────────────────────────────────
# 每次页面加载前强制等待 6-8s（均值 ~7s，≤~8.5 请求/分钟），防 BR 访问限制。
# 2026-07-27 用户要求间隔降到 ~7s（原 6-12s 偏慢）；保留随机抖动防指纹化。
RATE_LIMIT_BASE_S = 6.0
RATE_LIMIT_JITTER_S = 2.0

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
              "请稍候", "正在进行安全验证",
              # 2026-07-27 实测新增：headless 直连 BR 时命中「Performing
              # security verification / This website uses a security service to
              # protect against malicious bots」交互式挑战页（需真人点过），原
              # 标记漏判 → 被误当真实空页/404 缓存、静默丢数据。
              "Performing security verification", "security service",
              "verifies you are not a bot", "security verification")

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

    # 全量爬取默认起始赛季（子类可覆盖，如 TeamPBPCrawler 设 2000）。
    # 低于此的赛季视为 BR 大概率无此表，不在全量范围；可用
    # --start-season N 强制下探（full 模式下「无表」会干净跳过、不记失败）。
    FULL_CRAWL_START: int = 1997

    # 抗休眠/断连：单队撞到 CDP 连接断开（Mac 休眠后唤醒、网络瞬时
    # 抖动等）时，重置驱动并重连仍在 9223 的用户 Chrome，最多重试
    # _CDP_RETRY 次；仍失败再按原逻辑记失败并继续���绝不中断整季。
    _CDP_RETRY: int = 4
    _CDP_RETRY_WAIT: float = 15.0

    def __init__(self, cache_dir: Optional[str] = None,
                 dry_run: bool = False, resume: bool = False,
                 start_season: Optional[int] = None) -> None:
        # 默认缓存根统一放到 12T 数据盘，避免占项目盘；可用 --cache-dir 覆盖。
        self.cache_dir = cache_dir or os.path.join(
            "/Volumes/12T/NBA", f"br_{self.DOMAIN}_cache")
        self.dry_run = dry_run
        self.resume = resume
        # 全量爬取起始赛季（--start-season 覆盖 FULL_CRAWL_START）。
        self._start_season = start_season
        self._slug_map: Optional[Dict[str, str]] = None
        # 最近一次 fetch_team_page 是否命中风控(CF)挑战页。供调用方（如
        # br_player_page.run_players）区分「CF 拦截导致的 0 行」与「真无数据」，
        # 从而决定是暂停等用户清 CF 还是仅告警，避免缺口被静默清零。
        self._last_fetch_cf: bool = False
        # 最近一次 fetch_team_page 是否命中 404（页面不存在）。供调用方区分
        # 「404 永久失效」与「CF 拦截 / 空页」，从而隔离该 slug 而非死循环重试。
        self._last_fetch_404: bool = False
        # 调试：非 None 时把每次 fetch 的 HTML 落盘到该路径（供 agent
        # 跨隔离环境诊断「0 行」根因：CF 页 / 表 id 不对 / 真无数据）。
        self.dump_html_path: Optional[str] = None
        # 同进程内同 URL HTML 缓存（队页 PBP 的 Regular/Playoffs 两目标
        # 指向同一主页面，去重避免重复抓 BR 触发 Cloudflare）。
        self._html_cache: Dict[str, str] = {}

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
        # ── 严格限速：每次页面加载前强制静默等待（防 BR 访问限制）──
        _wait = RATE_LIMIT_BASE_S + random.uniform(0, RATE_LIMIT_JITTER_S)
        logger.info("  [限速] 加载前等待 %.1fs: %s", _wait, url)
        time.sleep(_wait)
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
        """写 ``crawl_failures(game_id=token, task_type, resolved=False)``。

        防御性实现：
          * 先 ``conn.rollback()`` 清理可能已中止的事务，避免上层在已
            中止事务上调用时连锁抛 ``InFailedSqlTransaction`` 导致整进程崩溃；
          * INSERT 自身失败也吞掉并记录 WARNING，绝不向上抛出。
        """
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO crawl_failures (game_id, task_type, resolved) "
                "VALUES (%s, %s, %s)",
                (token, self.TASK_TYPE, False),
            )
            conn.commit()
            cur.close()
        except Exception as _e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            logger.warning("register_failure 写入失败（已忽略）: %s", _e)

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
        # 注入 franchise_id：队表按 team_abbr/abbreviation 归入统一 franchise，
        # 落实"数据四性·统一连贯"——同一球队历史缩写(NJN/BRK 等)归属同一 franchise。
        if table in ('team_roster', 'team_per_36', 'team_coaches',
                     'team_leaderboards', 'team_lineups', 'team_referees', 'team_summaries'):
            if getattr(self, '_fmap', None) is None:
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT abbreviation, franchise_id FROM team_summaries WHERE franchise_id IS NOT NULL")
                self._fmap = {ab: fid for ab, fid in cur.fetchall()}
                cur.close()
            for r in rows:
                ab = r.get('team_abbr') or r.get('abbreviation')
                if ab and 'franchise_id' not in r and ab in self._fmap:
                    r['franchise_id'] = self._fmap[ab]
        # 去重：同一冲突键在单批次出现多次会触发
        # "ON CONFLICT DO UPDATE command cannot affect row a second time"
        # （首行 INSERT/UPDATE 后，次行对同一目标行再次 DO UPDATE）。
        # 冲突键即唯一约束，重复即同一逻辑行 -> 保留最后一次出现，幂等入库。
        _dedup: dict = {}
        for _r in rows:
            _dedup[tuple(_r.get(c) for c in conflict_cols)] = _r
        rows = list(_dedup.values())
        cols: List[str] = []
        for r in rows:
            for k in r.keys():
                if k not in cols:
                    cols.append(k)
        update_cols = [c for c in cols if c not in conflict_cols]
        col_sql = ", ".join(cols)
        # execute_values 只接受【单个】%s 占位符，由它将此 %s 展开为
        # (v1,...),(v2,...) 多行值列表。切勿写成 (%s, %s, %s) 多占位符，
        # 否则 psycopg2 抛 "the query contains more than one '%s' placeholder"。
        placeholders = "%s"
        if update_cols:
            upd_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in update_cols])
            conflict_sql = (f"ON CONFLICT ({', '.join(conflict_cols)}) "
                            f"DO UPDATE SET {upd_sql}")
        else:
            conflict_sql = f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
        sql = (f"INSERT INTO {table} ({col_sql}) VALUES {placeholders} "
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

    def _is_expected_empty(self, slug: str, season: int,
                           season_type: str) -> bool:
        """子类可覆盖：某 (队,季,season_type) 解析为空是否属「正常无数据」
        （而非抓取失败）。默认 False（空即记失败）。队页 PBP 用其让
        「未进季后赛故无 pbp_stats_post 表」不误记失败。"""
        return False

    # ── 全量赛季范围解析 ─────────────────────────────────────────────────
    def _resolve_all_seasons(self, conn) -> Tuple[int, int]:
        """全量爬取时的赛季范围 [start, end]。

        ``start`` = ``--start-season`` 或 ``FULL_CRAWL_START``（子类可覆盖，
        不低于 ``MIN_SEASON``）；``end`` = ``max(当前年, team_summaries
        最大 season)``，自动含入最新季（如 2026 季后赛结束后的 2026）。
        """
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(season), 0) FROM team_summaries")
        max_db = cur.fetchone()[0] or 0
        cur.close()
        cur_year = datetime.date.today().year
        end = max(cur_year, max_db)
        start = self._start_season or self.FULL_CRAWL_START
        start = max(start, self.MIN_SEASON)
        return start, end

    # ── 单队单季抓取 ──────────────────────────────────────────────────────
    def _crawl_one(self, conn, driver, slug: str, season: int,
                   season_type: str, cache_dir: Optional[str],
                   full: bool = False, html: Optional[str] = None) -> int:
        # ``html`` 由调用方提供时（按队分组、用页面 Previous/Next Season 按钮
        # 在同一次浏览器会话内走查多季），跳过 fetch_team_page，避免每季重新
        # driver.get 触发 Cloudflare；为 None 时退回原逻辑（build_url + 抓取
        # + 同 URL 进程内去重）。
        if html is None:
            url = self.build_url(slug, season, self.PAGE, season_type)
            cached = self._html_cache.get(url)
            if cached is not None:
                html = cached
            else:
                html = self.fetch_team_page(driver, url)
                self._html_cache[url] = html
        if self.dump_html_path:
            try:
                with open(self.dump_html_path, "w", encoding="utf-8") as _fh:
                    _fh.write(html or "")
                _low = (html or "").lower()
                logger.info("[dump] 落盘 %s (%d 字节)",
                           self.dump_html_path, len(html or ""))
                logger.info(
                    "[dump] pbp_stats=%s pbp_stats_post=%s CF=%s 404=%s",
                    "pbp_stats" in _low,
                    "pbp_stats_post" in _low,
                    any(m.lower() in _low for m in CF_MARKERS),
                    any(m.lower() in _low for m in NOT_FOUND_MARKERS),
                )
            except Exception as _exc:  # noqa: BLE001
                logger.warning("[dump] 落盘失败 %s: %s",
                              self.dump_html_path, _exc)
        # CF/404 判定：对「调用方提供 html」路径同样生效（page_source 取回的
        # 挑战页/404 页不是空串，必须显式识别，否则误当「真无数据」）。
        _cls = self._classify_html(html)
        if _cls == "cf":
            self._last_fetch_cf = True
            logger.warning("CF 挑战页，跳过: %s/%s/%s", slug, season, season_type)
            if full:
                return 0
            self.register_failure(conn, f"{slug}|{season}|{self.DOMAIN}")
            return 0
        if _cls == "404":
            self._last_fetch_404 = True
            logger.warning("BR 404 页面，隔离: %s/%s/%s", slug, season, season_type)
            if full:
                return 0
            self.register_failure(conn, f"{slug}|{season}|{self.DOMAIN}")
            return 0
        if _cls == "empty":
            if full:
                logger.info("  [full-跳过] %s/%s/%s 无 HTML（CF未清/404/空页），不记失败",
                            slug, season, season_type)
                return 0
            self.register_failure(conn, f"{slug}|{season}|{self.DOMAIN}")
            return 0
        # ── 队标抽取（logo 管线；仅 Regular 首遍，幂等+节流）──
        # 队页 HTML 已就绪即抽取 <img class="teamlogo"> src 并节流落盘到
        # /Volumes/12T/NBA/logo/{slug}-{season}.png。Playoffs 遍复用同页 HTML，
        # 故只走 Regular 一遍；失败绝不中断抓取（独立 try）。
        if season_type == "Regular":
            try:
                from common.logo_store import extract_team_logo_src, save_team_logo
                _src = extract_team_logo_src(html)
                if _src:
                    _path = save_team_logo(slug, season, _src)
                    if _path:
                        logger.info("  [logo] 存 %s", _path)
            except Exception as _le:  # noqa: BLE001
                logger.warning("  [logo] 抽取/下载失败（已忽略）: %s", _le)
        parsed = self.parse(html, season_type, slug)
        if not parsed:
            if full:
                logger.info(
                    "  [full-跳过] %s/%s/%s 页面无 %s 表（CF未清/404/该范围无数据），不记失败",
                    slug, season, season_type, self.TABLE_ID)
                return 0
            if not self._is_expected_empty(slug, season, season_type):
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
    # ── HTML 分类 / 页面按钮导航（同会话走查多季）────────────────────────
    def extra_extract(self, conn, driver, slug: str, season: int,
                     html: str) -> int:
        """同页多表抽取钩子（子类覆写）。基类默认无操作。

        在 ``_crawl_team`` 每季处理完（Regular+Playoffs 共用同一份
        ``html``）后调用一次，供子类在「零额外网络请求」前提下顺带
        抽取同页上的其他数据表（如 team_shooting）。
        """
        return 0

    def _classify_html(self, html: Optional[str]) -> str:
        """返回 'cf' | '404' | 'empty' | 'ok'。对「调用方提供 html」路径
        （page_source 取回的挑战页/404 页非空串）同样能识别，避免误当空数据。"""
        if not html:
            return "empty"
        low = html.lower()
        if any(mk.lower() in low for mk in CF_MARKERS):
            return "cf"
        if any(mk.lower() in low for mk in NOT_FOUND_MARKERS):
            return "404"
        return "ok"

    def _nav_button(self, driver, direction: str,
                    current_season: Optional[int] = None) -> Optional[str]:
        """在当前队页找出 'Previous Season' / 'Next Season' 邻季链接，返回其
        （绝对）href；找不到返回 None（调用方回退 ``driver.get`` 构造 URL）。

        为什么要这样设计（而非直接 ``a.click()`` 后读 ``page_source``）：
        Basketball-Reference 把 ``pbp_stats`` 表包在 HTML 注释里，靠页面脚本
        在 load 后才注入为真实 DOM。``a.click()`` 触发的客户端导航不会等待
        脚本执行，随后立即读 ``driver.page_source``（= ``documentElement.
        outerHTML``）往往在该表注入前/注释态读取，导致 ``_find_br_table``
        扫不到表 → 整季被静默判为空、丢数据（实跑 full_pbp4.log 暴露：凡经
        按钮导航的赛季全部「无 pbp_stats」）。``driver.get()`` 会等过 load，
        故稳定可取。因此本方法只负责**借按钮解析出正确的邻季 URL**（同时正确
        处理 franchise 搬迁：页面自身邻季链接指向正确的历史 franchise 页，
        而非用当前 slug 拼 ``year-1`` 可能 404），由调用方 ``driver.get(href)``
        强制完整加载。仍会 ``a.click()`` 以贴合「用页面按钮导航」的语义。

        匹配策略：优先按「目标赛季年」匹配 ``/teams/{任意slug}/{year}.html``
        的链接（文本不含 'Previous Season' 时也能命中，且天然处理搬迁）；
        其次兜底按链接文本含 'Previous/Next Season'。
        """
        ev = getattr(driver, "_eval", None)
        if ev is None:
            return None
        want = "Previous Season" if direction == "prev" else "Next Season"
        target_year = None
        if current_season is not None:
            target_year = (current_season - 1) if direction == "prev" \
                else (current_season + 1)
        # 同时返回 href 与是否命中目标年，便于调用方决定是否需回退。
        js = (
            "(() => {"
            "  const want = " + repr(want) + ";"
            "  const ty = " + ("null" if target_year is None else str(target_year)) + ";"
            "  const ym = /\\/teams\\/[^\\/]+\\/(\\d{4})\\.html/;"
            "  const as = Array.from(document.querySelectorAll('a[href]'));"
            "  let best = null;"
            "  for (const a of as) {"
            "    const href = a.getAttribute('href') || '';"
            "    const m = href.match(ym);"
            "    if (!m) continue;"
            "    const yr = parseInt(m[1], 10);"
            "    const t = (a.getAttribute('title')||'') + ' ' + (a.textContent||'');"
            "    if (ty !== null && yr === ty && t.indexOf(want) !== -1)"
            "      return {href: href, hit: true};"
            "    if (ty !== null && yr === ty && !best) { best = href; }"
            "    if (t.indexOf(want) !== -1 && !best) { best = href; }"
            "  }"
            "  return best ? {href: best, hit: !!best} : null;"
            "})()"
        )
        try:
            res = ev(js)
        except Exception:  # noqa: BLE001
            return None
        if not res or not res.get("href"):
            return None
        href = res["href"]
        # 相对路径补全为绝对 URL（CDP Page.navigate 需绝对地址）。
        if href.startswith("/"):
            href = "https://www.basketball-reference.com" + href
        # 点击按钮（贴合「用页面按钮导航」语义）；随后调用方会 driver.get(href)
        # 强制完整加载以可靠读取 pbp_stats 注释表。
        click_js = (
            "(() => {"
            "  const want = " + repr(want) + ";"
            "  const ty = " + ("null" if target_year is None else str(target_year)) + ";"
            "  const ym = /\\/teams\\/[^\\/]+\\/(\\d{4})\\.html/;"
            "  const as = Array.from(document.querySelectorAll('a[href]'));"
            "  for (const a of as) {"
            "    const href = a.getAttribute('href') || '';"
            "    const m = href.match(ym);"
            "    const yr = m ? parseInt(m[1], 10) : null;"
            "    const t = (a.getAttribute('title')||'') + ' ' + (a.textContent||'');"
            "    if (ty !== null && yr === ty && t.indexOf(want) !== -1) { a.click(); return; }"
            "    if (ty !== null && yr === ty) { a.click(); return; }"
            "    if (t.indexOf(want) !== -1) { a.click(); return; }"
            "  }"
            "})()"
        )
        try:
            ev(click_js)
        except Exception:  # noqa: BLE001 - 点击失败不致命，调用方仍 get(href)
            pass
        return href

    def _ensure_driver(self, driver):
        """懒加载并做 CF 握手的共享驱动（进程级单例）。"""
        if driver is None:
            driver = self.get_driver()
            # CF 握手：首次导航 BR 首页，遇挑战则无限等待用户在可见 Chrome
            # 窗口手动点过（CDP 模式）；cookie 持久于用户 Chrome profile，
            # 后续各队页复用，不再逐个挑战。
            ensure_cf_cleared(driver)
        return driver

    def _crawl_team(self, conn, driver, slug: str, start: int, end: int,
                    cache_dir, resume: bool, full: bool) -> int:
        """单 franchise 整段季走查：最新季 ``driver.get`` 载入，随后用页面
        **Previous Season** 按钮在同一次浏览器会话内逐季回退到 ``start``；
        每季解析 Regular + Playoffs。``--resume`` 跳过已落库季（仍继续走查
        以推进按钮），使中断后续跑无重复、无遗漏。返回该队落库行数。

        关键修正（修复 full_pbp4 静默丢数据）：按钮仅用于**解析出正确的邻季
        URL**（正确处理 franchise 搬迁），随后一律 ``driver.get(href)`` 强制
        完整加载——绝不直接读 ``a.click()`` 后的 ``page_source``（B-R 把
        pbp_stats 包注释、靠 load 后脚本注入真实 DOM，点击导航读到的是注入
        前/注释态，导致整季被误判为空）。
        """
        total = 0
        cur = end
        first = True
        pending_html: Optional[str] = None  # 上一轮导航/首载得到的页面 HTML
        while cur >= start:
            if first:
                html = self.fetch_team_page(driver, self.build_url(slug, cur, self.PAGE))
                first = False
            else:
                html = pending_html if pending_html is not None else driver.page_source
            for st in self.SEASON_TYPES:
                if resume and self._already_done(conn, slug, cur, st):
                    logger.info("  [resume] 跳过 %s/%s/%s（已落库）", slug, cur, st)
                    continue
                total += self._crawl_one(conn, driver, slug, cur, st,
                                         cache_dir, full, html=html)
            # 同页额外抽取（如 shooting）：零额外请求，独立 try 不中断主流程。
            try:
                self.extra_extract(conn, driver, slug, cur, html)
            except Exception as _ee:  # noqa: BLE001
                logger.warning("  [extra] 抽取失败（已忽略）: %s", _ee)
            # 推进到上一季：用 Previous Season 按钮解析出正确邻季 URL，
            # 再 driver.get 强制完整加载（见方法 docstring 的修正说明）。
            pending_html = None
            if cur > start:
                href = self._nav_button(driver, "prev", current_season=cur)
                if href:
                    pending_html = self.fetch_team_page(driver, href)
                else:
                    # 无 Previous 按钮（如最老季/挑战页）→ 用当前 slug 拼 URL
                    # 直连构造（同会话，cookie 已留存不触发 CF）。
                    logger.info("  [nav] %s/%d 无 Previous 按钮，回退 GET %d",
                                slug, cur, cur - 1)
                    pending_html = self.fetch_team_page(
                        driver, self.build_url(slug, cur - 1, self.PAGE))
            cur -= 1
        return total

    def run_pipeline(self, season: int, resume: bool = False,
                     dry_run: bool = False,
                     cache_dir: Optional[str] = None,
                     team: Optional[str] = None,
                     full: bool = False,
                     start_season: Optional[int] = None) -> int:
        """某季（或全量范围）全队抓取主循环。

        新版按 **franchise（队）× 季** 分组遍历：每队先 ``driver.get`` 载入其
        最新季页面，随后用页面上的 **Previous Season** 按钮在同一次浏览器会话内
        逐季回退（避免每季重新构造 URL 触发 Cloudflare）；到 ``start`` 截止。
        ``full=True`` 时范围由 ``_resolve_all_seasons`` 给出（可 ``--start-season``
        下探）。``--resume`` 跳过已落库队×季（断点续传，仍会继续走查以推进按钮）。
        ``dry_run`` 只枚举+打印计划，不取浏览器/不写库。
        """
        # ── 解析赛季范围 ──
        if full:
            _c0 = psycopg2.connect(**DB_CONFIG)
            try:
                start, end = self._resolve_all_seasons(_c0)
            finally:
                _c0.close()
            if start_season:
                start = max(int(start_season), self.MIN_SEASON)
        else:
            start = end = season
            if start < self.MIN_SEASON:
                logger.info("season %s < MIN_SEASON %s，跳过（已知 BR 无此域数据）",
                            season, self.MIN_SEASON)
                return 0
        self.cache_dir = cache_dir or self.cache_dir
        conn = psycopg2.connect(**DB_CONFIG)
        driver = None
        total = 0
        try:
            # franchise 集合：取 [start,end] 内所有出现过的队（含已搬迁/历史队，
            # 如原夏洛特黄蜂 CHH），避免只按 end 季枚举漏掉中途消失的 franchise。
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT abbreviation FROM team_summaries "
                "WHERE season BETWEEN %s AND %s", (start, end))
            abbrs = [r[0] for r in cur.fetchall()]
            cur.close()
            slugs = sorted({self._br_slug(conn, a) for a in abbrs})
            if team:
                slugs = [s for s in slugs if s.upper() == team.upper()]
            logger.info("范围 season %d → %d：%d 个 franchise 目标",
                        start, end, len(slugs))
            if dry_run:
                for sl in slugs:
                    for s in range(end, start - 1, -1):
                        for st in self.SEASON_TYPES:
                            logger.info("  [dry-run] 计划抓取 %s/%s/%s", sl, s, st)
                return 0
            for idx, sl in enumerate(slugs):
                n = 0
                for _ra in range(1, self._CDP_RETRY + 1):
                    try:
                        driver = self._ensure_driver(driver)
                        n = self._crawl_team(conn, driver, sl, start, end,
                                             cache_dir, resume, full)
                        break
                    except Exception as exc:  # noqa: BLE001 - 单队异常
                        _msg = str(exc).lower()
                        _is_conn = any(
                            k in _msg for k in (
                                "refused", "connect", "closed", "reset",
                                "timed out", "timeout", "websocket", "broken",
                                "eof", "no such", "crash", "target", "abort",
                            ))
                        if _is_conn and _ra < self._CDP_RETRY:
                            logger.warning(
                                "  [抗断连] %s CDP 连接异常(%s)，重置驱动重连用户 "
                                "Chrome，%ds 后重试(%d/%d)",
                                sl, exc, int(self._CDP_RETRY_WAIT), _ra, self._CDP_RETRY)
                            try:
                                reset_driver()
                            except Exception:  # noqa: BLE001
                                pass
                            try:
                                driver = self.get_driver()
                            except Exception:  # noqa: BLE001
                                pass
                            time.sleep(self._CDP_RETRY_WAIT)
                            continue
                        logger.error("  抓取失败 %s: %s", sl, exc)
                        try:
                            self.register_failure(conn, f"{sl}|{season}|{self.DOMAIN}")
                        except Exception:  # noqa: BLE001
                            pass
                        conn.commit()
                        break
                total += n
                # 队间限速
                if idx < len(slugs) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    from common.browser import quit_driver
                    quit_driver()
                except Exception:  # noqa: BLE001
                    pass
            conn.close()
        logger.info("完成：upsert %d 行（season %s%s）",
                    total, start, f"→{end}" if full else "")
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
    p.add_argument("--team", type=str, default=None,
                   help="只爬指定队（BR slug，如 SAS），用于试爬/调试")
    p.add_argument("--dump-html", type=str, default=None,
                   help="调试：把每次 fetch 的 HTML 落盘到该路径（含表/CF 诊断）")
    p.add_argument("--all-seasons", action="store_true",
                   help="全量自动爬取：遍历 [start, end] 所有赛季（end=max(当前年, team_summaries 最大季)），--resume 默认开启")
    p.add_argument("--start-season", type=int, default=None,
                   help="全量爬取起始赛季（覆盖各爬虫 FULL_CRAWL_START）")
    p.add_argument("--caffeinate", action="store_true",
                   help="macOS 下以 caffeinate -i 自包裹进程防休眠（无人值守全量用）")
    return p


def _maybe_caffeinate(argv: List[str]) -> None:
    """macOS 下若未被 caffeinate 包裹，则 re-exec 自身到 ``caffeinate -i``
    之下，使整批爬取期间 Mac 不休眠（无人值守）。

    靠环境变量 ``BR_CRAWL_CAFFEINATED`` 防递归；非 macOS 或系统无
    ``caffeinate`` 时直接返回（无副作用）。
    """
    if os.environ.get("BR_CRAWL_CAFFEINATED"):
        return
    if sys.platform != "darwin":
        return
    if not shutil.which("caffeinate"):
        return
    env = dict(os.environ, BR_CRAWL_CAFFEINATED="1")
    logger.info("全量无人值守：以 caffeinate -i 自包裹进程（防休眠）")
    os.execvpe("caffeinate", ["caffeinate", "-i", sys.executable, *argv], env)


def _run_all_seasons(crawler, args) -> None:
    """全量自动爬取：run_pipeline 内部已按 [start,end] 解析范围并队×季走查。

    ``--resume`` 默认开启（中断可续传，重跑跳过已落库球队）；``--dry-run``
    仅打印计划；``full=True`` 让「无表/404/CF 未清」干净跳过、不污染
    ``crawl_failures``。
    """
    total = crawler.run_pipeline(
        season=0, resume=True, dry_run=args.dry_run,
        cache_dir=args.cache_dir, team=args.team,
        full=True, start_season=args.start_season,
    )
    logger.info("全量爬取完成：累计落库 %d 行", total)


def dispatch_cli(crawler_cls, description: str) -> None:
    """统一的 __main__ 入口：解析参数并驱动 crawler。"""
    # 全量无人值守：macOS 下自包 caffeinate 防休眠（仅一次，env 防递归）。
    if "--caffeinate" in sys.argv:
        _maybe_caffeinate(sys.argv)
    args = build_arg_parser(description).parse_args()
    crawler = crawler_cls(cache_dir=args.cache_dir,
                          dry_run=args.dry_run, resume=args.resume,
                          start_season=args.start_season)
    if args.dump_html:
        crawler.dump_html_path = os.path.abspath(args.dump_html)
    if args.rework is not None:
        crawler.rework_season(args.rework, args.cache_dir)
    elif args.all_seasons:
        _run_all_seasons(crawler, args)
    elif args.season:
        crawler.run_pipeline(args.season, args.resume, args.dry_run,
                             args.cache_dir, args.team)
    else:
        print("需指定 --season <结束年> / --all-seasons / --rework <结束年>")
