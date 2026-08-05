# -*- coding: utf-8 -*-
"""crawl_br_team_pbp.py — Team Play-by-Play 爬虫（Step 0 已确认表 id）。

数据源: https://www.basketball-reference.com/teams/{ABBR}/{YEAR}.html
落库:   team_pbp_raw（长表，逐格捕获 data-stat，不猜列）

⚠️ 与 lineups/onoff/shooting 等**子页**爬虫不同：BR 球队页的 Play-by-Play
是**主页面上的一个 section**（`#all_pbp_stats`），**没有** `/pbp/` 子页。
故本爬虫用 build_url 覆写指向主 `.html` 页，而非 `{page}/` 子目录。

Step 0（2026-07-26 用户实贴 SAS/2026 真实页确认）：
  * 页面 "On this page" 导航含 `<a href="#all_pbp_stats">Play-by-Play</a>` →
    主表 id = `pbp_stats`，PO 表（若存在）按 BR 惯例 id = `pbp_stats_post`。
  * BR 季后赛表常包在 `<!-- -->` 注释里（与 player lineups 同坑）→ parse
    用注释感知 `_find_br_table` 回退扫描。

落库 schema：先用**长表 team_pbp_raw** 原样捕获每个 `data-stat` 单元格，
规避「未知列」问题；首次实爬后据 data-stat 清单再建宽表视图 team_pbp。

同页顺带抽取**队级**统计表（totals_stats / per_game_stats / per_poss /
advanced / adj_shooting / team_misc / team_and_opponent，及其 Playoffs 的
`_post` 变体）到长表 **team_page_raw**，实现「访问一次主页面获得
多项数据」，零额外网络请求（钩子 `TeamPBPCrawler.extra_extract`）。
注意：主页面 shooting 表是**球员级**，出手分布（team_shooting）在
`/teams/{ABBR}/{YEAR}/shooting/` 子页，需单独节流请求，不在本爬取内。

复用 common/br_team_page.BRTeamPageCrawler（CDP 抓取/IPv6 修复/缓存 MERGE/
404-CF 判别/限速/球员键桥接/upsert 全继承）。

用法（需 Mac 上经 CDP 过一次 CF）：
    BROWSER_BACKEND=cdp CHROME_CDP_URL=http://127.0.0.1:9222 \
        .venv/bin/python external_crawler/crawler/crawl_br_team_pbp.py \
        --season 2026 --dry-run
    BROWSER_BACKEND=cdp CHROME_CDP_URL=http://127.0.0.1:9222 \
        .venv/bin/python external_crawler/crawler/crawl_br_team_pbp.py \
        --season 2026 --resume --cache-dir /Volumes/12T/NBA/br_team_pbp_cache
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
from common.season_type_norm import canon_season_type  # season_type 写入约定统一对齐 dim_games
from bs4.element import Comment

from common.br_team_page import (
    BRTeamPageCrawler,
    build_arg_parser,
    dispatch_cli,
    safe_float,
    safe_int,
)


# ── 注释感知表查找（移植 crawl_br_player_lineup._find_br_table）──────────────
# BR 季后赛表常包在 <!-- --> 注释里，soup.find("table", id=...) 扫不到，
# 须先扫 Comment 节点、把每个注释重解析为子 soup 再找表。
# 同页多表抽取：见 TeamPBPCrawler.extra_extract（队级表长表捕获到
# team_page_raw，零额外请求）；不再复用 team_shooting 解析器（主页面
# shooting 表为球员级，出手分布在 /shooting/ 子页，需单独节流请求）。


def _find_br_table(soup: BeautifulSoup, table_id: str):
    """返回 id==table_id 的 <table>；常规找不到则回退扫描注释包裹的表。"""
    table = soup.find("table", id=table_id)
    if table is not None:
        return table
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        sub = BeautifulSoup(c, "html.parser")
        t = sub.find("table", id=table_id)
        if t is not None:
            return t
    return None


def _row_label(row) -> Optional[str]:
    """取行首单元格文本作为 split 标签（如 'Opponent' / 'Shot Clock < 10'）。"""
    first = row.find(["th", "td"])
    if first is None:
        return None
    return first.get_text(strip=True) or None


def parse_team_pbp_html(html: str, season_type: str = "Regular",
                       team_abbr: Optional[str] = None) -> List[Dict]:
    """解析 BR Team PBP 页 → 逐格记录列表（纯函数，不含 team/season 维度）。

    每条记录 = 一个 data-stat 单元格：
        {table_id, row_label, data_stat, val}
    team/season/season_type 由 build_rows 注入。
    BR 表每格都有 data-stat，故长表捕获无需预知列集。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    tid = "pbp_stats_post" if season_type == "Playoffs" else "pbp_stats"
    table = _find_br_table(soup, tid)
    if table is None:
        return []
    out: List[Dict] = []
    for tr in table.find_all("tr"):
        if "thead" in tr.get("class", []):
            continue
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        # 跳过分组表头行（首列 data-stat 以 header_ 开头，如 header_pos_estimates）
        if cells[0].get("data-stat", "").startswith("header_"):
            continue
        label = _row_label(tr) or ""   # 兜底空串，满足 PK NOT NULL
        for cell in cells[1:]:  # 跳过首列（split 标签列）
            ds = cell.get("data-stat", "")
            if not ds or ds.startswith("header_"):
                continue
            val = cell.get_text(strip=True)
            if val == "" or val == "":
                continue
            out.append({
                "table_id": tid,
                "row_label": label,
                "data_stat": ds,
                "val": val,
            })
    return out


class TeamPBPCrawler(BRTeamPageCrawler):
    """Team Play-by-Play 爬虫。"""

    DOMAIN = "team_pbp"
    TASK_TYPE = "br_team_pbp"
    TABLE = "team_pbp_raw"
    PAGE = ""                       # 主页面 section（非子页）
    TABLE_ID = "pbp_stats"          # Step 0 确认（2026-07-26 SAS/2026 实页）
    CONFLICT_COLS = ("team_abbr", "season", "season_type",
                     "table_id", "row_label", "data_stat")
    SEASON_TYPES = ("Regular", "Playoffs")  # SAS/2026 打进总决→PO 数据存在
    MIN_SEASON = 1997             # BR PBP 实质完整始于 1997+
    FULL_CRAWL_START = 2000       # 全量默认从 2000 起；更早赛季 BR 大概率无 pbp_stats 表（--start-season 可下探）

    # 主页面 URL（/teams/{slug}/{year}.html），非 {page}/ 子目录。
    def build_url(self, slug: str, season: int, page: str,
                  season_type: str = "Regular") -> str:
        return (f"https://www.basketball-reference.com/"
                f"teams/{slug}/{season}.html")

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        return parse_team_pbp_html(html, season_type, team_abbr)

    def build_rows(self, conn, team_abbr: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        row: Dict = {
            "team_abbr": team_abbr,
            "season": season,
            "season_type": canon_season_type(season_type),
            "table_id": rec.get("table_id"),
            "row_label": rec.get("row_label"),
            "data_stat": rec.get("data_stat"),
            "val": rec.get("val"),
        }
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)

    # ── 同页多表抽取（"一次页面访问获得多项数据"）──
    # 在 _crawl_team 每季处理完后调用一次（该季 Regular+Playoffs 共用
    # 同一份 html）；从此主页面 HTML 长表抽取**队级**统计表
    # （totals_stats / per_game_stats / per_poss / advanced / adj_shooting /
    #  team_misc / team_and_opponent，及其 Playoffs 的 _post 变体），
    # 落库到 team_page_raw —— 零额外网络请求。
    # 注意：主页面上的 shooting 表是**球员级**（Rk/name_display/age/
    #  pos/games），并非 team_shooting 的出手分布；后者在
    #  /teams/{ABBR}/{YEAR}/shooting/ 子页，需单独节流请求，不在此处。
    TEAM_LEVEL_TABLES = {
        "Regular": [
            "totals_stats", "per_game_stats", "per_poss",
            "advanced", "adj_shooting", "team_misc", "team_and_opponent",
        ],
        "Playoffs": [
            "totals_stats_post", "per_game_stats_post", "per_poss_post",
            "advanced_post", "adj_shooting_post",
        ],
    }

    def _extract_team_table(self, html: str, table_id: str,
                            season_type: str, slug: str,
                            season: int) -> List[Dict]:
        """从主页面 HTML 抽取单个**队级**表 → team_page_raw 行（纯函数风格）。

        仅捕获队级汇总表（Team/Opponent 等行），跳过分组表头
        （data-stat 以 header_ 开头）与无 data-stat 的单元格；每行首列
        作为 row_label（如 'Team' / 'Opponent' / 'Shot Clock < 10'）。
        BR 季后赛表常包在 <!-- --> 注释里 → 用 _find_br_table 注释感知回退。
        """
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        table = _find_br_table(soup, table_id)
        if table is None:
            return []
        out: List[Dict] = []
        for tr in table.find_all("tr"):
            # 跳过 <thead> 内的所有行（含列头行 over_header / 实际列头），
            # 其单元格文本是列名（如 'G'/'MP'），非数据，捕获会污染长表。
            if tr.find_parent("thead") is not None:
                continue
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            # 跳过分组表头行（首列 data-stat 以 header_ 开头）。
            if cells[0].get("data-stat", "").startswith("header_"):
                continue
            label = _row_label(tr) or ""
            for cell in cells[1:]:
                ds = cell.get("data-stat", "")
                if not ds or ds.startswith("header_"):
                    continue
                val = cell.get_text(strip=True)
                if val == "":
                    continue
                out.append({
                    "team_abbr": slug,
                    "season": season,
                    "season_type": canon_season_type(season_type),
                    "table_id": table_id,
                    "row_label": label,
                    "data_stat": ds,
                    "val": val,
                })
        return out

    def extra_extract(self, conn, driver, slug: str, season: int,
                     html: str) -> int:
        """同页多表抽取钩子：把队级统计表（含 Playoffs _post 变体）长表
        落地到 team_page_raw。零额外请求（复用 _crawl_team 已取回的 html）。"""
        total = 0
        for st, tids in self.TEAM_LEVEL_TABLES.items():
            for tid in tids:
                recs = self._extract_team_table(html, tid, st, slug, season)
                if not recs:
                    continue
                n = self._upsert_rows(
                    conn, "team_page_raw", recs,
                    ("team_abbr", "season", "season_type",
                     "table_id", "row_label", "data_stat"))
                total += n
                if n:
                    logger.info("  [page_raw] %s/%s/%s/%s 落 %d 行",
                                 slug, season, st, tid, n)
        return total

    # ── 队页 PBP 专用覆写 ──────────────────────────────────────────
    # 球队主页面同时含常规赛(pbp_stats)与季后赛(pbp_stats_post)两张表。
    # 基类按 team_summaries.playoffs 每队只排 1 个目标，会漏掉一定存在的
    # 常规赛表；此处每队排 Regular+Playoffs 两目标，抓同一主页面、各取
    # 对应表（_crawl_one 已做同 URL 进程内去重）。
    def enumerate_team_seasons(self, conn, season: int):
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT abbreviation FROM team_summaries "
            "WHERE season = %s ORDER BY abbreviation",
            (season,),
        )
        rows = cur.fetchall()
        cur.close()
        out = []
        seen = set()
        for (abbr,) in rows:
            slug = self._br_slug(conn, abbr)
            for st in self.SEASON_TYPES:
                key = (slug, st)
                if key in seen:
                    continue
                seen.add(key)
                out.append((slug, season, st))
        return out

    def _is_expected_empty(self, slug: str, season: int,
                             season_type: str) -> bool:
        # 季后赛表(pbp_stats_post)仅当球队打进季后赛才存在；未进季后赛
        # 属正常「无数据」，不当作抓取失败登记（避免污染 crawl_failures）。
        return season_type == "Playoffs"


if __name__ == "__main__":
    dispatch_cli(TeamPBPCrawler, "BR Team Play-by-Play 爬虫")
