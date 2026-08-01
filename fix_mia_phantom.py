#!/usr/bin/env python3
"""
fix_mia_phantom.py
==================

彻底纠正 2023-10-29 的脏数据（用户已拍板「彻底纠正」）：

阶段 1 —— 删除幽灵行 `202310290MIA`（不可逆，精确靶向，绝不波及真实场）：
  1) DELETE FROM play_by_play WHERE gameid='202310290MIA' AND source='BBRef';
  2) DELETE FROM game_id_map   WHERE br_gid='202310290MIA';
  3) DELETE FROM dim_games      WHERE game_id='202310290MIA';
  删前 / 删后均 SELECT 确认行数。

阶段 2 —— 把真实场 `202310290PHI`（POR@PHI，126-98，dim_games 正确行）的正确
  PBP 从 BR 抓取并灌入 play_by_play：
  - fetch_pbp_soup(https://www.basketball-reference.com/boxscores/pbp/202310290PHI.html)
  - parse_pbp(soup, away_abbr='POR', home_abbr='PHI', '202310290PHI')
    ！！绝不要把 POR 写成 MIA（这正是上轮犯的错误）
  - 幂等：先 DELETE 本 gameid 的 BBRef 行再批量 INSERT
  - UPDATE dim_games SET pbp_imported=true WHERE game_id='202310290PHI';

阶段 3 —— 自带验证段打印 6 条查询。

复用 br_fill_pbp.py 的抓取基础设施（build_driver / fetch_pbp_soup / RateLimiter / DB）
与 br_pbp_parse.parse_pbp 解析器。使用全新 profile 目录绕开 SingletonLock，
build_driver 带重试，单场异常只记录、继续，绝不让异常跳过末尾验证段。

运行（铁律：从项目根目录 + 设置 PYTHONPATH，否则 common 模块 import 失败）：
  cd <project_root> && PYTHONPATH=<project_root> .venv/bin/python fix_mia_phantom.py
"""
from __future__ import annotations

import os
import sys
import time
import shutil
import argparse
from collections import Counter

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
from selenium.common.exceptions import WebDriverException  # noqa: E402

# 关键修复：用全新 profile 目录，彻底绕开旧 .uc_pbp_profile / .uc_pbp_profile_run2
# 的 SingletonLock（旧锁会让 chrome 起不来，build_driver 抛 SessionNotCreatedException）。
_UDC_DIR = os.path.join(HERE, ".uc_fix_mia_profile")
os.makedirs(_UDC_DIR, exist_ok=True)
_bf.UDC_DIR = _UDC_DIR

PBP_URL = "https://www.basketball-reference.com/boxscores/pbp/{gid}.html"

REAL_GID = "202310290PHI"     # 真实场（POR@PHI，126-98），dim_games 正确行
REAL_AWAY = "POR"             # 真实客队 = 开拓者（绝不可写成 MIA）
REAL_HOME = "PHI"             # 真实主队 = 76人
PHANTOM_GID = "202310290MIA"  # 幽灵行（本任务删除，2023-10-29 MIA 根本没打）

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


def get_real_game_meta(conn):
    """读取真实场 202310290PHI 的元数据：赛季（覆盖 parse_pbp 写死的 2026）、
    主客队（核对一致性）、比赛日期。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT season, away_team_abbr, home_team_abbr, game_date "
            "FROM dim_games WHERE game_id=%s",
            (REAL_GID,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"真实场 {REAL_GID} 在 dim_games 中不存在，无法继续")
    season, away, home, gdate = row
    return {
        "season": int(season) if season is not None else 2024,
        "away": (away or "").strip(),
        "home": (home or "").strip(),
        "game_date": (gdate.isoformat() if hasattr(gdate, "isoformat") else str(gdate)),
    }


def phase1_delete_phantom(conn):
    """阶段1：精确靶向删除幽灵行 202310290MIA。删前/删后均 SELECT 确认。"""
    print("\n=== 阶段1: 删除幽灵行 202310290MIA ===", flush=True)
    with conn.cursor() as cur:
        # 删前确认当前行数
        cur.execute(
            "SELECT count(*) FROM play_by_play WHERE gameid=%s AND source='BBRef'",
            (PHANTOM_GID,),
        )
        pbp_before = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM game_id_map WHERE br_gid=%s", (PHANTOM_GID,))
        map_before = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM dim_games WHERE game_id=%s", (PHANTOM_GID,))
        dim_before = cur.fetchone()[0]
        print(
            f"  [确认-删前] play_by_play.BBRef={pbp_before}  "
            f"game_id_map={map_before}  dim_games={dim_before}",
            flush=True,
        )

        # 精确靶向删除（先子表再父表，安全）
        cur.execute(
            "DELETE FROM play_by_play WHERE gameid=%s AND source='BBRef'",
            (PHANTOM_GID,),
        )
        del_pbp = cur.rowcount
        cur.execute("DELETE FROM game_id_map WHERE br_gid=%s", (PHANTOM_GID,))
        del_map = cur.rowcount
        cur.execute("DELETE FROM dim_games WHERE game_id=%s", (PHANTOM_GID,))
        del_dim = cur.rowcount

        # 删后确认
        cur.execute("SELECT count(*) FROM play_by_play WHERE gameid=%s", (PHANTOM_GID,))
        pbp_after = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM game_id_map WHERE br_gid=%s", (PHANTOM_GID,))
        map_after = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM dim_games WHERE game_id=%s", (PHANTOM_GID,))
        dim_after = cur.fetchone()[0]
        print(
            f"  [删除] play_by_play 删 {del_pbp} 行 | "
            f"game_id_map 删 {del_map} 行 | dim_games 删 {del_dim} 行",
            flush=True,
        )
        print(
            f"  [确认-删后] play_by_play={pbp_after}  "
            f"game_id_map={map_after}  dim_games={dim_after}",
            flush=True,
        )
    conn.commit()
    print("  [已提交] 阶段1 删除已 commit。", flush=True)
    return dict(
        del_pbp=del_pbp, del_map=del_map, del_dim=del_dim,
        pbp_before=pbp_before, map_before=map_before, dim_before=dim_before,
        pbp_after=pbp_after, map_after=map_after, dim_after=dim_after,
    )


def phase2_fill_real(conn, driver, limiter, meta):
    """阶段2：抓取真实场 202310290PHI 正确 PBP（away=POR, home=PHI）并灌库。"""
    print("\n=== 阶段2: 灌入真实场 202310290PHI 正确 PBP (POR@PHI) ===", flush=True)
    url = PBP_URL.format(gid=REAL_GID)
    soup, status = None, None
    last_exc = None
    for attempt in range(1, MAX_PAGE_RETRY + 1):
        try:
            limiter.wait()  # 严格 <=15 BR 请求/分钟
            soup, status = fetch_pbp_soup(
                driver, url, br_gid=REAL_GID, season=meta["season"],
                game_date=meta["game_date"],
            )
            if soup is not None or status == "404":
                break
        except (SessionGone, WebDriverException) as e:
            # 任何浏览器崩溃（SessionGone / NoSuchWindow / 其它 WebDriverException）
            # 都清理并重建 driver 后重试，避免单场异常跳过写入与验证段。
            last_exc = e
            print(
                f"  ! 抓取异常({type(e).__name__}): {e}; "
                f"重建 driver 重试(第{attempt}次)...",
                flush=True,
            )
            try:
                driver.quit()
            except Exception:
                pass
            driver = build_driver_retry()
            soup, status = None, "driver_rebuilt"

    if soup is None:
        raise RuntimeError(
            f"抓取 {REAL_GID} 失败: status={status} "
            f"last_exc={type(last_exc).__name__ if last_exc else None}"
        )

    # 解析：away=POR / home=PHI（BR URL 后缀 PHI=主队，真实是 POR 客场@PHI）
    rows = parse_pbp(soup, REAL_AWAY, REAL_HOME, REAL_GID)
    if not rows:
        raise RuntimeError(f"解析 {REAL_GID} 得到 0 行, 疑似页面结构变化")

    # 修正 season 为库内赛季（parse_pbp 写死 2026，须覆盖为真实赛季）
    season = meta["season"]
    for r in rows:
        r["season"] = season

    # 统计 team 分布（必须仅 PHI / POR）
    dist = Counter(r["team"] for r in rows)
    print(
        f"  [解析] events={len(rows)}  team分布={dict(dist)} "
        f"(预期仅 {REAL_HOME}/{REAL_AWAY})",
        flush=True,
    )
    bad = [t for t in dist if t not in (REAL_HOME, REAL_AWAY, None)]
    if bad:
        raise RuntimeError(f"team 分布异常, 出现非 {REAL_HOME}/{REAL_AWAY} 的值: {bad}")
    if None in dist:
        print(
            f"  [注意] 存在 team=NULL 的行 {dist[None]} 条（中性事件，如跳球/节末），"
            f"不计入 PHI/POR 分布校验。",
            flush=True,
        )

    with conn.cursor() as cur:
        # 幂等：先删本 gameid 的 BBRef 行，再批量 INSERT
        cur.execute(
            "DELETE FROM play_by_play WHERE gameid=%s AND source='BBRef'",
            (REAL_GID,),
        )
        del_before = cur.rowcount
        execute_batch(cur, INSERT_SQL, rows, page_size=200)
        inserted = len(rows)
        # 翻标志（本就 True，再确认一次）
        cur.execute(
            "UPDATE dim_games SET pbp_imported=true WHERE game_id=%s", (REAL_GID,)
        )
    conn.commit()
    print(
        f"  [写入] 删除旧 BBRef 行 {del_before} 条后插入 {inserted} 条 | "
        f"team分布={dict(dist)}",
        flush=True,
    )
    print("  [已提交] 阶段2 写入已 commit。", flush=True)
    return dict(inserted=inserted, del_before=del_before, dist=dict(dist)), driver


def phase3_verify(conn):
    """阶段3：自带验证段（打印 6 条查询）。"""
    print("\n=== 阶段3: 验证 ===", flush=True)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM play_by_play WHERE gameid=%s AND source='BBRef'",
            (REAL_GID,),
        )
        v1 = cur.fetchone()[0]
        print(f"[V1] play_by_play(202310290PHI, BBRef) 行数 = {v1}", flush=True)

        cur.execute(
            "SELECT team, count(*) FROM play_by_play "
            "WHERE gameid=%s AND source='BBRef' GROUP BY 1 ORDER BY 2 DESC",
            (REAL_GID,),
        )
        v2 = cur.fetchall()
        print(f"[V2] team 分布 = {v2}", flush=True)

        cur.execute("SELECT count(*) FROM dim_games WHERE game_id=%s", (PHANTOM_GID,))
        v3 = cur.fetchone()[0]
        print(f"[V3] dim_games(202310290MIA) 行数 = {v3}", flush=True)

        cur.execute("SELECT count(*) FROM play_by_play WHERE gameid=%s", (PHANTOM_GID,))
        v4 = cur.fetchone()[0]
        print(f"[V4] play_by_play(202310290MIA) 行数 = {v4}", flush=True)

        cur.execute(
            "SELECT game_id, home_team_abbr, away_team_abbr "
            "FROM dim_games WHERE game_id=%s",
            (REAL_GID,),
        )
        v5 = cur.fetchone()
        print(f"[V5] dim_games(202310290PHI) = {v5}", flush=True)

        cur.execute(
            "SELECT br_gid, nba_api_id FROM game_id_map "
            "WHERE br_gid IN (%s,%s) ORDER BY br_gid",
            (PHANTOM_GID, REAL_GID),
        )
        v6 = cur.fetchall()
        print(f"[V6] game_id_map(202310290MIA/PHI) = {v6}", flush=True)
    return dict(v1=v1, v2=v2, v3=v3, v4=v4, v5=v5, v6=v6)


def run(args):  # noqa: C901
    conn = psycopg2.connect(**DB)
    conn.autocommit = False

    # 读取真实场元数据（赛季覆盖 + 主客队核对）
    meta = get_real_game_meta(conn)
    print(
        f"[i] 真实场 {REAL_GID}: season={meta['season']} "
        f"away={meta['away']} home={meta['home']} date={meta['game_date']}",
        flush=True,
    )
    if (meta["away"], meta["home"]) != (REAL_AWAY, REAL_HOME):
        print(
            f"[!] 警告: dim_games 主客队=({meta['away']}@{meta['home']}) 与"
            f"预期真实对阵=({REAL_AWAY}@{REAL_HOME}) 不一致！请核查。",
            flush=True,
        )
    else:
        print(
            f"[i] 主客队核对一致: away={REAL_AWAY}, home={REAL_HOME}", flush=True
        )

    p1: dict = {}
    p2: dict = {}
    driver = None
    try:
        driver = build_driver_retry()
        limiter = RateLimiter(max_per_minute=15, min_interval=4.5)

        # 阶段1（纯 DB 操作，不依赖抓取）
        p1 = phase1_delete_phantom(conn)

        # 阶段2（抓取 + 写库），独立 try，失败仅记日志、rollback，不阻断验证段
        try:
            p2, driver = phase2_fill_real(conn, driver, limiter, meta)
        except Exception as e:
            print(
                f"[!] 阶段2 抓取出错: {type(e).__name__}: {e}", flush=True
            )
            try:
                conn.rollback()
            except Exception:
                pass
    except Exception as e:
        print(
            f"[FATAL] 初始化/阶段1 失败: {type(e).__name__}: {e}", flush=True
        )
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    # 阶段3 验证段：无论前面如何都执行（展示当前库真实状态）
    p3 = phase3_verify(conn)
    conn.close()

    # 汇总
    print("\n=== 汇总 ===", flush=True)
    print(
        f"  阶段1 删除: play_by_play.BBRef 删 {p1.get('del_pbp')} 行"
        f"(删前 {p1.get('pbp_before')}, 删后 {p1.get('pbp_after')}) | "
        f"game_id_map 删 {p1.get('del_map')} 行"
        f"(删前 {p1.get('map_before')}, 删后 {p1.get('map_after')}) | "
        f"dim_games 删 {p1.get('del_dim')} 行"
        f"(删前 {p1.get('dim_before')}, 删后 {p1.get('dim_after')})",
        flush=True,
    )
    print(
        f"  阶段2 插入: 202310290PHI 插入 {p2.get('inserted')} 行, "
        f"删除旧 BBRef {p2.get('del_before')} 行, "
        f"team分布={p2.get('dist')}",
        flush=True,
    )
    print(
        f"  阶段3 验证: V1={p3.get('v1')} V3={p3.get('v3')} "
        f"V4={p3.get('v4')} V5={p3.get('v5')} V6={p3.get('v6')}",
        flush=True,
    )
    return p1, p2, p3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="仅打印计划，不执行删除/写入（保留用于安全预览）")
    args = ap.parse_args()
    if args.dry_run:
        print("[DRY-RUN] 此脚本含不可逆 DELETE，dry-run 仅展示元数据后退出。", flush=True)
        conn = psycopg2.connect(**DB)
        meta = get_real_game_meta(conn)
        print(f"[i] 真实场 {REAL_GID}: {meta}", flush=True)
        with conn.cursor() as cur:
            for label, sql, params in [
                ("play_by_play.BBRef",
                 "SELECT count(*) FROM play_by_play WHERE gameid=%s AND source='BBRef'",
                 (PHANTOM_GID,)),
                ("game_id_map",
                 "SELECT count(*) FROM game_id_map WHERE br_gid=%s",
                 (PHANTOM_GID,)),
                ("dim_games",
                 "SELECT count(*) FROM dim_games WHERE game_id=%s",
                 (PHANTOM_GID,)),
            ]:
                cur.execute(sql, params)
                print(f"  [DRY] 将删除 {label}: 当前 {cur.fetchone()[0]} 行", flush=True)
        conn.close()
        return
    run(args)


if __name__ == "__main__":
    main()
