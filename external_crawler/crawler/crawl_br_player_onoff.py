"""crawl_br_player_onoff.py — BR 球员级 on-off 爬虫。

🔴 纠错：BR on-off 是【球员级】页面（用户 2026-07-24 纠正）。废弃的
``crawl_br_team_onoff.py`` 抓的是球队级 ``/teams/{abbr}/{year}/on-off/``，本爬虫抓
球员级 ``/players/{letter}/{slug}/on-off/{year}``，数据模型完全不同。

数据源: https://www.basketball-reference.com/players/{letter}/{slug}/on-off/{year}
  * ``#on-off``      -> season_type='Regular'（常规赛）
  * ``#on-off-post`` -> season_type='Playoffs'（若存在；探测+跳过）
  一页 = 某球员某赛季的 on/off 影响力（On Court / Off Court / On-Off 三行）。

真实页结构（已用 antetgi01/2024 + jamesle01/2018 样本核实，2026-07-24 定稿）：
  * 常规赛表 id=``on-off``；季后赛表 id=``on-off-post``。
  * 每表恰好 3 行，由 ``data-stat="split_id"`` 区分：
    ``On Court`` / ``Off Court`` / ``On − Off``（U+2212，规范化为 ``On-Off``）。
  * 30 列：``split_id, team_id, mp`` + Team 组 9(``efg_pct...off_rtg``)
    + Opponent 组 9(``opp_*``) + Difference 组 9(``diff_*``)。
  * mp 异构：On/Off 行=分钟数(numeric)；On-Off 行="65%" -> min_pct=65.0。
  * 值可能带正负号（``+.035`` / ``-3.7``），safe_float 直接解析。

入库: psycopg2.extras.execute_values + ON CONFLICT
      (player_id, season, season_type, split) DO UPDATE（幂等）。

用法
----
  python crawl_br_player_onoff.py --resume
  python crawl_br_player_onoff.py --slugs antetgi01 --years 2024 --dry-run
  python crawl_br_player_onoff.py --slugs antetgi01,jamesle01 --years 2018,2024
  python crawl_br_player_onoff.py --rework antetgi01,2024
  python crawl_br_player_onoff.py --limit 5 --dry-run
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 仓库根加入 sys.path（common 包可解析）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from bs4 import BeautifulSoup

from common.br_player_onoff import BRPlayerOnOffCrawlerBase, DB_CONFIG
from common.br_team_page import safe_float, _row_data_stats

# split_id 原始文本 -> 规范化 split 值（BR 用 U+2212 减号 "On − Off"）。
SPLIT_NORMALIZE = {
    "On Court": "On Court",
    "Off Court": "Off Court",
    "On - Off": "On-Off",       # ASCII 连字符（防御）
    "On \u2212 Off": "On-Off",  # U+2212 减号（BR 实际）
    "On-Off": "On-Off",
}

# Team 组 9 列（球员所在队）
TEAM_STATS = (
    "efg_pct", "orb_pct", "drb_pct", "trb_pct",
    "ast_pct", "stl_pct", "blk_pct", "tov_pct", "off_rtg",
)
# Opponent 组 9 列
OPP_STATS = tuple(f"opp_{s}" for s in TEAM_STATS)
# Difference 组 9 列
DIFF_STATS = tuple(f"diff_{s}" for s in TEAM_STATS)


def _normalize_split(raw: Optional[str]) -> Optional[str]:
    """把 split_id 单元格文本规范化为 'On Court'/'Off Court'/'On-Off'。

    BR 用 U+2212 减号（"On − Off"），也防御 ASCII 连字符/多空格变体。
    未知文本原样返回（交由调用方决定是否丢弃）。
    """
    if not raw:
        return None
    s = " ".join(raw.split())  # 折叠多空格
    if s in SPLIT_NORMALIZE:
        return SPLIT_NORMALIZE[s]
    # 兜底：把任意减号类字符统一为 ASCII '-' 再查
    s2 = s.replace("\u2212", "-").replace("\u2013", "-").replace(" ", "")
    if s2 in ("On-Off",):
        return "On-Off"
    if s2 == "OnCourt":
        return "On Court"
    if s2 == "OffCourt":
        return "Off Court"
    return s  # 未知，原样返回


def _parse_mp(split: Optional[str], raw: Optional[str]):
    """解析 mp 单元格 -> (mp, min_pct)。

    * On Court / Off Court 行：raw 是分钟数（如 "2580"）-> (2580.0, None)
    * On-Off 行：raw 是在场占比（如 "65%"）-> (None, 65.0)
    """
    if raw is None or raw == "":
        return None, None
    txt = raw.strip()
    if split == "On-Off" or txt.endswith("%"):
        val = safe_float(txt.rstrip("%").strip())
        return None, val
    return safe_float(txt), None


# ── 纯函数：解析单张 on-off 表 ────────────────────────────────────────────────
def _parse_onoff_table(soup: BeautifulSoup, table_id: str,
                       season_type: str) -> List[Dict]:
    """解析单张 on-off 表（``on-off`` 或 ``on-off-post``）。

    每行由 ``split_id`` 区分（On Court / Off Court / On-Off），透传
    team_id + mp/min_pct + Team/Opponent/Difference 三组各 9 列。
    无有效 split 的行（表头/空行）跳过。
    """
    table = soup.find("table", id=table_id)
    if table is None:
        return []
    out: List[Dict] = []
    body = table.find("tbody") or table
    for row in body.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        vals = _row_data_stats(row)
        if not vals:
            continue
        split = _normalize_split(vals.get("split_id"))
        if split not in ("On Court", "Off Court", "On-Off"):
            continue
        mp, min_pct = _parse_mp(split, vals.get("mp"))
        rec: Dict = {
            "season_type": season_type,
            "split": split,
            "team_id": (vals.get("team_id") or None),
            "mp": mp,
            "min_pct": min_pct,
        }
        for s in TEAM_STATS:
            rec[s] = safe_float(vals.get(s))
        for s in OPP_STATS:
            rec[s] = safe_float(vals.get(s))
        for s in DIFF_STATS:
            rec[s] = safe_float(vals.get(s))
        out.append(rec)
    return out


def parse_player_onoff_html(html: str,
                            slug: Optional[str] = None,
                            year: Optional[int] = None) -> List[Dict]:
    """纯函数：解析 BR 球员 on-off 页 HTML -> 记录列表。

    解析 ``#on-off``(Regular) + 若存在 ``#on-off-post``(Playoffs) 双表。每条记录含
    ``season_type`` / ``split`` / ``team_id`` / ``mp`` / ``min_pct`` + Team/Opponent/
    Difference 三组各 9 列；不含 ``player_id`` / ``season``（由 ``build_rows`` 注入）。

    Args:
        html: BR 球员 on-off 页 HTML 文本。
        slug/year: 仅用于上下文/日志，不参与解析。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict] = []
    out += _parse_onoff_table(soup, "on-off", "Regular")
    if soup.find("table", id="on-off-post") is not None:
        out += _parse_onoff_table(soup, "on-off-post", "Playoffs")
    return out


# ── 具体爬虫 ─────────────────────────────────────────────────────────────────
class PlayerOnOffCrawler(BRPlayerOnOffCrawlerBase):
    """BR 球员 on-off 爬虫。

    实现 3 个钩子：
      * ``parse``     -> 委托纯函数 ``parse_player_onoff_html``
      * ``build_rows`` -> 注入 ``player_id``/``season``/``season_type``/``split``
      * ``upsert``    -> ``self._upsert_rows``（execute_values 单 %s + ON CONFLICT）
    """

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        """委托纯函数 parse_player_onoff_html。

        ``season_type`` 参数不使用——解析器内部探测 ``#on-off``(Regular) 和
        ``#on-off-post``(Playoffs) 双表，每条记录自带 ``season_type``。
        """
        return parse_player_onoff_html(html)

    def build_rows(self, conn, slug: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        """把一条解析记录补全为可落库行（注入 player_id/season/season_type/split）。"""
        row: Dict = {
            "player_id": slug,
            "season": season,
            "season_type": season_type,
            "split": rec.get("split"),
            "team_id": rec.get("team_id"),
            "mp": rec.get("mp"),
            "min_pct": rec.get("min_pct"),
        }
        for s in TEAM_STATS:
            row[s] = rec.get(s)
        for s in OPP_STATS:
            row[s] = rec.get(s)
        for s in DIFF_STATS:
            row[s] = rec.get(s)
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        """批量 upsert 到 player_onoff（ON CONFLICT 4 列键 DO UPDATE）。"""
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)


# ── CLI ─────────────────────────────────────────────────────────────────────
def main() -> None:
    """CLI 入口：支持 --slugs / --years / --limit / --resume / --dry-run / --rework。"""
    p = argparse.ArgumentParser(description="BR 球员 on-off 爬虫")
    p.add_argument("--slugs", type=str, default=None,
                   help="逗号分隔 slug 列表（小批量/定点测试）")
    p.add_argument("--years", type=str, default=None,
                   help="逗号分隔年份列表（赛季结束年，如 2024=2023-24 赛季）")
    p.add_argument("--limit", type=int, default=None,
                   help="最多处理 N 个 (slug,year) 对（小批量验证）")
    p.add_argument("--dry-run", action="store_true",
                   help="只枚举+打印计划，不取浏览器、不写库")
    p.add_argument("--resume", action="store_true",
                   help="跳过已落库 (slug,year)（断点续传）")
    p.add_argument("--rework", type=str, default=None,
                   help="从归档重解析某 (slug,year)（免爬）：--rework antetgi01,2024")
    args = p.parse_args()

    crawler = PlayerOnOffCrawler(dry_run=args.dry_run, resume=args.resume)

    # --rework 模式：从归档 HTML 重解析落库（免爬）
    if args.rework:
        parts = args.rework.split(",")
        if len(parts) != 2:
            print("--rework 格式：slug,year（如 antetgi01,2024）")
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
        total = crawler.run_onoff(
            conn, targets, resume=args.resume, dry_run=args.dry_run)
        print(f"完成：upsert {total} 行（处理 {len(targets)} 对）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
