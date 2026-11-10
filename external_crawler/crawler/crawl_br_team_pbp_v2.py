# -*- coding: utf-8 -*-
"""crawl_br_team_pbp_v2.py — Team PBP 爬虫 v2（修复 2026-08-16 代码审查 P0-①）

相对 crawl_br_team_pbp.py（原版保留不动）的修复：
  [P0-①] 原长表键 (table_id, row_label, data_stat) 不含行身份。当前 BR 队页
         pbp_stats 表首列是 Rk 序号（1..N），row_label 恰好逐行唯一，故存量
         数据实测未损坏（2026-08-16 已核验 GSW/2025：551 行 = 528 键对 + 23
         表头行，键内零重复）。但这是**侥幸依赖**：一旦 BR 改版去掉 Rk 列、
         或出现重复行标签，ON CONFLICT DO UPDATE 会后写覆盖先写、每节只剩
         最后一行。v2 显式加 row_idx 行身份列：
           * 首列为空（小计/分隔行，row_label=''）→ row_idx = 0，
             与迁移回填一致，保证重爬幂等命中旧行；
           * 首列文本可解析为整数 → row_idx = 该序号（与存量回填值一致，
             保证重爬幂等命中旧行）；
           * 否则（非空非数字，如重复小计行标签）→ 按解析顺序的枚举序号
             （1,000,000+ 空间，保底唯一化）。
  [顺带] 过滤 <thead> 内的表头行（原版只滤 class=thead，导致每队每季混入
         一行 row_label='Rk' 的表头垃圾行 ~23 格；2026-08-16 实测存在）。
  [顺带] 修掉原版 `val == "" or val == ""` 重复死条件（疑似漏写 "—" 过滤，
         v2 保持原语义仅过滤空值，不改数据口径）。

⚠️ 使用前置条件：先跑 migrate_team_pbp_rowidx.py 给 team_pbp_raw 加
   row_idx 列并换主键（该脚本自带备份与 dry-run）。未跑迁移直接用 v2
   会在 INSERT 时因未知列报错（安全失败，不会写坏数据）。

用法与原版完全一致（参数、缓存、CDP 流程均继承基类）：
    BROWSER_BACKEND=cdp CHROME_CDP_URL=http://127.0.0.1:9223 \
        .venv/bin/python external_crawler/crawler/crawl_br_team_pbp_v2.py \
        --season 2026 --dry-run
"""
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
from bs4.element import Comment

from common.br_team_page import (
    BRTeamPageCrawler,
    build_arg_parser,
    dispatch_cli,
    safe_float,
    safe_int,
)
from common.season_type_norm import canon_season_type


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


def parse_team_pbp_html_v2(html: str, season_type: str = "Regular",
                           team_abbr: Optional[str] = None) -> List[Dict]:
    """v2 解析：每条记录 = 一个 data-stat 单元格，附带 row_idx 行身份。

    row_idx 规则（见模块 docstring）：
      首列文本为纯数字 → int(首列)；否则按捕获顺序枚举（1 起）。
    另过滤 <thead> 内所有行（原版漏滤 → 'Rk' 表头垃圾行入库）。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    tid = "pbp_stats_post" if season_type == "Playoffs" else "pbp_stats"
    table = _find_br_table(soup, tid)
    if table is None:
        return []
    out: List[Dict] = []
    fallback_idx = 0
    for tr in table.find_all("tr"):
        if "thead" in tr.get("class", []):
            continue
        # v2：thead 内的所有行（列头行 / over_header）都不是数据，全滤。
        #     原版只滤 class=thead，BR 的 <thead><tr> 无 class 时会漏进一行
        #     row_label='Rk' 的表头垃圾（每队每季 ~23 格）。
        if tr.find_parent("thead") is not None:
            continue
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        # 跳过分组表头行（首列 data-stat 以 header_ 开头）
        if cells[0].get("data-stat", "").startswith("header_"):
            continue
        label = _row_label(tr) or ""
        # v2：行身份。Rk 序号优先（与存量迁移回填一致 → 重爬幂等）；
        #      无数字首列时用枚举序号保底唯一化。
        first_txt = cells[0].get_text(strip=True)
        if first_txt == "":
            # 空首列（小计/分隔行，row_label=''）：行身份=0，与迁移回填一致
            # → v2 重爬已迁移赛季时 UPSERT 命中同行，保证增量幂等。
            row_idx = 0
        elif first_txt.isdigit():
            row_idx = int(first_txt)
        else:
            fallback_idx += 1
            row_idx = 1_000_000 + fallback_idx   # 与 Rk 序号空间隔离，防撞
        for cell in cells[1:]:
            ds = cell.get("data-stat", "")
            if not ds or ds.startswith("header_"):
                continue
            val = cell.get_text(strip=True)
            if val == "":          # 原版 `val == "" or val == ""` 死条件，收敛为单条件、语义不变
                continue
            out.append({
                "table_id": tid,
                "row_label": label,
                "row_idx": row_idx,
                "data_stat": ds,
                "val": val,
            })
    return out


class TeamPBPCrawlerV2(BRTeamPageCrawler):
    """Team Play-by-Play 爬虫 v2：长表键加 row_idx 行身份。"""

    DOMAIN = "team_pbp"
    TASK_TYPE = "br_team_pbp"
    TABLE = "team_pbp_raw"
    PAGE = ""
    TABLE_ID = "pbp_stats"
    # v2：冲突键加入 row_idx —— 同标签多行不再互相覆盖（P0-① 根修）
    CONFLICT_COLS = ("team_abbr", "season", "season_type",
                     "table_id", "row_label", "row_idx", "data_stat")
    SEASON_TYPES = ("Regular", "Playoffs")
    MIN_SEASON = 1997
    FULL_CRAWL_START = 2000

    def build_url(self, slug: str, season: int, page: str,
                  season_type: str = "Regular") -> str:
        return (f"https://www.basketball-reference.com/"
                f"teams/{slug}/{season}.html")

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        return parse_team_pbp_html_v2(html, season_type, team_abbr)

    def build_rows(self, conn, team_abbr: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        row: Dict = {
            "team_abbr": team_abbr,
            "season": season,
            "season_type": canon_season_type(season_type),
            "table_id": rec.get("table_id"),
            "row_label": rec.get("row_label"),
            "row_idx": rec.get("row_idx", 0),
            "data_stat": rec.get("data_stat"),
            "val": rec.get("val"),
        }
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)

    # 同页多表抽取（与原版一致，抽的是队级汇总表，行标签天然唯一，无 P0-① 风险）
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
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        table = _find_br_table(soup, table_id)
        if table is None:
            return []
        out: List[Dict] = []
        for tr in table.find_all("tr"):
            if tr.find_parent("thead") is not None:
                continue
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
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
        """同页多表抽取钩子（与原版一致，落 team_page_raw）。"""
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
        # 与原版一致：未进季后赛的 PO 表属正常空，不登记失败。
        # （审查 P1「CF 残页被当未进季后赛」属已知权衡，v2 不改口径。）
        return season_type == "Playoffs"


if __name__ == "__main__":
    dispatch_cli(TeamPBPCrawlerV2, "BR Team Play-by-Play 爬虫 v2 (row_idx 行身份)")
