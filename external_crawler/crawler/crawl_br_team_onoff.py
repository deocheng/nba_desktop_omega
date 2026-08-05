"""crawl_br_team_onoff.py — ② On-Off (P2) 全历史回填。

数据源: https://www.basketball-reference.com/teams/{ABBR}/{YEAR}/on-off/
落库: team_on_off（每 team×season×season_type×player 一行，ON/OFF/DIFF 同 row）

BR 该页真实结构（#on_off）=「On Court / Off Court / Difference」三组，
每组 11 列 + player/split_id：
  * On Court 组（data-stat 无前缀）:
    mp, off_rtg, pace, efg_pct, tov_pct, orb_pct, drb_pct, trb_pct, stl_pct, blk_pct, ast_pct
  * Off Court 组（data-stat 带 opp_ 前缀）:
    opp_mp, opp_off_rtg, opp_pace, opp_efg_pct, opp_tov_pct, opp_orb_pct,
    opp_drb_pct, opp_trb_pct, opp_stl_pct, opp_blk_pct, opp_ast_pct
  * Difference 组（data-stat 带 diff_ 前缀）:
    diff_mp, diff_off_rtg, diff_pace, diff_efg_pct, diff_tov_pct, diff_orb_pct,
    diff_drb_pct, diff_trb_pct, diff_stl_pct, diff_blk_pct, diff_ast_pct
无 gp、无独立 def_rtg、无独立 net_rtg（净值由 Diff 组体现）。

列名映射 PRD→DDL: 直接按组前缀落库为 on_*/off_*/diff_*（见 ``ON_OFF_COLUMNS``）；
球员键 (br_player_id, player_id) 经 player_id_bridge 桥接。

复用 common/br_team_page.BRTeamPageCrawler。

用法:
  python crawl_br_team_onoff.py --season 2026 --resume --cache-dir br_onoff_cache
  python crawl_br_team_onoff.py --season 2026 --dry-run
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
from common.season_type_norm import canon_season_type  # season_type 写入约定统一对齐 dim_games
from common.br_team_page import (
    BRTeamPageCrawler,
    build_arg_parser,
    dispatch_cli,
    extract_player_links,
    safe_float,
    safe_int,
    _row_data_stats,
)

# BR on/off 表真实列（三组，每组 11 列）→ DDL 数值列，顺序与 DDL 列顺序一致，
# 供 ``build_rows`` 注入。无幻影列、无漏列。
ON_OFF_COLUMNS: List[str] = [
    # —— On Court 组（BR data-stat 无前缀）——
    "on_mp", "on_off_rtg", "on_pace", "on_efg_pct", "on_tov_pct",
    "on_orb_pct", "on_drb_pct", "on_trb_pct", "on_stl_pct", "on_blk_pct", "on_ast_pct",
    # —— Off Court 组（BR data-stat 带 opp_ 前缀）——
    "off_mp", "off_off_rtg", "off_pace", "off_efg_pct", "off_tov_pct",
    "off_orb_pct", "off_drb_pct", "off_trb_pct", "off_stl_pct", "off_blk_pct", "off_ast_pct",
    # —— Difference 组（BR data-stat 带 diff_ 前缀，净值）——
    "diff_mp", "diff_off_rtg", "diff_pace", "diff_efg_pct", "diff_tov_pct",
    "diff_orb_pct", "diff_drb_pct", "diff_trb_pct", "diff_stl_pct", "diff_blk_pct", "diff_ast_pct",
]

# BR 三组（DDL 前缀, BR data-stat 前缀 or None）+ 每组 11 个基础列。
_ON_GROUP = [  # (DDL 前缀, BR data-stat 前缀)
    ("on", None),
    ("off", "opp"),
    ("diff", "diff"),
]
_ON_BASE_STATS = [
    "mp", "off_rtg", "pace", "efg_pct", "tov_pct", "orb_pct",
    "drb_pct", "trb_pct", "stl_pct", "blk_pct", "ast_pct",
]


def parse_team_onoff_html(html: str, season_type: str = "Regular",
                           team_abbr: Optional[str] = None) -> List[Dict]:
    """解析 BR On-Off 页 → 记录列表（纯函数，无 DB/网络依赖）。

    每条记录含 ``player_slug`` / ``player_name`` 与 ON/OFF/DIFF 全部效率列
    （33 数值列，见 ``ON_OFF_COLUMNS``）；不含 team/season 维度（由
    ``build_rows`` 注入）。

    BR on/off 页真实结构：``#on_off`` 表由「On Court / Off Court / Difference」
    三组、每组 11 列构成。On Court 组 data-stat 无前缀（``mp``/``off_rtg``/…），
    Off Court 组带 ``opp_`` 前缀，Difference 组带 ``diff_`` 前缀。无 gp / 独立
    def_rtg / 独立 net_rtg（净值由 Diff 组体现）。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    tid = "on_off_po" if season_type == "Playoffs" else "on_off"
    table = soup.find("table", id=tid)
    if table is None:
        return []
    out: List[Dict] = []
    for row in table.find_all("tr"):
        if "thead" in row.get("class", []):
            continue
        vals = _row_data_stats(row)
        if not vals:
            continue
        pname = vals.get("player", "")
        if not pname or pname == "Player":
            continue
        cell = row.find(["th", "td"], attrs={"data-stat": "player"})
        players = extract_player_links(cell) if cell is not None else []
        slug = players[0][0] if players else None

        rec: Dict = {
            "player_slug": slug,
            "player_name": pname,
        }
        # 三组 × 11 列：把 BR data-stat 映射为 DDL on_*/off_*/diff_* 列。
        for ddl_prefix, br_prefix in _ON_GROUP:
            for base in _ON_BASE_STATS:
                br_stat = f"{br_prefix}_{base}" if br_prefix else base
                ddl_col = f"{ddl_prefix}_{base}"
                # mp 为整数分钟，其余为百分比/效率（浮点）。
                rec[ddl_col] = safe_int(vals.get(br_stat)) if base == "mp" \
                    else safe_float(vals.get(br_stat))
        out.append(rec)
    return out


class OnOffCrawler(BRTeamPageCrawler):
    """② On-Off 爬虫。"""

    DOMAIN = "onoff"
    TASK_TYPE = "br_team_onoff"
    TABLE = "team_on_off"
    PAGE = "on-off"
    TABLE_ID = "on_off"
    CONFLICT_COLS = ("team_abbr", "season", "season_type", "player_name")
    SEASON_TYPES = ("Regular",)
    MIN_SEASON = 1997  # BR on/off 数据约 1996-97 起

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        return parse_team_onoff_html(html, season_type, team_abbr)

    def build_rows(self, conn, team_abbr: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        slug = rec.get("player_slug")
        name = rec.get("player_name")
        br_pid, nba_pid = self.resolve_player(conn, name)
        row: Dict = {
            "team_abbr": team_abbr,
            "season": season,
            "season_type": canon_season_type(season_type),
            "br_player_id": slug or br_pid,
            "player_id": nba_pid,
            "player_name": name,
        }
        # 注入 33 个 ON/OFF/DIFF 数值列（严格对应 DDL，无幻影列）。
        for k in ON_OFF_COLUMNS:
            row[k] = rec.get(k)
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)


if __name__ == "__main__":
    dispatch_cli(OnOffCrawler, "BR On-Off 爬虫 (② P2)")
