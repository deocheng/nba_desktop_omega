"""common/br_player_page.py — BR 球员页爬虫基类（BRPlayerPageCrawler）。

继承 ``common.br_team_page.BRTeamPageCrawler``，复用其反屏蔽/限速/CF 检测/upsert/
失败登记与解析纯函数，**仅重写球员级**枚举、URL、双表解析主循环、原始 HTML 归档。
不动 ``br_team_page.py``（最小爆炸半径，满足「复用既有结构」约束）。

球员页与球队页的结构差异（见系统设计的 §1 决策）：
  * URL 无赛季：``/players/{slug[0]}/{slug}/shooting/``
  * 一页含该球员**全部赛季**两张表：``#shooting``(Regular) + ``#shooting_playoffs``
    (Playoffs)，每行 = 一个赛季。与基类 ``build_url(season)`` / 单队单季模型不兼容，
    故本类重写 ``build_url`` / ``enumerate_players`` / ``_crawl_player`` /
    ``run_players`` / ``save_raw_html`` / ``rework_from_archive``。

解析纯函数 ``parse_player_shooting_html`` 在 ``crawl_br_player_shooting.py`` 实现
（按文件列表归属）；本类的 ``_crawl_player`` 通过多态调用子类的 ``parse``。

DB 连接：强制 host=127.0.0.1, port=5433（对齐集群 B 铁律）；口令走 PGPASSWORD 环境变量。
"""
from __future__ import annotations

import logging
import os
import psycopg2
from pathlib import Path
from typing import List, Optional

# 复用基类（反屏蔽/限速/CF/失败登记/解析纯函数均在其内）
from common.br_team_page import BRTeamPageCrawler

# CF 握手门禁：爬取前在「爬虫驱动的标签页」里先清 CF，避免全新 profile 无
# cf_clearance 时全缺口 0 行的系统性失败（缺口永久卡死）。
from common.browser import ensure_cf_cleared  # noqa: E402  (common 包, 仅依赖标准库)

# ── DB 连接（集群 B 铁律：127.0.0.1:5433；口令禁硬编码）──────────────────────
DB_CONFIG = dict(
    host="127.0.0.1",
    port=5433,
    dbname="nba",
    user="postgres",
    password=os.environ.get("PGPASSWORD", ""),
)

# BR 球员页基地址
BR_PLAYER_URL = "https://www.basketball-reference.com/players/{letter}/{slug}/shooting/"

# 已知必存在的球员 slug（LeBron James），用于 Fix 4 的 URL/页面格式校验。
KNOWN_GOOD_SLUG = "jamesle01"


def build_player_shooting_url(slug: str) -> str:
    """构造 BR 球员 shooting 页 URL（与实例 build_url 同构，纯函数便于单测）。

    沙箱无法过 Cloudflare，**禁止在 sandbox 真正抓取 BR**；本函数仅做格式构造
    与静态断言，live 取法请在 Mac 上以用户 Chrome(CDP, 9222) 运行。
    """
    letter = (slug[0].lower() if slug else "a")
    return BR_PLAYER_URL.format(letter=letter, slug=slug)


def html_has_shooting_table(html: str) -> bool:
    """判定 HTML 是否含有效的 ``#shooting`` 表（真·球员页而非 404/挑战页）。

    BR 球员 shooting 页的 Regular 表 ``id="shooting"``；404 页与挑战页不含该表，
    借此把「404 永久失效」与「真·有数据页」区分开（供 Fix 4 校验与
    fetch_team_page 的 404 检测相互印证）。
    """
    if not html:
        return False
    return 'id="shooting"' in html


def self_test_player_url(slug: str = KNOWN_GOOD_SLUG) -> str:
    """Fix 4 自校验（**不抓 BR**）：断言 URL 格式正确并返回该 URL。

    仅校验 URL 构造与「该 slug 应有 #shooting 表」的契约；**不**发起任何 BR 网络
    请求（沙箱过不了 CF）。live 取值 + 断言 ``id="shooting"`` 的完整校验，请在
    Mac 上以用户 Chrome(CDP, 9222) 运行（runner 默认 BROWSER_BACKEND=cdp）。
    """
    assert slug, "slug 不能为空"
    url = build_player_shooting_url(slug)
    assert url.startswith("https://www.basketball-reference.com/players/"), url
    assert url.endswith("/shooting/"), url
    return url


class BRPlayerPageCrawler(BRTeamPageCrawler):
    """BR 球员页爬虫基类（球员级，重写枚举/URL/主循环/归档）。

    子类（如 ``PlayerShootingCrawler``）只需实现 ``parse`` / ``build_rows`` /
    ``upsert`` 三个钩子；本类固化「取浏览器→抓页→存原始 HTML→解析→入库」主流程。
    """

    # —— 子类共享常量（覆盖基类默认）——
    DOMAIN = "player_shooting"
    TASK_TYPE = "br_player_shooting"
    TABLE = "player_shooting"
    CONFLICT_COLS = ("player_id", "season", "season_type", "team")
    MIN_SEASON = 1997
    RAW_ARCHIVE = "raw_archive/br_players"

    def __init__(self, cache_dir: Optional[str] = None,
                 dry_run: bool = False, resume: bool = False) -> None:
        super().__init__(cache_dir=cache_dir, dry_run=dry_run, resume=resume)

    # ── URL（球员页无赛季维度）───────────────────────────────────────────
    def build_url(self, slug: str) -> str:
        """构造 BR 球员 shooting 页 URL：/players/{slug[0]}/{slug}/shooting/。"""
        letter = (slug[0].lower() if slug else "a")
        return BR_PLAYER_URL.format(letter=letter, slug=slug)

    # ── 原始 HTML 归档（对齐 br_fill_pbp 的 pbp_raw/ 约定）───────────────
    def save_raw_html(self, slug: str, html: str) -> Path:
        """把渲染 HTML 落盘 raw_archive/br_players/{slug}/shooting.html。"""
        d = Path(self.RAW_ARCHIVE) / slug
        d.mkdir(parents=True, exist_ok=True)
        p = d / "shooting.html"
        p.write_text(html, encoding="utf-8")
        return p

    # ── 球员枚举宇宙 ─────────────────────────────────────────────────────
    def enumerate_players(self, conn, priority_gap: bool = False) -> List[str]:
        """枚举待抓 slug。

        默认：``player_gamelog.br_player_id``(非 NULL) ∪ ``dim_players.player_id``
        (非 NULL，T0 确认 dim_players 的 slug 列就是 player_id) 去重。
        ``priority_gap=True``：仅返回「在 gamelog 宇宙内、但 player_shooting 缺
        Regular 组合」的 slug，实现优先补缺（先把 ~9,797 缺口快速补齐）；并**排除
        已隔离 slug**（``player_shooting_404``，来源为 Fix 2 运行时 404 隔离
        note='http_404'）。

        说明（Fix 3 跨度预过滤已移除）：原方案用赛季跨度(``MAX-MIN>25``)预过滤损坏
        slug，但真实库上 player_gamelog 会被同 slug 的后期冒名者污染（如
        garneke01/KG、stockjo01/Stockton、malonka01/Malone 的 gamelog 被 2017–2025
        冒名行顶到 span>25），跨度的预过滤会**误杀真实有效页面的球员、永久丢数据**
        （QA Round-2 实测 301 命中里含 KG/Stockton/Malone 及 30 条会真丢爬取）。
        死 slug / 损坏 slug 已由 Fix 2 的 ``_crawl_player`` 在运行时 fetch 命中 404
        后隔离进 ``player_shooting_404(note='http_404')`` 正确处理（无误杀、缺口口径
        诚实），故预过滤纯属「锦上添花」且风险大于收益，直接移除（QA 推荐方案 A）。
        """
        cur = conn.cursor()
        if priority_gap:
            cur.execute(
                """
                SELECT DISTINCT g.br_player_id AS slug
                FROM player_gamelog g
                LEFT JOIN player_shooting_404 q ON q.slug = g.br_player_id
                WHERE g.br_player_id IS NOT NULL
                  AND g.season >= 1997
                  AND q.slug IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM player_shooting ps
                    WHERE ps.player_id = g.br_player_id
                      AND ps.season = g.season
                      AND ps.season_type = 'Regular'
                  )
                """
            )
        else:
            cur.execute(
                """
                SELECT br_player_id FROM player_gamelog
                WHERE br_player_id IS NOT NULL
                UNION
                SELECT player_id FROM dim_players
                WHERE player_id IS NOT NULL
                """
            )
        rows = [r[0] for r in cur.fetchall() if r[0]]
        cur.close()
        # 去重保序
        seen = set()
        out: List[str] = []
        for s in rows:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    # ── 断点续跑：该 slug 是否已落库 ─────────────────────────────────────
    def _player_done(self, conn, slug: str) -> bool:
        """若 player_shooting 已有该 slug 任意一行，视为已抓（一页覆盖全赛季）。"""
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM {self.TABLE} WHERE player_id=%s LIMIT 1", (slug,)
        )
        found = cur.fetchone() is not None
        cur.close()
        return found

    # ── 404 slug 隔离（Fix 2）─────────────────────────────────────────────
    def _quarantine_slug(self, conn, slug: str, note: str = "http_404") -> None:
        """把运行时 fetch 命中 404 的 slug 隔离到 player_shooting_404。

        注意：本方法**只服务于 Fix 2 的运行时 404 隔离**（note='http_404'）。
        原 Fix 3 的「赛季跨度预过滤」已移除——跨度会被同 slug 后期冒名者污染、
        误杀真实有效页面的球员（garneke01/KG、stockjo01/Stockton、malonka01/Malone
        等，其 gamelog 被 2017–2025 冒名行顶到 span>25），预过滤会**永久丢失**这些
        球员的有效 shooting 数据。死 slug / 损坏 slug 已由本方法在运行时 fetch 命中
        404 后正确隔离（无误杀、缺口口径诚实），预过滤风险大于收益，故删除。
        """
        if conn is None:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO player_shooting_404 (slug, note) VALUES (%s, %s) "
                "ON CONFLICT (slug) DO UPDATE SET "
                "note = EXCLUDED.note, "
                "first_seen = LEAST(player_shooting_404.first_seen, now())",
                (slug, note),
            )
            conn.commit()
        finally:
            cur.close()

    # ── 单球员抓取（重写基类 _crawl_one 的球队模型）─────────────────────
    def _crawl_player(self, conn, driver, slug: str) -> int:
        """抓一个球员页：导航→（404 则隔离、不存档）→存原始 HTML→解析→入库。

        * CF 挑战 / 空页 → 登记失败，返回 0（run_players 决定是否暂停重试）。
        * **404 命中** → 隔离到 player_shooting_404（note='http_404'），
          **不**写 raw_archive、**不**解析、**不**登记 crawl_failures，返回 0。
          由 enumerate_players 后续排除该 slug，缺口数变真实、不再死循环卡死。
        """
        url = self.build_url(slug)
        html = self.fetch_team_page(driver, url)
        if not html:
            if self._last_fetch_404:
                # 404 是永久失效：隔离即可，不应污染 crawl_failures / raw_archive。
                self._quarantine_slug(conn, slug, note="http_404")
                logger.warning("  ⚠️ %s 命中 BR 404 → 隔离（不存档/不解析）", slug)
                return 0
            # CF 挑战页或空页：登记失败，交由 run_players 区分重试/告警。
            self.register_failure(conn, f"player_shooting|{slug}|all")
            return 0
        self.save_raw_html(slug, html)
        return self._consume_html(conn, slug, html)

    def _consume_html(self, conn, slug: str, html: str) -> int:
        """解析并入库一页 HTML（供 _crawl_player 与 rework_from_archive 复用）。"""
        parsed = self.parse(html)  # 多态→子类 parse（委托 parse_player_shooting_html）
        if not parsed:
            self.register_failure(conn, f"player_shooting|{slug}|all")
            return 0
        rows = [
            self.build_rows(conn, slug, rec.get("season"),
                            rec.get("season_type"), rec)
            for rec in parsed
        ]
        n = self.upsert(conn, rows)
        conn.commit()
        return n

    # ── 主循环 ───────────────────────────────────────────────────────────
    def run_players(self, conn, slugs: Optional[List[str]] = None,
                    resume: bool = False, dry_run: bool = False,
                    priority_gap: bool = False) -> int:
        """遍历 slug 列表抓取（断点续跑跳过已落库；dry_run 只枚举不抓）。

        ``slugs=None`` 时按 ``priority_gap`` 自动枚举。返回 upsert 总行数。

        加固点（针对 A 阶段「全缺口 0 行 → 缺口卡死」的系统性 CF 失败）：
          1. 爬取前先在「爬虫驱动的标签页」里做一次 CF 握手门禁
             （``ensure_cf_cleared``）：导航到 BR 主页、检测挑战页、命中则写
             /tmp/br_cf_challenge.flag 并提示用户在**该**标签页手动过 CF，
             轮询直到挑战消失再继续。杜绝「用户在 A 标签清了、爬虫驱动 B 标签」。
          2. 缺口 slug 解析/插入得 0 行且不是「已落库」跳过的，绝不静默当成功：
             - 若命中风控（``_last_fetch_cf``）：暂停等用户清 CF 后重试一次；
             - 否则：打醒目 WARNING，记为缺口未清（不把 0 行当成功）。
        """
        if slugs is None:
            slugs = self.enumerate_players(conn, priority_gap=priority_gap)
        if not slugs:
            logger.info("枚举为空，无需抓取")
            return 0
        logger.info("待处理 slug 数: %d", len(slugs))
        total = 0
        driver = None
        try:
            if not dry_run:
                driver = self.get_driver()
                # CF 握手门禁：在爬虫自己驱动的标签页里先清 CF 再开爬。
                # 异常不阻断爬取尝试（可能是网络抖动），交由后续每 slug 逻辑兜底。
                try:
                    ensure_cf_cleared(driver)
                except Exception as _e:  # noqa: BLE001
                    logger.warning("CF 握手前置检查异常（仍继续尝试抓取）: %s", _e)
            for i, slug in enumerate(slugs):
                if resume and self._player_done(conn, slug):
                    logger.info("  [resume] 跳过 %s（已落库）", slug)
                    continue
                if dry_run:
                    logger.info("  [dry-run] 计划抓取 %s", slug)
                    continue
                # 缺口 slug：最多 2 次尝试。命中 CF 挑战页则暂停等用户清完再重试，
                # 绝不把 0 行静默当成功（避免缺口假性清零 / 无限空转）。
                n = 0
                for _attempt in range(2):
                    try:
                        n = self._crawl_player(conn, driver, slug)
                    except Exception as exc:  # noqa: BLE001 - 单球员异常不中断整体
                        logger.error("  抓取失败 %s: %s", slug, exc)
                        self.register_failure(conn, f"player_shooting|{slug}|all")
                        conn.commit()
                        n = 0
                    if n > 0:
                        break
                    if self._last_fetch_cf:
                        logger.warning(
                            "  ⚠️ %s 抓取得 0 行且命中 CF 挑战页 → 暂停等待用户手动清 CF 后重试",
                            slug)
                        try:
                            ensure_cf_cleared(driver)
                        except Exception as _e:  # noqa: BLE001
                            logger.warning("  CF 握手等待异常（继续）: %s", _e)
                        continue  # 清完重试一次
                    logger.warning(
                        "  ⚠️ %s 抓取得 0 行（疑似 CF 拦截/解析失败/空数据），"
                        "不视为成功；记为缺口未清", slug)
                    break
                total += n
                logger.info("  %s: upsert %d 行", slug, n)
                # 限速（球员间）
                if i < len(slugs) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    self.quit_driver()
                except Exception:  # noqa: BLE001
                    pass
        logger.info("完成：upsert %d 行（处理 %d slug）", total, len(slugs))
        return total

    # ── 从归档重解析（免重爬，--rework）──────────────────────────────────
    def rework_from_archive(self, slug: str) -> int:
        """读取 raw_archive 归档 HTML 重解析落库（免爬）。"""
        path = Path(self.RAW_ARCHIVE) / slug / "shooting.html"
        if not path.exists():
            logger.warning("[rework] 归档缺失: %s", path)
            return 0
        html = path.read_text(encoding="utf-8")
        conn = psycopg2.connect(**DB_CONFIG)
        try:
            n = self._consume_html(conn, slug, html)
        finally:
            conn.close()
        logger.info("[rework] %s 重放完成: %d 行", slug, n)
        return n

    # ── upsert（覆盖基类：psycopg2.extras.execute_values 需单一 %s 占位）──
    def _upsert_rows(self, conn, table: str, rows: list,
                     conflict_cols: tuple) -> int:
        """批量 upsert（execute_values + ON CONFLICT DO UPDATE）。

        覆盖 ``BRTeamPageCrawler._upsert_rows``：psycopg2 的 ``execute_values``
        要求 SQL 中**仅一个** ``%s`` 占位（由库函数替换为多值元组列表），基类原实现
        生成了 ``len(cols)`` 个 ``%s`` 与 ``execute_values`` 不兼容。本实现使用单一
        ``%s`` 占位 + 列集并集，冲突键 ``conflict_cols`` 之外的列在冲突时刷新为
        EXCLUDED 值；``created_at`` 等默认值列不入 rows，由 DB 默认值填充。

        注：未修改 common/br_team_page.py（约束禁止），仅在子类覆盖修复。
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
        if update_cols:
            upd_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in update_cols])
            conflict_sql = (f"ON CONFLICT ({', '.join(conflict_cols)}) "
                            f"DO UPDATE SET {upd_sql}")
        else:
            conflict_sql = f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
        # 单一 %s 占位，execute_values 会替换为多值元组列表
        sql = f"INSERT INTO {table} ({col_sql}) VALUES %s {conflict_sql}"
        data = [tuple(r.get(c) for c in cols) for r in rows]
        cur = conn.cursor()
        psycopg2.extras.execute_values(cur, sql, data, page_size=1000)
        cur.close()
        return len(data)


# 模块级日志器（基类已配置 root handler；本模块复用）。
logger = logging.getLogger("br_player_page")
