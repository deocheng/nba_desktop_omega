"""NBA Cup 总决赛标记（幂等、可重跑）。

口径（用户 2026-07-10 确认）：
- 季中赛只有「总决赛」是额外多打、不计入常规赛战绩的比赛（半决赛虽在拉斯维加斯也计入）。
- 因此每季仅 1 场总决赛标 season_type='NBA Cup'，其余(小组赛/QF/SF)留 'Regular Season'。

数据来源：Basketball-Reference 月度 schedule 页（已核对）。
三季总决赛（已对齐归一化缩写）：
- season=2024: 2023-12-09 IND@LAL (LAL 123-109)  game_id=202312090LAL
- season=2025: 2024-12-17 MIL@OKC (OKC 81-97)   game_id=202412170OKC
- season=2026: 2025-12-13 NYK@ORL (ORL 107-124) game_id=202512130ORL
"""
import psycopg2

DB = dict(host='localhost', port=5433, dbname='nba', user='postgres', password='postgres')

# (game_id, game_date, season, home_abbr, away_abbr, home_pts, away_pts)
FINALS = [
    ('202312090LAL', '2023-12-09', 2024, 'LAL', 'IND', 123, 109),
    ('202412170OKC', '2024-12-17', 2025, 'OKC', 'MIL',  81,  97),
    ('202512130ORL', '2025-12-13', 2026, 'ORL', 'NYK', 107, 124),
]

ARENA = ('T-Mobile Arena', 'Las Vegas', 'NV')

def main():
    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    cur = conn.cursor()
    report = []

    for gid, gdate, season, h, a, hp, ap in FINALS:
        # existing?
        cur.execute("SELECT game_id, season_type FROM dim_games WHERE game_id=%s", (gid,))
        row = cur.fetchone()
        box = f"/boxscores/{gid}.html"
        if row is None:
            # INSERT missing final
            cur.execute(
                """INSERT INTO dim_games
                   (game_id, game_date, season, season_type,
                    home_team_abbr, away_team_abbr, home_pts, away_pts,
                    boxscore_url, source, arena_name, arena_city, arena_state, location)
                   VALUES (%s,%s,%s,'NBA Cup',%s,%s,%s,%s,%s,'BBRef',%s,%s,%s,'Neutral')""",
                (gid, gdate, season, h, a, hp, ap, box, *ARENA))
            report.append(f"INSERT {gid} ({a}@{h} {gdate}) -> NBA Cup")
        else:
            old_type = row[1]
            if old_type != 'NBA Cup':
                cur.execute(
                    """UPDATE dim_games
                       SET season_type='NBA Cup', arena_name=%s, arena_city=%s,
                           arena_state=%s, location='Neutral'
                       WHERE game_id=%s""",
                    (*ARENA, gid))
                report.append(f"UPDATE {gid}: {old_type} -> NBA Cup (+arena)")
            else:
                report.append(f"skip   {gid}: already NBA Cup")

    conn.commit()

    print("=== actions ===")
    for r in report:
        print("  ", r)

    print("\n=== verify: NBA Cup count per season ===")
    cur.execute("""SELECT season, count(*) FROM dim_games
                   WHERE season_type='NBA Cup' GROUP BY season ORDER BY season""")
    for s, c in cur.fetchall():
        print(f"  season={s} NBA Cup={c}")

    print("\n=== verify: RS count per season (finals should NOT be in RS) ===")
    cur.execute("""SELECT season, count(*) FROM dim_games
                   WHERE season_type='Regular Season' GROUP BY season ORDER BY season""")
    for s, c in cur.fetchall():
        print(f"  season={s} RS={c}")

    conn.close()

if __name__ == '__main__':
    main()
