"""crawl_br_player_shooting.py — BR 球员 shooting 爬虫（任务 A，逐季模式）。

数据源（与 shot_chart 爬虫同一页面，严格同构）：
    /players/{letter}/{slug}/shooting/{season}
  * 该页 ``#shooting`` 表 = **单季投篮拆分表**（Split/Value/FG/FGA/FG%/3P/3PA/3P%/eFG%/Ast'd/%Ast'd）。
  * BR 生涯页 ``/shooting/``（无年份）现已对所有人 404，故必须走逐季 URL（用户 2026-07-29 确认）。

解析：把拆分行 pivot 到 ``player_shooting`` 列：
    Season=Regular Season → fg_percent / 各 ShotPoints 的 FGA 占比
    Shot Distance(At Rim / 3 to <10 / 10 to <16 / 16 ft to <3-pt / 3-pt) → percent_fga_from_x*_range / fg_percent_from_x*_range
    Shot Points(2/3) → percent_assisted_x*_p_fg
    Shot Type=Dunk → percent_dunks_of_fga / num_of_dunks
  （0-3 ft 占比由 1-(3_10+10_16+16_3p+3p) 推导，精确；avg_dist_fga / corner / heaves 逐季页无，留 NULL。）

枚举：(slug, season) ∈ dim_players(year_to>=1997) 的 [1997,year_to]∩[1997,2026]，
  排除已落库(player_shooting) 与已失败(crawl_failures)。史前球员(year_to<1997)与 1997 无交集→自然排除，不烧请求。

复用：common.br_player_page.BRPlayerPageCrawler（反屏蔽/限速/CF/upsert/失败登记/原始归档全来自基类）。

用法
----
  python crawl_br_player_shooting.py --resume
  python crawl_br_player_shooting.py --slugs jamesle01 --season 2024 --dump-html /tmp/x.html
  python crawl_br_player_shooting.py --priority-gap --resume --limit 5
"""
import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from bs4 import BeautifulSoup

from common.br_player_page import BRPlayerPageCrawler, DB_CONFIG
from common.br_team_page import safe_int, safe_float
from common.browser import quit_driver  # 基类无 quit_driver 方法，勿用 self.quit_driver
from common.season_priority import season_tier  # 赛季抓取优先级（2010+ > 2000s > 1980s > pre-1980）
from common.season_type_norm import canon_season_type  # season_type 写入约定统一对齐 dim_games


DOMAIN = "player_shooting"
RAW_ARCHIVE = "raw_archive/br_players_shooting"
# 与唯一索引 uq_player_shooting_key 完全一致
CONFLICT_COLS = ("player_id", "season", "season_type", "team")


class TransientFetchError(RuntimeError):
    """瞬态抓取故障（CF 挑战/空响应/连接问题）——绝不写 crawl_failures。"""


def parse_per_season_shooting(html: str) -> List[Dict]:
    """从逐季 shooting 页 HTML 解析 Regular Season 投篮汇总 → 记录列表（纯函数）。

    返回 0 或 1 条（仅 Regular；Playoffs 汇总 BR 仅在已 404 的生涯页，逐季页不提供）。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="shooting")
    if table is None:
        return []
    # 收集拆分行，跟踪当前 split 类别（续行 split_id 为空）
    splits: Dict[Tuple[str, str], Dict[str, str]] = {}
    current_cat: Optional[str] = None
    for row in table.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        cells = row.find_all(["th", "td"])
        d = {c.get("data-stat", ""): c.get_text(strip=True) for c in cells}
        if not d:
            continue
        sid = d.get("split_id", "")
        sval = d.get("split_value", "")
        if sid:
            current_cat = sid
        if current_cat is None or not sval:
            continue
        splits[(current_cat, sval)] = d

    season_row = splits.get(("Season", "Regular Season"))
    if season_row is None:
        return []
    fga_total = safe_float(season_row.get("fga"))
    if not fga_total:
        return []

    def _pct(key) -> Optional[float]:
        v = splits.get(key)
        if v is None:
            return None
        return safe_float(v.get("fga"))

    def _fgpct(key) -> Optional[float]:
        v = splits.get(key)
        if v is None:
            return None
        return safe_float(v.get("fg_pct"))

    def _ratio(num, den):
        return round(num / den, 4) if (num is not None and den) else None

    pct_3_10 = _ratio(safe_float((splits.get(("Shot Distance", "3 to <10 ft")) or {}).get("fga")), fga_total)
    pct_10_16 = _ratio(safe_float((splits.get(("Shot Distance", "10 to <16 ft")) or {}).get("fga")), fga_total)
    pct_16_3 = _ratio(safe_float((splits.get(("Shot Distance", "16 ft to <3-pt")) or {}).get("fga")), fga_total)
    pct_3pt = _ratio(safe_float((splits.get(("Shot Points", "3")) or {}).get("fga")), fga_total)
    pct_2pt = _ratio(safe_float((splits.get(("Shot Points", "2")) or {}).get("fga")), fga_total)
    # 0-3 ft 占比由补集精确推导（5 桶之和=1）
    pct_0_3 = None
    if None not in (pct_3_10, pct_10_16, pct_16_3, pct_3pt):
        pct_0_3 = round(1.0 - (pct_3_10 + pct_10_16 + pct_16_3 + pct_3pt), 4)

    rec = {
        "lg": "NBA",
        "fg_percent": safe_float(season_row.get("fg_pct")),
        "avg_dist_fga": None,  # 逐季拆分表无此项
        "percent_fga_from_x2p_range": pct_2pt,
        "percent_fga_from_x0_3_range": pct_0_3,
        "percent_fga_from_x3_10_range": pct_3_10,
        "percent_fga_from_x10_16_range": pct_10_16,
        "percent_fga_from_x16_3p_range": pct_16_3,
        "percent_fga_from_x3p_range": pct_3pt,
        "fg_percent_from_x2p_range": _fgpct(("Shot Points", "2")),
        "fg_percent_from_x0_3_range": _fgpct(("Shot Distance", "At Rim")),  # At Rim 是 0-3ft 主体近似
        "fg_percent_from_x3_10_range": _fgpct(("Shot Distance", "3 to <10 ft")),
        "fg_percent_from_x10_16_range": _fgpct(("Shot Distance", "10 to <16 ft")),
        "fg_percent_from_x16_3p_range": _fgpct(("Shot Distance", "16 ft to <3-pt")),
        "fg_percent_from_x3p_range": _fgpct(("Shot Points", "3")),
        "percent_assisted_x2p_fg": safe_float((splits.get(("Shot Points", "2")) or {}).get("fg_ast_pct")),
        "percent_assisted_x3p_fg": safe_float((splits.get(("Shot Points", "3")) or {}).get("fg_ast_pct")),
        "percent_dunks_of_fga": _ratio(safe_float((splits.get(("Shot Type", "Dunk")) or {}).get("fga")), fga_total),
        "num_of_dunks": safe_int((splits.get(("Shot Type", "Dunk")) or {}).get("fga")),
        "percent_corner_3s_of_3pa": None,   # 逐季拆分表无 corner 细分
        "corner_3_point_percent": None,
        "num_heaves_attempted": None,
        "num_heaves_made": None,
        "season_type": canon_season_type("Regular"),
        "weight": None,
    }
    return [rec]


class PlayerShootingCrawler(BRPlayerPageCrawler):
    DOMAIN = DOMAIN
    TASK_TYPE = "br_player_shooting"
    TABLE = "player_shooting"
    RAW_ARCHIVE = RAW_ARCHIVE
    CONFLICT_COLS = CONFLICT_COLS

    def build_url(self, slug: str, season: int) -> str:
        letter = (slug[0].lower() if slug else "a")
        return (f"https://www.basketball-reference.com/players/"
                f"{letter}/{slug}/shooting/{season}")

    def save_raw_html(self, slug: str, season: int, html: str) -> Path:
        d = Path(self.RAW_ARCHIVE) / slug
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"shooting_{season}.html"
        p.write_text(html, encoding="utf-8")
        return p

    def _pair_done(self, conn, slug: str, season: int) -> bool:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM player_shooting WHERE player_id=%s AND season=%s AND season_type='Regular Season' LIMIT 1",
            (slug, season),
        )
        found = cur.fetchone() is not None
        cur.close()
        return found

    def load_team_map(self, conn) -> Dict[Tuple[str, int], str]:
        cur = conn.cursor()
        cur.execute(
            "SELECT player_id, season, team FROM fact_player_season_stats "
            "WHERE team IS NOT NULL AND season>=1997"
        )
        m = {(r[0], int(r[1])): r[2] for r in cur.fetchall()}
        cur.close()
        return m

    def enumerate_pairs(self, conn, priority_gap: bool = False) -> List[Tuple[str, int]]:
        """待抓 (slug, season) 对：直接枚举 ``fact_player_season_stats`` 中**实际出战**的
        (player_id, season)（season>=1997 且 <=2026），排除已落库(player_shooting) 与
        已失败(crawl_failures)。

        为什么用 fact 而非 dim_players 的 year_from..year_to：
          dim_players 的年份区间远宽于球员实际出战的赛季（如 weartr01 的 dim=2015..2018，
          实际只打了 2015、2018；leonaka01 的 dim 含 2022 但当年未出战）。若按 dim 区间枚举，
          会大量访问「球员根本没打的赛季」→ BR 返回 “No shooting splits” → 被误登记为 no-data，
          白白消耗限速请求（用户 2026-07-29 观测：直接访问 /shooting/{year} 无数据、点赛季才有，
          其实是因为所点赛季才是真出战的赛季）。
          fact_player_season_stats 是「实际出战赛季」权威源；且 fact_outside_dim_range=0 已验证
          fact 赛季必落在 dim 区间内，故 fact 枚举既不多漏也不多抓，且彻底消除 phantom 赛季浪费。
        """
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT fps.player_id, fps.season::int
            FROM fact_player_season_stats fps
            WHERE fps.season >= 1997 AND fps.season <= 2026
              AND fps.player_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM player_shooting ps
                             WHERE ps.player_id=fps.player_id AND ps.season=fps.season AND ps.season_type='Regular Season')
              AND NOT EXISTS (SELECT 1 FROM crawl_failures cf
                             WHERE cf.task_type='br_player_shooting'
                               AND cf.game_id='br_player_shooting|'||fps.player_id||'|'||fps.season::text)
            """
        )
        rows = [(r[0], int(r[1])) for r in cur.fetchall() if r[0]]
        cur.close()
        # 【赛季优先级 2026-08-01】最外层按分层（tier0=2010+ 先），层内近季先、slug 稳定兜底。
        # 与 shot_chart 保持一致；--limit 截断在枚举之后，故排序须在 enumerate 内完成，
        # 才能让 --limit 拿到的「高优先层」前 N 对（对齐数据四性·统一）。
        rows.sort(key=lambda r: (season_tier(r[1]), -r[1], r[0]))
        logger.info("枚举到 %d 个待抓 (slug,season) 对（fact 实际出战赛季缺口），已按赛季分层排序", len(rows))
        return rows

    def parse(self, html: str, season_type: str = "Regular", team=None):
        return parse_per_season_shooting(html)

    def build_rows(self, conn, slug: str, season: int, team: str, rec: Dict) -> Dict:
        row = dict(rec)
        row["player_id"] = slug
        row["season"] = int(season)
        row["team"] = team
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        if not rows:
            return 0
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)

    def register_failure(self, conn, token: str) -> None:
        """幂等：同 (game_id, task_type) 只登记一次。"""
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM crawl_failures WHERE game_id=%s AND task_type=%s LIMIT 1",
                (token, self.TASK_TYPE),
            )
            if cur.fetchone() is not None:
                cur.close()
                return
            cur.execute(
                "INSERT INTO crawl_failures (game_id, task_type, resolved) VALUES (%s, %s, %s)",
                (token, self.TASK_TYPE, False),
            )
            conn.commit()
            cur.close()
        except Exception as _e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("register_failure 写入失败（已忽略）: %s", _e)

    def _crawl_pair(self, conn, driver, slug: str, season: int, team: str) -> int:
        url = self.build_url(slug, season)
        html = self.fetch_team_page(driver, url)
        if not html:
            if getattr(self, "_last_fetch_404", False):
                self.register_failure(conn, f"{self.TASK_TYPE}|{slug}|{season}")
                logger.warning("  ⚠️ %s/%s 命中 BR 404 → 登记跳过", slug, season)
                return 0
            if getattr(self, "_last_fetch_cf", False):
                raise TransientFetchError(f"CF 挑战页: {slug}/{season}")
            raise TransientFetchError(f"空响应/导航失败: {slug}/{season}")
        self.save_raw_html(slug, season, html)
        recs = parse_per_season_shooting(html)
        if not recs:
            # 页存在但无 #shooting（如史前赛季 BR 无投篮拆分数据）→ 登记 no-data，不重试
            self.register_failure(conn, f"{self.TASK_TYPE}|{slug}|{season}")
            logger.warning("  ⚠️ %s/%s 页面正常但无 #shooting 表（真无数据）→ 登记", slug, season)
            return 0
        rows = [self.build_rows(conn, slug, season, team, r) for r in recs]
        n = self.upsert(conn, rows)
        conn.commit()
        return n

    TRANSIENT_WAITS = [5, 5, 15, 30]
    TRANSIENT_WAIT_S = 60
    TRANSIENT_MAX_RETRY = 30

    def _rebuild_driver(self, old_driver):
        try:
            quit_driver()
        except Exception:
            pass
        try:
            return self.get_driver()
        except Exception as exc:
            logger.warning("  [瞬态] 重建浏览器连接失败: %s", exc)
            return None

    def run_pairs(self, conn, pairs, resume=False, dry_run=False, limit=None,
                  skip_done_check=False):
        if limit is not None:
            pairs = pairs[: max(0, limit)]
        if not pairs:
            logger.info("枚举为空，无需抓取")
            return 0
        logger.info("待处理 (slug,season) 对: %d", len(pairs))
        team_map = self.load_team_map(conn) if not dry_run else {}
        total = 0
        driver = None
        try:
            if not dry_run:
                driver = self.get_driver()
            for i, (slug, season) in enumerate(pairs):
                if resume and not skip_done_check and self._pair_done(conn, slug, season):
                    logger.info("  [resume] 跳过 %s/%s（已落库）", slug, season)
                    continue
                if dry_run:
                    logger.info("  [dry-run] 计划抓取 %s/%s", slug, season)
                    continue
                team = team_map.get((slug, season)) or self._lookup_team(conn, slug, season)
                n = 0
                attempt = 0
                while True:
                    try:
                        n = self._crawl_pair(conn, driver, slug, season, team)
                        break
                    except Exception as exc:
                        attempt += 1
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        if attempt > self.TRANSIENT_MAX_RETRY:
                            logger.error(
                                "🔴 [瞬态] %s/%s 重试 %d 次仍失败，整体退出（未登记失败，下次 --resume 重抓）。最后错误: %s",
                                slug, season, self.TRANSIENT_MAX_RETRY, exc)
                            logger.info("完成：upsert %d 行（提前退出于第 %d 对）", total, i)
                            return total
                        _wait = (self.TRANSIENT_WAITS[attempt - 1]
                                 if attempt <= len(self.TRANSIENT_WAITS) else self.TRANSIENT_WAIT_S)
                        logger.warning(
                            "⏸️ [瞬态] %s/%s 抓取失败(第 %d/%d 次): %s → 等 %ds 后重建连接重试",
                            slug, season, attempt, self.TRANSIENT_MAX_RETRY, exc, _wait)
                        time.sleep(_wait)
                        nd = self._rebuild_driver(driver)
                        if nd is not None:
                            driver = nd
                total += n
                logger.info("  %s/%s: upsert %d 行", slug, season, n)
                if i < len(pairs) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    quit_driver()
                except Exception:
                    pass
        logger.info("完成：upsert %d 行（处理 %d 对）", total, len(pairs))
        return total

    def _lookup_team(self, conn, slug: str, season: int) -> Optional[str]:
        cur = conn.cursor()
        cur.execute(
            "SELECT team FROM fact_player_season_stats WHERE player_id=%s AND season=%s LIMIT 1",
            (slug, season))
        r = cur.fetchone()
        cur.close()
        return r[0] if r else None

    def rework_from_archive(self, slug: str, season: int, conn) -> int:
        path = Path(self.RAW_ARCHIVE) / slug / f"shooting_{season}.html"
        if not path.exists():
            logger.warning("[rework] 归档缺失: %s", path)
            return 0
        html = path.read_text(encoding="utf-8")
        team = self._lookup_team(conn, slug, season)
        recs = parse_per_season_shooting(html)
        if not recs:
            logger.warning("[rework] %s/%s 解析 0 行", slug, season)
            return 0
        rows = [self.build_rows(conn, slug, season, team, x) for x in recs]
        n = self.upsert(conn, rows)
        conn.commit()
        logger.info("[rework] %s/%s 重放完成: %d 行", slug, season, n)
        return n


logger = logging.getLogger("br_player_shooting")


def main() -> None:
    p = argparse.ArgumentParser(description="BR 球员 shooting 爬虫 (A, 逐季模式)")
    p.add_argument("--slugs", type=str, default=None,
                   help="逗号分隔 slug（定点测试）")
    p.add_argument("--season", type=int, default=None,
                   help="限定单季（配合 --slugs）")
    p.add_argument("--priority-gap", action="store_true",
                   help="仅枚举 player_shooting 缺失的 (slug,season) 对")
    p.add_argument("--dry-run", action="store_true",
                   help="只枚举+打印计划，不取浏览器、不写库")
    p.add_argument("--resume", action="store_true",
                   help="跳过已落库 (slug,season) 对（断点续传）")
    p.add_argument("--rework", type=str, default=None,
                   help="从归档重解析某 slug（免爬）：--rework jamesle01 后接 --season")
    p.add_argument("--limit", type=int, default=None,
                   help="最多处理 N 对（小批量验证，不跑全量）")
    p.add_argument("--dump-html", type=str, default=None,
                   help="把抓到的 HTML 落盘到该路径（调试用）")
    args = p.parse_args()

    crawler = PlayerShootingCrawler(dry_run=args.dry_run, resume=args.resume)

    if args.rework:
        if args.season is None:
            print("[rework] 必须配合 --season 指定赛季")
            return
        conn = psycopg2.connect(**DB_CONFIG)
        try:
            n = crawler.rework_from_archive(args.rework, int(args.season), conn)
        finally:
            conn.close()
        print(f"[rework] {args.rework}/{args.season}: upsert {n} 行")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        if args.slugs:
            slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
            pairs = [(s, args.season) for s in slugs] if args.season is not None \
                else [(s, int(re.search(r"(\d{4})", s) and 2024)) for s in slugs]
            # 若未给 --season，则从 dim_players 取该 slug 的赛季范围（简化：用 2024 占位，实际跑全量枚举更可靠）
            if args.season is None:
                pairs = []
                for s in slugs:
                    cur = conn.cursor()
                    cur.execute("SELECT GREATEST(1997,year_from), LEAST(2026,year_to) FROM dim_players WHERE player_id=%s", (s,))
                    r = cur.fetchone()
                    cur.close()
                    if r and r[0] is not None:
                        for yr in range(int(r[0]), int(r[1]) + 1):
                            pairs.append((s, yr))
        else:
            pairs = crawler.enumerate_pairs(conn, priority_gap=args.priority_gap)
        skip_done_check = (args.slugs is None)
        if args.limit is not None:
            pairs = pairs[: max(0, args.limit)]
        total = crawler.run_pairs(
            conn, pairs, resume=args.resume,
            dry_run=args.dry_run, limit=args.limit,
            skip_done_check=skip_done_check,
        )
        print(f"完成：upsert {total} 行（处理 {len(pairs)} 对）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
