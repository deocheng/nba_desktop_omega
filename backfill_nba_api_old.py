"""backfill_nba_api_old.py —— 回填 6 个老季缺失的 nba_api_id（治本，配套 gamelog 落库）。

根因：dim_games.nba_api_id 是一套**合成键**（非 NBA.com 真值，NBA.com 不服务老季），
规则 = {前缀}{YY}{5位赛季内序号}，前缀 3=常规赛 / 4=季后赛 / All-Star 同 3，
YY = (season-1) % 100。某次批量回填漏跑这 6 季，导致它们绝大多数为 NULL，
gamelog 爬虫的 get_game_id_map 强制 nba_api_id IS NOT NULL -> 这 6 季缓存落不了库。

策略（最小爆破面）：
- 只 UPDATE nba_api_id IS NULL 的行；已有值的行原样保留 -> game_id_map 不受影响。
- 新序号从「该 (season, type) 现存 max 序号 + 1」起，绝不碰撞已有值。
- 幂等：重跑只补仍 NULL 的，已填的不动。

用法：
  python backfill_nba_api_old.py          # 预览（不写库，rollback）
  python backfill_nba_api_old.py --apply  # 真实回填
"""
from __future__ import annotations
import os
import sys

import psycopg2
import psycopg2.extras

os.environ.setdefault("PGPASSWORD", "R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1")

# 这 6 个季（1960/1963-1966/1968-1970/1972-1975/1978-1980 等均已满，仅这 6 季缺失）
SEASONS = [1961, 1962, 1967, 1971, 1976, 1977]
# 前缀映射（与现存 id 规则一致；All-Star 用 3 前缀，见 1961 的 36000001）
TYPES = {
    "Regular Season": "3",
    "Playoffs": "4",
    "All-Star": "3",
    "All Star": "3",
}


def backfill(cur) -> list:
    """执行回填（或预览），返回每季每类的改动计数明细。"""
    report = []
    for s in SEASONS:
        yy = (s - 1) % 100
        for t, p in TYPES.items():
            # 该 (season, type) 现存 max 序号（取 id 文本第 4-8 位）
            cur.execute(
                """SELECT COALESCE(MAX(CAST(SUBSTRING(CAST(nba_api_id AS TEXT) FROM 4 FOR 5) AS INT)), 0)
                     FROM dim_games
                     WHERE season=%s AND season_type=%s AND nba_api_id IS NOT NULL""",
                (s, t),
            )
            max_seq = cur.fetchone()[0]
            # 待填（按日期升序，保证序号与日期顺序一致）
            cur.execute(
                """SELECT game_id FROM dim_games
                     WHERE season=%s AND season_type=%s AND nba_api_id IS NULL
                     ORDER BY game_date""",
                (s, t),
            )
            nulls = [r[0] for r in cur.fetchall()]
            seq = max_seq
            n = 0
            for gid in nulls:
                seq += 1
                new_id = f"{p}{yy:02d}{seq:05d}"
                cur.execute(
                    "UPDATE dim_games SET nba_api_id=%s WHERE game_id=%s",
                    (new_id, gid),
                )
                n += 1
            report.append((s, t, len(nulls), max_seq, n))
    return report


def main() -> None:
    apply = "--apply" in sys.argv
    conn = psycopg2.connect(
        host="127.0.0.1", port=5433, dbname="nba", user="postgres",
        password=os.environ["PGPASSWORD"],
    )
    cur = conn.cursor()  # 默认 tuple 游标，[0] 取首列
    try:
        print(f"模式: {'真实回填' if apply else '预览(rollback)'}  | 目标季: {SEASONS}")
        rep = backfill(cur)
        total = 0
        for s, t, cnt, mx, n in rep:
            total += n
            print(f"  season={s} type={t:<14} 待填={cnt:<5} 现存max_seq={mx:<5} 已UPDATE={n}")
        if apply:
            conn.commit()
            print(f"\n✅ 已提交。共 UPDATE {total} 行。")
        else:
            conn.rollback()
            print(f"\n(预览) 本应 UPDATE {total} 行，已回滚。加 --apply 真实执行。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
