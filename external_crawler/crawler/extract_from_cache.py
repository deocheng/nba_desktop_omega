"""纯离线抽取驱动：只吃 raw_archive/br_players 本地缓存，零线上请求。

复用:
  - common.player_nickname.extract_nickname + upsert_nickname  → dim_players.nickname
  - common.player_bio_ext.PlayerBioExtExtractor.extract_all + upsert_player_bio_ext
    → dim_players(bio_ext 列 + career_honors_text) + player_career_honors

设计符合 nba-br-crawler §0a「本地留档优先」：
  线上抓取(gamelog 浏览器通道)已把主球员页 HTML 落盘到 raw_archive/br_players；
  本脚本只做**离线解析入库**，全程不碰 BR（不重锤 Cloudflare、不烧 IP 预算）。

与 crawl_br_nicknames.py / crawl_br_player_bio_ext.py 的区别：
  那两个从 dim_players 拉「未抽取」名单去**线上**补抽；本脚本只处理
  **已落盘缓存**的页，适合「先批量缓存、后统一离线榨取」的 cache-first 工作流。

用法:
  python extract_from_cache.py              # 处理全部缓存页(当前 552)
  python extract_from_cache.py --limit 20  # 小批量试跑(先验证再全量)
"""
import argparse
import logging
import sys
from pathlib import Path

import psycopg2

# 项目根（本文件向上两级）加入 sys.path，使 import common.* / backend.* 可解析
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.player_page_cache import CACHE_ROOT, get_cached_html
from common.player_nickname import extract_nickname
from common.player_bio_ext import PlayerBioExtExtractor, upsert_player_bio_ext
from backend.core import config  # noqa: E402 —— fail-safe DSN（不回退弱口令 'postgres'）


def upsert_nickname(conn, player_id: str, nickname: "str | None") -> None:
    """UPDATE dim_players SET nickname=%s WHERE player_id=%s（空串归并为 NULL）。
    与 crawl_br_nicknames.py 的 upsert 逻辑一致，本地自包含。"""
    value = nickname if (nickname and nickname.strip()) else None
    cur = conn.cursor()
    cur.execute(
        "UPDATE dim_players SET nickname = %s WHERE player_id = %s",
        (value, player_id),
    )
    cur.close()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("extract_from_cache")


def main(limit: int = None) -> None:
    conn = psycopg2.connect(config.db_dsn())

    all_html = sorted(CACHE_ROOT.rglob("*.html"))
    total = len(all_html)
    files = all_html[:limit] if limit else all_html
    logger.info("缓存页总数=%d，本次处理=%d", total, len(files))

    nick_ok = nick_empty = bio_ok = failed = 0

    for i, fp in enumerate(files, 1):
        player_id = fp.stem
        html = get_cached_html(player_id)
        if not html:
            logger.warning("[%d/%d] %s 缓存读空，跳过", i, len(files), player_id)
            failed += 1
            continue

        # ── nickname ──────────────────────────────────────────────
        try:
            nick = extract_nickname(html)
            upsert_nickname(conn, player_id, nick)  # 函数内不 commit
            conn.commit()  # nickname 单独落库，避免 bio 失败回滚丢失
            if nick:
                nick_ok += 1
            else:
                nick_empty += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("[%d/%d] %s nickname 失败: %s", i, len(files), player_id, exc)
            conn.rollback()
            failed += 1
            continue

        # ── bio_ext ─────────────────────────────────────────────
        try:
            data = PlayerBioExtExtractor.extract_all(html)
            upsert_player_bio_ext(conn, player_id, data)  # 函数内 commit
            bio_ok += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("[%d/%d] %s bio_ext 失败: %s", i, len(files), player_id, exc)
            conn.rollback()
            failed += 1
            continue

        if i % 50 == 0:
            logger.info("进度 %d/%d ...", i, len(files))

    conn.close()
    logger.info("=" * 50)
    logger.info(
        "完成! nickname有=%d 无=%d bio_ext写=%d 失败=%d 总=%d",
        nick_ok, nick_empty, bio_ok, failed, len(files),
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="只吃本地缓存的离线抽取(nickname + bio_ext)")
    ap.add_argument("--limit", type=int, default=None, help="最多处理几页（试跑用）")
    args = ap.parse_args()
    main(args.limit)
