#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Player Weight Scraper — Safe BR Edition
========================================
使用 br_safe_scraper 模块，10-15 秒间隔，小批量爬取。

设计:
  - 每次只跑一小批（默认 20 个球员）
  - 请求间隔 12-18 秒
  - 断点续传（已爬取的自动跳过）
  - Cookie 持久化（减少 Cloudflare 验证）
  - 被封自动停止，不硬冲

用法:
  python crawler/scrape_player_weight.py                  # 默认跑 20 个
  python crawler/scrape_player_weight.py --batch 400      # 跑 400 个（每100人休息10分钟）
  python crawler/scrape_player_weight.py --batch 0        # 跑全部（不推荐）
  python crawler/scrape_player_weight.py --player achiupr01  # 单个球员
  python crawler/scrape_player_weight.py --min-delay 15 --max-delay 25  # 自定义间隔
  python crawler/scrape_player_weight.py --batch 400 --rest-every 100 --rest-seconds 600
"""
import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import psycopg2
from bs4 import BeautifulSoup

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from br_safe_scraper import BR_BASE, HAS_BS4, SafeBRScraper

# ── A3 T-A3-2: §6 收口 ───────────────────────────────────────────────────────
# Route weight persistence through the backend data_layer writer
# (backend.data_layer.weight_writer.upsert_player_weight) so the parameterized
# SQL lives in ONE designated writer, not in the crawler body. If the backend
# package is not importable (crawler run from a different layout), fall back to
# the local parameterized upsert below.
_USE_BACKEND_WRITER = False
try:
    _CRAWLER_DIR = os.path.dirname(os.path.abspath(__file__))
    # 两种布局都要认：
    #   a) external_crawler/nba_desktop/nba_desktop_omega/（旧嵌套布局）
    #   b) 仓库根（当前布局：external_crawler/crawler/ 之上两级即仓库根）
    for _cand in (
        os.path.abspath(os.path.join(_CRAWLER_DIR, "..", "nba_desktop", "nba_desktop_omega")),
        os.path.abspath(os.path.join(_CRAWLER_DIR, "..", "..")),
    ):
        if os.path.isdir(os.path.join(_cand, "backend", "data_layer")):
            sys.path.insert(0, _cand)
            from backend.data_layer.weight_writer import upsert_player_weight  # noqa: F401
            _USE_BACKEND_WRITER = True
            break
except Exception:  # pragma: no cover - optional integration
    _USE_BACKEND_WRITER = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "..", "logs", "weight_scrape.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("WeightScraper")


def _load_dotenv_quietly() -> None:
    """把仓库根 .env 灌进 os.environ（若存在且 python-dotenv 可用）。

    crawler 常常独立于 backend 包运行，此时没有 config 模块代劳加载 .env；
    这里做一次 best-effort 加载，失败不致命（后续 DB 连接会明确报错）。
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # pragma: no cover - dotenv 未安装
        return
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    for cand in (os.path.join(root, ".env"), os.path.join(os.getcwd(), ".env")):
        if os.path.isfile(cand):
            load_dotenv(cand, override=False)
            return


def _db_config() -> dict:
    """DB 连接配置 —— 口令与端点一律走 env（禁止硬编码）。

    🔴 2026-11-10 修正：此前此处硬编码 ``password="postgres"``，与生产库实际
       口令不符 → 脚本连库直接 ``FATAL: password authentication failed``，
       即**整个补爬脚本在当前环境下完全不可用**。
    """
    _load_dotenv_quietly()
    pw = os.environ.get("DB_PASSWORD") or os.environ.get("PGPASSWORD") or ""
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "5433")),
        "dbname": os.environ.get("DB_NAME", "nba"),
        "user": os.environ.get("DB_USER", "postgres"),
        "password": pw.strip().strip('"').strip("'"),
    }


DB_CONFIG = _db_config()

DEFAULT_BATCH = 20  # 默认每批 20 个球员


# ── Parser ───────────────────────────────────────────────────────────────────

def parse_player_info(html: str) -> Dict:
    """Parse weight, height, born from BR player page HTML."""
    soup = BeautifulSoup(html, "lxml")
    result = {
        "weight_lbs": None,
        "weight_kg": None,
        "height": None,
        "born": None,
        "position": None,
        "shoots": None,
    }

    # Method 1: Look in <li> items in the player info section
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)

        if "Weight:" in text:
            m_lbs = re.search(r"(\d+)\s*lb", text)
            m_kg = re.search(r"\[(\d+)\s*kg\]", text)
            if m_lbs:
                result["weight_lbs"] = int(m_lbs.group(1))
            if m_kg:
                result["weight_kg"] = int(m_kg.group(1))

        elif "Height:" in text:
            m = re.search(r"Height:\s*(.+?)(?:\s*$)", text)
            if m:
                result["height"] = m.group(1).strip()

        elif "Born:" in text:
            m = re.search(r"Born:\s*(.+?)(?:\s*$)", text)
            if m:
                result["born"] = m.group(1).strip()

        elif "Position:" in text:
            m = re.search(r"Position:\s*(.+?)(?:\s*Shoots:|$)", text)
            if m:
                result["position"] = m.group(1).strip()

        elif "Shoots:" in text:
            m = re.search(r"Shoots:\s*(.+?)(?:\s*$)", text)
            if m:
                result["shoots"] = m.group(1).strip()

    # Method 2: JSON-LD
    if not result["weight_lbs"]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict) and "weight" in data:
                    w = str(data["weight"])
                    m = re.search(r"(\d+)", w)
                    if m:
                        result["weight_lbs"] = int(m.group(1))
            except Exception:
                pass

    return result


# ── Database ──────────────────────────────────────────────────────────────────

def ensure_table(conn):
    """Create player_weight_history table if not exists, and migrate missing columns."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_weight_history (
            player_id TEXT PRIMARY KEY,
            player_name TEXT,
            weight_lbs INTEGER,
            weight_kg INTEGER,
            height TEXT,
            born TEXT,
            position TEXT,
            shoots TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Idempotent column migrations (handles older schemas missing position/shoots)
    cur.execute("ALTER TABLE player_weight_history ADD COLUMN IF NOT EXISTS position TEXT")
    cur.execute("ALTER TABLE player_weight_history ADD COLUMN IF NOT EXISTS shoots TEXT")
    conn.commit()
    cur.close()


def get_players_to_scrape(conn, batch_size=DEFAULT_BATCH, single_player=None):
    """Get list of player_ids to scrape (skip already done).

    🔴 2026-11-10 修正：候选宇宙原为 ``player_per_game``（= 有赛季统计的球员），
       比目标表窄 —— 2026-11-10 实测有 9 名 dim_players 球员缺 weight，其中 6 人
       从未出现在 player_per_game（无 fact 赛季行），因此**永远不会被补爬**
       （"Remaining players to scrape: 3" 正是当年的老 3 人）。
       改为以 ``dim_players``（权威球员表）为候选宇宙，与目标口径一致。
    """
    cur = conn.cursor()

    if single_player:
        # 显式指定时以 dim_players 为准（该球员可能没有任何赛季统计行）
        cur.execute("""
            SELECT player_id, player_name FROM dim_players
            WHERE player_id = %s
            LIMIT 1
        """, (single_player,))
    else:
        if batch_size > 0:
            cur.execute("""
                SELECT DISTINCT d.player_id, d.player_name
                FROM dim_players d
                WHERE d.player_id IS NOT NULL
                  AND d.player_id NOT IN (SELECT player_id FROM player_weight_history)
                ORDER BY d.player_id
                LIMIT %s
            """, (batch_size,))
        else:
            cur.execute("""
                SELECT DISTINCT d.player_id, d.player_name
                FROM dim_players d
                WHERE d.player_id IS NOT NULL
                  AND d.player_id NOT IN (SELECT player_id FROM player_weight_history)
                ORDER BY d.player_id
            """)

    rows = cur.fetchall()
    cur.close()
    return rows


def get_remaining_count(conn) -> int:
    """获取还需要爬取的球员总数（候选宇宙与 get_players_to_scrape 一致：dim_players）。"""
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(DISTINCT d.player_id)
        FROM dim_players d
        WHERE d.player_id IS NOT NULL
          AND d.player_id NOT IN (SELECT player_id FROM player_weight_history)
    """)
    count = cur.fetchone()[0]
    cur.close()
    return count


def save_player(conn, player_id: str, player_name: str, info: Dict):
    """Save scraped player info to database.

    A3 §6 收口: when the backend package is importable, persistence is delegated
    to ``backend.data_layer.weight_writer.upsert_player_weight`` (the single
    designated writer). Otherwise the identical parameterized upsert below runs.
    Either path is fully parameterized — no identifier string interpolation.
    """
    if _USE_BACKEND_WRITER:
        try:
            upsert_player_weight(
                player_id, player_name,
                info.get("weight_lbs"), info.get("weight_kg"),
                info.get("height"), info.get("born"),
                info.get("position"), info.get("shoots"),
            )
            return
        except Exception as exc:  # pragma: no cover - fallback safety
            logger.warning("backend weight_writer failed (%s); using local upsert", exc)
    # Local fallback (parameterized, identical semantics)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO player_weight_history
            (player_id, player_name, weight_lbs, weight_kg, height, born, position, shoots)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (player_id) DO UPDATE SET
            player_name = EXCLUDED.player_name,
            weight_lbs = EXCLUDED.weight_lbs,
            weight_kg = EXCLUDED.weight_kg,
            height = EXCLUDED.height,
            born = EXCLUDED.born,
            position = EXCLUDED.position,
            shoots = EXCLUDED.shoots,
            scraped_at = CURRENT_TIMESTAMP
    """, (player_id, player_name,
          info["weight_lbs"], info["weight_kg"],
          info["height"], info["born"],
          info["position"], info["shoots"]))
    conn.commit()
    cur.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Safely scrape player weight from BR")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH,
                        help=f"Number of players per batch (default={DEFAULT_BATCH}, 0=all)")
    parser.add_argument("--player", type=str, default=None,
                        help="Single player_id to scrape")
    parser.add_argument("--min-delay", type=float, default=12.0,
                        help="Minimum delay between requests (seconds, default=12)")
    parser.add_argument("--max-delay", type=float, default=18.0,
                        help="Maximum delay between requests (seconds, default=18)")
    parser.add_argument("--rest-every", type=int, default=100,
                        help="Pause after every N players (default=100, 0=no pause)")
    parser.add_argument("--rest-seconds", type=int, default=600,
                        help="Rest duration in seconds (default=600, i.e. 10 min)")
    parser.add_argument("--no-warmup", action="store_true",
                        help="Skip session warmup")
    parser.add_argument("--force-playwright", action="store_true",
                        help="Force Playwright mode (skip curl_cffi)")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    ensure_table(conn)

    remaining = get_remaining_count(conn)
    logger.info(f"Remaining players to scrape: {remaining}")

    if remaining == 0 and not args.player:
        logger.info("All players already scraped! Nothing to do.")
        conn.close()
        return

    players = get_players_to_scrape(conn, args.batch, args.player)
    logger.info(f"This batch: {len(players)} players | "
                f"Delay: {args.min_delay}-{args.max_delay}s between requests")
    if args.rest_every > 0:
        logger.info(f"Rest strategy: pause {args.rest_seconds}s "
                    f"({args.rest_seconds/60:.0f}min) every {args.rest_every} players")

    if not players:
        logger.info("No players to scrape in this batch.")
        conn.close()
        return

    # 创建安全爬取器
    scraper = SafeBRScraper(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_retries=3,
        use_playwright=args.force_playwright,
    )
    mode = "Playwright(forced)" if args.force_playwright else "curl_cffi → Playwright(fallback)"
    logger.info(f"Scraper mode: {mode}")

    # 预热 session
    if not args.no_warmup:
        warmup_ok = scraper.warmup()
        if not warmup_ok:
            logger.error("Warmup failed — BR is blocking us. Exiting to avoid getting banned.")
            logger.error("Try again in 30-60 minutes.")
            scraper.close()
            conn.close()
            return

    success = 0
    failed = 0
    no_weight = 0
    blocked_streak = 0
    MAX_BLOCKED_STREAK = 3  # 连续被拦 3 次就停止
    start_time = time.time()

    for i, (player_id, player_name) in enumerate(players):
        url = f"{BR_BASE}/players/{player_id[0]}/{player_id}.html"
        logger.info(f"[{i+1}/{len(players)}] {player_name} ({player_id})")

        html = scraper.fetch(url)
        if not html:
            failed += 1
            blocked_streak += 1
            logger.warning(f"  Failed to fetch page (streak: {blocked_streak})")

            # 连续失败太多次，停止避免被永久封
            if blocked_streak >= MAX_BLOCKED_STREAK:
                logger.error(f"  {MAX_BLOCKED_STREAK} consecutive failures — stopping to avoid ban.")
                logger.error("  Resume later with: python crawler/scrape_player_weight.py")
                break
        else:
            blocked_streak = 0  # 重置连续失败计数
            info = parse_player_info(html)
            if info["weight_lbs"]:
                save_player(conn, player_id, player_name, info)
                success += 1
                logger.info(f"  Weight: {info['weight_lbs']} lbs "
                            f"({info['weight_kg'] or '?'} kg), "
                            f"Height: {info['height'] or '?'}")
            else:
                no_weight += 1
                # 🔴 2026-11-10 修正：此前此分支也调用 save_player → 写入
                #    「weight/height/born 全 NULL」的空行，破坏 player_weight_history
                #    的完整性不变量（with_kg == total），且每次重跑都会重新插入。
                #    BR 页面确实没有体重字段的球员（实测 leedi01 / mitchmu01 /
                #    wertira01 —— 页面只有 per-game 统计表，无 bio info 表）
                #    **不写库**，只在日志留痕；其 dim_players.weight 保持 NULL。
                logger.warning("  No weight data found (not persisted: row would carry no data)")

        # 进度报告
        if (i + 1) % 5 == 0 or i == len(players) - 1:
            elapsed = time.time() - start_time
            remaining_total = get_remaining_count(conn)
            logger.info(f"  Progress: {success} success, {failed} failed, "
                        f"{no_weight} no_weight | "
                        f"Elapsed: {elapsed:.0f}s | "
                        f"Remaining total: {remaining_total}")

        # 每 N 个球员暂停休息（防封策略）
        if args.rest_every > 0 and (i + 1) % args.rest_every == 0 and i < len(players) - 1:
            rest_min = args.rest_seconds / 60
            logger.info("-" * 60)
            logger.info(f"REST BREAK: {args.rest_seconds}s ({rest_min:.0f} min) — "
                        f"completed {i+1}/{len(players)} this batch, "
                        f"resuming at {datetime.now().strftime('%H:%M:%S')} + {rest_min:.0f}min")
            logger.info("-" * 60)
            time.sleep(args.rest_seconds)
            logger.info("Resuming after rest break...")

    elapsed = time.time() - start_time
    stats = scraper.get_stats()
    logger.info("=" * 60)
    logger.info(f"Batch done! Success: {success}, Failed: {failed}, "
                f"No weight: {no_weight}, Total: {len(players)}")
    logger.info(f"Time: {elapsed:.0f}s ({elapsed/max(len(players),1):.1f}s/player)")
    logger.info(f"Scraper stats: {stats}")
    remaining_total = get_remaining_count(conn)
    logger.info(f"Remaining players: {remaining_total}")
    if remaining_total > 0:
        logger.info("Next batch: python crawler/scrape_player_weight.py "
                    "--batch 400 --rest-every 100 --rest-seconds 600")
    logger.info("=" * 60)

    scraper.close()
    conn.close()


if __name__ == "__main__":
    main()
