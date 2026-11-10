#!/usr/bin/env python3
"""
adapters/br_gamelog_adapter.py — v2 的 Basketball-Reference 球员 gamelog 适配器。

设计原则（严格遵守"严禁凭空猜"铁律）：
  - 不重写解析 / 写库逻辑。直接复用旧版已验证函数（单向 import 复用，旧版不被修改）：
      * crawl_br_gamelog.parse_gamelog_html   —— 纯函数：HTML -> 比赛 dict 列表（已验证）
      * crawl_br_gamelog.build_insert         —— 纯函数：构造 (columns, values) 列/值对齐（已验证）
      * crawl_br_gamelog._fetch_html          —— 浏览器通道取渲染页 + 崩溃重建 + 500/CF 判定（已验证）
      * crawl_br_gamelog.canon_team           —— 队名历史/现代缩写归一（已验证，与回填侧一致）
      * crawl_br_gamelog.get_game_id_map      —— (date, team) -> nba_api_id（数字，存 gameid）
      * crawl_br_gamelog.get_game_id_full_map —— (date, team) -> game_id（字母数字全量 id，存 game_id_full）
      * crawl_br_gamelog.load_player_id_bridge—— br_player_id -> nba_player_id（int）
      * crawl_br_gamelog.get_players          —— 目标(缺口)查询：本季 player_per_game 球员列表
      * crawl_br_gamelog.BRServerError        —— BR 源站 500 异常（绕开语义）
      * crawl_br_gamelog._default_bypass_file —— 500 绕开清单默认路径
      * crawl_br_gamelog.save_gamelog_html / load_gamelog_html / has_gamelog_html
                                                  —— 双轨缓存·HTML 轨道（raw 归档，离线重解）
  - 只把"编排"搬进 v2 抽象层：BaseCrawler 的 limiter/缓存/Store。
  - DB 写入严守 §6：经 PGStore.save（参数化、列名白名单、DELETE+INSERT 幂等、key=(gameid, br_player_id)）。
    复用旧 build_insert 的列/值对齐，绝不自造 SQL 字符串。

多源 game_id 对齐约定（保留旧代码语义）：
  - player_gamelog.gameid 存 **数字** nba_api_id（经 get_game_id_map，键 (date, canon_team(team))，
    缺失时回退 opp 队）。game_id_full 存字母数字全量 id（经 get_game_id_full_map，同键）。
  - 跨源(ESPN/nba_api)对齐将以 dim_games 为桥：用 (game_date, home/away abbr, score, tip-off time)
    解析到同一 nba_api_id / game_id，见 espn_adapter / nba_api_adapter 脚手架契约。

运行：
  python -m adapters.br_gamelog_adapter --season 2026 --dry-run
  python -m adapters.br_gamelog_adapter --season 2026 --cache-dir gamelog_cache --only-br-ids ids.txt
"""
import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# 把迁移包根目录与 crawler/ 加入 path，以便复用旧版已验证模块（单向复用，旧版不被修改）。
# 用 lazy import（_legacy()）包裹，避免在本沙箱缺 dotenv 时连模块都 import 不进来；
# 在用户既有 crawler 运行环境（已装 dotenv 等）下正常工作。
ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
CRAWLER_DIR = os.path.join(ROOT, "external_crawler", "crawler")
for _p in (ROOT, CRAWLER_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.base_crawler import BaseCrawler, SessionGone  # noqa: E402  (v2 core, 无 dotenv 依赖)
from core.store import StoreFactory  # noqa: E402

log = logging.getLogger("br_crawler_v2.br_gamelog")

# v2 落库目标（§6 白名单：仅小写字母/数字/下划线）
TABLE = "player_gamelog"
KEY_COLUMNS = ["gameid", "br_player_id"]


def _legacy():
    """惰性导入旧版 crawl_br_gamelog 模块（含其既有 dotenv 依赖）。

    返回模块对象并缓存。所有对旧函数的调用都经此函数，确保"复用而非重写"，
    且不污染本模块的顶层 import（缺 dotenv 环境仍可 import 本适配器做语法/结构检查）。
    """
    mod = getattr(_legacy, "_mod", None)
    if mod is None:
        import crawl_br_gamelog as m  # type: ignore
        _legacy._mod = m
    return _legacy._mod


class BrGamelogAdapter(BaseCrawler):
    """BR 球员 gamelog 爬取适配器（v2 抽象层 + 旧版已验证解析/写库函数）。"""

    def __init__(self, season: int, store=None, cache_dir: str = None,
                 rate_per_min: int = 10, min_interval: float = 6.0,
                 dry_run: bool = False, bypass_file: str = None,
                 only_br_ids: Optional[List[str]] = None, force_fetch: bool = False):
        super().__init__(store=store or StoreFactory.create("pg"),
                         cache_ttl=0, cache_dir=cache_dir,
                         rate_per_min=rate_per_min, min_interval=min_interval)
        self.season = season
        self.cache_dir = cache_dir
        self.dry_run = dry_run
        self.force_fetch = force_fetch
        self.only_br_ids = set(only_br_ids) if only_br_ids else None
        self.bypass_file = bypass_file or _legacy()._default_bypass_file()
        # 500 绕开清单（旧语义：BR 返回 500 的球员 br_id 记入文件，后续跳过不再重撞）
        self.bypass_set = set()
        if os.path.exists(self.bypass_file):
            with open(self.bypass_file) as _bf:
                self.bypass_set = {l.strip() for l in _bf if l.strip()}

        # ---- 载入旧版已验证映射（复用 get_game_id_map / get_game_id_full_map / load_player_id_bridge） ----
        # 这些查询走 v2 PGStore 的连接，保持单一 DB 配置来源。
        conn = self.store._connect()
        leg = _legacy()
        self.game_map = leg.get_game_id_map(conn, season)            # (date, team) -> nba_api_id(数字)
        self.game_id_full_map = leg.get_game_id_full_map(conn, season)  # (date, team) -> game_id(字母数字)
        self.bridge_map = leg.load_player_id_bridge(conn)            # br_player_id -> nba_player_id(int)
        log.info("载入映射: gameid=%d, game_id_full=%d, bridge=%d (season %d)",
                 len(self.game_map), len(self.game_id_full_map), len(self.bridge_map), season)

        # 丢弃计数（防"静默丢弃 + 假完成"）：缺 nba_api_id 无法入库的比赛必须被计数并暴露。
        self._dropped_total = 0
        self._dropped_keys: Dict[Tuple[str, str], int] = {}

    # ---- 基类契约覆盖 ----
    def store_table(self) -> str:
        return TABLE

    def key_columns(self) -> List[str]:
        return KEY_COLUMNS

    # ---- 复用旧版 fetch 语义（浏览器通道 + 崩溃重建 + 500/CF 判定 + raw 归档） ----
    def _url(self, player_id: str) -> str:
        first = player_id[0].lower()
        return (f"https://www.basketball-reference.com/players/{first}/"
                f"{player_id}/gamelog/{self.season}")

    def fetch(self, target: Tuple[str, str]) -> Dict[str, Any]:
        """取原始渲染页（HTML 字符串）。复用旧 _fetch_html（含 driver 崩溃重建）。

        返回 {"status":"ok","html":<str>,"from_cache":<bool>}；
        BRServerError / CFChallengeError 由 run() 捕获处理（不在此抛 SessionGone）。
        """
        player_name, player_id = target
        leg = _legacy()
        # 速率硬上限（v2 limiter：>=min_interval 间隔 + 滚动窗口）
        self.limiter.wait()
        # 双轨·HTML 轨道 cache-first（免重爬，复用旧 has/load + parse_gamelog_html）
        if self.cache_dir and not self.force_fetch and leg.has_gamelog_html(self.season, player_id, self.cache_dir):
            html = leg.load_gamelog_html(self.season, player_id, self.cache_dir)
            if html and "player_game_log_reg" in html:
                return {"status": "ok", "html": html, "from_cache": True}
        # 线上抓取（旧 _fetch_html 内部自动重建崩溃的 driver，BR 500 抛 BRServerError）
        html = leg._fetch_html(self._url(player_id))
        # raw 归档：抓取成功即存原始 HTML（供改解析器后免重爬重解，复用旧 save_gamelog_html）
        if self.cache_dir:
            leg.save_gamelog_html(self.season, player_id, html, self.cache_dir)
        return {"status": "ok", "html": html, "from_cache": False}

    def parse(self, raw: Dict[str, Any], target: Tuple[str, str]) -> List[Dict[str, Any]]:
        """原始 HTML -> 结构化比赛 dict 列表。复用旧 parse_gamelog_html（已验证，纯函数）。"""
        if not isinstance(raw, dict) or raw.get("status") != "ok":
            return []
        return _legacy().parse_gamelog_html(raw["html"])

    def normalize(self, rows: List[Dict[str, Any]], target: Tuple[str, str]) -> List[Dict[str, Any]]:
        """字段对齐/清洗：解析 game_id / game_id_full / nba_player_id，复用旧 build_insert 列/值对齐。

        返回可直接交给 PGStore.save 的行 dict 列表（键 = build_insert 的 29 列，不含 created_at）。
        缺 nba_api_id 映射的比赛计入丢弃统计，绝不静默跳过。
        """
        player_name, player_id = target
        leg = _legacy()
        out: List[Dict[str, Any]] = []
        for g in rows:
            date_str = g.get("date")
            team = g.get("team")
            game_id = self.game_map.get((date_str, leg.canon_team(team)))
            if not game_id:
                game_id = self.game_map.get((date_str, leg.canon_team(g.get("opp", ""))))
            if not game_id:
                # 【禁止静默丢弃】dim_games 该场无 nba_api_id -> 无法入库，计数并暴露。
                self._dropped_total += 1
                k = (date_str, team)
                self._dropped_keys[k] = self._dropped_keys.get(k, 0) + 1
                continue
            game_id = str(game_id)  # player_gamelog.gameid 是 varchar
            game_id_full = self.game_id_full_map.get((date_str, leg.canon_team(team)))
            if not game_id_full:
                game_id_full = self.game_id_full_map.get((date_str, leg.canon_team(g.get("opp", ""))))
            game_id_full = str(game_id_full) if game_id_full else None

            g2 = dict(g)
            g2["game_id"] = game_id
            g2["season"] = self.season
            # 复用旧 build_insert：构造 (columns, values)——保证列/值对齐与旧版完全一致，不重造。
            columns, values = leg.build_insert(
                player_name, player_id, g2, game_id_full,
                nba_player_id=self.bridge_map.get(player_id))
            out.append(dict(zip(columns, values)))
        return out

    # ---- 覆盖 run：缺口遍历 + 500 绕开 + 丢弃汇总 + 幂等写库 ----
    def run(self, targets: List[Tuple[str, str]]) -> Dict[str, int]:
        ok = fail = skip = 0
        fails: List[Tuple[str, str]] = []
        try:
            for i, (player_name, player_id) in enumerate(targets, 1):
                if not player_id:
                    log.info("[%d/%d] %s (None) 跳过(无 player_id)", i, len(targets), player_name)
                    skip += 1
                    continue
                if player_id in self.bypass_set:
                    log.info("[%d/%d] %s (%s) 绕开(已记录 BR 500)", i, len(targets), player_name, player_id)
                    skip += 1
                    continue
                log.info("[%d/%d] %s (%s)…", i, len(targets), player_name, player_id)
                try:
                    raw = self.fetch((player_name, player_id))
                except Exception as e:  # noqa: BLE001
                    # 映射旧异常到 v2 语义
                    from common.browser import CFChallengeError  # lazy（仅异常分支需）
                    leg = _legacy()
                    if isinstance(e, leg.BRServerError):
                        # BR 源站 500：绕开，记录清单，不计入 failed（避免空转重试烧 IP）
                        self._record_bypass(player_id)
                        skip += 1
                        log.warning("BRServerError(500, 绕开不再重撞): %s", e)
                        continue
                    if isinstance(e, CFChallengeError):
                        # 站点级 CF 故障：跳过该球员，不烧重建周期
                        fail += 1
                        fails.append((player_id, "cf_challenge"))
                        log.warning("CFChallengeError(站点级, 跳过): %s", e)
                        continue
                    # 其余异常：视为该球员失败
                    fail += 1
                    fails.append((player_id, type(e).__name__))
                    log.error("fetch 异常(%s): %s", type(e).__name__, e)
                    continue

                games = self.parse(raw, (player_name, player_id))
                if not games:
                    log.info("  0 场 (skip)")
                    skip += 1
                    continue
                rows = self.normalize(games, (player_name, player_id))
                if not rows:
                    # 全部比赛都因缺映射被丢弃
                    log.warning("  %d 场全部丢弃(无 nba_api_id) ⚠", len(games))
                    fail += 1
                    fails.append((player_id, "all_dropped"))
                    continue

                if not self.dry_run:
                    columns = list(rows[0].keys())  # 复用 build_insert 列序（已验证）
                    written = self.store.save(TABLE, columns, KEY_COLUMNS, rows)
                else:
                    written = len(rows)
                ok += 1
                log.info("  %d 场入库 ✓ (from_cache=%s)", written, raw.get("from_cache"))

                # 周期长休（沿用旧速率策略：长间隔进一步降频，防 CF 墙）
                if i < len(targets) and (i % 20 == 0):
                    log.info("  [rate-limit] 长休 30s (已处理 %d 人)", i)
                    import time
                    time.sleep(30)
        finally:
            try:
                self.store.close()
            except Exception:  # noqa: BLE001
                pass

        # ---- 丢弃汇总（必须显式打印，即使为 0） ----
        if self._dropped_total:
            worst = sorted(self._dropped_keys.items(), key=lambda kv: -kv[1])[:15]
            log.warning("丢弃 %d 场 (dim_games 无 nba_api_id 映射); 前 %d 项(共 %d 键):",
                        self._dropped_total, len(worst), len(self._dropped_keys))
            for (d, t), n in worst:
                log.warning("    %s  %s  x%d", d, t, n)
        log.info("[done] 成功 %d 失败 %d 跳过(含绕开) %d 丢弃 %d",
                 ok, fail, skip, self._dropped_total)
        if fails:
            log.info("失败明细: %s", fails[:30])
        return {"ok": ok, "fail": fail, "skip": skip, "dropped": self._dropped_total}

    def _record_bypass(self, player_id: str) -> None:
        """把 BR 500 的球员 br_id 追加进绕开清单（旧语义：后续直接跳过不再重撞）。"""
        if player_id in self.bypass_set:
            return
        try:
            with open(self.bypass_file, "a") as _bf:
                _bf.write(player_id + "\n")
        except OSError:
            pass
        self.bypass_set.add(player_id)


# ═══════════════════════════════════════════════════════════════════════════
# 目标(缺口)查询：复用旧 get_players + only_br_ids 过滤
# ═══════════════════════════════════════════════════════════════════════════
def _get_targets(season: int, limit: int = None, resume: bool = False,
                 only_br_ids: List[str] = None, store=None) -> List[Tuple[str, str]]:
    """复用旧版缺口查询逻辑：从 player_per_game 取本季球员列表（resume=跳过已有）。"""
    st = store or StoreFactory.create("pg")
    conn = st._connect()
    leg = _legacy()
    players = leg.get_players(conn, season, limit, resume and not only_br_ids)
    if only_br_ids:
        wanted = set(only_br_ids)
        players = [p for p in players if p[1] in wanted]
    return [(p[0], p[1]) for p in players]


def main():
    ap = argparse.ArgumentParser(description="BR 球员 gamelog 爬取 (v2 适配器)")
    ap.add_argument("--season", type=int, required=True, help="赛季结束年 (如 2026 = 2025-26 赛季)")
    ap.add_argument("--limit", type=int, default=None, help="最多爬几人 (测试用)")
    ap.add_argument("--resume", action="store_true", help="跳过已有数据的球员(断点续传)")
    ap.add_argument("--only-br-ids", type=str, default=None,
                    help="只爬该文件列出的 br_player_id(每行一个)，智能补齐缺口")
    ap.add_argument("--bypass-500-file", type=str, default=None,
                    help="500 绕开清单文件：BR 返回 500 的球员 br_id 记入并后续跳过")
    ap.add_argument("--cache-dir", type=str, default=None,
                    help="本季缓存目录(双轨 HTML+JSON)，抓取落盘供返工")
    ap.add_argument("--force-fetch", action="store_true",
                    help="跳过 HTML 轨道 cache-first，强制重新抓取")
    ap.add_argument("--dry-run", action="store_true", help="只测试不写库")
    ap.add_argument("--rate-per-min", type=int, default=10)
    ap.add_argument("--min-interval", type=float, default=6.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    only_ids = None
    if args.only_br_ids:
        try:
            with open(args.only_br_ids) as f:
                only_ids = [l.strip() for l in f if l.strip()]
        except OSError as e:
            log.error("无法读取 --only-br-ids 文件 %s: %s", args.only_br_ids, e)
            sys.exit(2)

    targets = _get_targets(args.season, limit=args.limit, resume=args.resume,
                           only_br_ids=only_ids)
    log.info("待处理球员(缺口): %d (season=%d, dry_run=%s)", len(targets), args.season, args.dry_run)
    if not targets:
        return
    adapter = BrGamelogAdapter(
        season=args.season, cache_dir=args.cache_dir, dry_run=args.dry_run,
        rate_per_min=args.rate_per_min, min_interval=args.min_interval,
        bypass_file=args.bypass_500_file, only_br_ids=only_ids, force_fetch=args.force_fetch)
    adapter.run(targets)


if __name__ == "__main__":
    main()
