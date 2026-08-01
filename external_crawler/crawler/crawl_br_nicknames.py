"""BR 球员「绰号(nickname)」批量补抽 + 入库。

数据源: https://www.basketball-reference.com/players/{first}/{player_id}.html
写入:   dim_players.nickname  （player_bio 视图随 dim_players 加列自动暴露，见
        sql/006_add_player_nickname.sql）

为何是独立脚本（而非塞进 nba_daily_crawler 的 player_bio 规则）:
  * nba_daily_crawler.py 的 'player_bio' 项仅是一个**未实现的配置占位**（无
    crawl_player_bio 方法），真实 bio 数据由其他流程灌入 dim_players。
  * 本次只新增「绰号」一个维度，按 headshots 增量范式做成**自包含脚本**，
    零耦合、零风险干扰任何在跑爬虫（headshots / awards / gamelog / pbp）。
  * 单一数据源 = BR 球员页 FAQ；抽取逻辑全在 common/player_nickname.py，
    落库只 UPDATE dim_players.nickname。

零干扰铁律:
  * **不触碰 9222 Chrome**：抓取走 requests / curl_cffi 直连（common.player_nickname），
    与运行中的 gamelog / headshots CDP 会话完全隔离。
  * 限速 2-4s；单人失败记日志不中断整体；per-player commit（resume 安全）。
  * 只读 PG 连接 + UPDATE dim_players.nickname（在线 DDL 已加好列）。

用法:
  python crawl_br_nicknames.py --resume                 # 全量补抽（跳过已有 nickname 的行）
  python crawl_br_nicknames.py --limit 5 --dry-run      # 测试：只跑流程，不抓取不写库
  python crawl_br_nicknames.py --limit 20 --resume      # 小批量补抽
  python crawl_br_nicknames.py                          # 全量（nickname IS NULL 的都抽）
"""
import argparse
import logging
import random
import sys
import time
from pathlib import Path

import psycopg2

# 项目根（本文件向上两级）加入 sys.path，使 `import common.*` / `import backend.*` 可解析
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.player_nickname import extract_nickname, fetch_player_page
from common.player_page_cache import is_valid_player_page
from backend.core import config  # noqa: E402  —— fail-safe DSN（不回退弱口令 'postgres'）

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("crawl_br_nicknames")

# crawl_failures 登记用（与 br_player_shot_chart 同范式）。
# 语义：仅登记「页面抓到了、但该球员确实没有绰号」的确定性空结果，
#      用于把「已查过·真无数据」与「从没查过」区分开——两者在
#      dim_players.nickname 里都是 NULL，不登记就无法区分，
#      导致 --resume 每轮把它们全部捞回重抓（永久空转）。
# 瞬态故障（CF 挑战 / 网络失败 / 空响应）**绝不登记**，保留 NULL 让下轮重试。
TASK_TYPE = "br_player_nickname"

# 页面有效性门槛：extract_nickname() 对「真无绰号 / 残页 / CF 挑战页」一律返回
# None，三者不可区分。若不加校验就登记，一张挑战页会被永久标记为「确认无绰号」，
# 造成不可逆的数据缺失（违反完整/正确）。故仅在确认拿到**完整球员页**时才登记。
# 判据统一收敛到 common.player_page_cache.is_valid_player_page（bio_ext 共用同一份，
# 避免两处副本漂移）。


def _failure_token(player_id: str) -> str:
    """crawl_failures.game_id 令牌：{task_type}|{player_id}（球员级粒度，无 season）。"""
    return f"{TASK_TYPE}|{player_id}"


def _connect() -> psycopg2.extensions.connection:
    """用 backend.core.config 的 fail-safe DSN 建立连接（不硬编码弱口令）。"""
    return psycopg2.connect(config.db_dsn())


def register_no_nickname(conn, player_id: str) -> None:
    """幂等登记「确认无绰号」到 crawl_failures。

    crawl_failures 主键在 id、无 (game_id,task_type) 唯一约束，故先查后插，
    避免同一球员被反复插入堆积（与 shot_chart.register_failure 一致）。
    写入失败只告警、不中断主流程。
    """
    if conn is None:
        return
    token = _failure_token(player_id)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM crawl_failures WHERE game_id=%s AND task_type=%s LIMIT 1",
            (token, TASK_TYPE),
        )
        if cur.fetchone() is not None:
            cur.close()
            return
        cur.execute(
            "INSERT INTO crawl_failures (game_id, task_type, resolved) "
            "VALUES (%s, %s, %s)",
            (token, TASK_TYPE, False),
        )
        conn.commit()
        cur.close()
    except Exception as exc:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("register_no_nickname 写入失败（已忽略）: %s", exc)


def get_players(conn, limit=None, resume=False) -> list:
    """SELECT player_id, player_name FROM dim_players。

    resume=True 时取「nickname IS NULL **且** 未登记为确认无绰号」的行。

    仅按 nickname IS NULL 过滤是不够的：确认无绰号的球员写回的也是 NULL，
    与「从没查过」无法区分，会被每轮重复捞回（2026-07-31 实测：4 轮都从
    [1/3404] 重头开始，永远走不完）。故排除 crawl_failures 中已登记者。
    """
    cur = conn.cursor()
    if resume:
        query = """
            SELECT p.player_id, p.player_name FROM dim_players p
            WHERE p.nickname IS NULL
              AND NOT EXISTS (
                    SELECT 1 FROM crawl_failures cf
                    WHERE cf.task_type = %(task_type)s
                      AND cf.game_id = %(task_type)s || '|' || p.player_id
              )
            ORDER BY p.player_id
        """
        params = {"task_type": TASK_TYPE}
    else:
        query = """
            SELECT player_id, player_name FROM dim_players
            ORDER BY player_id
        """
        params = None
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query, params)
    return cur.fetchall()


def upsert_nickname(conn, player_id: str, nickname: "str | None") -> None:
    """UPDATE dim_players SET nickname=%s WHERE player_id=%s（空串归并为 NULL）。"""
    value = nickname if (nickname and nickname.strip()) else None
    cur = conn.cursor()
    cur.execute(
        "UPDATE dim_players SET nickname = %s WHERE player_id = %s",
        (value, player_id),
    )
    cur.close()


def run_pipeline(limit=None, dry_run=False, resume=False, rate=3.0) -> None:
    """主循环：直连抓取 + 抽取 + UPDATE；限速 rate±1s；单人异常不中断。

    Args:
        limit:   最多处理几人（测试用）。
        dry_run: 只打印计划，不抓取不写库。
        resume:  只处理 nickname IS NULL 且未登记「确认无绰号」的行。
        rate:    基础限速秒数（实际 rate ± 1s 随机抖动）。
    """
    conn = _connect()
    players = get_players(conn, limit, resume)

    if resume and limit is None:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM dim_players WHERE nickname IS NOT NULL")
        already = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM crawl_failures WHERE task_type=%s", (TASK_TYPE,)
        )
        no_nick = cur.fetchone()[0]
        cur.close()
        logger.info(
            "resume 模式：已有绰号 %d 行 + 确认无绰号 %d 行 跳过，待处理 %d 行",
            already, no_nick, len(players),
        )
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
                logger.warning("    抓取失败（CF/网络），记 failed 跳过")
                failed += 1
                # 抓取失败的也写 NULL？不：保留 NULL 以便 resume 重试，但不算 ok
                continue

            nickname = extract_nickname(html)
            # 写库（per-player commit，resume 安全）
            try:
                upsert_nickname(conn, player_id, nickname)
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                logger.error("    DB 写入失败 %s: %s", player_id, exc)
                conn.rollback()
                failed += 1
                continue

            if nickname:
                ok += 1
                logger.info("    → nickname: %s", nickname)
            elif is_valid_player_page(html):
                # 页面完整 + 解析不到绰号 = 确定性空结果（非瞬态故障）。
                # 登记 crawl_failures，使 --resume 下轮跳过，缺口可收敛到 0。
                empty += 1
                register_no_nickname(conn, player_id)
                logger.info("    → 无绰号（页面完整确认）→ 登记 crawl_failures")
            else:
                # 解析为空但页面不完整（残页 / CF 挑战页）→ 瞬态，绝不登记，
                # 保留 nickname IS NULL 让 --resume 下轮重试。
                failed += 1
                logger.warning(
                    "    → 解析为空但页面异常（len=%d，疑似 CF/残页）→ 不登记，下轮重试",
                    len(html or ""),
                )

            # 限速
            if i < len(players) - 1:
                time.sleep(max(0.5, rate - 1 + random.uniform(0, 2)))
    finally:
        if dry_run:
            conn.rollback()
        conn.close()

    logger.info("=" * 50)
    logger.info("完成! 有绰号=%d 无绰号=%d 抓取失败=%d 跳过=%d",
                ok, empty, failed, skipped)
    if dry_run:
        logger.info("[dry-run] 已 rollback，未写库")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BR 球员 nickname 补抽")
    parser.add_argument("--limit", type=int, default=None, help="最多抽几人（测试用）")
    parser.add_argument("--dry-run", action="store_true", help="只跑流程，不抓取不写库")
    parser.add_argument("--resume", action="store_true",
                        help="只抽 nickname IS NULL 的行（断点续传）")
    parser.add_argument("--rate", type=float, default=3.0,
                        help="基础限速秒数（默认 3.0，实际 ±1s 抖动）")
    args = parser.parse_args()

    run_pipeline(args.limit, args.dry_run, args.resume, args.rate)
