#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest_nba_api_v2.py — NBA API 入库 v2（修复 2026-08-16 代码审查 P0-④）

相对 ingest_nba_api.py（原版保留不动）的修复：
  [P0-④] 原版 process_game 调 4 个 upsert（game_metadata / player_stats /
         starting_lineup×2 / games 表更新），每个函数**各自 conn.commit()**。
         第 3 个失败时前两个已提交 → 比赛处于半写入状态（元数据有、
         球队统计无），run_pipeline 的 rollback 无法撤销。
         v2 用连接代理把四个函数的内部 commit 变 no-op，由 process_game
         末尾统一 commit / 失败统一 rollback —— 单场比赛原子落库。

实现方式（不动原版一行代码）：
  * AtomicConn 代理连接：commit() 为 no-op，其余属性/方法透传真实连接。
  * v2 的 process_game 全文复用原版解析逻辑，仅「Upsert 段」改为
    代理 + 统一事务边界。
  * `base.process_game = process_game` 打补丁后，原版 run_pipeline /
    CLI 全部照常工作（run_pipeline 按模块全局名调用 process_game）。

用法（与原版 CLI 完全一致）：
    .venv/bin/python external_crawler/crawler/ingest_nba_api_v2.py --auto
    .venv/bin/python external_crawler/crawler/ingest_nba_api_v2.py --season 2025 --resume
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import ingest_nba_api as base
from ingest_nba_api import logger  # 复用原版 logger，日志格式一致


class AtomicConn:
    """连接代理：commit() 变 no-op，其余全部透传真实连接。

    用途：包住原版 4 个 upsert 函数，屏蔽它们各自的内部 commit，
    使单场比赛的 4 次写入共享一个事务（由调用方统一 commit/rollback）。
    """

    def __init__(self, real_conn):
        self._real = real_conn

    def commit(self):  # no-op —— 事务边界由 v2 的 process_game 统一控制
        pass

    def __getattr__(self, name):
        return getattr(self._real, name)


def process_game(conn, gid_8: str, api_season: str, dry_run: bool = False) -> bool:
    """v2 单场比赛处理：解析逻辑与原版逐行一致；Upsert 段原子化。

    Returns:
        True if data was fetched and stored, False otherwise
    """
    gid_10 = gid_8.zfill(10)

    # Fetch
    data = base.fetch_gamedetail(gid_10, api_season)
    if not data:
        return False

    g = data.get("g", {})
    st = g.get("st")

    if st != 3:
        logger.debug(f"  Skip {gid_10}: status={st} (not final)")
        return False

    vls = g.get("vls", {})
    hls = g.get("hls", {})
    pstsg_v = vls.get("pstsg", [])
    pstsg_h = hls.get("pstsg", [])

    if not pstsg_v and not pstsg_h:
        logger.debug(f"  Skip {gid_10}: no player stats")
        return False

    # Parse（全部复用原版函数）
    meta = base.parse_game_metadata(g, api_season)
    game_date = g.get("gdte")
    season_end = int(api_season) + 1

    away_players = base.parse_player_stats(
        pstsg_v, gid_10, str(vls.get("tid", "")), vls.get("ta", ""), is_home=False
    )
    home_players = base.parse_player_stats(
        pstsg_h, gid_10, str(hls.get("tid", "")), hls.get("ta", ""), is_home=True
    )
    all_players = away_players + home_players

    away_lineup = base.parse_starting_lineup(pstsg_v, gid_10, vls.get("ta", ""), game_date, season_end)
    home_lineup = base.parse_starting_lineup(pstsg_h, gid_10, hls.get("ta", ""), game_date, season_end)

    away_team_stats = base.parse_team_stats(vls.get("tstsg", {}), is_home=False)
    home_team_stats = base.parse_team_stats(hls.get("tstsg", {}), is_home=True)

    if dry_run:
        logger.info(f"  [DRY RUN] {gid_10}: {vls.get('ta')}@{hls.get('ta')} "
                    f"{vls.get('s')}-{hls.get('s')} | {len(all_players)} players | "
                    f"arena={meta['arena_name']}")
        return True

    # ── v2 原子 Upsert：4 项写库共享一个事务（P0-④ 根修）──
    # 代理屏蔽各 upsert 内部的 conn.commit()；任一失败 → 整体回滚，
    # 杜绝「元数据已提交、球队统计缺失」的半写入状态。
    prox = AtomicConn(conn)
    try:
        base.upsert_game_metadata(prox, meta)
        base.upsert_player_stats(prox, all_players)
        if away_lineup:
            base.upsert_starting_lineup(prox, away_lineup)
        if home_lineup:
            base.upsert_starting_lineup(prox, home_lineup)
        base.update_games_table(prox, gid_10, home_team_stats, away_team_stats, meta)
        conn.commit()
    except Exception:
        conn.rollback()
        logger.warning(f"  {gid_10}: 本场写入失败已整体回滚（原子事务）")
        raise

    return True


# 打补丁：原版 run_pipeline 内按模块全局名调用 process_game，
# 替换后 run_pipeline 自动走 v2 原子版。
base.process_game = process_game


if __name__ == "__main__":
    # CLI 与原版完全一致（原版 CLI 写在 __main__ 内无法复用，此处照抄）
    parser = argparse.ArgumentParser(description="NBA data.nba.com → PostgreSQL ingester (v2 atomic)")
    parser.add_argument("--season", type=int, default=0,
                        help="DB season end year (e.g., 2025 = 2024-25 season)")
    parser.add_argument("--limit", type=int, default=3000,
                        help="Max games to process (default: 3000/all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch only, don't write to DB")
    parser.add_argument("--batch", type=int, default=50,
                        help="Batch commit size (default: 50)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip games already in game_metadata (断点续传)")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-detect next incomplete season and crawl")

    args = parser.parse_args()

    if args.auto:
        base.run_pipeline(season_end=0, limit=500, dry_run=args.dry_run,
                          batch_commit=args.batch, resume=True, auto=True)
    elif args.resume:
        base.run_pipeline(season_end=args.season,
                          limit=args.limit if args.limit != 3000 else 500,
                          dry_run=args.dry_run, batch_commit=args.batch,
                          resume=True, auto=False)
    else:
        base.run_pipeline(season_end=args.season,
                          limit=args.limit if args.limit != 3000 else None,
                          dry_run=args.dry_run, batch_commit=args.batch,
                          resume=False, auto=False)
