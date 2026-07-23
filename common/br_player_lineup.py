"""common/br_player_lineup.py — BR 球员 lineup 爬虫中间基类（BRPlayerLineupCrawlerBase）。

继承 ``common.br_player_page.BRPlayerPageCrawler``，在其 CF/限速/upsert/归档/断点
续跑机制之上，增加 ``(slug, year)`` 二维迭代模型——lineup 页是 per-player per-year
``/players/{letter}/{slug}/lineups/{year}``，与 shooting 的「一页全赛季、按 slug
一维迭代」模型不同。

核心差异（相对 BRPlayerPageCrawler）：
  * URL 带 year 维度：``build_url(slug, year)``
  * 归档带 year：``save_raw_html(slug, year, html)`` -> ``lineups_{year}.html``
  * 断点续跑键 = ``(slug, year)`` 对（非 slug 单列）
  * 404 隔离表 ``player_lineups_404`` 以 ``(slug, year)`` 复合 PK
  * slug 宇宙源 = ``player_shooting.player_id``（禁用 player_gamelog.br_player_id）
  * 主循环 ``run_lineups`` 遍历 ``(slug, year)`` 列表

**不修改** ``common/br_player_page.py``（最小爆炸半径）；子类 ``PlayerLineupCrawler``
只需实现 ``parse`` / ``build_rows`` / ``upsert`` 三个钩子。

DB 连接：host=127.0.0.1, port=5433, dbname=nba, user=postgres；
口令走 PGPASSWORD 环境变量（禁止硬编码）。
"""
from __future__ import annotations

import logging
import os
import psycopg2
from pathlib import Path
from typing import List, Optional, Tuple

from common.br_player_page import BRPlayerPageCrawler, DB_CONFIG

# CF 握手门禁：爬取前在「爬虫驱动的标签页」里先清 CF。
from common.browser import ensure_cf_cleared  # noqa: E402

# BR 球员 lineup 页基地址（year = 赛季结束年，如 2014 = 2013-14 赛季）
BR_PLAYER_LINEUP_URL = (
    "https://www.basketball-reference.com/players/{letter}/{slug}/lineups/{year}"
)


class BRPlayerLineupCrawlerBase(BRPlayerPageCrawler):
    """球员 lineup 爬虫中间基类（2D (slug, year) 迭代模型）。

    子类（如 ``PlayerLineupCrawler``）只需实现 ``parse`` / ``build_rows`` /
    ``upsert`` 三个钩子；本类固化「取浏览器 -> CF 握手 -> (slug,year) 二维迭代 ->
    抓页 -> 归档 -> 解析 -> 入库 -> 断点续跑」主流程。
    """

    # —— 类常量（覆盖 BRPlayerPageCrawler 默认）——
    DOMAIN = "player_lineup"
    TASK_TYPE = "br_player_lineup"
    TABLE = "player_lineups"
    QUARANTINE_TABLE = "player_lineups_404"
    CONFLICT_COLS = ("player_id", "season", "season_type", "lineup_key")
    MIN_SEASON = 1997
    MAX_SEASON = 2026
    RAW_ARCHIVE = "raw_archive/br_players"  # 复用 shooting 归档根

    # ── URL（球员 lineup 页带 year 维度）─────────────────────────────────
    def build_url(self, slug: str, year: Optional[int] = None) -> str:
        """构造 BR 球员 lineup 页 URL：/players/{letter}/{slug}/lineups/{year}。

        ``year`` 为赛季结束年（2014 = 2013-14 赛季）。若 ``year`` 为 None
        （不该发生，但防御性处理），退回 0 以避免格式异常。
        """
        letter = (slug[0].lower() if slug else "a")
        y = year if year is not None else 0
        return BR_PLAYER_LINEUP_URL.format(letter=letter, slug=slug, year=y)

    # ── 原始 HTML 归档（per-year，不与 shooting 冲突）────────────────────
    def save_raw_html(self, slug: str, year: int, html: str) -> Path:
        """把渲染 HTML 落盘 raw_archive/br_players/{slug}/lineups_{year}.html。

        shooting 归档在 ``shooting.html``，lineup 在 ``lineups_{year}.html``，
        两者不冲突、共存于同一 slug 目录。
        """
        d = Path(self.RAW_ARCHIVE) / slug
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"lineups_{year}.html"
        p.write_text(html, encoding="utf-8")
        return p

    # ── (slug, year) 目标枚举 ─────────────────────────────────────────────
    def enumerate_lineup_targets(self, conn) -> List[Tuple[str, int]]:
        """枚举待抓 ``(slug, year)`` 对。

        宇宙源: ``player_shooting`` 的 ``DISTINCT (player_id, season)`` WHERE
        ``season_type='Regular'`` AND ``season >= 1997``。
        排除:
          1. 已落库 ``player_lineups`` 的 ``(player_id, season)``
          2. 已隔离 ``player_lineups_404`` 的 ``(slug, year)``

        ⚠️ 禁用 ``player_gamelog.br_player_id``（corrupt，含 phantom slug）。
        """
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ps.player_id AS slug, ps.season AS year
            FROM player_shooting ps
            LEFT JOIN player_lineups_404 q
                   ON q.slug = ps.player_id AND q.year = ps.season
            WHERE ps.season_type = 'Regular'
              AND ps.player_id IS NOT NULL
              AND ps.season >= %s
              AND q.slug IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM player_lineups pl
                  WHERE pl.player_id = ps.player_id
                    AND pl.season = ps.season
              )
            ORDER BY ps.player_id, ps.season
            """,
            (self.MIN_SEASON,),
        )
        rows: List[Tuple[str, int]] = [(r[0], r[1]) for r in cur.fetchall()]
        cur.close()
        return rows

    def build_targets(self, conn, slugs: Optional[List[str]] = None,
                      years: Optional[List[int]] = None) -> List[Tuple[str, int]]:
        """构造 ``(slug, year)`` 目标列表（供 CLI --slugs/--years 使用）。

        * 两个都给 -> 笛卡尔积
        * 只给 ``slugs`` -> 另一维从 ``player_shooting`` 取该 slug 全赛季
        * 只给 ``years`` -> 另一维从 ``player_shooting`` 取该年全 slug
        * 都不给 -> ``enumerate_lineup_targets(conn)``
        """
        if slugs and years:
            return [(s, y) for s in slugs for y in years]
        cur = conn.cursor()
        if slugs and not years:
            cur.execute(
                "SELECT DISTINCT player_id, season FROM player_shooting "
                "WHERE season_type='Regular' AND player_id IS NOT NULL "
                "AND season >= %s AND player_id = ANY(%s) "
                "ORDER BY player_id, season",
                (self.MIN_SEASON, list(slugs)),
            )
            rows = [(r[0], r[1]) for r in cur.fetchall()]
            cur.close()
            return rows
        if years and not slugs:
            cur.execute(
                "SELECT DISTINCT player_id, season FROM player_shooting "
                "WHERE season_type='Regular' AND player_id IS NOT NULL "
                "AND season >= %s AND season = ANY(%s) "
                "ORDER BY player_id, season",
                (self.MIN_SEASON, list(years)),
            )
            rows = [(r[0], r[1]) for r in cur.fetchall()]
            cur.close()
            return rows
        cur.close()
        return self.enumerate_lineup_targets(conn)

    # ── 断点续跑：(slug, year) 是否已落库 ──────────────────────────────────
    def _player_done(self, conn, slug: str, year: int) -> bool:
        """若 player_lineups 已有 (player_id=slug, season=year) 行，视为已抓。"""
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM {self.TABLE} "
            f"WHERE player_id=%s AND season=%s LIMIT 1",
            (slug, year),
        )
        found = cur.fetchone() is not None
        cur.close()
        return found

    # ── 404 隔离：(slug, year) 复合 PK ─────────────────────────────────────
    def _quarantine_slug(self, conn, slug: str, year: int,
                         note: str = "http_404") -> None:
        """把运行时 fetch 命中 404 的 (slug, year) 隔离到 player_lineups_404。

        复合 PK ``(slug, year)``：404 可能只影响某年（如早期赛季页面不存在），
        不应隔离整个 slug 的所有年份。
        """
        if conn is None:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO player_lineups_404 (slug, year, note) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (slug, year) DO UPDATE SET "
                "note = EXCLUDED.note, "
                "first_seen = LEAST(player_lineups_404.first_seen, now())",
                (slug, year, note),
            )
            conn.commit()
        finally:
            cur.close()

    # ── 单 (slug, year) 抓取 ──────────────────────────────────────────────
    def _crawl_player(self, conn, driver, slug: str, year: int) -> int:
        """抓一个 (slug, year) 页：导航 -> 404隔离/CF处理 -> 归档 -> 解析入库。

        * CF 挑战 / 空页 -> 登记失败，返回 0（run_lineups 决定是否暂停重试）。
        * **404 命中** -> 隔离到 player_lineups_404（note='http_404'），
          **不**写 raw_archive、**不**解析、**不**登记 crawl_failures，返回 0。
        """
        url = self.build_url(slug, year)
        html = self.fetch_team_page(driver, url)
        if not html:
            if self._last_fetch_404:
                self._quarantine_slug(conn, slug, year, note="http_404")
                logger.warning(
                    "  ⚠️ %s/%s 命中 BR 404 -> 隔离（不存档/不解析）", slug, year)
                return 0
            # CF 挑战页或空页：登记失败，交由 run_lineups 区分重试/告警。
            self.register_failure(conn, f"{slug}|{year}|player_lineup")
            return 0
        self.save_raw_html(slug, year, html)
        return self._consume_html(conn, slug, year, html)

    def _consume_html(self, conn, slug: str, year: int, html: str) -> int:
        """解析并入库一页 HTML（供 _crawl_player 与 rework_from_archive 复用）。

        ``self.parse(html)`` 返回的记录含 ``season_type`` 字段（由解析器从
        ``#lineups``/``#lineups_po`` 表探测）；``year`` 作为 ``season`` 注入。
        """
        parsed = self.parse(html)  # 多态 -> 子类 parse（委托 parse_player_lineups_html）
        if not parsed:
            self.register_failure(conn, f"{slug}|{year}|player_lineup")
            return 0
        rows = []
        for rec in parsed:
            st = rec.get("season_type", "Regular")
            rows.append(self.build_rows(conn, slug, year, st, rec))
        n = self.upsert(conn, rows)
        conn.commit()
        return n

    # ── 主循环：(slug, year) 二维迭代 ─────────────────────────────────────
    def run_lineups(self, conn, targets: List[Tuple[str, int]],
                    resume: bool = False, dry_run: bool = False) -> int:
        """遍历 ``(slug, year)`` 列表抓取（断点续跑跳过已落库；dry_run 只枚举不抓）。

        返回 upsert 总行数。

        加固点（对齐 run_players 的 CF 处理策略）：
          1. 爬取前先在「爬虫驱动的标签页」里做一次 CF 握手门禁。
          2. 缺口 (slug, year) 抓取/解析得 0 行且不是「已落库」跳过的，
             绝不静默当成功：
             - 若命中风控（``_last_fetch_cf``）：暂停等用户清 CF 后重试一次；
             - 否则：打醒目 WARNING，记为缺口未清。
        """
        if not targets:
            logger.info("枚举为空，无需抓取")
            return 0
        logger.info("待处理 (slug, year) 对数: %d", len(targets))
        total = 0
        driver = None
        try:
            if not dry_run:
                driver = self.get_driver()
                # CF 握手门禁：在爬虫自己驱动的标签页里先清 CF 再开爬。
                try:
                    ensure_cf_cleared(driver)
                except Exception as _e:  # noqa: BLE001
                    logger.warning("CF 握手前置检查异常（仍继续尝试抓取）: %s", _e)
            for i, (slug, year) in enumerate(targets):
                if resume and self._player_done(conn, slug, year):
                    logger.info("  [resume] 跳过 %s/%s（已落库）", slug, year)
                    continue
                if dry_run:
                    logger.info("  [dry-run] 计划抓取 %s/%s", slug, year)
                    continue
                # 缺口 (slug, year)：最多 2 次尝试。命中 CF 挑战页则暂停等用户
                # 清完再重试，绝不把 0 行静默当成功。
                n = 0
                for _attempt in range(2):
                    try:
                        n = self._crawl_player(conn, driver, slug, year)
                    except Exception as exc:  # noqa: BLE001 - 单页异常不中断整体
                        logger.error("  抓取失败 %s/%s: %s", slug, year, exc)
                        self.register_failure(
                            conn, f"{slug}|{year}|player_lineup")
                        conn.commit()
                        n = 0
                    if n > 0:
                        break
                    if self._last_fetch_cf:
                        logger.warning(
                            "  ⚠️ %s/%s 抓取得 0 行且命中 CF 挑战页 -> "
                            "暂停等待用户手动清 CF 后重试", slug, year)
                        try:
                            ensure_cf_cleared(driver)
                        except Exception as _e:  # noqa: BLE001
                            logger.warning("  CF 握手等待异常（继续）: %s", _e)
                        continue  # 清完重试一次
                    logger.warning(
                        "  ⚠️ %s/%s 抓取得 0 行（疑似 CF 拦截/解析失败/空数据），"
                        "不视为成功；记为缺口未清", slug, year)
                    break
                total += n
                logger.info("  %s/%s: upsert %d 行", slug, year, n)
                # 限速（(slug, year) 对之间）
                if i < len(targets) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    from common.browser import quit_driver
                    quit_driver()
                except Exception:  # noqa: BLE001
                    pass
        logger.info("完成：upsert %d 行（处理 %d 对）", total, len(targets))
        return total

    # ── 从归档重解析（免爬，--rework slug,year）───────────────────────────
    def rework_from_archive(self, slug: str, year: int) -> int:
        """读取 raw_archive 归档 HTML 重解析落库（免爬）。

        归档路径: ``raw_archive/br_players/{slug}/lineups_{year}.html``
        样例 HTML 到位后可用此入口免爬重放校验解析器。
        """
        path = Path(self.RAW_ARCHIVE) / slug / f"lineups_{year}.html"
        if not path.exists():
            logger.warning("[rework] 归档缺失: %s", path)
            return 0
        html = path.read_text(encoding="utf-8")
        conn = psycopg2.connect(**DB_CONFIG)
        try:
            n = self._consume_html(conn, slug, year, html)
        finally:
            conn.close()
        logger.info("[rework] %s/%s 重放完成: %d 行", slug, year, n)
        return n


# 模块级日志器（基类已配置 root handler；本模块复用）。
logger = logging.getLogger("br_player_lineup")
