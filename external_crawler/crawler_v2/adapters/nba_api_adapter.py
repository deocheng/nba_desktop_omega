#!/usr/bin/env python3
"""
adapters/nba_api_adapter.py — nba_api 球员 gamelog 适配器【接口脚手架 / SCAFFOLD】。

⚠️ 这是为 BBRef / ESPN / nba_api 多源对齐预留的**统一适配器契约脚手架**，
   不是可运行实现。fetch/parse/normalize 全部抛 NotImplementedError，
   **不编造任何 nba_api 解析逻辑**（严守"严禁凭空猜"铁律）。

统一适配器契约（三源 BBRef/ESPN/nba_api 必须共同遵守）：
  1. 接口同 core.base_crawler.BaseCrawler：
       fetch(target)      -> 取原始页/JSON（抛 SessionGone 表示会话失效）
       parse(raw, target) -> 原始 -> 结构化行（复用各自已验证 parse 函数）
       normalize(rows, target) -> 字段对齐/清洗（映射到统一落库 schema）
  2. 统一落库 schema（与 br_gamelog_adapter 对齐）：
       最终写 player_gamelog，列顺序/口径严格复用旧
       crawl_br_gamelog.build_insert 的 29 列（fg, fga, fg_pct, ..., minutes），
       并额外带 source='NBA_API' 标识来源（ESPN 源用 'ESPN'）。
  3. 跨源 game_id 对齐约定（home/away + score + tip-off time）：
       nba_api 自身即持有权威 game_id / nba_api_id，可直接经 dim_games 校验对齐：
           (game_date, home_team_abbr, away_team_abbr, home_score, away_score, tipoff_time)
             -> dim_games.nba_api_id  (写 player_gamelog.gameid，数字)
             -> dim_games.game_id     (写 player_gamelog.game_id_full，字母数字)
       对齐函数**复用既有跨源 bridge 约定**（如 common 下的 team/date 归一等），
       不在此重写；实现时从对应旧模块 import 真实对齐函数。
  4. 写库严守 §6：经 PGStore.save(table, columns, key_columns, rows)，
       幂等键 key=(gameid, br_player_id)（nba_api 源用各自 player slug 作为身份键），
       表名/列名走白名单，参数化写。

实现 TODO（待接入真实 nba_api 解析，复用既有跨源 bridge）：
   - fetch:   接入 nba_api 球员 game log 端点（或既有 nba_api 抓取模块）。
   - parse:   复用 nba_api 已验证 parse 函数（不得臆造）。
   - normalize: 映射到 29 列统一 schema + source='NBA_API' + 经 dim_games 对齐 gameid。
"""
import argparse
import logging
from typing import Any, Dict, List

from core.base_crawler import BaseCrawler, SessionGone
from core.store import StoreFactory

log = logging.getLogger("br_crawler_v2.nba_api")


class NbaApiAdapter(BaseCrawler):
    """nba_api 球员 gamelog 适配器（脚手架）。接口契约同 BaseCrawler，解析待接入。"""

    def __init__(self, season: int = None, store=None, cache_dir: str = None,
                 rate_per_min: int = 15, min_interval: float = 4.5, dry_run: bool = False):
        super().__init__(store=store or StoreFactory.create("pg"), cache_ttl=0,
                         cache_dir=cache_dir, rate_per_min=rate_per_min, min_interval=min_interval)
        self.season = season
        self.dry_run = dry_run

    def store_table(self) -> str:
        return "player_gamelog"

    def key_columns(self) -> List[str]:
        # nba_api 源以各自 player slug 作为身份键（实现时替换为 nba_api 玩家标识列）
        return ["gameid", "br_player_id"]

    def fetch(self, target: Any) -> Any:
        raise NotImplementedError(
            "SCAFFOLD: 待接入 nba_api 真实抓取（复用既有 nba_api 通道/跨源 bridge 约定），不编造解析")

    def parse(self, raw: Any, target: Any) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "SCAFFOLD: 待接入 nba_api 真实解析，复用既有跨源 bridge 约定")

    def normalize(self, rows: List[Dict[str, Any]], target: Any) -> List[Dict[str, Any]]:
        # 约定：映射为 29 列统一 schema（复用 crawl_br_gamelog.build_insert 列序）+ source='NBA_API'
        #       + 经 dim_games (game_date, home/away abbr, score, tipoff_time) 对齐 gameid。
        raise NotImplementedError(
            "SCAFFOLD: 待接入 nba_api 字段对齐，复用既有跨源 game_id 桥接约定")

    def run(self, targets: List[Any]) -> Dict[str, int]:
        raise NotImplementedError("SCAFFOLD: NbaApiAdapter 尚未实现，仅预留统一适配器契约")


def main():
    ap = argparse.ArgumentParser(description="nba_api 球员 gamelog 适配器 (SCAFFOLD)")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache-dir", type=str, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.error("NbaApiAdapter 为脚手架，尚未实现：fetch/parse/normalize 均抛 NotImplementedError")


if __name__ == "__main__":
    main()
