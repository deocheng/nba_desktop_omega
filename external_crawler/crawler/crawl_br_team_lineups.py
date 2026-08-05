"""crawl_br_team_lineups.py — ① Lineups (P1) 全历史回填。

数据源: https://www.basketball-reference.com/teams/{ABBR}/{YEAR}/lineups/
落库: team_lineups（每 team×season×season_type×lineup 一行，2~5 人组合）

⚠️ 2026-07-28 实测（LAL/2026 live HTML）：BR 该页是**净差值(Net)表**，
真实 data-stat 列 = ranker / lineup / mp(文本 "227:33") / diff_pts / diff_fg /
diff_fga / diff_fg_pct / diff_fg3 / diff_fg3a / diff_fg3_pct / diff_efg_pct /
diff_ft / diff_fta / diff_ft_pct / diff_orb / diff_orb_pct / diff_drb /
diff_drb_pct / diff_trb / diff_trb_pct / diff_ast / diff_stl / diff_blk /
diff_tov / diff_pf。**没有** gp/won/lost/pts/opp_pts/off_rtg/def_rtg/net_rtg。
球员键三件套（br_player_id*/player_id*/player_name*）经 player_id_bridge 桥接；
lineup_key 为 2~5 个 br_player_id 排序后 '|' 连接（无序去重）。

仅抓取 BR 实际列出的 2~5 人组合（与 starting_lineups「存实际组合」先例一致）；
最小分钟阈值可由 parse 层 min_minutes 过滤（默认 0 = 全存，不改变语义）。

复用 common/br_team_page.BRTeamPageCrawler。

用法:
  python crawl_br_team_lineups.py --season 2026 --resume --cache-dir br_lineups_cache
  python crawl_br_team_lineups.py --season 2026 --dry-run
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup, Comment
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

# 最小上场分钟阈值（默认 0 = 全存 BR 实际组合，不改变语义；可在 parse 层过滤）。
MIN_MINUTES = 0

# 净差值列（BR lineups 页真实 data-stat → DB 同名列）
DIFF_COLS = (
    "diff_pts", "diff_fg", "diff_fga", "diff_fg_pct",
    "diff_fg3", "diff_fg3a", "diff_fg3_pct", "diff_efg_pct",
    "diff_ft", "diff_fta", "diff_ft_pct",
    "diff_orb", "diff_orb_pct", "diff_drb", "diff_drb_pct",
    "diff_trb", "diff_trb_pct",
    "diff_ast", "diff_stl", "diff_blk", "diff_tov", "diff_pf",
)


def _mp_to_minutes(mp: Optional[str]) -> Optional[float]:
    """'227:33' → 227.55（分钟小数）；无法解析返回 None。"""
    if not mp:
        return None
    s = str(mp).strip()
    if ":" in s:
        try:
            m, sec = s.split(":", 1)
            return round(int(m) + int(sec) / 60.0, 2)
        except (ValueError, TypeError):
            return None
    return safe_float(s)


def _find_lineup_table(soup, tid):
    """注释感知的表查找（BR 阵容表常包在 HTML 注释里）。"""
    t = soup.find("table", id=tid)
    if t is not None:
        return t
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        if f'id="{tid}"' in c:
            sub = BeautifulSoup(c, "html.parser")
            t = sub.find("table", id=tid)
            if t is not None:
                return t
    return None


def parse_team_lineups_html(html: str, season_type: str = "Regular",
                             team_abbr: Optional[str] = None,
                             min_minutes: int = MIN_MINUTES) -> List[Dict]:
    """解析 BR Lineups 页 → 记录列表（纯函数）。

    每条记录含 ``players``（(br_slug, name) 列表，长度 2~5）与全部数值列；
    不含 team/season 维度（由 ``build_rows`` 注入）。BR 按阵容人数拆成多张表
    （2/3/4/5-man），分别 id=``lineups_{n}-man_``（常规赛）/
    ``lineups_{n}-man__p``（季后赛）。本函数遍历全部四张表，**不再硬过滤非 5
    人组**，使 2~5 人组合都能落库（旧实现只取 5-man 表并丢弃 2/3/4 人组，已修正）。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    # BR 表 id：常规赛 lineups_{n}-man_（尾随下划线）；季后赛 lineups_{n}-man__p（双下划线）。
    suffix = "__p" if season_type == "Playoffs" else "_"
    out: List[Dict] = []
    for n in (2, 3, 4, 5):
        tid = f"lineups_{n}-man{suffix}"
        table = _find_lineup_table(soup, tid)
        if table is None:
            # 某些队/赛季 BR 可能不列出全部人数表（如仅 5-man），缺表跳过即可。
            continue
        for row in table.find_all("tr"):
            if "thead" in row.get("class", []):
                continue
            vals = _row_data_stats(row)
            if not vals:
                continue
            lineup = vals.get("lineup", "")
            if not lineup:
                continue
            cell = row.find(["th", "td"], attrs={"data-stat": "lineup"})
            players = extract_player_links(cell) if cell is not None else []
            if not players:
                # 无球员链接的异常行跳过；不再以固定 5 人硬过滤，允许 2~5 人组。
                continue
            mp_raw = vals.get("mp")
            mp_min = _mp_to_minutes(mp_raw)
            if mp_min is not None and mp_min < min_minutes:
                continue
            rec = {
                "players": players,   # List[Tuple[slug, name]]
                "group_size": n,      # 该组合人数（取自表声明，2/3/4/5）
                "mp": mp_raw,         # 原始文本 "227:33"
            }
            for c in DIFF_COLS:
                rec[c] = safe_float(vals.get(c))
            out.append(rec)
    return out


class LineupsCrawler(BRTeamPageCrawler):
    """① Lineups 爬虫。"""

    DOMAIN = "lineups"
    TASK_TYPE = "br_team_lineups"
    TABLE = "team_lineups"
    PAGE = "lineups"
    TABLE_ID = "lineups"
    CONFLICT_COLS = ("team_abbr", "season", "season_type", "lineup_key")
    SEASON_TYPES = ("Regular", "Playoffs")
    MIN_SEASON = 1997  # BR lineups 数据约 1996-97 起

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        return parse_team_lineups_html(html, season_type, team_abbr)

    def build_rows(self, conn, team_abbr: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        players = rec.get("players", [])
        slugs = sorted([p[0] for p in players if p[0]])
        # lineup_key：以 br slug 排序后 '|' 连接（无序去重）；无 slug 时退回按 name。
        lineup_key = "|".join(slugs) if slugs else "|".join(
            sorted(p[1] for p in players))
        row: Dict = {
            "team_abbr": team_abbr,
            "season": season,
            "season_type": canon_season_type(season_type),
            "lineup_key": lineup_key,
        }
        for i, (slug, name) in enumerate(players, start=1):
            br_pid, nba_pid = self.resolve_player(conn, name)
            row[f"br_player_id{i}"] = slug or br_pid
            row[f"player_id{i}"] = nba_pid
            row[f"player_name{i}"] = name
        row["group_size"] = rec.get("group_size") or len(players)
        row["mp"] = rec.get("mp")
        for k in DIFF_COLS:
            row[k] = rec.get(k)
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)


if __name__ == "__main__":
    dispatch_cli(LineupsCrawler, "BR Lineups 爬虫 (① P1)")
