"""BR 球员「主数据维度增量(bio_ext)」批量补抽 + 入库。

数据源: https://www.basketball-reference.com/players/{first}/{player_id}.html
写入:   dim_players（7 个新列 + bio_ext_scraped_at）
       player_career_honors（归一化荣誉表）

为何是独立脚本（而非塞进 nba_daily_crawler 的 player_bio 规则）:
  * nba_daily_crawler.py 的 'player_bio' 项仅是一个**未实现的配置占位**
    （无 crawl_player_bio 方法），真实 bio 数据由其他流程灌入 dim_players。
  * 本次新增 bio_ext 7 维度 + 荣誉表，按 headshots/nickname 增量范式做成
    **自包含脚本**，零耦合、零风险干扰任何在跑爬虫
    （headshots / awards / gamelog / pbp）。
  * 单一数据源 = BR 球员页；抽取逻辑全在 common/player_bio_ext.py，
    落库只 UPDATE dim_players + DELETE/INSERT player_career_honors。

零干扰铁律:
  * **不触碰 9222 Chrome**：抓取走 curl_cffi 直连（common.player_bio_ext
    复用的 common.player_nickname.fetch_player_page），与运行中的
    gamelog / headshots CDP 会话完全隔离。
  * 限速 3±1s；单人失败记日志不中断整体；per-player commit（resume 安全）。
  * DB 连接走 backend.core.config.db_dsn()（不硬编码弱口令 'postgres'）。
  * 在线 DDL 已加好列（sql/007）；本脚本只做 UPDATE/DELETE/INSERT。

用法:
  python crawl_br_player_bio_ext.py --resume                 # 全量补抽（bio_ext_scraped_at IS NULL）
  python crawl_br_player_bio_ext.py --limit 5 --dry-run      # 测试：只跑流程，不抓取不写库
  python crawl_br_player_bio_ext.py --limit 20 --resume      # 小批量补抽
  python crawl_br_player_bio_ext.py                          # 全量（bio_ext_scraped_at IS NULL 的都抽）
"""
import argparse
import fcntl
import logging
import os
import random
import sys
import time
from pathlib import Path

import psycopg2

# 项目根（本文件向上两级）加入 sys.path，使 `import common.*` / `import backend.*` 可解析
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.player_bio_ext import (
    PlayerBioExtExtractor,
    fetch_player_page,
    player_page_url,
    upsert_player_bio_ext,
)
from common.player_page_cache import is_valid_player_page
from backend.core import config  # noqa: E402  —— fail-safe DSN（不回退弱口令 'postgres'）

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("crawl_br_player_bio_ext")

# 单实例文件锁路径（与脚本同目录）
_LOCK_PATH = Path(__file__).resolve().parent / ".crawl_br_player_bio_ext.lock"


def _acquire_lock() -> int:
    """获取文件锁，保证单实例运行；失败直接退出。"""
    fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.error("已有同脚本实例在运行（锁文件 %s），退出", _LOCK_PATH)
        os.close(fd)
        sys.exit(1)
    return fd


def _connect() -> psycopg2.extensions.connection:
    """用 backend.core.config 的 fail-safe DSN 建立连接（不硬编码弱口令）。"""
    return psycopg2.connect(config.db_dsn())


def get_players(conn, limit=None, resume=False) -> list:
    """SELECT player_id, player_name FROM dim_players。

    resume=True 时只取 bio_ext_scraped_at IS NULL 的行（断点续传，已抽的跳过）。
    """
    cur = conn.cursor()
    if resume:
        query = """
            SELECT player_id, player_name FROM dim_players
            WHERE bio_ext_scraped_at IS NULL
            ORDER BY player_id
        """
    else:
        query = """
            SELECT player_id, player_name FROM dim_players
            ORDER BY player_id
        """
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query)
    return cur.fetchall()


def run_pipeline(limit=None, dry_run=False, resume=False, rate=3.0) -> None:
    """主循环：直连抓取 + 抽取 + upsert；限速 rate±1s；单人异常不中断。

    Args:
        limit:   最多处理几人（测试用）。
        dry_run: 只打印计划，不抓取不写库。
        resume:  只处理 bio_ext_scraped_at IS NULL 的行。
        rate:    基础限速秒数（实际 rate ± 1s 随机抖动）。
    """
    conn = _connect()
    players = get_players(conn, limit, resume)

    if resume and limit is None:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM dim_players WHERE bio_ext_scraped_at IS NOT NULL")
        already = cur.fetchone()[0]
        logger.info("resume 模式：已抽 %d 行跳过，待处理 %d 行", already, len(players))
    elif resume:
        logger.info("resume 模式：待处理 %d 行（limit=%s）", len(players), limit)
    else:
        logger.info("全量模式：待处理 %d 行", len(players))

    if dry_run:
        logger.info("[dry-run] 不抓取、不写库；仅打印计划")

    ok = empty = failed = skipped = 0

    try:
        for i, (player_id, player_name) in enumerate(players):
            if not player_id:
                logger.info("[%d/%d] %s (None) → 跳过（无 player_id）",
                            i + 1, len(players), player_name)
                skipped += 1
                continue
            logger.info("[%d/%d] %s (%s)...", i + 1, len(players), player_name, player_id)

            if dry_run:
                logger.info("    [dry-run] 计划处理（不实际操作）")
                continue

            # 直连抓取（不碰 9222 Chrome）
            html = fetch_player_page(player_id)
            if not html:
                logger.warning("    抓取失败（CF/网络），记 failed 跳过（保留 NULL 以便 resume）")
                failed += 1
                continue

            # 页面有效性门槛（2026-07-31 加固）：
            # upsert_player_bio_ext() 无论抽到什么都会写 bio_ext_scraped_at=now()，
            # 而 --resume 正是以该列判「已处理」。若把 CF 挑战页 / 残页 / 截断页
            # 喂进去，会静默写入全 NULL 且**永久跳过**，属不可逆数据缺失
            # （违反正确/完整）。注意 fetch_player_page 是 cache-first，其内建的
            # CF 校验**只覆盖实网分支**，历史脏缓存会绕过 —— 故此处必须再验一次。
            if not is_valid_player_page(html):
                logger.warning(
                    "    页面无效（残页/截断/CF 挑战，len=%d），记 failed 跳过（保留 NULL 以便 resume）",
                    len(html),
                )
                failed += 1
                continue

            try:
                data = PlayerBioExtExtractor.extract_all(html)
                url = player_page_url(player_id)
                upsert_player_bio_ext(conn, player_id, data, source_url=url)
            except Exception as exc:  # noqa: BLE001
                logger.error("    DB 写入失败 %s: %s", player_id, exc)
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                failed += 1
                continue

            honors_n = len(data.get("honors") or [])
            jersey = data.get("jersey_numbers") or []
            if honors_n or data.get("hof_inducted_year") or jersey:
                ok += 1
                logger.info(
                    "    → honors=%d hof=%s jersey=%s died=%s aba=%s",
                    honors_n, data.get("hof_inducted_year"),
                    ",".join(jersey) if jersey else "-",
                    data.get("died"), data.get("aba_debut"),
                )
            else:
                empty += 1
                logger.info("    → 无荣誉/号码等（仍写入 NULL 标记）")

            # 限速
            if i < len(players) - 1:
                time.sleep(max(0.5, rate - 1 + random.uniform(0, 2)))
    finally:
        if dry_run:
            conn.rollback()
        conn.close()

    logger.info("=" * 50)
    logger.info("完成! 有数据=%d 无数据=%d 抓取/写失败=%d 跳过=%d",
                ok, empty, failed, skipped)
    if dry_run:
        logger.info("[dry-run] 已 rollback，未写库")


if __name__ == "__main__":
    # 单实例锁（先抢锁，避免重复运行）
    _acquire_lock()

    parser = argparse.ArgumentParser(description="BR 球员 bio_ext 维度补抽")
    parser.add_argument("--limit", type=int, default=None, help="最多抽几人（测试用）")
    parser.add_argument("--dry-run", action="store_true", help="只跑流程，不抓取不写库")
    parser.add_argument("--resume", action="store_true",
                        help="只抽 bio_ext_scraped_at IS NULL 的行（断点续传）")
    parser.add_argument("--rate", type=float, default=3.0,
                        help="基础限速秒数（默认 3.0，实际 ±1s 抖动）")
    args = parser.parse_args()

    run_pipeline(args.limit, args.dry_run, args.resume, args.rate)
