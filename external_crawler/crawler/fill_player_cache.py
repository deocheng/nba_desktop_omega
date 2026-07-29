"""补齐主球员页缓存（headless, 幂等）。

对 dim_players 中**尚未缓存**的 player_id，用无头 Playwright(get_driver) 抓
主球员页并落盘到 raw_archive/br_players/{首}/{id}.html。

不解析 gamelog（已在库 169 万行）、不抽 nickname/bio_ext（留给
extract_from_cache.py 离线榨取）。纯粹把"线上页面原文"铺满本地，符合
nba-br-crawler §0a「本地留档优先 / 榨干字段前先存原始页」。

与之前 gamelog 爬虫里内嵌的 cache-first 逻辑一致，但**独立成脚本、跳过
冗余的 gamelog 重爬**，专门干"铺缓存"这一件事，效率更高。

用法:
  python fill_player_cache.py               # 补齐全部未缓存(约 4924 页)
  python fill_player_cache.py --limit 20   # 试跑
  python fill_player_cache.py --season 2023 # 只补某季关联球员(可选)
"""
import argparse
import logging
import random
import sys
import time
from pathlib import Path

import psycopg2

# 项目根（本文件向上两级）加入 sys.path，使 import common.* / backend.* 可解析
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.player_page_cache import (  # noqa: E402
    is_cached,
    save_html,
    player_page_url,
)
from backend.core import config  # noqa: E402 —— fail-safe DSN（不回退弱口令 'postgres'）

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("fill_player_cache")

# ── 防撞机制（CF 波动不可靠，撞墙后严禁无限重试空转）──
# 设计：连续撞墙达上限 → 判定全局封禁 → 进入冷却（断掉撞击）→
#       冷却结束自动重置计数、续跑剩余，无需手动重开（自恢复）。
CF_BREACH_LIMIT = 5      # 连续撞墙达此次数 → 触发熔断冷却
CF_BACKOFF_SEC = 30       # 单次撞墙后退避秒数（降低 CF 再次挑战概率）
CF_COOLDOWN_SEC = 600     # 熔断后冷却时长（默认 10 分钟，断掉撞击等待 CF 宽松）
CF_MAX_COOLDOWNS = 0      # 最大冷却次数（0=无限自恢复，持续续跑直到跑完）


def _load_player_ids(conn, season: int | None) -> list:
    """从 dim_players 取所有非空 player_id（可选按赛季关联过滤）。"""
    cur = conn.cursor()
    if season:
        cur.execute(
            """
            SELECT DISTINCT p.player_id
            FROM player_gamelog g
            JOIN dim_players p ON p.player = g.player
            WHERE g.season = %s AND p.player_id IS NOT NULL
            """,
            (season,),
        )
    else:
        cur.execute(
            "SELECT player_id FROM dim_players WHERE player_id IS NOT NULL"
        )
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    return rows


def main(limit: int | None = None, season: int | None = None,
          cf_breach_limit: int = CF_BREACH_LIMIT,
          cf_backoff: int = CF_BACKOFF_SEC,
          cf_cooldown: int = CF_COOLDOWN_SEC,
          cf_max_cooldowns: int = CF_MAX_COOLDOWNS) -> None:
    conn = psycopg2.connect(config.db_dsn())
    rows = _load_player_ids(conn, season)
    conn.close()

    # 幂等：只处理未缓存的
    todo = [pid for pid in rows if pid and not is_cached(pid)]
    logger.info("dim_players player_id=%d，未缓存=%d", len(rows), len(todo))
    if limit:
        todo = todo[:limit]

    ok = fail = 0
    from common.browser import get_driver, CFChallengeError  # noqa: E402 —— 懒加载
    from common.cf_breaker import CFBreaker  # noqa: E402
    br = CFBreaker(cf_breach_limit, cf_backoff, cf_cooldown, cf_max_cooldowns)
    cf_breached = False   # 是否因冷却次数达上限而放弃

    drv = None
    for i, pid in enumerate(todo, 1):
        url = player_page_url(pid)
        try:
            if drv is None:
                drv = get_driver()  # 进程级单例, 首个球员时构建一次
            drv.get(url)
            html = drv.page_source
            if html and "Just a moment" not in html and "Checking your browser" not in html:
                if save_html(pid, html):
                    ok += 1
                    br.on_success()  # 成功 → 重置连续撞墙计数
                else:
                    fail += 1
                    logger.warning("[%d/%d] %s 落盘失败", i, len(todo), pid)
            else:
                # 命中 CF 挑战页：不落盘(避免污染缓存), 计入熔断器
                decision = br.on_breach()  # 内含退避/冷却 sleep
                fail += 1
                logger.warning("[%d/%d] %s CF 挑战页", i, len(todo), pid)
                if decision == "giveup":
                    cf_breached = True
                    break
        except CFChallengeError as exc:
            # browser 层熔断器已处理冷却/自恢复；这里仅记录并计入
            decision = br.on_breach()
            fail += 1
            logger.warning(
                "[%d/%d] %s CF 未清除: %s",
                i, len(todo), pid, exc,
            )
            if decision == "giveup":
                cf_breached = True
                break
        except Exception as exc:  # noqa: BLE001
            fail += 1
            logger.error("[%d/%d] %s 失败: %s", i, len(todo), pid, exc)

        # ── 防撞熔断已委托给 br(CFBreaker)：on_breach() 内含
        # 退避/冷却 sleep，连续撞墙达上限→冷却(零线上请求)→
        # 冷却结束自动重置计数续跑(自恢复)；达 max_cooldowns 才 giveup。
        # 这里无需再写冷却逻辑。

        if i % 50 == 0:
            logger.info("进度 %d/%d (新缓存=%d 失败=%d)", i, len(todo), ok, fail)

        # 限速 2-4s（尊重 BR 速率, 也降低 CF 再次挑战概率）
        if i < len(todo) and not cf_breached:
            time.sleep(2 + random.uniform(0, 2))

    logger.info("=" * 50)
    if cf_breached:
        logger.info(
            "因 CF 熔断提前退出；完成度 新缓存=%d 失败=%d 总=%d（已缓存自动跳过）",
            ok, fail, len(todo),
        )
    else:
        logger.info(
            "完成! 新缓存=%d 失败=%d 总=%d（已缓存的自动跳过）",
            ok, fail, len(todo),
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="补齐主球员页缓存(headless, 幂等)")
    ap.add_argument("--limit", type=int, default=None, help="最多补几页(试跑)")
    ap.add_argument("--season", type=int, default=None, help="只补某季关联球员")
    ap.add_argument("--cf-breach-limit", type=int, default=CF_BREACH_LIMIT,
                    help="连续撞墙多少次触发熔断冷却(默认 5)")
    ap.add_argument("--cf-backoff", type=int, default=CF_BACKOFF_SEC,
                    help="单次撞墙后退避秒数(默认 30)")
    ap.add_argument("--cf-cooldown", type=int, default=CF_COOLDOWN_SEC,
                    help="熔断后冷却时长秒数/自恢复等待(默认 600=10分钟)")
    ap.add_argument("--cf-max-cooldowns", type=int, default=CF_MAX_COOLDOWNS,
                    help="最大冷却次数(0=无限自恢复, 持续续跑; 默认 0)")
    args = ap.parse_args()
    main(args.limit, args.season, args.cf_breach_limit,
         args.cf_backoff, args.cf_cooldown, args.cf_max_cooldowns)
