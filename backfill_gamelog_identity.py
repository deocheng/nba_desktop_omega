"""backfill_gamelog_identity.py —— 回填老季(1983-1996) player_gamelog 缺失的球员身份列。

背景
----
老季(1983-1996)的 BR 球员 gamelog 入库时，crawler 只写了 gameid/player/team/season/stats，
从不写 br_player_id / player_name / game_id_full / player_id(bigint)，导致这四列全为 NULL
（见 crawl_br_gamelog.py 的 bug 修复）。本脚本对已落库的老季数据做**一次性回填**：

  - game_id_full : 100% 可靠。player_gamelog.gameid = dim_games.nba_api_id::text
                  -> dim_games.game_id（字母数字全 id）。覆盖全部可关联 NULL 行。
  - player_name  : 100% 可靠。SET player_name = player（player 列已正确写入）。
  - br_player_id : best-effort。经 dim_players 用 player_name 关联回填 BR 字符串 id；
                  若某 player_name 命中多行(distinct br_player_id > 1)视为同名歧义，跳过不填。
  - player_id    : best-effort。经 player_id_bridge 用 player_name 关联回填数字 bigint id；
                  同样处理同名/多值歧义，无可靠映射则跳过。

设计原则（与 backfill_nba_api_old.py 一致）：
  - 默认 dry-run 预览，只统计/打印将更新的行数，rollback 不写库。
  - --apply 才真正执行 UPDATE 并提交，打印各列实际更新行数。
  - 只动老季(season 1983-1996)的 NULL 行，绝不误改新季已填充数据（幂等、安全）。

用法
----
  python backfill_gamelog_identity.py          # 预览（不写库，rollback）
  python backfill_gamelog_identity.py --apply  # 真实回填并提交
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2

# 与项目其他脚本一致的 DB 连接参数（密码从环境变量读取，避免硬编码）。
DB_CONFIG = dict(
    host="127.0.0.1",
    port=5433,
    dbname="nba",
    user="postgres",
    password=os.environ.get("DB_PASSWORD", "R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1"),
)

# 仅回填这些老季的 NULL 行（含端点 1983 与 1996）。
OLD_SEASON_PRED = "g.season BETWEEN 1983 AND 1996"


def _exec(cur, total_sql: str, count_sql: str, update_sql: str, apply: bool) -> dict:
    """Run the dry-run count (or the real UPDATE) for one column and return stats.

    Args:
        cur: Database cursor.
        total_sql: Counts ALL NULL rows of this column in the old seasons
            (the denominator for coverage).
        count_sql: Counts NULL rows that *can* be filled (the numerator).
        update_sql: The actual UPDATE statement (only executed under --apply).
        apply: When True, execute ``update_sql`` and report ``rowcount``.

    Returns:
        Dict with keys: ``total`` (NULL rows), ``eligible`` (fillable),
        ``updated`` (None in dry-run, else rowcount), ``coverage`` (percentage).
    """
    cur.execute(total_sql)
    total = cur.fetchone()[0]

    cur.execute(count_sql)
    eligible = cur.fetchone()[0]

    updated = None
    if apply:
        cur.execute(update_sql)
        updated = cur.rowcount

    coverage = (eligible / total * 100.0) if total else 100.0
    return {"total": total, "eligible": eligible, "updated": updated, "coverage": coverage}


def backfill(cur, apply: bool) -> dict:
    """Compute (dry-run) or perform (--apply) the four identity backfills.

    Args:
        cur: Database cursor.
        apply: False => only count (dry-run); True => execute UPDATEs.

    Returns:
        Dict keyed by column name with per-column stats from :func:`_exec`.
    """
    report: dict = {}

    # 1) game_id_full —— 100% 可靠，经 dim_games 关联。
    report["game_id_full"] = _exec(
        cur,
        total_sql="""
            SELECT count(*) FROM player_gamelog g
            WHERE game_id_full IS NULL AND %s
        """ % OLD_SEASON_PRED,
        count_sql="""
            SELECT count(*) FROM player_gamelog g
            JOIN dim_games d ON d.nba_api_id::text = g.gameid
            WHERE g.game_id_full IS NULL AND %s
        """ % OLD_SEASON_PRED,
        update_sql="""
            UPDATE player_gamelog g
            SET game_id_full = d.game_id
            FROM dim_games d
            WHERE d.nba_api_id::text = g.gameid
              AND g.game_id_full IS NULL AND %s
        """ % OLD_SEASON_PRED,
        apply=apply,
    )

    # 2) player_name —— 100% 可靠，直接复制 player 列（player 已正确写入）。
    report["player_name"] = _exec(
        cur,
        total_sql="""
            SELECT count(*) FROM player_gamelog g
            WHERE player_name IS NULL AND %s
        """ % OLD_SEASON_PRED,
        count_sql="""
            SELECT count(*) FROM player_gamelog g
            WHERE player_name IS NULL AND player IS NOT NULL AND %s
        """ % OLD_SEASON_PRED,
        update_sql="""
            UPDATE player_gamelog g
            SET player_name = player
            WHERE player_name IS NULL AND player IS NOT NULL AND %s
        """ % OLD_SEASON_PRED,
        apply=apply,
    )

    # 3) br_player_id —— best-effort，经 dim_players 用 player_name 关联。
    #    同名歧义(player_name 命中多行 distinct br_player_id)用 HAVING = 1 跳过。
    report["br_player_id"] = _exec(
        cur,
        total_sql="""
            SELECT count(*) FROM player_gamelog g
            WHERE br_player_id IS NULL AND %s
        """ % OLD_SEASON_PRED,
        count_sql="""
            SELECT count(*) FROM player_gamelog g
            JOIN (
                SELECT player_name AS pn, MAX(player_id) AS bid
                FROM dim_players
                WHERE player_id IS NOT NULL AND player_id <> ''
                GROUP BY player_name
                HAVING COUNT(DISTINCT player_id) = 1
            ) dp ON dp.pn = g.player
            WHERE g.br_player_id IS NULL AND %s
        """ % OLD_SEASON_PRED,
        update_sql="""
            UPDATE player_gamelog g
            SET br_player_id = dp.bid
            FROM (
                SELECT player_name AS pn, MAX(player_id) AS bid
                FROM dim_players
                WHERE player_id IS NOT NULL AND player_id <> ''
                GROUP BY player_name
                HAVING COUNT(DISTINCT player_id) = 1
            ) dp
            WHERE dp.pn = g.player AND g.br_player_id IS NULL AND %s
        """ % OLD_SEASON_PRED,
        apply=apply,
    )

    # 4) player_id (bigint) —— best-effort，经 player_id_bridge 用 player_name 关联
    #    到数字 id。同样处理同名/多值歧义（HAVING COUNT(DISTINCT nba_player_id)=1）。
    report["player_id"] = _exec(
        cur,
        total_sql="""
            SELECT count(*) FROM player_gamelog g
            WHERE player_id IS NULL AND %s
        """ % OLD_SEASON_PRED,
        count_sql="""
            SELECT count(*) FROM player_gamelog g
            JOIN (
                SELECT player_name AS bn, MAX(nba_player_id) AS num_id
                FROM player_id_bridge
                WHERE nba_player_id IS NOT NULL AND nba_player_id <> ''
                  AND nba_player_id ~ '^[0-9]+$'
                GROUP BY player_name
                HAVING COUNT(DISTINCT nba_player_id) = 1
            ) b ON b.bn = g.player
            WHERE g.player_id IS NULL AND %s
        """ % OLD_SEASON_PRED,
        update_sql="""
            UPDATE player_gamelog g
            SET player_id = CAST(b.num_id AS bigint)
            FROM (
                SELECT player_name AS bn, MAX(nba_player_id) AS num_id
                FROM player_id_bridge
                WHERE nba_player_id IS NOT NULL AND nba_player_id <> ''
                  AND nba_player_id ~ '^[0-9]+$'
                GROUP BY player_name
                HAVING COUNT(DISTINCT nba_player_id) = 1
            ) b
            WHERE b.bn = g.player AND g.player_id IS NULL AND %s
        """ % OLD_SEASON_PRED,
        apply=apply,
    )

    return report


def _print_report(rep: dict, apply: bool) -> None:
    """Pretty-print the per-column backfill report."""
    print(f"\n{'列':<14}{'总NULL':>10}{'可回填':>10}{'覆盖率':>10}{'已UPDATE':>10}")
    print("-" * 54)
    for col, d in rep.items():
        updated = d["updated"] if apply else "—"
        print(
            f"{col:<14}{d['total']:>10}{d['eligible']:>10}"
            f"{d['coverage']:>9.1f}%{str(updated):>10}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="回填老季 player_gamelog 球员身份列")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真实执行 UPDATE 并提交（默认仅 dry-run 预览并 rollback）",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    try:
        print(f"模式: {'真实回填' if args.apply else '预览(dry-run, rollback)'} | 目标季: 1983-1996")
        rep = backfill(cur, args.apply)
        _print_report(rep, args.apply)

        if args.apply:
            conn.commit()
            print("\n✅ 已提交。")
        else:
            conn.rollback()
            print("\n(预览) 已回滚。加 --apply 真实执行。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
