#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daemon/runner.py — v2 主入口/编排器，忠实还原 recrawl_2004_2026_autofill.sh。

还原的关键语义（逐条对照旧脚本，不臆造）：
  1. 赛季倒序 2026→1980 遍历；STATE 已记录季自动跳过。
  2. 每季：跑适配器 → verify_gaps.py 权威自检（门禁=rc=0 且 minutes 填充率达标）
     → 不达标则幂等重跑补齐缺口（最多 MAX_RETRY），达标写 STATE 进下一季。
  3. 智能补齐：用 verify_gaps.py --missing-ids 只爬缺口，过滤 500 bypass 文件。
  4. FAILURES（真缺口达最大重试）/ BYPASSED（剩余全为 500 绕开项）/
     STOP_AFTER 标志：语义对齐旧脚本，不空转。
  5. handoff_watcher：当某源 gap(≥2001) 归零，自动从 shot_chart 切到球队数据
     （保留此语义；旧实现未在本任务提供的脚本内，按描述建模，见下方注释）。
  6. 终检：verify_gaps.py --all。
  7. 通过 core 抽象层调用 adapters（br_gamelog_adapter / br_pbp_adapter）；
     verify_gaps 门禁复用旧 verify_gaps.py（subprocess），不重写爬取逻辑。

新增：--seasons-override（定向某季）、--dry-run（不写 STATE/FAILURES/BYPASSED，适配器 dry_run）。

本文件只在 crawler_v2/daemon/ 新建，绝不改动旧 crawler/ 脚本与 nba_daily_crawler.py。
"""
import os
import re
import sys
import time
import argparse
import subprocess
import logging
from pathlib import Path

# ---- 路径（从本文件推导，避免硬编码 ROOT）----
HERE = Path(__file__).resolve().parent            # crawler_v2/daemon
CRAWLER_V2 = HERE.parent                          # crawler_v2
ROOT = CRAWLER_V2.parents[1]                      # nba_desktop_omega_mac_migrate_2026-07-13
CRAWLER = CRAWLER_V2.parent                       # external_crawler
LOGDIR = ROOT / "logs"
sys.path.insert(0, str(CRAWLER_V2))
from core.config import get_db_config, get_cdp_url, clear_outbound_proxy  # noqa: E402

LOGDIR.mkdir(exist_ok=True)

STATE = LOGDIR / "recrawl_done_2004_2026.txt"
MASTERLOG = LOGDIR / "recrawl_2004_2026_autofill.log"
FAILURES = LOGDIR / "recrawl_failed_2004_2026.txt"
BYPASS_FILE = LOGDIR / "gamelog_500_bypass.txt"
BYPASSED = LOGDIR / "recrawl_bypassed_2004_2026.txt"
STOP_AFTER_FLAG = LOGDIR / "stop_after_season.flag"
CACHE_DIR = CRAWLER / "gamelog_cache"
VERIFY_GAPS = CRAWLER / "verify_gaps.py"

MAX_RETRY = 5              # 每季最多额外重跑次数（补齐缺口）
MIN_PCT_THRESH = 99.0      # minutes 填充达标线（DNP 本就 NULL，不计入缺失）
GAME_COV_THRESH = 0.995    # 比赛覆盖达标线（保留常量，供自检语义对齐）

# 近季优先倒序；STATE 中已记录的季自动跳过，不受顺序影响。
# 扩展下界至 1980（用户要求 1980~2013 全量爬取）。
SEASONS = list(range(2026, 1979, -1))

CDP_PORT = 9223

LOG = logging.getLogger("br_crawler_v2.runner")


# ============================ 工具 ============================
def setup_logging():
    LOG.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(MASTERLOG, encoding="utf-8")
    fh.setFormatter(fmt)
    LOG.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    LOG.addHandler(sh)


def cdp_alive():
    """Chrome(9223) 活体检查：不可达直接停，避免无谓空转。"""
    import urllib.request
    url = f"http://127.0.0.1:{CDP_PORT}/json/version"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _conn():
    import psycopg2
    return psycopg2.connect(connect_timeout=10, **get_db_config())


def readset(p):
    if not p.exists():
        return set()
    return {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
            if re.match(r"^\d{4}$", l.strip())}


def readlines(p):
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def append(p, val):
    with p.open("a", encoding="utf-8") as f:
        f.write(str(val) + "\n")


# ============================ verify_gaps 门禁（复用旧脚本）============================
def run_verify_gaps(*args, capture=False):
    """复用旧 verify_gaps.py 作权威门禁（subprocess 调用，不改旧脚本）。"""
    cmd = [sys.executable, str(VERIFY_GAPS), *[str(a) for a in args]]
    if capture:
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, (p.stdout or "")
    return subprocess.run(cmd).returncode, ""


def verify_gaps_pass(season):
    rc, _ = run_verify_gaps(season)
    return rc == 0


def verify_gaps_missing_ids(season):
    rc, out = run_verify_gaps(season, "--missing-ids", capture=True)
    return [l.strip() for l in out.splitlines() if l.strip()]


def min_pct(season):
    """minutes 填充率（与旧 selfcheck 的 SQL 一致）。"""
    sql = (
        "SELECT round(100.0*count(*) FILTER (WHERE minutes IS NOT NULL)"
        "/NULLIF(count(*),0),1) FROM player_gamelog "
        "WHERE season=%s AND br_player_id IS NOT NULL AND br_player_id <> ''")
    try:
        with _conn() as c:
            with c.cursor() as cur:
                cur.execute(sql, (season,))
                v = cur.fetchone()[0]
        return float(v) if v is not None else 0.0
    except Exception as e:
        LOG.error("[min_pct %s] DB 失败: %s", season, e)
        return 0.0


def selfcheck(season):
    """权威自检：verify_gaps rc=0 且 minutes 填充率 >= MIN_PCT_THRESH。"""
    rc, _ = run_verify_gaps(season)
    mp = min_pct(season)
    LOG.info("[selfcheck %s] min_pct=%.1f (需>=%.1f)", season, mp, MIN_PCT_THRESH)
    if rc == 0 and mp >= MIN_PCT_THRESH:
        return True
    if rc != 0:
        LOG.info("[selfcheck %s] 不达标: verify_gaps 发现逐人/覆盖缺口", season)
    else:
        LOG.info("[selfcheck %s] 不达标: min_pct=%.1f < %.1f", season, mp, MIN_PCT_THRESH)
    return False


# ============================ 适配器调用（import 优先，CLI 回退）============================
def call_adapter(module_name, season, gap_file, dry_run):
    """调用某数据源适配器。优先 import 调用（任务要求），失败回退 CLI（与旧
    crawl_br_gamelog.py 等价，不重写爬取逻辑）。adapter 接口约定（假设，需与
    另一 agent 产出的 br_gamelog_adapter 对齐）：
        run(season=, only_br_ids=, bypass_500_file=, cache_dir=, dry_run=) -> rc/None
    或 CLI: python -m adapters.<module> --season S [--only-br-ids f] [--bypass-500-file f]
            [--cache-dir d] [--dry-run]
    """
    try:
        mod = __import__(module_name, fromlist=["run"])
        if hasattr(mod, "run"):
            return mod.run(season=season, only_br_ids=gap_file,
                           bypass_500_file=(BYPASS_FILE if BYPASS_FILE.exists() else None),
                           cache_dir=CACHE_DIR, dry_run=dry_run)
    except Exception as e:
        LOG.warning("import 调用 %s 失败，回退 CLI: %s", module_name, e)
    cmd = [sys.executable, "-m", f"adapters.{module_name}", "--season", str(season)]
    if gap_file is not None:
        cmd += ["--only-br-ids", str(gap_file)]
    if BYPASS_FILE.exists():
        cmd += ["--bypass-500-file", str(BYPASS_FILE)]
    cmd += ["--cache-dir", str(CACHE_DIR)]
    if dry_run:
        cmd.append("--dry-run")
    LOG.info("[call_adapter] %s", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=False).returncode


def call_gamelog_adapter(season, gap_file, dry_run):
    return call_adapter("br_gamelog_adapter", season, gap_file, dry_run)


def call_team_adapter(season, dry_run):
    """handoff_watcher 切到的「球队数据」源（假设由另一 adapter 提供，非致命）。"""
    return call_adapter("br_team_adapter", season, None, dry_run)


def _shot_chart_gap(season):
    """shot_chart 源剩余缺口（与旧 verify_gaps 同口径：player_shot_chart distinct
    gameid vs dim_games(Regular Season)）。失败抛异常交由调用方降级。"""
    sql = (
        "SELECT (SELECT count(*) FROM dim_games "
        "        WHERE season=%s AND season_type='Regular Season') "
        "     - (SELECT count(*) FROM dim_games d "
        "        WHERE d.season=%s AND season_type='Regular Season' "
        "          AND EXISTS (SELECT 1 FROM player_shot_chart s "
        "                     WHERE s.season=%s AND s.game_id::bigint=d.nba_api_id))")
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, (season, season, season))
            v = cur.fetchone()[0]
    return int(v) if v is not None else 0


def handoff_watcher(season, dry_run):
    """保留旧版语义：某源 gap(≥2001) 归零，自动从 shot_chart 切到球队数据。
    旧实现未在本任务提供的脚本内，此处按描述忠实建模：当 shot_chart 缺口为 0
    （且 season>=2001）触发切源；查询/适配器缺失则降级跳过（不致命、不空转）。
    """
    if season < 2001:
        return
    try:
        gap = _shot_chart_gap(season)
    except Exception as e:
        LOG.warning("[handoff] shot_chart 缺口查询失败（可能表/列不存在），跳过 handoff: %s", e)
        return
    if gap == 0:
        LOG.info("[handoff] season %s shot_chart 缺口归零，切到 team 数据", season)
        try:
            call_team_adapter(season, dry_run)
        except Exception as e:
            LOG.warning("[handoff] team 数据适配器调用失败（非致命）: %s", e)


def pre_delete_orphans(season):
    """清本季 gameid 与 dim_games 错配的旧编码行（重爬按当前 gameid 删不掉会留脏副本）。"""
    sql = (
        "DELETE FROM player_gamelog gl WHERE season=%s "
        "  AND (gameid IS NULL OR NOT EXISTS ("
        "    SELECT 1 FROM dim_games d WHERE d.season=%s "
        "    AND d.nba_api_id = gl.gameid::bigint));")
    try:
        with _conn() as c:
            with c.cursor() as cur:
                cur.execute(sql, (season, season))
            c.commit()
        LOG.info("[pre-delete %s] 完成", season)
    except Exception as e:
        LOG.error("[pre-delete %s] 失败: %s", season, e)


# ============================ 主流程 ============================
def main():
    ap = argparse.ArgumentParser(description="v2 BR 爬虫编排器")
    ap.add_argument("--seasons-override", nargs="+", type=int, default=None,
                    help="定向某季（如 2003）；不传则全量 2026→1980")
    ap.add_argument("--dry-run", action="store_true",
                    help="不写 STATE/FAILURES/BYPASSED，适配器以 dry_run 运行")
    args = ap.parse_args()

    setup_logging()
    clear_outbound_proxy()
    os.environ["CHROME_CDP_URL"] = get_cdp_url()
    os.environ["BROWSER_BACKEND"] = "cdp"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    LOG.info("===== AUTOFILL START =====")
    if not cdp_alive():
        LOG.error("!! Chrome(9223) 不可达 —— 请先启动 launch_chrome_cdp.sh 并保持窗口。停止。")
        sys.exit(2)

    seasons = args.seasons_override or SEASONS

    for S in seasons:
        if S in readset(STATE):
            LOG.info("----- skip season %s (STATE 已记录) -----", S)
            continue
        if S in readset(BYPASSED):
            LOG.info("----- skip season %s (已标记 BYPASSED: 剩余缺口均为 BR 500 绕开项) -----", S)
            continue
        if S in readset(FAILURES):
            LOG.info("----- skip season %s (已标记 FAILURES: 真缺口达最大重试) -----", S)
            continue

        # 每季日志（供 watchdog current_season 判定，对齐旧 recrawl_gamelog_*.log 契约）
        season_log = LOGDIR / f"recrawl_gamelog_{S}.log"

        def slog(m):
            try:
                with season_log.open("a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")
            except Exception:
                pass

        if not args.dry_run:
            pre_delete_orphans(S)

        attempt = 0
        while True:
            attempt += 1
            LOG.info("===== [%s] attempt %d/%d START =====", S, attempt, MAX_RETRY + 1)
            slog(f"attempt {attempt} START")

            # 智能补齐：先算 verify_gaps 缺口球员，只爬缺口
            raw_gap = verify_gaps_missing_ids(S)
            bypass = set(readlines(BYPASS_FILE))
            gap = [p for p in raw_gap if p not in bypass]
            raw_n, fil_n = len(raw_gap), len(gap)
            if gap:
                LOG.info("[%s] 智能补齐：仅爬 %d 名缺口球员（已排除 %d 个 500 绕开项）",
                        S, fil_n, raw_n - fil_n)
                gap_file = Path(f"/tmp/gap_{S}.txt")
                gap_file.write_text("\n".join(gap) + "\n", encoding="utf-8")
                call_gamelog_adapter(S, gap_file, args.dry_run)
            else:
                if verify_gaps_pass(S):
                    LOG.info("[%s] 无逐人缺口且 verify_gaps 通过 → 跳过爬取，直接自检", S)
                elif raw_gap:
                    # 有缺口球员但全部已被 500 绕开 → 标记 BYPASSED，跳过本季（不空转）
                    LOG.info("[%s] 剩余缺口 %d 人全部为 BR 500 绕开项 → 标记 BYPASSED，跳过本季",
                            S, raw_n)
                    if not args.dry_run:
                        append(BYPASSED, S)
                    break
                else:
                    # 无逐人缺口但比赛覆盖不足 → 整季重跑兜底
                    LOG.info("[%s] 无逐人缺口但比赛覆盖不足 → 整季重跑兜底", S)
                    call_gamelog_adapter(S, None, args.dry_run)

            if selfcheck(S):
                LOG.info("[%s] VERIFIED & DONE (attempt %d)", S, attempt)
                if not args.dry_run:
                    append(STATE, S)
                handoff_watcher(S, args.dry_run)
                break
            if attempt >= MAX_RETRY + 1:
                LOG.error("[%s] 已达最大重试(%d) 仍不达标 —— 记录到 FAILURES 并继续下一季",
                          S, MAX_RETRY)
                if not args.dry_run:
                    append(FAILURES, S)
                break
            LOG.info("[%s] 缺口补齐: 幂等重跑 (attempt %d) ...", S, attempt + 1)

        # 停止控制：本季即为「跑完即停」目标季 → 跳出，不再继续后续赛季
        if STOP_AFTER_FLAG.exists() and STOP_AFTER_FLAG.read_text(encoding="utf-8").strip() == str(S):
            LOG.info("[%s] 为 STOP_AFTER_SEASON 目标季（已完成或已放弃），停止后续赛季", S)
            break

    # 终检：用 verify_gaps --all 作权威全量校验
    LOG.info("===== BYPASSED: %d 季 =====", _count_bypassed())
    LOG.info("===== FINAL AUDIT (verify_gaps --all, 权威终检) =====")
    run_verify_gaps("--all")
    LOG.info("===== AUTOFILL FINISH =====")


def _count_bypassed():
    return len(readset(BYPASSED))


if __name__ == "__main__":
    main()
