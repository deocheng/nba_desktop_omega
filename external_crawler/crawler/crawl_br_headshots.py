"""BR 球员头像（headshot）批量抓取 + 入库。

数据源: https://www.basketball-reference.com/players/{first}/{player_id}.html
写入:   dim_players.headshot_path / headshot_url / headshot_status / headshot_scraped_at

设计要点（详见 docs/ARCH_headshots_incremental.md）：
  * 复用 common.browser.get_driver()（CDP 直连用户 Chrome，串行隔离）。
  * 头像 src 必须运行时从球员页抽取（BR 的 /req/日期/ 前缀会变化，绝不硬编码）。
  * 头像托管在 BR 自身域名（非 cdn.nba.com），复用同一 CF 会话即可取。
  * 断点续传 / 幂等：--resume 跳过 status IN ('ok','missing') 的行（failed/NULL 重试）。
  * 限速 3-6s；单人失败记 failed 不中断整体（HS-09）。
  * 零干扰铁律：本脚本独立、独立单实例锁名、独立运行脚本，绝不触碰 gamelog 任何逻辑。

用法:
  python crawl_br_headshots.py --resume            # 全量补抓（已成功/缺失跳过）
  python crawl_br_headshots.py --limit 5 --dry-run # 测试：只跑流程，不下载不写库
  python crawl_br_headshots.py --limit 20 --resume # 小批量补抓
"""
import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path

import psycopg2

# 确保项目根（本文件向上两级）在 sys.path，使 `import common.*` 可解析
# （与 crawl_br_gamelog.py 同款写法）。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.headshot_store import (
    BR_HEADSHOT_HOST,
    HEADSHOT_ROOT,
    download_image,
    ensure_root,
    extract_headshot_src,
    fetch_image_via_cdp,
    headshot_path_for,
    magic_ext,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("crawl_br_headshots")

DB_CONFIG = dict(
    host="localhost",
    port=5433,
    dbname="nba",
    user="postgres",
    password=os.environ.get("DB_PASSWORD"),
)

PLAYER_PAGE = "https://www.basketball-reference.com/players/{first}/{player_id}.html"


def get_players(conn, limit=None, resume=False) -> list:
    """SELECT player_id, player_name FROM dim_players。

    resume=True 时跳过已成功 / 永久缺失的行（status IN ('ok','missing')），
    只重试 failed / NULL。全量约 5476 行。
    """
    cur = conn.cursor()
    if resume:
        query = """
            SELECT player_id, player_name FROM dim_players
            WHERE headshot_status IS NULL OR headshot_status = 'failed'
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


def upsert_path(conn, player_id, path, url, status) -> None:
    """UPDATE dim_players SET headshot_*=... WHERE player_id=%s。

    headshot_scraped_at 显式 now()（迁移时未设 DEFAULT，保持 NULL=未抓）。
    """
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE dim_players
        SET headshot_path = %s,
            headshot_url = %s,
            headshot_status = %s,
            headshot_scraped_at = now()
        WHERE player_id = %s
        """,
        (path, url, status, player_id),
    )
    cur.close()


def _resolve_stored_path(player_id: str) -> "str | None":
    """从磁盘反查已落盘的头像绝对路径（jpg/png/webp 任一，非空即返回）。"""
    for ext in ("jpg", "png", "webp"):
        p = HEADSHOT_ROOT / f"{player_id}.{ext}"
        if p.is_file() and p.stat().st_size > 0:
            return str(p)
    return None


def scrape_player(player_id: str, player_name, driver) -> "tuple[str, str | None]":
    """抓取单个球员的头像。

    返回 (status, url|None)：
      status ∈ {ok, missing, failed}
        - ok      : 抽到 src 且成功落盘
        - missing : 球员页无头像（BR 本身缺图，与 failed 区分，resume 跳过）
        - failed  : 抽到 src 但两级下载均失败（可经 --resume 重试）
      url = 抽到的头像图片 URL（failed 也记录，便于排查）。

    注：按架构签名返回 (status, url)；落盘路径由 run_pipeline 通过
    _resolve_stored_path 反查后写入 headshot_path。
    """
    first = player_id[0].lower()
    url = PLAYER_PAGE.format(first=first, player_id=player_id)
    try:
        driver.get(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("  导航球员页失败 %s: %s", player_id, exc)
        return ("failed", None)

    html = driver.page_source
    src = extract_headshot_src(html)
    if not src:
        # BR 球员页本身无头像（历史球员 / 无 NBA 生涯）
        return ("missing", None)

    referer = BR_HEADSHOT_HOST + "/"
    dest = headshot_path_for(player_id, src)

    # Tier-1：直连 GET
    path = download_image(src, dest, referer)
    if path is None:
        # Tier-2：CDP 独立 target 保底
        data = fetch_image_via_cdp(driver, src)
        if data:
            ext = magic_ext(data) or "jpg"
            path = HEADSHOT_ROOT / f"{player_id}.{ext}"
            ensure_root()
            path.write_bytes(data)
            logger.debug("Tier-2 落盘成功: %s", path)

    if path is not None and path.exists() and path.stat().st_size > 0:
        return ("ok", src)
    return ("failed", src)


def run_pipeline(limit=None, dry_run=False, resume=False) -> None:
    """主循环：限速 3-6s，单人异常不中断；末打印 ok/missing/failed/skipped 汇总。"""
    conn = psycopg2.connect(**DB_CONFIG)
    players = get_players(conn, limit, resume)

    if resume and limit is None:
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM dim_players "
            "WHERE headshot_status IN ('ok','missing')"
        )
        already = cur.fetchone()[0]
        logger.info("resume 模式：已处理 %d 行跳过，待处理 %d 行", already, len(players))
    elif resume:
        logger.info("resume 模式：待处理 %d 行（limit=%s）", len(players), limit)
    else:
        logger.info("全量模式：待处理 %d 行", len(players))

    if dry_run:
        logger.info("[dry-run] 不加载浏览器、不下载、不写库；仅打印计划")

    ok = missing = failed = skipped_players = 0
    driver = None

    try:
        for i, (player_id, player_name) in enumerate(players):
            if not player_id:
                logger.info("[%d/%d] %s (None) → 跳过（无 player_id）",
                            i + 1, len(players), player_name)
                skipped_players += 1
                continue
            logger.info("[%d/%d] %s (%s)...", i + 1, len(players), player_name, player_id)

            if dry_run:
                # 不加载浏览器、不下载、不写库
                logger.info("    [dry-run] 计划处理（不实际操作）")
                continue

            # 懒加载 driver（仅 live 模式，且只读一次，进程级单例）
            if driver is None:
                from common.browser import get_driver
                driver = get_driver()
                ensure_root()

            try:
                status, url = scrape_player(player_id, player_name, driver)
            except Exception as exc:  # noqa: BLE001 - 单人异常不中断整体
                logger.error("    单人异常: %s", exc)
                status, url = "failed", None

            # 写库（per-player commit，resume 安全，与 gamelog 风格一致）
            try:
                path = _resolve_stored_path(player_id) if status == "ok" else None
                upsert_path(conn, player_id, path, url, status)
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                logger.error("    DB 写入失败 %s: %s", player_id, exc)
                conn.rollback()

            if status == "ok":
                ok += 1
            elif status == "missing":
                missing += 1
            else:
                failed += 1
            logger.info("    → %s", status)

            # 限速 3-6s（与 gamelog 一致）
            if i < len(players) - 1:
                time.sleep(3 + random.uniform(0, 3))
    finally:
        if driver is not None:
            try:
                from common.browser import quit_driver
                quit_driver()
            except Exception:  # noqa: BLE001
                pass
        if dry_run:
            conn.rollback()
        conn.close()

    logger.info("=" * 50)
    logger.info("完成! ok=%d missing=%d failed=%d skipped=%d",
                ok, missing, failed, skipped_players)
    if dry_run:
        logger.info("[dry-run] 已 rollback，未写库")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BR 球员 headshot 抓取")
    parser.add_argument("--limit", type=int, default=None, help="最多抓几人（测试用）")
    parser.add_argument("--dry-run", action="store_true", help="只跑流程，不下载不写库")
    parser.add_argument("--resume", action="store_true",
                        help="跳过已成功/缺失球员（断点续传，只重试 failed/NULL）")
    args = parser.parse_args()

    run_pipeline(args.limit, args.dry_run, args.resume)
