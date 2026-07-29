"""crawl_br_player_shooting.py — BR 球员级 shooting 爬虫（任务 A）。

数据源: https://www.basketball-reference.com/players/{slug[0]}/{slug}/shooting/
  * ``#shooting``          → season_type='Regular'
  * ``#shooting_playoffs`` → season_type='Playoffs'
  一页含该球员全部赛季，每行 = 一个赛季。顺带覆盖 Playoffs。

复用: common.br_player_page.BRPlayerPageCrawler（继承 BRTeamPageCrawler），
      反屏蔽/限速/CF/upsert/失败登记/原始 HTML 归档全部来自既有，零新建。
      runner 设 BROWSER_BACKEND=uc 切 UC-Chrome 后端（version_main=150）。

入库: psycopg2.extras.execute_values + ON CONFLICT
      (player_id, season, season_type, team) DO UPDATE（幂等；team 入键容纳赛季中交易）。

用法
----
  python crawl_br_player_shooting.py --priority-gap --resume
  python crawl_br_player_shooting.py --slugs brownja02,allenja01 --dry-run
  python crawl_br_player_shooting.py --rework brownja02
  python crawl_br_player_shooting.py --limit 2 --dry-run   # 小批量验证
"""
import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 仓库根加入 sys.path（common 包可解析）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from bs4 import BeautifulSoup

from common.br_player_page import BRPlayerPageCrawler, DB_CONFIG
from common.br_team_page import safe_int, safe_float

# ── BR shooting 表 data-stat → player_shooting 列 映射 ──────────────────────
# 经 T0 研究确认：BR 球员 shooting 页每行带这些 data-stat（与 player_shooting
# 34 列对齐）。其中 num_heaves_made 在 BR 页为「HEAVE%」百分比，需由
# round(HEAVE% × #HEAVE) 推导为整数命中数。weight 不在 BR 页（置 NULL）。
_DATA_STAT_MAP = {
    "fg_percent": "fg_percent",
    "avg_dist_fga": "avg_dist_fga",
    "pct_fga_2pt": "percent_fga_from_x2p_range",
    "pct_fga_0_3": "percent_fga_from_x0_3_range",
    "pct_fga_3_10": "percent_fga_from_x3_10_range",
    "pct_fga_10_16": "percent_fga_from_x10_16_range",
    "pct_fga_16_3": "percent_fga_from_x16_3p_range",
    "pct_fga_3p": "percent_fga_from_x3p_range",
    "fg_pct_2pt": "fg_percent_from_x2p_range",
    "fg_pct_0_3": "fg_percent_from_x0_3_range",
    "fg_pct_3_10": "fg_percent_from_x3_10_range",
    "fg_pct_10_16": "fg_percent_from_x10_16_range",
    "fg_pct_16_3": "fg_percent_from_x16_3p_range",
    "fg_pct_3p": "fg_percent_from_x3p_range",
    "pct_fg_ast_2pt": "percent_assisted_x2p_fg",
    "pct_fg_ast_3pt": "percent_assisted_x3p_fg",
    "pct_fga_dunk": "percent_dunks_of_fga",
    "fg_dunk": "num_of_dunks",
    "pct_fg_3pt_corner": "percent_corner_3s_of_3pa",
    "fg_pct_3pt_corner": "corner_3_point_percent",
    "fg3a_heave": "num_heaves_attempted",   # BR "#HEAVE"：尝试次数
    "fg3_heave": "heave_pct",               # BR "HEAVE%"：命中百分比 → 推导 num_heaves_made
}

_SEASON_RE = re.compile(r"(\d{4})-(\d{2})")          # 如 2025-26
_HREF_RE = re.compile(r"NBA_(\d{4})_")               # 如 /leagues/NBA_2025_shooting.html


# ── 纯函数：解析双表 ────────────────────────────────────────────────────────
def _extract_player_name(soup: BeautifulSoup) -> Optional[str]:
    """从页面 <h1> 抽取球员姓名（BR 球员页标题即姓名）。"""
    h1 = soup.find("h1")
    if h1 is None:
        return None
    return h1.get_text(strip=True).replace("\n", " ").strip() or None


def _parse_season(row) -> Optional[int]:
    """从赛季单元格解析赛季结束年（如 2025-26 → 2026）。

    优先取单元格内链接 href 的 NBA_<year>；回退到文本 20xx-yy 的结束年。
    非赛季行（Career / Did Not Play）返回 None，由调用方跳过。
    """
    cell = row.find(["th", "td"], {"data-stat": "season"})
    if cell is None:
        return None
    a = cell.find("a")
    if a is not None:
        m = _HREF_RE.search(a.get("href", "") or "")
        if m:
            return int(m.group(1)) + 1
        txt = a.get_text(strip=True)
    else:
        txt = cell.get_text(strip=True)
    m = _SEASON_RE.search(txt)
    if not m:
        return None
    yy = int(m.group(2))
    # 两位年 → 四位年：70-99→19xx，00-69→20xx（覆盖 1997-2069）
    return 1900 + yy if yy >= 70 else 2000 + yy


def _build_record(vals: Dict[str, str], season: int,
                  season_type: str, player_name: Optional[str]) -> Dict:
    """把一行 data-stat 映射为 player_shooting 记录（不含 player_id）。"""
    heave_att = safe_int(vals.get("fg3a_heave"))
    heave_pct = safe_float(vals.get("fg3_heave"))
    heave_made = None
    if heave_att is not None and heave_pct is not None:
        heave_made = int(round(heave_pct * heave_att))

    rec = {
        "season": season,
        "lg": vals.get("lg_id"),
        "player": player_name,
        "age": safe_int(vals.get("age")),
        "team": vals.get("team_id"),
        "pos": vals.get("pos"),
        "g": safe_int(vals.get("g")),
        "gs": safe_int(vals.get("gs")),
        "mp": safe_int(vals.get("mp")),
        "fg_percent": safe_float(vals.get("fg_percent")),
        "avg_dist_fga": safe_float(vals.get("avg_dist_fga")),
        "percent_fga_from_x2p_range": safe_float(vals.get("pct_fga_2pt")),
        "percent_fga_from_x0_3_range": safe_float(vals.get("pct_fga_0_3")),
        "percent_fga_from_x3_10_range": safe_float(vals.get("pct_fga_3_10")),
        "percent_fga_from_x10_16_range": safe_float(vals.get("pct_fga_10_16")),
        "percent_fga_from_x16_3p_range": safe_float(vals.get("pct_fga_16_3")),
        "percent_fga_from_x3p_range": safe_float(vals.get("pct_fga_3p")),
        "fg_percent_from_x2p_range": safe_float(vals.get("fg_pct_2pt")),
        "fg_percent_from_x0_3_range": safe_float(vals.get("fg_pct_0_3")),
        "fg_percent_from_x3_10_range": safe_float(vals.get("fg_pct_3_10")),
        "fg_percent_from_x10_16_range": safe_float(vals.get("fg_pct_10_16")),
        "fg_percent_from_x16_3p_range": safe_float(vals.get("fg_pct_16_3")),
        "fg_percent_from_x3p_range": safe_float(vals.get("fg_pct_3p")),
        "percent_assisted_x2p_fg": safe_float(vals.get("pct_fg_ast_2pt")),
        "percent_assisted_x3p_fg": safe_float(vals.get("pct_fg_ast_3pt")),
        "percent_dunks_of_fga": safe_float(vals.get("pct_fga_dunk")),
        "num_of_dunks": safe_int(vals.get("fg_dunk")),
        "percent_corner_3s_of_3pa": safe_float(vals.get("pct_fg_3pt_corner")),
        "corner_3_point_percent": safe_float(vals.get("fg_pct_3pt_corner")),
        "num_heaves_attempted": heave_att,
        "num_heaves_made": heave_made,
        "season_type": season_type,
        "weight": None,  # BR 球员 shooting 页无每行 weight（T0 确认）
    }
    return rec


def _parse_one_table(soup: BeautifulSoup, table_id: str,
                     season_type: str, player_name: Optional[str]) -> List[Dict]:
    """解析单张表（#shooting 或 #shooting_playoffs）为记录列表。"""
    table = soup.find("table", id=table_id)
    if table is None:
        return []
    out: List[Dict] = []
    for row in table.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        # 收集本行全部 data-stat → 文本
        vals: Dict[str, str] = {}
        for cell in row.find_all(["th", "td"]):
            ds = cell.get("data-stat", "")
            if ds:
                vals[ds] = cell.get_text(strip=True)
        if not vals:
            continue
        season = _parse_season(row)
        if season is None:
            # Career 汇总行 / Did Not Play 行（无年份）→ 跳过
            continue
        if season < BRPlayerPageCrawler.MIN_SEASON:
            # 1983–1996 无 BR shooting 数据，跳过（不登记失败）
            continue
        rec = _build_record(vals, season, season_type, player_name)
        out.append(rec)
    return out


def parse_player_shooting_html(html: str) -> List[Dict]:
    """解析 BR 球员 shooting 页 HTML → 记录列表（纯函数，无 DB/网络依赖）。

    解析 ``#shooting``(Regular) + ``#shooting_playoffs``(Playoffs) 双表。
    每条记录含 33 列（不含 player_id；player_id 由 build_rows 注入=slug）：
    season, lg, player, age, team, pos, g, gs, mp, fg_percent, avg_dist_fga,
    percent_fga_from_*, fg_percent_from_*, percent_assisted_*, percent_dunks_of_fga,
    num_of_dunks, percent_corner_3s_of_3pa, corner_3_point_percent,
    num_heaves_attempted, num_heaves_made, season_type, weight。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    player_name = _extract_player_name(soup)
    out: List[Dict] = []
    out += _parse_one_table(soup, "shooting", "Regular", player_name)
    out += _parse_one_table(soup, "shooting_playoffs", "Playoffs", player_name)
    return out


# ── 具体爬虫 ────────────────────────────────────────────────────────────────
class PlayerShootingCrawler(BRPlayerPageCrawler):
    """BR 球员 shooting 爬虫（A）。"""

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        """委托纯函数 parse_player_shooting_html。"""
        return parse_player_shooting_html(html)

    def build_rows(self, conn, slug: str, season, season_type: str,
                   rec: Dict) -> Dict:
        """把一条解析记录补全为可落库行：注入 player_id=slug。

        season / season_type / team 已在 rec 中（解析阶段产出）。
        """
        row = dict(rec)
        row["player_id"] = slug
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        """批量 upsert 到 player_shooting（ON CONFLICT 4 列键 DO UPDATE）。"""
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)


# ── CLI ─────────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(description="BR 球员 shooting 爬虫 (A)")
    p.add_argument("--slugs", type=str, default=None,
                   help="逗号分隔 slug 列表（小批量/定点测试）")
    p.add_argument("--priority-gap", action="store_true",
                   help="只枚举有 Regular 缺口的 slug（优先补缺 ~9,797）")
    p.add_argument("--dry-run", action="store_true",
                   help="只枚举+打印计划，不取浏览器、不写库")
    p.add_argument("--resume", action="store_true",
                   help="跳过已落库 slug（断点续传）")
    p.add_argument("--rework", type=str, default=None,
                   help="从归档重解析某 slug（免爬）：--rework brownja02")
    p.add_argument("--limit", type=int, default=None,
                   help="最多处理 N 个 slug（小批量验证，不跑全量）")
    args = p.parse_args()

    crawler = PlayerShootingCrawler(dry_run=args.dry_run, resume=args.resume)

    if args.rework:
        n = crawler.rework_from_archive(args.rework)
        print(f"[rework] {args.rework}: upsert {n} 行")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        slugs = args.slugs.split(",") if args.slugs else None
        if slugs is None:
            slugs = crawler.enumerate_players(conn, priority_gap=args.priority_gap)
        if args.limit is not None:
            slugs = slugs[: max(0, args.limit)]
        total = crawler.run_players(
            conn, slugs, resume=args.resume,
            dry_run=args.dry_run, priority_gap=args.priority_gap,
        )
        print(f"完成：upsert {total} 行（处理 {len(slugs)} slug）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
