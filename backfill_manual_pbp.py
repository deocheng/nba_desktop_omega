#!/usr/bin/env python3
"""
backfill_manual_pbp.py
======================

手动回填 4 场 Basketball-Reference 逐回合 (PBP) 数据到 `play_by_play` 表
(source='BBRef')，并翻转 `dim_games.pbp_imported` / `pbp_no_data` 标志。

设计要点（来自 team-lead 任务说明）：
1. **复用 br_fill_pbp.py 的抓取基础设施**：`build_driver()` + `fetch_pbp_soup()`
   用 undetected_chromedriver 绕过 Cloudflare，绝不复写裸 requests/selenium。
2. **复用 br_pbp_parse.parse_pbp** 解析器（与库内已有 ~460 场 BBRef 行格式一致）。
3. **gameid 必须用库的 db_game_id（现代缩写）**，不能用 URL 里的历史缩写直接写。
   BR URL 用「当时」的历史队名（如 1997 的 WSB=Washington Bullets），而 dim_games.game_id
   用现代缩写（WAS）。
4. **幂等**：先 `DELETE FROM play_by_play WHERE gameid=%(db_game_id)s AND source='BBRef'`
   再批量 INSERT；重跑安全。
5. **不碰 202311160CHI 等其它行**：脚本只操作下方 4 个 db_game_id。
6. 4 场全部插完后：`UPDATE dim_games SET pbp_imported=true, pbp_no_data=false
   WHERE game_id = ANY(%(成功插入的 db_game_id)s)`。
   （注：若某场 BR 抓取 404/空/异常，则不翻转该场的标志，避免虚假覆盖率；单独报告。）

健壮性修复（前台实跑踩坑后的关键改动）：
- 用**全新** profile 目录（覆盖 br_fill_pbp.UDC_DIR），避免旧 profile 的 SingletonLock
  导致 chrome 起不来、build_driver() 抛 SessionNotCreatedException 后整脚本中断、
  末尾的 UPDATE 永远执行不到（这是首跑只有 3 场写入、标志全没翻的真因）。
- build_driver 带重试：失败则清理 profile 重建。
- **每场单独 try/except**：单场异常只记入 failed 并继续，绝不让一场失败阻断
  后续场与末尾的 UPDATE + 验证打印。

4 个目标（br_gid=URL 历史缩写, db_game_id=写入 key）：
  #1  199701020WSB -> 199701020WAS   NYK@WAS  1997-01-02
  #2  199703150WSB -> 199703150WAS   UTA@WAS  1997-03-15
  #3  199912300POR -> 199912300POR   PHI@POR  1999-12-30
  #4  202310290PHI -> 202310290MIA   MIA@PHI  2023-10-29  (dim_games 主客队写反, 见下)

关于 #4 主客队：dim_games 存的是 home=MIA / away=PHI，与真实 MIA@PHI 相反。
若把 dim_games 的错误缩写喂给 parse_pbp，会让每行的 team 标反。因此本脚本
把「正确」的 away=MIA / home=PHI 喂给解析器（保证 team 标签正确），但 gameid
仍写库的 202310290MIA；dim_games 本身不改动（只翻标志），差异单独回报。

运行（铁律：从项目根目录 + 设置 PYTHONPATH，否则 common 模块 import 失败）：
  cd <project_root> && PYTHONPATH=<project_root> .venv/bin/python backfill_manual_pbp.py
"""
from __future__ import annotations

import os
import sys
import time
import shutil
import argparse
import psycopg2
from psycopg2.extras import execute_batch

# --- path setup（与 br_fill_pbp.py 一致：把项目根加入 sys.path[0]） ---
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except Exception:
    pass

# 复用既能绕过 Cloudflare 的抓取基础设施，又不触发 br_fill_pbp 的 main()/watchdog
# （main() 仅在 __name__ == "__main__" 时执行，import 安全）。
import br_fill_pbp as _bf  # noqa: E402
from br_fill_pbp import (  # noqa: E402
    build_driver as _raw_build_driver,
    fetch_pbp_soup,
    SessionGone,
    RateLimiter,
    DB,
)
from br_pbp_parse import parse_pbp  # noqa: E402

# 关键修复：用全新 profile 目录，彻底绕开旧 .uc_pbp_profile 的 SingletonLock
# （旧锁会让 chrome 起不来，build_driver 抛 SessionNotCreatedException）。
_UDC_DIR = os.path.join(HERE, ".uc_pbp_profile_run2")
os.makedirs(_UDC_DIR, exist_ok=True)
_bf.UDC_DIR = _UDC_DIR

PBP_URL = "https://www.basketball-reference.com/boxscores/pbp/{gid}.html"

# 4 个目标。away/home 为「真实」对阵（保证 team 标签正确）；br_gid 为 URL 历史缩写。
TARGETS = [
    {
        "br_gid": "199701020WSB",
        "db_game_id": "199701020WAS",
        "away": "NYK", "home": "WAS",
        "date": "1997-01-02",
    },
    {
        "br_gid": "199703150WSB",
        "db_game_id": "199703150WAS",
        "away": "UTA", "home": "WAS",
        "date": "1997-03-15",
    },
    {
        "br_gid": "199912300POR",
        "db_game_id": "199912300POR",
        "away": "PHI", "home": "POR",
        "date": "1999-12-30",
    },
    {
        "br_gid": "202310290PHI",
        "db_game_id": "202310290MIA",
        "away": "MIA", "home": "PHI",  # 真实 MIA@PHI（dim_games 写反了，本脚本不修）
        "date": "2023-10-29",
    },
]

MAX_PAGE_RETRY = 3
MAX_DRIVER_RETRY = 4

INSERT_SQL = """
    INSERT INTO play_by_play (
        gameid, season, eventnum, period, clock, clock_seconds,
        h_pts, a_pts, team, playerid, player,
        event_type, subtype, action_verb, result, x, y, dist, description, current_team,
        homedescription, visitordescription, neutraldescription,
        scorehome, scorevisitor, scoremargin, source
    ) VALUES (
        %(gameid)s, %(season)s, %(eventnum)s, %(period)s, %(clock)s, %(clock_seconds)s,
        %(h_pts)s, %(a_pts)s, %(team)s, %(playerid)s, %(player)s,
        %(event_type)s, %(subtype)s, %(action_verb)s, %(result)s, %(x)s, %(y)s, %(dist)s, %(description)s, %(current_team)s,
        %(homedescription)s, %(visitordescription)s, %(neutraldescription)s,
        %(scorehome)s, %(scorevisitor)s, %(scoremargin)s, %(source)s
    )
"""


def build_driver_retry():
    """build_driver 带重试：失败清理 profile 目录后重建，规避 SingletonLock 等启动失败。"""
    last_err = None
    for attempt in range(1, MAX_DRIVER_RETRY + 1):
        try:
            return _raw_build_driver()
        except Exception as e:  # SessionNotCreatedException 等
            last_err = e
            print(f"  ! build_driver 失败(第{attempt}次): {type(e).__name__}: {e}", flush=True)
            try:
                shutil.rmtree(_UDC_DIR, ignore_errors=True)
                os.makedirs(_UDC_DIR, exist_ok=True)
            except Exception:
                pass
            time.sleep(2)
    raise last_err


def get_dim_games_seasons(conn, db_ids):
    """返回 {db_game_id: {'season':int, 'away':str, 'home':str}}，用于 season 覆盖
    与 #4 主客队差异检测。"""
    out = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT game_id, season, away_team_abbr, home_team_abbr "
            "FROM dim_games WHERE game_id = ANY(%s)",
            (db_ids,),
        )
        for gid, season, away, home in cur.fetchall():
            out[gid] = {
                "season": int(season) if season is not None else None,
                "away": (away or "").strip(),
                "home": (home or "").strip(),
            }
    return out


def fetch_with_retry(driver, url, br_gid, season, game_date, limiter):
    """带速率限制 + SessionGone 重建的抓取；返回 (driver, soup, status)。"""
    soup, status = None, None
    for _ in range(1, MAX_PAGE_RETRY + 1):
        try:
            limiter.wait()  # 严格 <=15 BR 请求/分钟
            soup, status = fetch_pbp_soup(
                driver, url, br_gid=br_gid, season=season, game_date=game_date
            )
            if soup is not None or status == "404":
                break
        except SessionGone:
            print("  ! driver 会话失效, 重建中...", flush=True)
            try:
                driver.quit()
            except Exception:
                pass
            driver = build_driver_retry()
            soup, status = None, "session_rebuilt"
    return driver, soup, status


def print_verification(conn, db_ids):
    """打印脚本自带的验证段（play_by_play 行数 + dim_games 标志）。"""
    print("\n=== 验证: play_by_play (BBRef) 行数 ===", flush=True)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT gameid, count(*) FROM play_by_play "
            "WHERE gameid = ANY(%s) AND source='BBRef' GROUP BY gameid",
            (db_ids,),
        )
        rows = cur.fetchall()
        have = {r[0]: r[1] for r in rows}
        for gid in db_ids:
            print(f"  {gid}: {have.get(gid, 0)} 行", flush=True)
    print("\n=== 验证: dim_games 标志 ===", flush=True)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT game_id, pbp_imported, pbp_no_data FROM dim_games "
            "WHERE game_id = ANY(%s) ORDER BY game_id",
            (db_ids,),
        )
        for r in cur.fetchall():
            print(f"  {r[0]}: pbp_imported={r[1]} pbp_no_data={r[2]}", flush=True)


def run(args):
    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    db_ids = [t["db_game_id"] for t in TARGETS]
    dim = get_dim_games_seasons(conn, db_ids)

    # 报告 #4 主客队差异
    for t in TARGETS:
        gid = t["db_game_id"]
        d = dim.get(gid)
        if d and (d["away"], d["home"]) != (t["away"], t["home"]):
            print(
                f"[!] 数据质量: {gid} dim_games 主客队=({d['away']}@{d['home']}) "
                f"与真实对阵=({t['away']}@{t['home']}) 不一致; "
                f"解析按真实对阵标 team，gameid 仍写 {gid}（不动 dim_games）。",
                flush=True,
            )

    driver = None
    inserted = {}        # db_game_id -> 行数
    failed = []          # (db_game_id, status/原因)
    try:
        driver = build_driver_retry()
        limiter = RateLimiter(max_per_minute=15, min_interval=4.5)
        for i, t in enumerate(TARGETS, 1):
            br_gid = t["br_gid"]
            db_gid = t["db_game_id"]
            season = dim.get(db_gid, {}).get("season")
            url = PBP_URL.format(gid=br_gid)
            # 单场独立 try：一场失败只记录、继续，绝不阻断后续场与末尾 UPDATE
            try:
                driver, soup, status = fetch_with_retry(
                    driver, url, br_gid, season, t["date"], limiter
                )
                if soup is None:
                    print(f"[{i}/{len(TARGETS)}] {db_gid} FAIL({status}) {url}", flush=True)
                    failed.append((db_gid, status))
                    continue

                # 解析：away/home 用「真实」对阵，确保 team 标签正确
                rows = parse_pbp(soup, t["away"], t["home"], db_gid)
                if not rows:
                    print(
                        f"[{i}/{len(TARGETS)}] {db_gid} FAIL(parsed_0_events) {url}",
                        flush=True,
                    )
                    failed.append((db_gid, "parsed_0"))
                    continue

                # 强制覆盖 gameid 为库的 db_game_id，并修正 season 为库内赛季
                for r in rows:
                    r["gameid"] = db_gid
                    if season is not None:
                        r["season"] = season

                if args.dry_run:
                    print(
                        f"[{i}/{len(TARGETS)}] [DRY] {db_gid} {t['date']} "
                        f"{t['away']}@{t['home']} events={len(rows)}",
                        flush=True,
                    )
                    inserted[db_gid] = len(rows)
                    continue

                with conn.cursor() as cur:
                    # 幂等：仅删本 gameid 的 BBRef 行，不影响其它 source / 其它 gameid
                    cur.execute(
                        "DELETE FROM play_by_play WHERE gameid=%s AND source='BBRef'",
                        (db_gid,),
                    )
                    execute_batch(cur, INSERT_SQL, rows, page_size=200)
                conn.commit()
                inserted[db_gid] = len(rows)
                print(
                    f"[{i}/{len(TARGETS)}] {db_gid} {t['date']} {t['away']}@{t['home']} "
                    f"inserted={len(rows)}",
                    flush=True,
                )
            except Exception as e:
                print(
                    f"[{i}/{len(TARGETS)}] {db_gid} EXCEPTION({type(e).__name__}: {e})",
                    flush=True,
                )
                failed.append((db_gid, f"exc:{type(e).__name__}"))
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue
    except Exception as e:
        # build_driver 彻底失败等：打印但继续到验证段（展示当前库状态）
        print(f"[FATAL] 初始化失败: {type(e).__name__}: {e}", flush=True)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    # 仅对成功插入的场翻标志（404/空/异常场不翻转，避免虚假覆盖率）
    ok_ids = [g for g, n in inserted.items() if n > 0]
    if ok_ids and not args.dry_run:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dim_games SET pbp_imported=true, pbp_no_data=false "
                "WHERE game_id = ANY(%s)",
                (ok_ids,),
            )
        conn.commit()
        print(f"[i] 已翻 pbp_imported/pbp_no_data 标志: {ok_ids}", flush=True)

    print_verification(conn, db_ids)
    conn.close()

    print("\n=== 汇总 ===", flush=True)
    print(f"  成功插入(场): {len(inserted)} -> {inserted}", flush=True)
    print(f"  失败(场): {len(failed)} -> {failed}", flush=True)
    if failed:
        print(
            "  [!] 以下场处理失败（已单独报告，未中断其它场）: "
            + ", ".join(f"{g}({s})" for g, s in failed),
            flush=True,
        )
    return inserted, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只解析打印，不写库")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()
