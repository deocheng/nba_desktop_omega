"""crawl_br_player_lineup.py — BR 球员级 lineup 爬虫。

数据源: https://www.basketball-reference.com/players/{letter}/{slug}/lineups/{year}
  * ``#lineups-5-man`` / ``-4-man`` / ``-3-man`` / ``-2-man`` -> season_type='Regular'（阵容人数 5/4/3/2）
  * ``#lineups-post-5-man`` / ``-post-4-man`` / ... -> season_type='Playoffs'（BR 真实 id，探测+跳过）
  一页 = 某球员某赛季各阵容人数(2~5)的阵容组及每 100 回合净差值统计。

真实页结构（已用 boguemu01/2001 样本核实，2026-07-24 修订）：
  * 4 张阵容人数表（5/4/3/2-man）均被 Chrome 渲染为可解析 DOM（非 HTML 注释），BeautifulSoup 均可 find。
  * 季后赛对应 ``lineups-post-{n}-man`` 表（BR 真实 id）；探测到才解析，否则跳过。
  * 列 = ``ranker`` / ``lineup`` / ``team_id`` / ``mp``(格式 M:SS)
         + 22 个 ``diff_*``（每 100 回合净差值，带 +/-）。
  * N 人组合在 ``data-stat="lineup"`` 单元格内，N 个 ``/players/{l}/{slug}.html`` 链接（N = 阵容人数）。
  * 单元格 ``csk`` 属性给出权威已排序 lineup_key（':' 分隔），仅作校验。

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

import argparse
import re
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

# 22 个「每 100 回合净差值」列（与 DDL player_lineups.diff_* 一一对应）。
DIFF_STATS = (
    "diff_fg", "diff_fga", "diff_fg_pct",
    "diff_fg3", "diff_fg3a", "diff_fg3_pct", "diff_efg_pct",
    "diff_ft", "diff_fta", "diff_ft_pct",
    "diff_pts",
    "diff_orb", "diff_orb_pct", "diff_drb", "diff_drb_pct",
    "diff_trb", "diff_trb_pct",
    "diff_ast", "diff_stl", "diff_blk", "diff_tov", "diff_pf",
)

# 阵容人数表 id（BR 实际格式）：
#   Regular  -> lineups-{n}-man
#   Playoffs -> lineups-post-{n}-man  （注意单词顺序：post 在前，非 -post 后缀）
LINEUP_SIZES = (5, 4, 3, 2)          # 阵容人数：5 / 4 / 3 / 2（man）
REG_PREFIX = "lineups-{n}-man"           # Regular 表 id
PO_PREFIX = "lineups-post-{n}-man"       # Playoffs 表 id（BR 真实格式）


def parse_minutes(val: Optional[str]) -> Optional[int]:
    """把 BR ``mp`` 文本（格式 ``M:SS``）解析为总秒数。

    ``"132:57"`` -> ``7857``（132*60+57）。空/*/None -> None。
    解析失败（非预期格式）-> None，不抛异常。
    """
    if not val:
        return None
    s = val.strip()
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return int(m) * 60 + int(sec)
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _find_br_table(soup: BeautifulSoup, table_id: str):
    """BR 注释感知表查找（兜底）。

    BR 把部分表（尤其季后赛 ``lineups-post-{n}-man`` 表）原样注释在
    ``<!-- ... <table id="lineups-post-5-man"> ... -->`` 里
    （外层 ``div`` 带 ``setup_commented commented`` 类），``html.parser`` 默认
    跳过注释内容，致 ``soup.find('table', id=table_id)`` 对注释内表返回
    ``None``（Regular 表一般为可见表，PO 表多为注释表 → 独漏 PO）。

    本函数：先直接 ``find``；失败则扫描所有 ``Comment`` 节点，命中
    ``id="<table_id>"`` 者把注释文本当子 soup 再 ``find``，返回真实表。
    对可见表无副作用（首查即命中返回）。
    """
    t = soup.find("table", id=table_id)
    if t is not None:
        return t
    from bs4 import Comment
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if f'id="{table_id}"' in c:
            sub = BeautifulSoup(c, "html.parser")
            t = sub.find("table", id=table_id)
            if t is not None:
                return t
    return None


# ── 纯函数：解析 lineup 页 ───────────────────────────────────────────────────
def _parse_lineups_table(soup: BeautifulSoup, table_id: str,
                         season_type: str, size: int,
                         min_minutes: int = MIN_MINUTES) -> List[Dict]:
    """解析单张 lineup 表（``lineups-{size}-man`` 或季后赛 ``*-post`` 变体）。

    每行 ``data-stat="lineup"`` 单元格内 ``size`` 个球员链接 +
    22 个 ``diff_*`` 净差列 + ``mp``(M:SS) + ``team_id`` + ``ranker``。
    BR 阵容组合人数须恰好 = ``size``，不足/超出（汇总行/误入他表）则跳过。
    """
    table = _find_br_table(soup, table_id)
    if table is None:
        return []
    out: List[Dict] = []
    for row in table.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        vals = _row_data_stats(row)
        if not vals:
            continue
        cell = row.find(["th", "td"], attrs={"data-stat": "lineup"})
        players = extract_player_links(cell) if cell is not None else []
        if len(players) != size:
            # 汇总行（"Player Average"）无 <a> 链接 → 跳过；
            # 人数不符（如 5-man 表误入 4-man 行）也跳过。
            continue
        mp = parse_minutes(vals.get("mp"))
        if mp is not None and mp < min_minutes:
            continue
        csk = cell.get("csk") if cell is not None else None
        rec: Dict = {
            "season_type": season_type,
            "lineup_size": size,
            "players": players,  # List[Tuple[slug, name]]，长度须为 size
            "ranker": safe_int(vals.get("ranker")),
            "team_id": (vals.get("team_id") or None),
            "minutes": mp,
            "csk": csk,  # 权威已排序 key（':' 分隔），仅校验用
        }
        for ds in DIFF_STATS:
            rec[ds] = safe_float(vals.get(ds))
        out.append(rec)
    return out


def parse_player_lineups_html(html: str,
                              slug: Optional[str] = None,
                              year: Optional[int] = None) -> List[Dict]:
    """纯函数：解析 BR 球员 lineup 页 HTML -> 记录列表。

    解析全部 4 种阵容人数表（Regular + Playoffs）：
      ``#lineups-5-man`` / ``-4-man`` / ``-3-man`` / ``-2-man``（Regular）
      ``#lineups-post-5-man`` / ... / ``-post-2-man``（Playoffs，BR 真实 id，探测到才解析）
    每条记录含 ``season_type`` / ``lineup_size`` / ``players`` / 阵容元数据 /
    22 个 ``diff_*`` 净差列；不含 ``player_id`` / ``season``（由 ``build_rows`` 注入）。

    输出每条记录的契约：
        {
            "season_type": str,                    # 'Regular' / 'Playoffs'
            "lineup_size": int,                   # 2 / 3 / 4 / 5
            "players": [(br_slug, display_name), ...],  # 长度须为 lineup_size
            "ranker": Optional[int],
            "team_id": Optional[str],
            "minutes": Optional[int],              # 总秒数（M:SS 已解析）
            "csk": Optional[str],                # 权威 key（':' 分隔），仅校验
            "diff_fg": Optional[float], ...      # 22 个 diff_* 净差列
        }

    Args:
        html: BR 球员 lineup 页 HTML 文本。
        slug: BR 球员 slug（仅用于上下文/日志，不参与解析）。
        year: 赛季结束年（仅用于上下文/日志，不参与解析）。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict] = []
    for size in LINEUP_SIZES:
        # Regular
        out += _parse_lineups_table(
            soup, REG_PREFIX.format(n=size), "Regular", size)
        # Playoffs：BR 真实 id = lineups-post-{size}-man（探测到才解析）
        po_id = PO_PREFIX.format(n=size)
        if _find_br_table(soup, po_id) is not None:
            out += _parse_lineups_table(soup, po_id, "Playoffs", size)
    return out


# ── 具体爬虫 ─────────────────────────────────────────────────────────────────
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

        ``season_type`` 参数不使用——解析器内部探测 ``#lineups-5-man``(Regular)
        和 ``#lineups-post-5-man``(Playoffs) 双表，每条记录自带 ``season_type``。
        """
        return parse_player_lineups_html(html)

    def build_rows(self, conn, slug: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        """把一条解析记录补全为可落库行。

        注入 ``player_id=slug`` / ``season`` / ``season_type`` / ``lineup_size``；
        计算 ``lineup_key``（N 个 br_player_id 排序后 ``|`` 连接，N=lineup_size，对齐
        team_lineups 约定）；展开 5× ``br_player_id`` / ``player_name``（不足位留 NULL）；
        透传 ranker / team_id / minutes / 22 个 diff_*。
        用单元格 ``csk`` 校验 lineup_key（不一致仅告警不阻断）。
        """
        players: List[Tuple[Optional[str], str]] = rec.get("players", [])
        slugs = sorted([p[0] for p in players if p[0]])
        # lineup_key：以 br slug 排序后 '|' 连接（无序去重）；
        # 无 slug 时退回按 player_name 排序（降级方案，与 team_lineups 一致）。
        lineup_key = "|".join(slugs) if slugs else "|".join(
            sorted(p[1] for p in players))
        # csk 权威校验：':' -> '|' 后应与计算的 lineup_key 一致。
        csk = rec.get("csk")
        if csk:
            expected = csk.replace(":", "|")
            if expected != lineup_key:
                print(
                    f"[warn] lineup_key 不一致 slug={slug} year={season}: "
                    f"csk={expected!r} vs 计算={lineup_key!r}")
        row: Dict = {
            "player_id": slug,
            "season": season,
            "season_type": season_type,
            "lineup_size": rec.get("lineup_size"),
            "lineup_key": lineup_key,
        }
        for i, (br_slug, name) in enumerate(players, start=1):
            row[f"br_player_id{i}"] = br_slug
            row[f"player_name{i}"] = name
        row["ranker"] = rec.get("ranker")
        row["team_id"] = rec.get("team_id")
        row["minutes"] = rec.get("minutes")
        for ds in DIFF_STATS:
            row[ds] = rec.get(ds)
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        """批量 upsert 到 player_lineups（ON CONFLICT 5 列键 DO UPDATE：player_id, season, season_type, lineup_size, lineup_key）。"""
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
