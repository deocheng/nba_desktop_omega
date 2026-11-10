#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_team_pbp_rowidx.py — team_pbp_raw 加 row_idx 行身份列（v2 前置迁移）

修复背景（2026-08-16 代码审查 P0-①）：原主键 (team_abbr, season, season_type,
table_id, row_label, data_stat) 无行身份，靠 BR 首列 Rk 序号恰好唯一才没出事。
v2 爬虫（crawl_br_team_pbp_v2.py）冲突键加入 row_idx，本迁移负责：

  1. 全表备份 → team_pbp_raw_fullbak_<ts>（可回滚铁律）
  2. ADD COLUMN row_idx integer NOT NULL DEFAULT 0
  3. 回填：row_label 为纯数字 → row_idx = row_label::int（与 v2 解析规则一致，
     重爬同季可幂等命中旧行）；空标签('')→ 保持 0（pbp_stats 小计/分隔行，
     靠 data_stat 在键内唯一，且 v2 解析器对空首列也置 row_idx=0 → 重爬幂等）；
     「非空、非数字、非 Rk」标签 → 触发防呆中止（不应出现，需人工核查）
  4. 备份并删除 row_label='Rk' 的表头垃圾行（原版漏滤 thead 造成，
     每队每季 ~23 格；2026-08-16 实测存在，非数据）
  5. 换主键：DROP 旧 PK → ADD (…, row_label, row_idx, data_stat)

用法：
    python3 migrate_team_pbp_rowidx.py --dry-run   # 只打印将执行的步骤与统计
    python3 migrate_team_pbp_rowidx.py             # 实际执行（带备份）
回滚：
    DROP 表主键恢复：ALTER TABLE team_pbp_raw DROP CONSTRAINT …, ADD PRIMARY KEY(旧6列);
    数据恢复：INSERT INTO team_pbp_raw SELECT * FROM team_pbp_raw_fullbak_<ts> …
    （备份表含全部原始行，人工按需恢复）
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.nba_paths import REPO_ROOT

PROJECT = str(REPO_ROOT)


def db_password() -> str:
    for line in open(f"{PROJECT}/.env"):
        m = re.match(r"^\s*DB_PASSWORD\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1)
    raise RuntimeError("未在 .env 找到 DB_PASSWORD")


STEPS = [
    # (说明, SQL)
    ("加列 row_idx",
     "ALTER TABLE team_pbp_raw ADD COLUMN IF NOT EXISTS row_idx integer NOT NULL DEFAULT 0"),
    ("回填 row_idx（数字行标签→序号）",
     "UPDATE team_pbp_raw SET row_idx = row_label::int WHERE row_label ~ '^[0-9]+$' AND row_idx = 0"),
    ("删除 Rk 表头垃圾行（已备份）",
     "DELETE FROM team_pbp_raw WHERE row_label = 'Rk'"),
    ("换主键（加 row_idx）",
     "ALTER TABLE team_pbp_raw DROP CONSTRAINT team_pbp_raw_pkey, "
     "ADD PRIMARY KEY (team_abbr, season, season_type, table_id, row_label, row_idx, data_stat)"),
]


def main():
    dry = "--dry-run" in sys.argv
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    conn = psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba",
                            user="postgres", password=db_password())
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET max_parallel_workers_per_gather = 0")

    # 现状统计
    cur.execute("SELECT count(*) FROM team_pbp_raw")
    total = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM team_pbp_raw WHERE row_label ~ '^[0-9]+$'")
    numeric = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM team_pbp_raw WHERE row_label = 'Rk'")
    rk = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM team_pbp_raw WHERE row_label = ''")
    empty = cur.fetchone()[0]
    # 仅拦截「非空、非数字、非 Rk」的标签（如 'Opponent'/'Team' 重复小计行），
    # 空标签('')属 pbp_stats 小计/分隔行，靠 data_stat 在键内唯一，row_idx=0 安全。
    cur.execute("SELECT count(*) FROM team_pbp_raw "
                "WHERE row_label <> '' AND row_label !~ '^[0-9]+$' "
                "AND row_label <> 'Rk'")
    other = cur.fetchone()[0]
    print(f"team_pbp_raw 现状：总行数={total}  数字标签={numeric}  "
          f"Rk表头行={rk}  空标签(→0)={empty}  其他非数字标签={other}")
    if other:
        print("⚠️ 存在「非空、非数字、非 Rk」的行标签，回填后这些行 row_idx=0，"
              "若同键内多行会撞 0 —— 请先人工核查：")
        cur.execute("SELECT DISTINCT table_id, row_label FROM team_pbp_raw "
                    "WHERE row_label <> '' AND row_label !~ '^[0-9]+$' "
                    "AND row_label <> 'Rk' LIMIT 20")
        for r in cur.fetchall():
            print(f"    {r[0]} | {r[1]}")
        conn.rollback()
        print("已中止（防呆）。处理完上述标签后重跑。")
        return 1

    print(f"\n将执行 {len(STEPS) + 1} 步"
          f"{'（DRY-RUN，不落库）' if dry else ''}：")
    print(f"  0. 全表备份 → team_pbp_raw_fullbak_{ts}（{total} 行）")
    for i, (desc, _sql) in enumerate(STEPS, 1):
        print(f"  {i}. {desc}")

    if dry:
        conn.rollback()
        print("\nDRY-RUN 结束，未做任何修改。去掉 --dry-run 实跑。")
        return 0

    # 0. 全表备份
    cur.execute(f"CREATE TABLE team_pbp_raw_fullbak_{ts} AS "
                f"SELECT * FROM team_pbp_raw")
    cur.execute(f"SELECT count(*) FROM team_pbp_raw_fullbak_{ts}")
    assert cur.fetchone()[0] == total, "备份行数不一致，中止"
    print(f"✅ 备份完成：team_pbp_raw_fullbak_{ts}（{total} 行）")

    for i, (desc, sql) in enumerate(STEPS, 1):
        cur.execute(sql)
        print(f"✅ {i}. {desc}（影响 {cur.rowcount} 行）")

    conn.commit()
    # 迁移后自检
    cur.execute("SELECT count(*), count(DISTINCT (team_abbr, season, season_type, "
                "table_id, row_label, row_idx, data_stat)) FROM team_pbp_raw")
    n1, n2 = cur.fetchone()
    print(f"\n迁移后自检：行数={n1}，新键去重数={n2} "
          f"{'✅ 一致' if n1 == n2 else '❌ 不一致（不应发生，主键已强制）'}")
    cur.close()
    conn.close()
    print("完成。现在可使用 crawl_br_team_pbp_v2.py。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
