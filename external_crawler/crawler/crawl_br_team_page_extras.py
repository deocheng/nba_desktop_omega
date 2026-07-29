"""crawl_br_team_page_extras.py — BR 球队主页面 Group A 缺失板块爬虫。

数据源: https://www.basketball-reference.com/teams/{ABBR}/{YEAR}.html
  主页面 HTML 内含多个板块（2026-07-29 用户核实，全部在同一份 HTML 内，
  非独立子页）；本爬虫**抓主页面一次**即解析全部缺失 Group A 板块：
    * Roster              -> #roster（每球员一行）
    * Per 36 Minutes     -> #per_minute（队级 Team/Opponent 汇总）
    * Assistant Coaches  -> 页面 "Coaching Staff" 区块（尽力解析）
    * Players on League Leaderboards -> 页面 Leaderboards 区块（尽力解析）

设计：复用 common.br_team_page.BRTeamPageCrawler 的 CDP 抓取 / CF-404 检测 /
限速 / _upsert_rows / get_driver / ensure_cf_cleared 原语；解析层为纯函数。
一次抓取、同事务多表 upsert（类比球员页 crawl_br_player_page_extras.py）。

落库: team_roster / team_per_36 / team_coaches / team_leaderboards（4 表）。
已覆盖板块（Per Game/Totals/Per 100/Advanced/Misc/Team&Opponent/PBP）由既有
爬虫负责，本爬虫**不重抓、不重复写**。

用法
----
  python crawl_br_team_page_extras.py --slugs SAS --season 2026
  python crawl_br_team_page_extras.py --all-seasons --resume
  python crawl_br_team_page_extras.py --rework SAS --season 2026
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from bs4 import BeautifulSoup, Comment

from common.br_team_page import (
    BRTeamPageCrawler,
    DB_CONFIG,
    safe_int,
    safe_float,
)
from common.browser import ensure_cf_cleared

logger = logging.getLogger("team_page_extras")

# 主页面基地址（.html 后缀，非子目录）
BR_MAIN_URL = "https://www.basketball-reference.com/teams/{slug}/{season}.html"

RAW_ARCHIVE = "raw_archive/br_teams"

# Per 36 逐球员表（#per_minute_stats）data-stat -> 列名映射。
# 注意：BR 该表是「逐球员」表（每位球员一行 Per-36 数据），
# 列名形如 fg_per_minute_36 / pts_per_minute_36 等。
_PER36_MAP = {
    "fg_per_minute_36": "fg", "fga_per_minute_36": "fga", "fg_pct": "fg_pct",
    "fg3_per_minute_36": "x3p", "fg3a_per_minute_36": "x3pa", "fg3_pct": "x3p_pct",
    "fg2_per_minute_36": "x2p", "fg2a_per_minute_36": "x2pa", "fg2_pct": "x2p_pct",
    "efg_pct": "efg_pct",
    "ft_per_minute_36": "ft", "fta_per_minute_36": "fta", "ft_pct": "ft_pct",
    "orb_per_minute_36": "orb", "drb_per_minute_36": "drb", "trb_per_minute_36": "trb",
    "ast_per_minute_36": "ast", "stl_per_minute_36": "stl", "blk_per_minute_36": "blk",
    "tov_per_minute_36": "tov", "pf_per_minute_36": "pf", "pts_per_minute_36": "pts",
}


def _find_br_table(soup: BeautifulSoup, table_id: str):
    """注释感知表查找（BR 季后赛/部分表包在 HTML 注释里）。"""
    t = soup.find("table", id=table_id)
    if t is not None:
        return t
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        if f'id="{table_id}"' in c:
            sub = BeautifulSoup(c, "html.parser")
            t = sub.find("table", id=table_id)
            if t is not None:
                return t
    return None


def _row_data_stats(row) -> Dict[str, str]:
    vals: Dict[str, str] = {}
    for td in row.find_all(["th", "td"]):
        ds = td.get("data-stat", "")
        if ds:
            vals[ds] = td.get_text(strip=True)
    return vals


# ── 解析：Roster ─────────────────────────────────────────────────────────
def parse_team_roster(html: str) -> List[Dict]:
    """解析 #roster 表 -> 每球员一行。纯函数。"""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    t = _find_br_table(soup, "roster")
    if t is None:
        return []
    out: List[Dict] = []
    for row in t.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        vals = _row_data_stats(row)
        if not vals:
            continue
        player_cell = row.find(["th", "td"], attrs={"data-stat": "player"})
        if player_cell is None:
            continue
        a = player_cell.find("a")
        slug = None
        if a is not None:
            m = re.search(r"/players/[a-z]/([a-z0-9]+)", a.get("href", ""))
            slug = m.group(1) if m else None
        # 表头/汇总行（"Player"/"Team Totals"）无 /players/ 链接 → slug 为空，必须跳过，
        # 否则 player_slug NOT NULL 约束报错（真实 bug：曾把表头当数据行插入）。
        if not slug:
            continue
        name = a.get_text(strip=True) if a is not None else player_cell.get_text(strip=True)
        if not name:
            continue
        out.append({
            "player_slug": slug,
            "player_name": name,
            "jersey": vals.get("jersey"),
            "pos": vals.get("pos"),
            "height": vals.get("height"),
            "weight": vals.get("weight"),
            "birth_date": vals.get("birth_date"),
            "experience": vals.get("experience"),
            "college": vals.get("college"),
        })
    return out


# ── 解析：Per 36 ────────────────────────────────────────────────────────
def parse_team_per36(html: str, season_type: str = "Regular") -> List[Dict]:
    """解析 #per_minute_stats（PO: #per_minute_stats_post）逐球员 Per-36 表。

    该表为「每位球员一行」的 Per-36 Minutes 统计（data-stat 形如
    fg_per_minute_36 / pts_per_minute_36 / fg_pct ...），并非 Team/Opponent 汇总。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    tid = "per_minute_stats_post" if season_type == "Playoffs" else "per_minute_stats"
    t = _find_br_table(soup, tid)
    if t is None:
        return []
    out: List[Dict] = []
    for row in t.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        player_cell = row.find(["th", "td"], attrs={"data-stat": "name_display"})
        if player_cell is None:
            continue
        a = player_cell.find("a")
        slug = None
        if a is not None:
            m = re.search(r"/players/[a-z]/([a-z0-9]+)", a.get("href", ""))
            slug = m.group(1) if m else None
        # 表头/汇总行无 /players/ 链接 → 跳过
        if not slug:
            continue
        name = a.get_text(strip=True) if a is not None else player_cell.get_text(strip=True)
        if not name:
            continue
        vals = _row_data_stats(row)
        rec: Dict = {"player_slug": slug, "player_name": name, "pos": vals.get("pos")}
        for ds, col in _PER36_MAP.items():
            rec[col] = safe_float(vals.get(ds))
        # 上下文整数字段
        rec["g"] = safe_int(vals.get("games"))
        rec["gs"] = safe_int(vals.get("games_started"))
        rec["mp"] = safe_int(vals.get("mp"))
        if vals.get("awards"):
            rec["awards"] = vals.get("awards")
        out.append(rec)
    return out


# ── 解析：Coaches（尽力）───────────────────────────────────────────────
def parse_team_coaches(html: str) -> List[Dict]:
    """尽力解析页面 "Coaching Staff" 区块 -> 教练名+角色。纯函数，失败返回 []。"""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict] = []
    try:
        # BR 教练区块常以 <strong>Head Coach</strong> 或列表形式出现；
        # 依次扫描含 "Coach" 文本的元素，取其后兄弟/父容器内的人名链接。
        for el in soup.find_all(string=re.compile(r"Coach", re.I)):
            parent = el.parent
            if parent is None:
                continue
            # 角色：取该元素文本（如 "Head Coach" / "Assistant Coach"）
            role = parent.get_text(strip=True) or el.strip()
            for a in parent.find_all("a"):
                href = a.get("href", "")
                nm = a.get_text(strip=True)
                if not nm:
                    continue
                slug = None
                m = re.search(r"/coaches/([a-z0-9]+)", href)
                if m:
                    slug = m.group(1)
                out.append({"coach_name": nm, "role": role, "coach_slug": slug})
    except Exception as _e:  # noqa: BLE001 - 尽力解析，绝不崩溃
        logger.warning("[coaches] 解析异常（已忽略）: %s", _e)
        return []
    # 去重（同名同角色）
    seen = set()
    uniq = []
    for r in out:
        k = (r["coach_name"], r["role"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


# ── 解析：Leaderboards（尽力）──────────────────────────────────────────
def parse_team_leaderboards(html: str) -> List[Dict]:
    """解析 #all_leaderboard 区块 -> 球员 + 类别(h4) + 排名。

    BR 结构：<h4>类别</h4> 后跟 <p> 列出该类别上榜球员链接，每个链接后有
    "(3rd)" 形式的排名文本。逐 h4 取类别，再在紧随的 <p> 内取球员链接 + 排名。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    el = soup.find(id="all_leaderboard")
    if el is None:
        return []
    # 该区块表/链接常包在 HTML 注释里，先展开
    try:
        for c in el.find_all(string=lambda x: isinstance(x, Comment)):
            sub = BeautifulSoup(c, "html.parser")
            for tag in sub.find_all(True):
                el.append(tag)
    except Exception:  # noqa: BLE001
        pass
    out: List[Dict] = []
    try:
        for a in el.find_all("a", href=re.compile(r"/players/[a-z]/")):
            m = re.search(r"/players/[a-z]/([a-z0-9]+)", a.get("href", ""))
            if not m:
                continue
            slug = m.group(1)
            nm = a.get_text(strip=True)
            if not nm:
                continue
            # 类别 = 最近的 preceding <h4>（如 "Points" / "Total Rebounds"）
            h = a.find_previous("h4")
            cat = h.get_text(strip=True) if h is not None else None
            if not cat:
                continue
            rank = None
            # 排名以独立 <a> 链接形式紧跟球员链接之后，文本形如 "(3rd)"
            nxt = a.find_next_sibling()
            if nxt is not None:
                txt = nxt.get_text(strip=True) if getattr(nxt, "name", None) else str(nxt)
                rm = re.search(r"\(?(\d{1,2})(?:st|nd|rd|th)\)?", txt)
                if rm:
                    rank = safe_int(rm.group(1))
            out.append({
                "player_slug": slug, "player_name": nm,
                "leaderboard": cat, "rank": rank,
            })
    except Exception as _e:  # noqa: BLE001
        logger.warning("[leaderboards] 解析异常（已忽略）: %s", _e)
        return []
    # 去重（同球员同类别保留首个）
    seen = set()
    uniq = []
    for r in out:
        k = (r["player_slug"], r["leaderboard"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq
    return out


# ── 爬虫类 ────────────────────────────────────────────────────────────
class TeamPageExtrasCrawler(BRTeamPageCrawler):
    """BR 球队主页面 Group A 缺失板块爬虫（一次抓取多表）。"""

    DOMAIN = "team_page_extras"
    TASK_TYPE = "br_team_page_extras"

    CONFLICT = {
        "team_roster": ("team_abbr", "season", "player_slug"),
        "team_per_36": ("team_abbr", "season", "season_type", "player_slug"),
        "team_coaches": ("team_abbr", "season", "coach_name", "role"),
        "team_leaderboards": ("team_abbr", "season", "player_slug", "leaderboard"),
    }

    def build_url(self, slug: str, season: int) -> str:
        return BR_MAIN_URL.format(slug=slug, season=season)

    # ── 枚举队季（从 team_summaries 取权威缩写，经 team_mapping 归一）──
    def enumerate_teams(self, conn, season: int,
                        season_type: str = "Regular") -> List[tuple]:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT abbreviation FROM team_summaries WHERE season=%s",
            (season,))
        abbrs = [r[0] for r in cur.fetchall() if r[0]]
        cur.close()
        slugs = sorted({self._br_slug(conn, a) for a in abbrs})
        return [(s, season) for s in slugs]

    def _team_done(self, conn, slug: str, season: int) -> bool:
        """以 team_roster 是否有该队季行判定整页已抓（多表同源同页）。"""
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM team_roster WHERE team_abbr=%s AND season=%s LIMIT 1",
            (slug, season))
        f = cur.fetchone() is not None
        cur.close()
        return f

    def save_raw_html(self, slug: str, season: int, html: str) -> Path:
        d = Path(RAW_ARCHIVE) / slug
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{season}.html"
        p.write_text(html, encoding="utf-8")
        return p

    # ── 单队单季 ──
    def _crawl_team(self, conn, driver, slug: str, season: int) -> int:
        url = self.build_url(slug, season)
        html = self.fetch_team_page(driver, url)
        if not html:
            if self._last_fetch_404:
                logger.warning("  ⚠️ %s/%d 命中 BR 404，跳过", slug, season)
                return 0
            self.register_failure(conn, f"team_page_extras|{slug}|{season}")
            return 0
        self.save_raw_html(slug, season, html)
        return self._consume(conn, slug, season, html)

    def _consume(self, conn, slug: str, season: int, html: str) -> int:
        n = 0
        # Roster
        roster = [dict(r, team_abbr=slug, season=season) for r in parse_team_roster(html)]
        if roster:
            n += self._upsert_rows(conn, "team_roster", roster,
                                   self.CONFLICT["team_roster"])
            logger.info("  [roster] %s/%d: %d 球员", slug, season, len(roster))
        # Per 36（Regular + Playoffs）
        for st in ("Regular", "Playoffs"):
            per36 = [dict(r, team_abbr=slug, season=season, season_type=st)
                     for r in parse_team_per36(html, st)]
            if per36:
                n += self._upsert_rows(conn, "team_per_36", per36,
                                       self.CONFLICT["team_per_36"])
                logger.info("  [per36/%s] %s/%d: %d 行", st, slug, season, len(per36))
        # Coaches（尽力）
        coaches = [dict(r, team_abbr=slug, season=season) for r in parse_team_coaches(html)]
        if coaches:
            n += self._upsert_rows(conn, "team_coaches", coaches,
                                   self.CONFLICT["team_coaches"])
            logger.info("  [coaches] %s/%d: %d 条", slug, season, len(coaches))
        # Leaderboards（尽力）
        lbs = [dict(r, team_abbr=slug, season=season) for r in parse_team_leaderboards(html)]
        if lbs:
            n += self._upsert_rows(conn, "team_leaderboards", lbs,
                                   self.CONFLICT["team_leaderboards"])
            logger.info("  [leaderboards] %s/%d: %d 条", slug, season, len(lbs))
        conn.commit()
        # 队标按年落盘（前向：每次抓队主页顺手存图；缺口由 crawl_br_team_logos.py 回填并入库）。
        # 非致命：失败仅告警，不影响板块数据入库。
        try:
            from common.logo_store import extract_team_logo_src, save_team_logo
            src = extract_team_logo_src(html)
            if src:
                save_team_logo(slug, season, src)
        except Exception as _e:  # noqa: BLE001
            logger.warning("  [队标] 落盘跳过(非致命) %s/%d: %s", slug, season, _e)
        return n

    def rework_from_archive(self, slug: str, season: int) -> int:
        path = Path(RAW_ARCHIVE) / slug / f"{season}.html"
        if not path.exists():
            logger.warning("[rework] 归档缺失: %s", path)
            return 0
        html = path.read_text(encoding="utf-8")
        conn = psycopg2.connect(**DB_CONFIG)
        try:
            n = self._consume(conn, slug, season, html)
        finally:
            conn.close()
        logger.info("[rework] %s/%d 重放完成: %d 行", slug, season, n)
        return n

    # ── 主循环 ──
    def run_teams(self, conn, slugs: Optional[List[str]] = None,
                  season: Optional[int] = None, resume: bool = False,
                  dry_run: bool = False) -> int:
        if slugs:
            targets = [(s.strip(), season or 2026) for s in slugs]
        elif season:
            targets = self.enumerate_teams(conn, season)
        else:
            logger.info("需指定 --slugs 或 --season")
            return 0
        logger.info("待处理队季数: %d", len(targets))
        total = 0
        driver = None
        try:
            if not dry_run:
                driver = self.get_driver()
                try:
                    ensure_cf_cleared(driver)
                except Exception as _e:
                    logger.warning("CF 握手前置检查异常（仍继续）: %s", _e)
            for i, (slug, ssn) in enumerate(targets):
                if resume and self._team_done(conn, slug, ssn):
                    logger.info("  [resume] 跳过 %s/%d（已落库）", slug, ssn)
                    continue
                if dry_run:
                    logger.info("  [dry-run] 计划抓取 %s/%d", slug, ssn)
                    continue
                n = 0
                try:
                    n = self._crawl_team(conn, driver, slug, ssn)
                except Exception as exc:
                    logger.error("  抓取失败 %s/%d: %s", slug, ssn, exc)
                    self.register_failure(conn, f"team_page_extras|{slug}|{ssn}")
                    conn.commit()
                    n = 0
                total += n
                logger.info("  %s/%d: upsert %d 行", slug, ssn, n)
                if i < len(targets) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    self.quit_driver()
                except Exception:
                    pass
        logger.info("完成：upsert %d 行（处理 %d 队季）", total, len(targets))
        return total


def main() -> None:
    p = argparse.ArgumentParser(description="BR 球队主页面 Group A 缺失板块爬虫")
    p.add_argument("--slugs", type=str, default=None, help="逗号分隔队 slug（小批量测试）")
    p.add_argument("--season", type=int, default=None, help="赛季结束年（如 2026）")
    p.add_argument("--resume", action="store_true", help="跳过已落库队季")
    p.add_argument("--dry-run", action="store_true", help="只枚举+打印，不取浏览器/不写库")
    p.add_argument("--rework", type=str, default=None, help="从归档重解析某队（配合 --season）")
    args = p.parse_args()

    crawler = TeamPageExtrasCrawler()

    if args.rework:
        if not args.season:
            print("--rework 需配合 --season")
            return
        n = crawler.rework_from_archive(args.rework.strip(), args.season)
        print(f"[rework] {args.rework}/{args.season}: upsert {n} 行")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        slugs_list = ([s.strip() for s in args.slugs.split(",") if s.strip()]
                      if args.slugs else None)
        if slugs_list is None and args.season is None:
            print("需指定 --slugs <队slug> 或 --season <结束年> （可加 --resume）")
            return
        total = crawler.run_teams(conn, slugs=slugs_list, season=args.season,
                                  resume=args.resume, dry_run=args.dry_run)
        print(f"完成：upsert {total} 行")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
