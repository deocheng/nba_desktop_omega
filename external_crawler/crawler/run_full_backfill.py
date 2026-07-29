#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_full_backfill.py — 球队/球员 extras 全量回填编排器。

执行顺序（遵循用户指令「先球队再球员，倒序，全量」）：
  1) TeamPageExtrasCrawler  (team_roster / team_per_36 / team_coaches / team_leaderboards)
  2) LineupsCrawler        (team_lineups, 净差值表, 1997+)
  3) RefereesCrawler       (team_referees, 1997+)
  4) PlayerPageExtrasCrawler (game_highs/series/similarity/allstar/adj_shooting/overview)

关键约定：
- 倒序：每个爬虫按赛季结束年 2026 → 1947（lineups/referees 内部跳过 <1997）逐季处理；
  球员按最近活跃赛季倒序。
- 全量：resume=True 幂等（已落库队季/球员自动跳过），可随时中断重跑续传。
- 速率：复用基类 RATE_LIMIT_BASE_S=6.0+JITTER=2.0（~7s/请求 ≈ 0.14 req/s），
  远低于用户上限「≤9 req/s」，且单一 Chrome(9223) 串行、不并发抢浏览器。
- CF 守护：单季/批次若产生大量新失败（疑似 Cloudflare 拦截），自动暂停 10min 等待用户在
  可见 Chrome 窗口手动通过验证，然后重试同一季/批次；最多重试若干次后跳过（留待 resume 补）。
"""
from __future__ import annotations

import os
import sys
import time
import logging
from typing import Callable, List, Optional

# ── 路径：脚本位于 external_crawler/crawler，common 在项目根 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
for p in (PROJECT_ROOT, SCRIPT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2  # noqa: E402
from common.br_team_page import DB_CONFIG  # noqa: E402

from crawl_br_team_page_extras import TeamPageExtrasCrawler   # noqa: E402
from crawl_br_team_lineups import LineupsCrawler             # noqa: E402
from crawl_br_team_referees import RefereesCrawler           # noqa: E402
from crawl_br_player_page_extras import PlayerPageExtrasCrawler  # noqa: E402

# ── 配置 ──
MAX_SEASON = 2026          # 上限（含）
MIN_SEASON = 1947          # team_page_extras 下限（含）；lineups/referees 内部 <1997 自动跳过
CF_STALL_THRESHOLD = 8     # 单季/批次新增失败数 ≥ 此值 → 疑似 CF 拦截
CF_PAUSE_S = 600           # 暂停等待用户清 CF 的秒数
CF_MAX_RETRIES = 8         # 同一季/批次最多重试次数（≈ 80min 窗）

LOG_PATH = "/Volumes/12T/NBA/crawl_full_backfill.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("full_backfill")


# ── 失败计数快照（用于 CF 守护）──
def _fail_count(task_type: str) -> int:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM crawl_failures WHERE task_type=%s AND resolved=False",
            (task_type,),
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


def _run_with_cf_guard(label: str, task_type: str, fn: Callable[[], None]) -> None:
    """执行 fn（单季或球员批次）；若疑似 CF 拦截则暂停重试。"""
    for attempt in range(CF_MAX_RETRIES + 1):
        before = _fail_count(task_type)
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - 顶层兜底，绝不中断整轮
            log.exception("⚠️ %s 执行异常（已兜底，继续）: %s", label, exc)
        new_fail = _fail_count(task_type) - before
        if new_fail >= CF_STALL_THRESHOLD:
            if attempt < CF_MAX_RETRIES:
                log.warning(
                    "🛑 %s 疑似 Cloudflare 拦截（新增 %d 失败），暂停 %ds 等用户在 Chrome 清挑战，"
                    "随后重试(%d/%d)",
                    label, new_fail, CF_PAUSE_S, attempt + 1, CF_MAX_RETRIES,
                )
                time.sleep(CF_PAUSE_S)
                continue
            else:
                log.error("❌ %s CF 暂停后仍未恢复，跳过（可后续 resume 重跑补齐）", label)
        return


def _player_slugs_desc(conn) -> List[str]:
    """球员 slug 按最近活跃赛季倒序（无 shooting 记录的置末）。

    取数口径对齐 PlayerPageExtrasCrawler.enumerate_players：
    player_gamelog.br_player_id（slug）UNION dim_players.player_id（slug）。
    最近赛季从 player_shooting（远小于 gamelog）取，避免对千万行 gamelog
    做 NOT IN / GROUP BY 造成长时间阻塞。
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT br_player_id FROM player_gamelog "
        "WHERE br_player_id IS NOT NULL"
    )
    from_gamelog = [r[0] for r in cur.fetchall()]
    cur.execute(
        "SELECT player_id FROM dim_players WHERE player_id IS NOT NULL"
    )
    from_dim = [r[0] for r in cur.fetchall()]
    # 去重保序
    seen, slugs = set(), []
    for s in from_gamelog + from_dim:
        if s and s not in seen:
            seen.add(s)
            slugs.append(s)
    # 最近赛季（player_shooting 较小，便宜）
    recency: dict = {}
    try:
        cur.execute(
            "SELECT player_id, MAX(season) FROM player_shooting GROUP BY player_id"
        )
        recency = {r[0]: r[1] for r in cur.fetchall()}
    except Exception as _e:  # noqa: BLE001
        log.warning("player_shooting 取最近赛季失败（降级置 0）: %s", _e)
    cur.close()
    return sorted(slugs, key=lambda s: (-(recency.get(s) or 0), s or ""))


def main() -> None:
    log.info("=" * 70)
    log.info("全量回填启动 | 顺序: 球队(t-page→lineups→referees) → 球员 | 倒序 | resume 幂等")
    log.info("速率: 基类 ~7s/请求(远低于 ≤9 req/s) | 单 Chrome 9223 串行")
    log.info("请确认 Chrome(9223) 已通过 Cloudflare 验证；过期时脚本会自动暂停等您手动清挑战")
    log.info("=" * 70)

    # 共享 DB 连接（team_page_extras / player 需要；lineups/referees 内部自建）
    conn = psycopg2.connect(**DB_CONFIG)

    # ───────────────────────── 1) team_page_extras ─────────────────────────
    log.info("\n########## [1/4] TeamPageExtras（roster/per36/coaches/leaderboards）##########")
    tpe = TeamPageExtrasCrawler()
    for s in range(MAX_SEASON, MIN_SEASON - 1, -1):
        _run_with_cf_guard(
            f"team_page_extras/{s}", tpe.TASK_TYPE,
            lambda s=s: tpe.run_teams(conn, season=s, resume=True),
        )

    # ───────────────────────── 2) lineups ─────────────────────────
    log.info("\n########## [2/4] Lineups（team_lineups 净差值，1997+）##########")
    lu = LineupsCrawler()
    for s in range(MAX_SEASON, MIN_SEASON - 1, -1):
        _run_with_cf_guard(
            f"lineups/{s}", lu.TASK_TYPE,
            lambda s=s: lu.run_pipeline(s, resume=True),
        )

    # ───────────────────────── 3) referees ─────────────────────────
    log.info("\n########## [3/4] Referees（team_referees 赛季汇总，1997+）##########")
    rf = RefereesCrawler()
    for s in range(MAX_SEASON, MIN_SEASON - 1, -1):
        _run_with_cf_guard(
            f"referees/{s}", rf.TASK_TYPE,
            lambda s=s: rf.run_pipeline(s, resume=True),
        )

    # ───────────────────────── 4) players ─────────────────────────
    log.info("\n########## [4/4] PlayerPageExtras（6 类，按最近赛季倒序）##########")
    pc = PlayerPageExtrasCrawler()
    slugs = _player_slugs_desc(conn)
    log.info("球员总数: %d，按最近活跃赛季倒序", len(slugs))
    BATCH = 150
    for i in range(0, len(slugs), BATCH):
        batch = slugs[i:i + BATCH]
        _run_with_cf_guard(
            f"players/{i}-{i+len(batch)}", pc.TASK_TYPE,
            lambda batch=batch: pc.run_players(conn, slugs=batch, resume=True),
        )

    conn.close()
    log.info("=" * 70)
    log.info("🎉 全量回填编排完成（含 CF 跳过项可随时 resume 重跑补齐）")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
