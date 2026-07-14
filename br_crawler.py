#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
br_crawler.py —— BR 综合爬虫(功能完整 / 无值守 / 2023→now 优先)
=================================================================
把散落、各自为战的 BR 真·爬虫统一成一个入口。全部【复用既有已验证脚本】,
绝不重写脆弱的解析器(UC+Chrome / Cloudflare / 历史球队缩写 / action_verb 抽取)。

覆盖的数据集(各对应一个经过验证的子爬虫):
  pbp      → br_fill_pbp.py            (UC+Chrome, 永远【无 --force】→ 不覆盖真实坐标)
  teams    → br_fill_teams.py          (UC+Chrome, 补全 dim_games 球队名)
  gamelog  → external_crawler/crawler/crawl_br_gamelog.py  (requests, --resume 幂等)
  player   → external_crawler/nba_daily_crawler.py --full-season S
            (per_game/advanced/shooting/per_36/per_100/totals + team_game_splits + team_totals)
  games    → external_crawler/nba_daily_crawler.py --table games --date D  (向前增量赛程/PBP 源)

特性:
  --datasets pbp teams gamelog player [games]   选定要跑的数据集(默认全 4 项)
  --seasons 2023 2024 2025 2026           赛季范围(默认 2023→now)
  --since 2023-07-01                         pbp 用"日期以来"模式(向前增量, 不重扫历史)
  --dry-run                                  只打印将要执行的命令, 不实际抓取
  --loop / --interval 3600 / --with-player  无值守循环(--loop 时默认去掉 player 以免反复重爬)
  PG 5433 探活自拉起(会话刷新杀掉也能恢复)
  统一日志 br_crawler.log + 控制台; 子爬失败自动重试 --retries 次

重要现实(写入 nba-br-crawler skill):
  2023→now 的 BR 各表【已全覆盖】(PBP 被 BBRef/ESPN/br_crawler 覆盖, 球员表已填满)。
  因此本爬虫对 2023+ 实质是【维持现状 + 抓未来新比赛】; 真正补数靠 --seasons 指定更早赛季。
  绝不对 2023+ 用 --force 跑 pbp(会 DELETE 现有行再写 BBRef, 毁掉真实坐标)。

用法:
  python br_crawler.py --dry-run
  nohup python br_crawler.py --loop --interval 3600 > br_crawler.out 2>&1 &
"""
import os
import sys
import time
import logging
import subprocess
import argparse
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(BASE, ".venv", "bin", "python")
PGCTL = "/opt/homebrew/opt/postgresql@18/bin/pg_ctl"
PGDATA = "/Users/deocheng/nba_pg"
PGPORT = 5433
PGLOG = "/tmp/nba_pg.log"
LOG_FILE = os.path.join(BASE, "br_crawler.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("br_crawler")


# ----------------------------------------------------------------------------
# PG 探活自拉起
# ----------------------------------------------------------------------------
def ensure_pg():
    """返回 True 表示 PG 5433 可用。不可用时尝试 pg_ctl 拉起。"""
    ok = subprocess.run(["pg_isready", "-h", "localhost", "-p", str(PGPORT)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if ok:
        return True
    log.warning("PG %d 未就绪, 尝试 pg_ctl 拉起...", PGPORT)
    rc = subprocess.run(
        [PGCTL, "-D", PGDATA, "-o", f"-p {PGPORT} -k /tmp", "-l", PGLOG, "start"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode
    if rc != 0:
        log.error("pg_ctl start 失败 rc=%s, 见 %s", rc, PGLOG)
        return False
    time.sleep(4)
    return subprocess.run(["pg_isready", "-h", "localhost", "-p", str(PGPORT)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


# ----------------------------------------------------------------------------
# 命令构建
# ----------------------------------------------------------------------------
def build_commands(datasets, seasons, since):
    """按数据集 + 赛季范围, 生成 [(name, [cmd...]), ...]。"""
    cmds = []
    for ds in datasets:
        if ds == "pbp":
            if since:
                cmds.append(("pbp", [PY, "br_fill_pbp.py", "--since", since]))
            else:
                cmds.append(("pbp", [PY, "br_fill_pbp.py", "--seasons"] + [str(s) for s in seasons]))
        elif ds == "bridge":
            # 跨源身份对账（G1）：扫 dim_games → upsert game_id_map（幂等）。
            # 不放 --season（默认 season>=2023 全量对账，幂等可重跑）。
            cmds.append(("bridge", [PY, "game_id_bridge.py"]))
        elif ds == "espn_broad":
            # ESPN 宽爬（G3）：抓 summary→盒式/坐标→落盘→写 espn_boxscore。
            cmds.append(("espn_broad", [PY, "espn_broad_crawler.py"]))
        elif ds == "teams":
            cmds.append(("teams", [PY, "br_fill_teams.py"]))
        elif ds == "gamelog":
            for s in seasons:
                cmds.append((f"gamelog:{s}",
                             [PY, "external_crawler/crawler/crawl_br_gamelog.py",
                              "--season", str(s), "--resume"]))
        elif ds == "player":
            for s in seasons:
                cmds.append((f"player:{s}",
                             [PY, "external_crawler/nba_daily_crawler.py",
                              "--full-season", str(s)]))
        elif ds == "games":
            cmds.append(("games",
                         [PY, "external_crawler/nba_daily_crawler.py",
                          "--table", "games", "--date", date.today().isoformat()]))
        else:
            log.warning("未知数据集 %s, 跳过", ds)
    return cmds


# ----------------------------------------------------------------------------
# 执行(带重试)
# ----------------------------------------------------------------------------
def run_cmd(name, cmd, dry_run, retries):
    if dry_run:
        log.info("[dry-run] 将执行 %s:\n    %s", name, " ".join(cmd))
        return 0
    for attempt in range(1, retries + 2):  # 首次 + retries 次
        log.info("=== 开始 %s (尝试 %d/%d) ===", name, attempt, retries + 1)
        try:
            rc = subprocess.run(cmd, cwd=BASE).returncode
        except Exception as e:  # noqa: BLE001
            rc = -1
            log.error("%s 异常: %s", name, e)
        if rc == 0:
            log.info("=== %s 完成 rc=0 ===", name)
            return 0
        log.warning("%s 失败 rc=%s", name, rc)
        if attempt <= retries:
            time.sleep(5 * attempt)
    log.error("%s 经 %d 次重试仍失败, 继续下一项", name, retries + 1)
    return rc


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def run_once(datasets, seasons, since, dry_run, retries, loop_mode):
    cmds = build_commands(datasets, seasons, since)
    if not cmds:
        log.error("没有可执行的命令(检查 --datasets / --seasons)")
        return 2
    log.info("本轮计划执行 %d 项: %s", len(cmds), ", ".join(n for n, _ in cmds))
    failed = 0
    for name, cmd in cmds:
        rc = run_cmd(name, cmd, dry_run, retries)
        if rc != 0:
            failed += 1
    log.info("本轮结束: 共 %d 项, 失败 %d", len(cmds), failed)
    return 0 if failed == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="BR 综合爬虫(功能完整 / 无值守 / 2023→now 优先)")
    ap.add_argument("--datasets", nargs="+",
                   default=["bridge", "pbp", "teams", "gamelog", "player"],
                   choices=["bridge", "pbp", "teams", "gamelog", "player", "games", "espn_broad"],
                   help="要跑的数据集(默认 bridge pbp teams gamelog player)")
    ap.add_argument("--seasons", nargs="+", type=int,
                   default=[2023, 2024, 2025, 2026],
                   help="赛季范围(默认 2023→now)")
    ap.add_argument("--since", type=str, default="2023-07-01",
                   help="pbp 用'日期以来'模式(向前增量); 置空则用 --seasons")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令不抓取")
    ap.add_argument("--retries", type=int, default=2, help="单命令失败重试次数")
    ap.add_argument("--loop", action="store_true", help="无值守循环")
    ap.add_argument("--interval", type=int, default=3600, help="--loop 间隔秒")
    ap.add_argument("--with-player", action="store_true",
                   help="--loop 时也跑 player(默认循环模式去掉 player 以免反复重爬)")
    args = ap.parse_args()

    datasets = list(args.datasets)
    # --loop 只做【向前增量】: 去掉一次性/重型数据集, 保留 pbp(--since)+gamelog(--resume)+games(--date)
    if args.loop:
        if "teams" in datasets:
            datasets.remove("teams")
            log.info("--loop 去掉 teams(一次性补全, 向前增量不需要)")
        if "player" in datasets and not args.with_player:
            datasets.remove("player")
            log.info("--loop 去掉 player(避免反复重爬整季); --with-player 可保留")

    since = args.since if args.since else None
    log.info("BR 综合爬虫启动 | datasets=%s seasons=%s since=%s dry=%s loop=%s",
             datasets, args.seasons, since, args.dry_run, args.loop)

    if not ensure_pg():
        log.error("PG %d 不可用且无法拉起, 退出", PGPORT)
        return 3

    if args.loop:
        log.info("进入无值守循环(间隔 %ds)...", args.interval)
        while True:
            try:
                run_once(datasets, args.seasons, since, args.dry_run, args.retries, True)
            except KeyboardInterrupt:
                log.info("收到中断, 退出循环")
                break
            except Exception as e:  # noqa: BLE001
                log.exception("循环异常: %s", e)
            log.info("睡眠 %ds 后进入下一轮", args.interval)
            time.sleep(args.interval)
    else:
        return run_once(datasets, args.seasons, since, args.dry_run, args.retries, False)


if __name__ == "__main__":
    sys.exit(main() or 0)
