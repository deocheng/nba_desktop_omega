"""backfill_playoff_player_id.py —— 回填 player_shooting 孤儿 Playoffs 行的 player_id（任务 B）。

背景
----
全部 6,099 行 Playoffs 的 player_id 为 NULL（但 player 姓名字段有值），是孤儿行。
player_shooting.player_id 必须是 **BR slug**（text），须对齐 dim_players.player_id
（经 T0 实测确认 dim_players 的 slug 列就是 ``player_id``，姓名列是 ``player_name``；
dim_players 不存在 br_player_id / slug 列）。

设计（对齐 backfill_gamelog_identity.py 的「同名多值安全跳过」范式）：
  * 阶段1：经 dim_players 用 player_name → 唯一 BR slug 回填；同名歧义（HAVING
    COUNT(DISTINCT player_id)=1 不成立）的行不动。
  * 阶段2（兜底）：同 (player, season) 的 Regular 行 player_id 回填 Playoffs 行。
  * 阶段3：仍未匹配（歧义/缺失）的行写入回查表 backfill_review，供人工处理。

安全性：幂等、低危。默认真实执行（--dry-run 仅预览并 rollback）。
口令走环境变量 PGPASSWORD，禁止硬编码。

用法
----
  python backfill_playoff_player_id.py            # 真实回填（幂等）
  python backfill_playoff_player_id.py --dry-run  # 仅统计预览，不写库
  python backfill_playoff_player_id.py --stats    # 仅打印前后孤儿计数
"""
from __future__ import annotations

import argparse
import os
from typing import Dict

import psycopg2

# 集群 B 连接：host=127.0.0.1, port=5433；口令从环境变量读，禁止硬编码。
DB_CONFIG = dict(
    host="127.0.0.1",
    port=5433,
    dbname="nba",
    user="postgres",
    password=os.environ.get("PGPASSWORD", ""),
)

# dim_players 列名（T0 实测确认）：
#   slug 列 = player_id（character varying，5476 行）
#   姓名列  = player_name（text，5476 行）
#   br_player_id / slug 列均不存在。
SLUG_COL = "player_id"
NAME_COL = "player_name"

# player_shooting.player 对名人堂球员带 '*' 展示后缀（如 'Allen Iverson*'），
# 与 dim_players.player_name（无后缀）无法精确匹配。JOIN 时归一（去尾 '*' + 去空格），
# 仍需满足「姓名→唯一 slug」才更新（安全跳过歧义）。
NORM = "TRIM(TRAILING '*' FROM ps.player)"

# 回查表 DDL（仅记录歧义/缺失行，绝不影响主流程）
REVIEW_DDL = """
CREATE TABLE IF NOT EXISTS backfill_review (
    id          SERIAL PRIMARY KEY,
    season      BIGINT,
    player      TEXT,
    season_type VARCHAR,
    reason      TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
)
"""


class BackfillPlayoffPlayerId:
    """回填 player_shooting 孤儿 Playoffs 行的 player_id。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    # ── 孤儿计数 ──────────────────────────────────────────────────────────
    def report_orphans(self) -> int:
        """返回 Playoffs 且 player_id IS NULL 的孤儿行数。"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM player_shooting "
            "WHERE season_type='Playoffs' AND player_id IS NULL"
        )
        n = cur.fetchone()[0]
        cur.close()
        return n

    # ── 阶段1：经 dim_players 回填（姓名→唯一 slug 才更新）────────────────
    def backfill_via_dim_players(self) -> int:
        """经 dim_players 用 player_name 关联回填唯一 BR slug。

        仅更新「姓名映射到唯一 slug」的行；同名歧义行不动（安全跳过）。
        返回实际 UPDATE 行数。
        """
        sql = f"""
            WITH uniq AS (
                SELECT {NAME_COL} AS pn, MAX({SLUG_COL}) AS bid
                FROM dim_players
                WHERE {SLUG_COL} IS NOT NULL AND {SLUG_COL} <> ''
                GROUP BY {NAME_COL}
                HAVING COUNT(DISTINCT {SLUG_COL}) = 1
            )
            UPDATE player_shooting ps
            SET player_id = u.bid
            FROM uniq u
            WHERE ps.season_type = 'Playoffs'
              AND ps.player_id IS NULL
              AND {NORM} = u.pn
        """
        cur = self.conn.cursor()
        cur.execute(sql)
        n = cur.rowcount
        cur.close()
        return n

    # ── 阶段2（兜底）：同 (player, season) 的 Regular 行补 slug ────────────
    def backfill_via_self_join(self) -> int:
        """用同 (player, season) 的 Regular 行 player_id 回填仍空缺的 Playoffs 行。

        同一 (player, season) 的所有 Regular 行 player_id 必为同一 slug（BR slug
        与赛季无关），故 MAX 安全；返回实际 UPDATE 行数。
        """
        sql = """
            UPDATE player_shooting po
            SET player_id = reg.player_id
            FROM player_shooting reg
            WHERE po.season_type = 'Playoffs'
              AND po.player_id IS NULL
              AND reg.season_type = 'Regular'
              AND reg.player_id IS NOT NULL
              AND po.player = reg.player
              AND po.season = reg.season
        """
        cur = self.conn.cursor()
        cur.execute(sql)
        n = cur.rowcount
        cur.close()
        return n

    # ── 阶段3：未匹配行登记回查表 ─────────────────────────────────────────
    def log_unmatched(self) -> int:
        """把仍空缺的 Playoffs 孤儿行写入 backfill_review（歧义/缺失）。

        先 TRUNCATE 再 INSERT，保证重复运行幂等（不会重复累积）。
        """
        cur = self.conn.cursor()
        cur.execute(REVIEW_DDL)
        cur.execute("TRUNCATE TABLE backfill_review")
        cur.execute(
            """
            INSERT INTO backfill_review (season, player, season_type, reason)
            SELECT season, player, season_type, 'no_unique_dim_players_slug'
            FROM player_shooting
            WHERE season_type = 'Playoffs' AND player_id IS NULL
        """
        )
        n = cur.rowcount
        cur.close()
        return n

    # ── 主流程 ────────────────────────────────────────────────────────────
    def run(self, dry_run: bool = False) -> Dict[str, int]:
        """执行三阶段回填，返回统计。dry_run 时只统计不写库（rollback）。"""
        before = self.report_orphans()
        if dry_run:
            # 预览：用同一 CTE 估算可匹配数（不执行 UPDATE）
            cur = self.conn.cursor()
            cur.execute(
                f"""
                WITH uniq AS (
                    SELECT {NAME_COL} AS pn, MAX({SLUG_COL}) AS bid
                    FROM dim_players
                    WHERE {SLUG_COL} IS NOT NULL AND {SLUG_COL} <> ''
                    GROUP BY {NAME_COL}
                    HAVING COUNT(DISTINCT {SLUG_COL}) = 1
                )
                SELECT COUNT(*) FROM player_shooting ps
                JOIN uniq u ON u.pn = {NORM}
                WHERE ps.season_type='Playoffs' AND ps.player_id IS NULL
                """
            )
            stage1_eligible = cur.fetchone()[0]
            cur.close()
            self.conn.rollback()
            return {
                "before": before,
                "stage1_eligible": stage1_eligible,
                "stage1_updated": None,
                "stage2_updated": None,
                "after": before,
                "review": None,
            }

        n1 = self.backfill_via_dim_players()
        n2 = self.backfill_via_self_join()
        n_review = self.log_unmatched()
        self.conn.commit()
        after = self.report_orphans()
        return {
            "before": before,
            "stage1_eligible": None,
            "stage1_updated": n1,
            "stage2_updated": n2,
            "after": after,
            "review": n_review,
        }


def _print_report(rep: Dict[str, int], dry_run: bool) -> None:
    print("\n=== player_shooting Playoffs 孤儿回填报告 ===")
    print(f"  回填前孤儿行 : {rep['before']}")
    if dry_run:
        print(f"  阶段1可匹配  : {rep['stage1_eligible']} (预览, 未写库)")
        print("  (dry-run) 已 rollback，未做任何修改。")
    else:
        print(f"  阶段1 UPDATE : {rep['stage1_updated']}")
        print(f"  阶段2 UPDATE : {rep['stage2_updated']} (自连接兜底)")
        print(f"  回填后孤儿行 : {rep['after']}")
        print(f"  入回查表     : {rep['review']} (歧义/缺失)")
        ok = rep["after"] == 0
        print(f"  结论         : {'✅ 孤儿已清零' if ok else '⚠️ 仍有孤儿，见 backfill_review'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="回填 player_shooting 孤儿 Playoffs 行的 player_id（B）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅统计预览并 rollback，不写库（默认真实执行）",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="仅打印当前孤儿计数后退出（不写库）",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        if args.stats:
            n = BackfillPlayoffPlayerId(conn).report_orphans()
            print(f"Playoffs 孤儿行 (player_id IS NULL): {n}")
            return
        bf = BackfillPlayoffPlayerId(conn)
        rep = bf.run(dry_run=args.dry_run)
        _print_report(rep, args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
