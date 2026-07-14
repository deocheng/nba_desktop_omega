import os
"""QA 轻量独立复核 #114：确认 BBRef 2026 playerid 回填的关键不变量。

纯参数化查询（§6 合规），仅 SELECT，不改任何数据。
"""
import psycopg2

CONN = dict(host="localhost", port=5433, dbname="nba", user="postgres", password=os.environ.get("DB_PASSWORD"))


def q(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchall()


def main():
    conn = psycopg2.connect(**CONN)
    cur = conn.cursor()
    try:
        bbref_null = q(cur,
            "SELECT count(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
            ("BBRef", 2026))[0][0]
        nba_api_null = q(cur,
            "SELECT count(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
            ("nba_api", 2026))[0][0]
        br_crawler_null = q(cur,
            "SELECT count(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NULL",
            ("br_crawler", 2026))[0][0]
        bbref_total = q(cur,
            "SELECT count(*) FROM play_by_play WHERE source=%s AND season=%s",
            ("BBRef", 2026))[0][0]
        bbref_nonnull = q(cur,
            "SELECT count(*) FROM play_by_play WHERE source=%s AND season=%s AND playerid IS NOT NULL",
            ("BBRef", 2026))[0][0]

        print("== #114 复核关键不变量 ==")
        print(f"BBRef 2026 总行数            : {bbref_total}")
        print(f"BBRef 2026 playerid 非NULL   : {bbref_nonnull}")
        print(f"BBRef 2026 playerid IS NULL  : {bbref_null}  (回填前 239,328)")
        print(f"nba_api  2026 playerid IS NULL: {nba_api_null}  (应未变、且原本应很低)")
        print(f"br_crawler 2026 playerid IS NULL: {br_crawler_null}  (应未变)")
        print()
        print("== BBRef 2026 playerid IS NULL 按 player 分布 (Top 15) ==")
        for name, cnt in q(cur,
                "SELECT player, count(*) FROM play_by_play "
                "WHERE source=%s AND season=%s AND playerid IS NULL "
                "GROUP BY player ORDER BY count(*) DESC LIMIT 15",
                ("BBRef", 2026)):
            print(f"  {name!r:28} {cnt}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
