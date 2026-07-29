"""crawl_br_team_referees.py — ③ Referees (P4) 全历史回填。

数据源: https://www.basketball-reference.com/teams/{ABBR}/{YEAR}_referees.html
       ⚠️ URL 是 ``{year}_referees.html`` 后缀式（用户 2026-07-28 提供），
       **不是**目录式 ``/{year}/referees/``（后者 404）——故本类覆写 build_url。

⚠️ 2026-07-28 SAS/2026 实抓真相：该页表 id = ``refs-summary``，粒度是
**team×season×referee 的赛季汇总**（每裁判一行：g/wins/losses/win_pct/pace +
team_/opp_/diff_ 的 pts/fta/pf/sfoul/ofoul），**不是逐场裁判名单**。
故落库改为 ``team_referees``（本爬虫专表）；逐场 ``game_referees`` 数据源在
box score 主页（/boxscores/{gid}.html "Officials:"），保留空表另行决策。

复用 common/br_team_page.BRTeamPageCrawler。

用法:
  python crawl_br_team_referees.py --season 2026 --resume --cache-dir br_referees_cache
  python crawl_br_team_referees.py --season 2026 --dry-run
"""
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup, Comment
from common.br_team_page import (
    BRTeamPageCrawler,
    build_arg_parser,
    dispatch_cli,
    safe_float,
    safe_int,
    _row_data_stats,
)

_REF_SLUG_RE = re.compile(r"/referees/([^./]+)\.html")

# refs-summary 表数值列（data-stat 与 DB 同名）
_INT_COLS = ("rank", "g", "wins", "losses")
_FLOAT_COLS = (
    "win_pct", "pace",
    "team_pts", "team_fta", "team_pf", "team_sfoul", "team_ofoul",
    "opp_pts", "opp_fta", "opp_pf", "opp_sfoul", "opp_ofoul",
    "diff_pts", "diff_fta", "diff_pf", "diff_sfoul", "diff_ofoul",
)


def _find_refs_table(soup):
    """注释感知查找 #refs-summary（实测直接可见，兜底注释内）。"""
    t = soup.find("table", id="refs-summary")
    if t is not None:
        return t
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        if 'id="refs-summary"' in c:
            sub = BeautifulSoup(c, "html.parser")
            t = sub.find("table", id="refs-summary")
            if t is not None:
                return t
    return None


def parse_team_referees_html(html: str, season_type: str = "Regular",
                              team_abbr: Optional[str] = None) -> List[Dict]:
    """解析 BR Referees 页（refs-summary）→ 记录列表（纯函数）。

    每条记录 = 一名裁判在该队该季的汇总：``{referee_slug, referee_name,
    rank, g, wins, losses, win_pct, pace, team_*, opp_*, diff_*}``；
    不含 team/season 维度（由 ``build_rows`` 注入）。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = _find_refs_table(soup)
    if table is None:
        return []
    body = table.find("tbody") or table
    out: List[Dict] = []
    for row in body.find_all("tr"):
        if "thead" in row.get("class", []):
            continue
        vals = _row_data_stats(row)
        if not vals:
            continue
        cell = row.find(["th", "td"], attrs={"data-stat": "referee"})
        if cell is None:
            continue
        a = cell.find("a")
        name = (a.get_text(strip=True) if a is not None
                else cell.get_text(strip=True))
        if not name:
            continue
        slug = None
        if a is not None:
            m = _REF_SLUG_RE.search(a.get("href", ""))
            if m:
                slug = m.group(1)
        rec: Dict = {
            "referee_slug": slug or name.lower().replace(" ", "_"),
            "referee_name": name,
        }
        for c in _INT_COLS:
            rec[c] = safe_int(vals.get(c))
        for c in _FLOAT_COLS:
            rec[c] = safe_float(vals.get(c))
        out.append(rec)
    return out


class RefereesCrawler(BRTeamPageCrawler):
    """③ Referees 爬虫（team×season×referee 赛季汇总 → team_referees）。"""

    DOMAIN = "referees"
    TASK_TYPE = "br_team_referees"
    TABLE = "team_referees"
    PAGE = "referees"
    TABLE_ID = "refs-summary"
    CONFLICT_COLS = ("team_abbr", "season", "referee_slug")
    SEASON_TYPES = ("Regular",)  # 页面为全季汇总（不分常规/季后）
    MIN_SEASON = 1997            # sfoul/ofoul 依赖 PBP 时代（随实爬校验下界）

    def build_url(self, slug: str, season: int, page: str,
                  season_type: str = "Regular") -> str:
        """referees 页是后缀式 URL：/teams/{slug}/{year}_referees.html。"""
        return (f"https://www.basketball-reference.com/teams/"
                f"{slug}/{season}_referees.html")

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        return parse_team_referees_html(html, season_type, team_abbr)

    def build_rows(self, conn, team_abbr: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        row: Dict = {
            "team_abbr": team_abbr,
            "season": season,
        }
        row.update({k: rec.get(k) for k in (
            "referee_slug", "referee_name", *_INT_COLS, *_FLOAT_COLS)})
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)


if __name__ == "__main__":
    dispatch_cli(RefereesCrawler, "BR Referees 爬虫 (③ P4)")
