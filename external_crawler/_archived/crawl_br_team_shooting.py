"""crawl_br_team_shooting.py — ⑤ Team Shooting (P0) 全历史回填。

⚠️ 已归档（2026-10-22）—— 解析目标表不存在，实跑必然 0 行，禁止直接运行。

本脚本找的是 BR 队页的队级出手区域分布表 `team_shooting` / `opponent_shooting`。
实测（2026-10-22）该表 id 在 BR 队页 2015–2026 全部赛季中，raw HTML 与全部 HTML
注释节点内均**不存在**；`/teams/{slug}/{year}_shooting.html` 与
`/teams/{slug}/{year}/shooting/` 均 404。BR 队页**从未有过**这个表 id。

注意：队级距离数据并非被下线，而是换了形状 —— 它在**球员级 `shooting` 表**里，
以**距离桶列**（%FGA / FG% by Distance: 2P, 0-3, 3-10, 10-16, 16-3P, 3P）
加 **tfoot "Team Totals" 行**存在。`orchestrator_tasks.py:266` 早在 2026-08-05
即已记录此事实。
但该形状只给**百分比**，不给分桶的原始 fg/fga/mp，而 `team_shooting` 表结构要求
每 zone 含 fg/fga/mp → 语义不等价，不能简单改 URL 或改表 id 复活。
复活路径（降级 schema / 换 NBA 官方 API / 维持归档）见同目录 README.md。

`team_shooting` 表从未建立 → 本脚本历史上未落库任何数据，归档无数据损失。
现役爬虫清单见 crawler_console/registry.py。

─── 以下为原脚本说明（保留供追溯，其中数据源描述已过时）─────────────────────
数据源: 主队页 https://www.basketball-reference.com/teams/{ABBR}/{YEAR}.html
        （#all_shooting 区块；独立的 /shooting/ 子页已于 2026-07-27 实测 404，故废弃）
  * 主页面 ``team_shooting``    → vs_type='self'（本队出手分布）
  * 主页面 ``opponent_shooting`` → vs_type='opp'（对对手出手分布）
  * 季后赛 ``team_shooting_post`` / ``opponent_shooting_post``（同页 #all_shooting）
落库: team_shooting（每 team×season×season_type×vs_type×zone 一行）

BR 该页标准列集全覆盖：mp/g/fg/fga/fg_pct/fg2/fga2/fg2_pct/fg3/fga3/fg3_pct/
pct_of_fga/avg_shot_dist（其中 fg2_pct/fg3_pct 为 INFERRED 补全，详见 DDL）。
mp 为真实 BR 页的「该 zone 总分钟」列；原冗余 INFERRED 的 gp 已从 DDL/解析移除。
仅保留已知 zone / 距离桶标签行，跳过 BR 的 "Team" 汇总行（避免污染）。

复用 common/br_team_page.BRTeamPageCrawler（CDP/缓存MERGE/枚举/限速/失败登记/桥接）。

用法:
  python crawl_br_team_shooting.py --season 2026 --resume --cache-dir br_shooting_cache
  python crawl_br_team_shooting.py --season 2026 --dry-run
  python crawl_br_team_shooting.py --rework 2026 --cache-dir br_shooting_cache
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

# BR team_shooting / opponent_shooting 表已知 zone / 距离桶标签（受控词表）。
# 仅这些标签的行被保留；其余（如 "Team" 汇总行、空行）跳过。
SHOOTING_ZONES = {
    "Restricted Area", "In The Paint (Non-RA)", "Mid-Range",
    "Left Corner 3", "Right Corner 3", "Above the Break 3",
}
DISTANCE_LABELS = {
    "0-3 Feet", "3-10 Feet", "10-16 Feet", "16-3P Feet", "3-Point Range",
}


def _parse_shooting_table(table, vs_type: str) -> List[Dict]:
    """解析单张出手分布表 → 记录列表（仅保留已知 zone / 距离桶行）。"""
    out: List[Dict] = []
    for row in table.find_all("tr"):
        if "thead" in row.get("class", []):
            continue
        vals = _row_data_stats(row)
        if not vals:
            continue
        # 标签列是 data-stat="zone"（部分旧页可能是首列 team 单元格）。
        label = (vals.get("zone") or vals.get("team") or "").strip()
        if not label:
            continue
        # 跳过汇总/分组行（"Team" / "Total" 等），仅留具体 zone / 距离桶。
        if label in ("Team", "Total"):
            continue
        if label not in SHOOTING_ZONES and label not in DISTANCE_LABELS:
            continue
        out.append({
            "vs_type": vs_type,
            "zone": label,
            "mp": safe_int(vals.get("mp")),                 # BR 真实页 mp 列
            "g": safe_int(vals.get("g")),                   # BR G（场次计数）
            "fg": safe_int(vals.get("fg")),
            "fga": safe_int(vals.get("fga")),
            "fg_percent": safe_float(vals.get("fg_pct")),
            "fg2": safe_int(vals.get("fg2")),
            "fga2": safe_int(vals.get("fga2")),
            "fg2_pct": safe_float(vals.get("fg2_pct")),
            "fg3": safe_int(vals.get("fg3")),
            "fga3": safe_int(vals.get("fga3")),
            "fg3_pct": safe_float(vals.get("fg3_pct")),
            "pct_of_fga": safe_float(vals.get("pct_of_fga")),
            "avg_shot_dist": safe_float(vals.get("avg_shot_dist")),
        })
    return out


def parse_team_shooting_html(html: str, season_type: str = "Regular",
                              team_abbr: Optional[str] = None) -> List[Dict]:
    """解析 BR Team Shooting 子页 → 记录列表（纯函数，无 DB/网络依赖）。

    每条记录含 ``vs_type`` / ``zone`` 与全部数值列；不含 team/season 维度
    （由 ``build_rows`` 注入）。同时解析本队表与对手表。

    返回示例:
        [{'vs_type':'self','zone':'Restricted Area','fg':350,'fga':520,...}, ...]

    表 id 鲁棒探测：球队 zone 分布（Restricted Area / Mid-Range /
    Corner 3 / Above the Break 3 等）位于主队页 ``#all_shooting`` 区块，
    表 id 为 ``team_shooting``（本队）/ ``opponent_shooting``（对手），
    季后赛 ``team_shooting_post`` / ``opponent_shooting_post``。
    优先匹配上述 team/opp zone 表；仅当缺失时回退到同区块的球员级
    ``shooting`` / ``shooting_post``（其行标签非 zone，不会被
    SHOOTING_ZONES/DISTANCE_LABELS 命中 → 返回空，安全无污染）。
    命中第一个即用，杜绝「表 id 猜错 → 全季 0 行」的静默丢数据。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    # 候选表 id（按经验覆盖 BR 各命名变体；命中第一个即用）。
    if season_type == "Playoffs":
        self_ids = ["team_shooting_post", "shooting_post"]
        opp_ids = ["opponent_shooting_post"]
    else:
        self_ids = ["team_shooting", "shooting"]
        opp_ids = ["opponent_shooting"]
    out: List[Dict] = []
    for tid in self_ids:
        t = soup.find("table", id=tid)
        if t is not None:
            out += _parse_shooting_table(t, "self")
            break
    for tid in opp_ids:
        t = soup.find("table", id=tid)
        if t is not None:
            out += _parse_shooting_table(t, "opp")
            break
    return out


class TeamShootingCrawler(BRTeamPageCrawler):
    """⑤ Team Shooting（zone 分布）爬虫。"""

    DOMAIN = "shooting"
    TASK_TYPE = "br_team_shooting"
    TABLE = "team_shooting"
    PAGE = "shooting"          # 注意：build_url 已重写为主队页 .html（/shooting/ 子页实测 404）
    TABLE_ID = "team_shooting"
    CONFLICT_COLS = ("team_abbr", "season", "season_type", "vs_type", "zone")
    # 子页同时含 RS(shooting) 与 PO(shooting_post) 两张表，一次抓取两者。
    SEASON_TYPES = ("Regular", "Playoffs")
    MIN_SEASON = 1997         # BR shot-location 数据约 1996-97 起
    FULL_CRAWL_START = 1997    # 全量回填从 1997 起

    # ── URL 重写：team zone 分布位于【主队页】.html 的 #all_shooting
    # 区块（表 team_shooting / opponent_shooting；季后赛 _post 变体），
    # 与独立的 /shooting/ 子页无关（该子页 2026-07-27 实测 404）。
    # Regular 与 Playoffs 共用同一份主队页 HTML，靠基类 _html_cache
    # 按 URL 去重，不会重复抓 BR。
    def build_url(self, slug: str, season: int, page: str,
                  season_type: str = "Regular") -> str:
        return f"https://www.basketball-reference.com/teams/{slug}/{season}.html"

    def parse(self, html: str, season_type: str = "Regular",
              team_abbr: Optional[str] = None) -> List[Dict]:
        return parse_team_shooting_html(html, season_type, team_abbr)

    def build_rows(self, conn, team_abbr: str, season: int, season_type: str,
                   rec: Dict) -> Dict:
        row = dict(rec)
        row["team_abbr"] = team_abbr
        row["season"] = season
        row["season_type"] = canon_season_type(season_type)
        return row

    def upsert(self, conn, rows: List[Dict]) -> int:
        return self._upsert_rows(conn, self.TABLE, rows, self.CONFLICT_COLS)

    def _is_expected_empty(self, slug: str, season: int,
                             season_type: str) -> bool:
        # 未进季后赛 / 该队子页无 PO 出手分布表 → 正常无数据，
        # 不当作抓取失败登记（避免污染 crawl_failures）。
        return season_type == "Playoffs"


if __name__ == "__main__":
    dispatch_cli(TeamShootingCrawler, "BR Team Shooting 爬虫 (⑤ P0)")
