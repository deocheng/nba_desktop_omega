"""crawl_br_player_lineup.py — BR 球员级 lineup 爬虫。

数据源: https://www.basketball-reference.com/players/{letter}/{slug}/lineups/{year}
  * ``#lineups``      -> season_type='Regular'
  * ``#lineups_po``   -> season_type='Playoffs'（P2，解析器已预留探测）
  一页 = 某球员某赛季的 5 人阵容组及出场时间/效率统计。

复用: common.br_player_lineup.BRPlayerLineupCrawlerBase（继承 BRPlayerPageCrawler），
      CF/限速/upsert/归档/断点续跑/404 隔离全部来自既有，零新建。

入库: psycopg2.extras.execute_values + ON CONFLICT
      (player_id, season, season_type, lineup_key) DO UPDATE（幂等）。

用法
----
  python crawl_br_player_lineup.py --resume
  python crawl_br_player_lineup.py --slugs antetgi01 --years 2014 --dry-run
  python crawl_br_player_lineup.py --slugs antetgi01,jamesle01 --years 2014,2015
  python crawl_br_player_lineup.py --rework antetgi01,2014
  python crawl_br_player_lineup.py --limit 5 --dry-run   # 小批量验证
"""
# ⚠️ UNVERIFIED — 球员级 lineup 页表结构待样例 HTML
# （raw_archive/br_players/antetgi01/lineups_2014.html）确认；
# 用户存入后用 --rework antetgi01,2014 重放校验。
# 当前解析器以队级 crawl_br_team_lineups.py 的 parse_team_lineups_html 为蓝本
# （table id=lineups/lineups_po、5 人组合抽取、效率列），是合理起点而非瞎猜。

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 仓库根加入 sys.path（common 包可解析）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from bs4 import BeautifulSoup

from common.br_player_lineup import BRPlayerLineupCrawlerBase, DB_CONFIG
from common.br_team_page import (
    extract_player_links,
    safe_float,
    safe_int,
    _row_data_stats,
)

# 最小上场分钟阈值（默认 0 = 全存 BR 实际组合，不改变语义）。
MIN_MINUTES = 0


# ── 纯函数：解析 lineup 页 ───────────────────────────────────────────────────
def _parse_lineups_table(soup: BeautifulSoup, table_id: str,
                         season_type: str,
                         min_minutes: int = MIN_MINUTES) -> List[Dict]:
    """解析单张 lineup 表（``#lineups`` 或 ``#lineups_po``）为记录列表。

    以队级 ``parse_team_lineups_html`` 为蓝本：table id / data-stat 列名 /
    5 人组合抽取逻辑完全对齐。BR 5 人组合必须恰好 5 人，不足则跳过以防脏数据。
    """
    table = soup.find("table", id=table_id)
    if table is None:
        return []
    out: List[Dict] = []
    for row in table.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        vals = _row_data_stats(row)
        if not vals:
            continue
        lineup = vals.get("lineup", "")
        if not lineup:
            continue
        cell = row.find(["th", "td"], attrs={"data-stat": "lineup"})
        players = extract_player_links(cell) if cell is not None else []
        if len(players) != 5:
            # BR 5-man lineup 必须 5 人；非 5 人（如 4-man/3-man 子表误入）跳过。
            continue
        mp = safe_int(vals.get("mp")) or safe_int(vals.get("min"))
        if mp is not None and mp < min_minutes:
            continue
        rec: Dict = {
            "season_type": season_type,
            "players": players,  # List[Tuple[slug, name]]
            "gp": safe_int(vals.get("gp")),
            "minutes": mp,
            "won": safe_int(vals.get("won")),
            "lost": safe_int(vals.get("lost")),
            "pts": safe_int(vals.get("pts")),
            "opp_pts": safe_int(vals.get("opp_pts")),
            "off_rtg": safe_float(vals.get("off_rtg")),
            "def_rtg": safe_float(vals.get("def_rtg")),
            "net_rtg": safe_float(vals.get("net_rtg")),
        }
        out.append(rec)
    return out


def parse_player_lineups_html(html: str,
                              slug: Optional[str] = None,
                              year: Optional[int] = None) -> List[Dict]:
    """纯函数：解析 BR 球员 lineup 页 HTML -> 记录列表。

    解析 ``#lineups``(Regular) + ``#lineups_po``(Playoffs) 双表（若存在）。
    每条记录含 ``season_type`` / ``players`` / 9 个数值列；
    不含 ``player_id`` / ``season`` 维度（由 ``build_rows`` 注入）。

    输出每条记录的契约：
        {
            "season_type": str,                    # 'Regular' / 'Playoffs'
            "players": [(br_slug, display_name), ...],  # 长度须为 5
            "gp": Optional[int],
            "minutes": Optional[int],
            "won": Optional[int],
            "lost": Optional[int],
            "pts": Optional[int],
            "opp_pts": Optional[int],
            "off_rtg": Optional[float],
            "def_rtg": Optional[float],
            "net_rtg": Optional[float],
        }

    ⚠️ 表 id / data-stat 列名映射待样例 HTML 确认（见模块顶部注释）。
       预期表 id 为 ``lineups`` / ``lineups_po``（类比 team_lineups），
       但球员级页结构可能不同——以实际 HTML 为准。

    Args:
        html: BR 球员 lineup 页 HTML 文本。
        slug: BR 球员 slug（仅用于上下文/日志，不参与解析）。
        year: 赛季结束年（仅用于上下文/日志，不参与解析）。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict] = []
    out += _parse_lineups_table(soup, "lineups", "Regular")
    out += _parse_lineups_table(soup, "lineups_po", "Playoffs")
    return out


# ── 具体爬虫 ────────────────────────────────────────────────────────────────
class PlayerLineupCrawler(BRPlayerLineupCrawlerBase):
    """BR 球员 lineup 爬虫。

    实现 3 个钩子：
      * ``parse``     -> 委托纯函数 ``parse_player_lineups_html``
      * ``build_rows`` -> 注入 ``player_id``/``season``/``season_type``/``lineup_key``
      * ``upsert``    -> ``self._upsert_rows``（execute_values + ON CONFLICT）
    """

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        """委托纯函数 parse_player_lineups_html。

        ``season_type`` 参数不使用——解析器内部探测 ``#lineups``(Regular) 和
        ``#lineups_po``(Playoffs) 双表，每条记录自带 ``season_type`` 字段。
        """
        return parse_player_lineups_html(html)

    def build_rows(self, conn, slug: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        """把一条解析记录补全为可落库行。

        注入 ``player_id=slug`` / ``season`` / ``season_type``；
        计算 ``lineup_key``（5 个 br_player_id 排序后 ``|`` 连接，对齐
        team_lineups 约定）；展开 5× ``br_player_id`` / ``player_name``。
        """
        players: List[Tuple[Optional[str], str]] = rec.get("players", [])
        slugs = sorted([p[0] for p in players if p[0]])
        # lineup_key：以 br slug 排序后 '|' 连接（无序去重）；
        # 无 slug 时退回按 player_name 排序（降级方案，与 team_lineups 一致）。
        lineup_key = "|".join(slugs) if slugs else "|".join(
            sorted(p[1] for p in players))
        row: Dict = {
            "player_id": slug,
            "season": season,
            "season_type": season_type,
            "lineup_key": lineup_key,
        }
        for i, (br_slug, name) in enumerate(players, start=1):
            row[f"br_player_id{i}"] = br_slug
            row[f"player_name{i}"] = name
        for k in ("gp", "minutes", "won", "lost", "pts", "opp_pts",
                  "off_rtg", "def_rtg", "net_rtg"):
            row[k] = rec.get(k)
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        """批量 upsert 到 player_lineups（ON CONFLICT 4 列键 DO UPDATE）。"""
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)


# ── CLI ─────────────────────────────────────────────────────────────────────
def main() -> None:
    """CLI 入口：支持 --slugs / --years / --limit / --resume / --dry-run / --rework。"""
    p = argparse.ArgumentParser(description="BR 球员 lineup 爬虫")
    p.add_argument("--slugs", type=str, default=None,
                   help="逗号分隔 slug 列表（小批量/定点测试）")
    p.add_argument("--years", type=str, default=None,
                   help="逗号分隔年份列表（赛季结束年，如 2014=2013-14 赛季）")
    p.add_argument("--limit", type=int, default=None,
                   help="最多处理 N 个 (slug,year) 对（小批量验证）")
    p.add_argument("--dry-run", action="store_true",
                   help="只枚举+打印计划，不取浏览器、不写库")
    p.add_argument("--resume", action="store_true",
                   help="跳过已落库 (slug,year)（断点续传）")
    p.add_argument("--rework", type=str, default=None,
                   help="从归档重解析某 (slug,year)（免爬）：--rework antetgi01,2014")
    args = p.parse_args()

    crawler = PlayerLineupCrawler(dry_run=args.dry_run, resume=args.resume)

    # --rework 模式：从归档 HTML 重解析落库（免爬）
    if args.rework:
        parts = args.rework.split(",")
        if len(parts) != 2:
            print("--rework 格式：slug,year（如 antetgi01,2014）")
            sys.exit(1)
        slug = parts[0].strip()
        year = int(parts[1].strip())
        n = crawler.rework_from_archive(slug, year)
        print(f"[rework] {slug}/{year}: upsert {n} 行")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        slugs_list = (
            [s.strip() for s in args.slugs.split(",") if s.strip()]
            if args.slugs else None
        )
        years_list = (
            [int(y.strip()) for y in args.years.split(",") if y.strip()]
            if args.years else None
        )
        targets = crawler.build_targets(conn, slugs=slugs_list, years=years_list)
        if args.limit is not None:
            targets = targets[: max(0, args.limit)]
        total = crawler.run_lineups(
            conn, targets, resume=args.resume, dry_run=args.dry_run)
        print(f"完成：upsert {total} 行（处理 {len(targets)} 对）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
