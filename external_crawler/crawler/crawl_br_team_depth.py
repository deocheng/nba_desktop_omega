"""crawl_br_team_depth.py — ④ Depth Charts (P3) 增量 upsert 2025-26。

数据源: https://www.basketball-reference.com/teams/{ABBR}/{YEAR}/depth-charts/
落库: team_depth_chart（复用现有表；ALTER 已加 position / player_id 两列，唯一键替换为
       (season, team_abbr, position, depth_rank)）

仅跑 2025-26 一季（BR URL 年 = 2026，即结束年）。每个位置（PG/SG/SF/PF/C）深度排序
逐槽位落库：position + depth_rank(1..5) + player_name + player_id（桥接）。

BR depth-charts 页仅 Regular Season（无 PO 深度图），故 SEASON_TYPES=('Regular',)。

复用 common/br_team_page.BRTeamPageCrawler（仅复用枚举/桥接/upsert 框架；
本域只跑单季，run 脚本固定 --season 2026）。

用法:
  python crawl_br_team_depth.py --season 2026 --resume --cache-dir br_depth_cache
  python crawl_br_team_depth.py --season 2026 --dry-run
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
from common.br_team_page import (
    BRTeamPageCrawler,
    build_arg_parser,
    dispatch_cli,
    extract_player_links,
    _row_data_stats,
)


def parse_team_depth_html(html: str, season_type: str = "Regular",
                           team_abbr: Optional[str] = None) -> List[Dict]:
    """解析 BR Depth Charts 页 → 记录列表（纯函数）。

    每个位置行（data-stat='pos'）的后续 td 槽位（1..5）各含一名球员链接，
    深度排序 = 槽位序号。返回每条 ``{position, depth_rank, player_name, player_slug}``。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="depth_charts")
    if table is None:
        return []
    out: List[Dict] = []
    for row in table.find_all("tr"):
        if "thead" in row.get("class", []):
            continue
        pos_cell = row.find(["th", "td"], attrs={"data-stat": "pos"})
        if pos_cell is None:
            continue
        position = pos_cell.get_text(strip=True)
        if not position:
            continue
        slots = row.find_all("td")
        for idx, cell in enumerate(slots, start=1):
            links = extract_player_links(cell)
            if not links:
                continue
            slug, name = links[0]
            out.append({
                "position": position,
                "depth_rank": idx,
                "player_name": name,
                "player_slug": slug,
            })
    return out


class DepthCrawler(BRTeamPageCrawler):
    """④ Depth Charts 爬虫（仅 2025-26 增量 upsert）。"""

    DOMAIN = "depth"
    TASK_TYPE = "br_team_depth"
    TABLE = "team_depth_chart"
    PAGE = "depth-charts"
    TABLE_ID = "depth_charts"
    CONFLICT_COLS = ("season", "team_abbr", "position", "depth_rank")
    SEASON_TYPES = ("Regular",)
    MIN_SEASON = 2026  # 仅增量补 2025-26（结束年 2026）；运行脚本固定 --season 2026

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        return parse_team_depth_html(html, season_type, team_abbr)

    def build_rows(self, conn, team_abbr: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        # team_depth_chart 无 br_player_id 列；仅桥接 NBA 数字 id 落 player_id。
        _, nba_pid = self.resolve_player(conn, rec.get("player_name"))
        row: Dict = {
            "team_abbr": team_abbr,
            "season": season,
            "position": rec.get("position"),
            "depth_rank": rec.get("depth_rank"),
            "player_name": rec.get("player_name"),
            "player_id": nba_pid,
        }
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)


if __name__ == "__main__":
    dispatch_cli(DepthCrawler, "BR Depth Charts 爬虫 (④ P3, 仅 2025-26)")
