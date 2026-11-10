#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daemon/watchdog.py — v2 看门狗（忠实还原 crawler_watchdog_v2.sh 的运维语义）

还原的关键语义（严禁凭空猜，逐条对照旧脚本）：
  1. 监管 crawler driver(runner.py) / Chrome CDP(9223) 存活；
     CDP 死则复用旧 launch_chrome_cdp.sh 思路重启（shell out，旧脚本不改动）。
  2. 卡死判定用【DB 行数】(player_gamelog 当前季行数) 而非日志 mtime ——
     CF 墙时爬虫狂写 ERR 行(mtime 很新)但行数不动，mtime 法会漏判。
  3. CF 墙判定：连续 MAX_STALL 次卡死 → 写 PAUSED 并退出（不空转烧 IP）。
  4. 单例锁(lock 文件) / stop 标志文件 / heartbeat 心跳文件。
  5. 子命令：status（看状态/进程/9223）、stop（写标志下轮退出）。
  6. 两段式停止爬虫树（TERM→等待→KILL→等待），拉起前确认旧进程死透，
     杜绝新旧爬虫并发删插同一季互相踩数据（crawler_watchdog_v2.sh [P0-②]）。
  7. DB 查询失败与「行数=0/不变」区分：失败时跳过本轮卡死判定，
     不把 DB 抖动累计成 CF 墙误杀（v2 修复点）。

本文件只在 crawler_v2/daemon/ 新建，绝不改动旧 crawler/ 脚本。
"""
import argparse
import importlib.util
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---- 路径（从本文件推导，避免硬编码 ROOT）----
HERE = Path(__file__).resolve().parent            # crawler_v2/daemon
CRAWLER_V2 = HERE.parent                          # crawler_v2
ROOT = CRAWLER_V2.parents[1]                      # nba_desktop_omega_mac_migrate_2026-07-13
LAUNCH_CHROME = ROOT / "launch_chrome_cdp.sh"
LOGDIR = ROOT / "logs"
LOGDIR.mkdir(exist_ok=True)

WATCHLOG = LOGDIR / "crawler_watchdog.log"
STATUS = LOGDIR / "crawler_watchdog.status"
HEARTBEAT = LOGDIR / "crawler_watchdog.heartbeat"
PIDFILE = LOGDIR / "crawler_watchdog.pid"
STOPFLAG = LOGDIR / "crawler_watchdog.stop"
STATE = LOGDIR / "recrawl_done_2004_2026.txt"
FAILURES = LOGDIR / "recrawl_failed_2004_2026.txt"
BYPASSED = LOGDIR / "recrawl_bypassed_2004_2026.txt"
STOP_AFTER_FLAG = LOGDIR / "stop_after_season.flag"
DRIVER = CRAWLER_V2 / "daemon" / "runner.py"
DRIVER_OUT = LOGDIR / "crawler_watchdog.driver.out"

# ---- 调参（与 crawler_watchdog_v2.sh 一致）----
CDP_PORT = 9223
SLEEP_LOOP = 30           # 主循环间隔(秒)
STALL_MINUTES = 30        # 当前季行数多久无增长判定为卡死
MAX_STALL = 3             # 连续卡死几次 → 判定 CF 墙 → PAUSE 退出
KILL_TERM_WAIT = 15       # TERM 后等进程自行退出的秒数
KILL_KILL_WAIT = 15       # KILL 后确认消失的秒数

# 进程匹配模式（v2：runnner.py 为 driver；适配器/旧 crawler 一并纳入清理）
DRIVER_PATTERNS = ["runner.py", "recrawl_2004_2026"]
CRAWLER_PATTERNS = ["runner.py", "br_gamelog_adapter", "br_pbp_adapter",
                    "crawl_br_gamelog.py", "recrawl_2004_2026"]

# 把 crawler_v2 加入 path 以便 import core / 载入 runner.SEASONS
sys.path.insert(0, str(CRAWLER_V2))
try:
    from core.config import clear_outbound_proxy, get_db_config  # noqa: E402
except Exception:  # pragma: no cover —— py_compile 阶段不影响语法
    get_db_config = None
    clear_outbound_proxy = lambda: None

LOG = logging.getLogger("br_crawler_v2.watchdog")

# 模块级卡死追踪状态
_LAST_ROWS = None
_LAST_TS = 0.0


# ============================ 基础工具 ============================
def log(msg, *args):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + (msg % args if args else msg)
    try:
        with WATCHLOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def set_status(s):
    try:
        STATUS.write_text(s, encoding="utf-8")
        HEARTBEAT.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n  " + s + "\n",
                             encoding="utf-8")
    except Exception:
        pass


def cdp_alive():
    """CDP(9223) 健康检查：端口活着即可（GET /json/version，零 tab 创建）。"""
    import urllib.request
    url = f"http://127.0.0.1:{CDP_PORT}/json/version"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def start_chrome():
    """复用旧 launch_chrome_cdp.sh 重启 CDP Chrome（detach 成独立会话）。"""
    if cdp_alive():
        return True
    if not LAUNCH_CHROME.exists():
        log("[cdp] 找不到 launch_chrome_cdp.sh: %s", LAUNCH_CHROME)
        return False
    log("[cdp] Chrome 不存活，尝试重启 (launch_chrome_cdp.sh)...")
    try:
        with open(LOGDIR / "crawler_watchdog.chrome.out", "a", encoding="utf-8") as out:
            subprocess.Popen(
                ["bash", str(LAUNCH_CHROME)],
                stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True,           # 等价于旧脚本 os.setsid 脱离看门狗会话
                env=dict(os.environ),
            )
    except Exception as e:
        log("[cdp] 启动失败: %s", e)
        return False
    for _ in range(30):
        time.sleep(2)
        if cdp_alive():
            log("[cdp] Chrome 已重启 (9223 活)")
            return True
    log("[cdp] !! Chrome 重启后 60s 内未就绪（可能需人工过 CF）")
    return False


def current_season():
    """当前正在爬的季（取最新 recrawl_gamelog_*.log 文件名中的年份）。"""
    import re
    files = sorted(LOGDIR.glob("recrawl_gamelog_*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    m = re.search(r"recrawl_gamelog_(\d+)\.log", files[0].name)
    return int(m.group(1)) if m else None


def season_rows(season):
    """当前季 player_gamelog 行数；查询失败返回 'ERR'（与数值区分）。"""
    if get_db_config is None:
        return "ERR"
    import psycopg2
    try:
        conn = psycopg2.connect(connect_timeout=10, **get_db_config())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM player_gamelog WHERE season=%s;", (season,))
                row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as e:
        log("[season_rows] DB 查询失败: %s", e)
        return "ERR"


def _count_file(p):
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip().isdigit() and len(line.strip()) == 4:
            n += 1
    return n


def state_count():
    return _count_file(STATE)


def done_count():
    """已「处理完」的季 = STATE(真通过)+BYPASSED(500绕开)+FAILURES(真缺口放弃)。"""
    return _count_file(STATE) + _count_file(BYPASSED) + _count_file(FAILURES)


def total_seasons():
    """从 runner.SEASONS 动态取总数（等价于旧脚本解析 driver 的 SEASONS 数组）。"""
    try:
        spec = importlib.util.spec_from_file_location("v2runner", str(DRIVER))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return len(list(mod.SEASONS))
    except Exception:
        return 47  # 2026..1980 共 47 季的兜底值


# ============================ 进程管理（两段式）============================
def _pids_for(pattern):
    try:
        out = subprocess.run(["pgrep", "-f", pattern],
                             capture_output=True, text=True).stdout
        return [int(x) for x in out.split() if x.strip().isdigit()]
    except Exception:
        return []


def _any_alive(patterns):
    return any(_pids_for(p) for p in patterns)


def _pkill(pattern, sig):
    try:
        subprocess.run(["pkill", f"-{sig}", "-f", pattern],
                       capture_output=True, text=True)
    except Exception:
        pass


def kill_crawler_tree(label):
    """v2 核心：两段式停止爬虫树（TERM→确认→KILL→确认）。返回 True=已清空。"""
    pids = set()
    for pat in CRAWLER_PATTERNS:
        pids.update(_pids_for(pat))
    if not pids:
        log("[kill:%s] 无爬虫进程，跳过", label)
        return True
    log("[kill:%s] 发送 SIGTERM (recrawl_2004_2026* + 适配器)...", label)
    for pat in CRAWLER_PATTERNS:
        _pkill(pat, 15)
    for _ in range(KILL_TERM_WAIT):
        if not _any_alive(CRAWLER_PATTERNS):
            log("[kill:%s] TERM 后已退出", label)
            return True
        time.sleep(1)
    log("[kill:%s] TERM %ds 未退净，升级 kill -9（逐 pgid）...", label, KILL_TERM_WAIT)
    for pid in list(pids):
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, 9)
        except Exception:
            pass
        try:
            os.kill(pid, 9)
        except Exception:
            pass
    for _ in range(KILL_KILL_WAIT):
        if not _any_alive(CRAWLER_PATTERNS):
            log("[kill:%s] KILL 后已全部消失", label)
            return True
        time.sleep(1)
    log("[kill:%s] !! kill -9 后仍有残留进程，本轮不拉新（防并发踩数据）", label)
    return False


# ============================ 卡死 / CF 墙 ============================
def is_stalled():
    """卡死检测：当前季行数在 STALL_MINUTES 内无增长 → 卡死。
    DB 查询失败(ERR)跳过本轮，不累计卡死也不算有进展。"""
    global _LAST_ROWS, _LAST_TS
    S = current_season()
    if S is None:
        return False
    rows = season_rows(S)
    if rows == "ERR":
        log("[stall] DB 查询失败（区别于行数不变），本轮跳过卡死判定")
        return False
    now = time.time()
    if rows != _LAST_ROWS:
        _LAST_ROWS = rows
        _LAST_TS = now
        return False  # 有增长 → 未卡死
    age = (now - _LAST_TS) / 60.0
    if age >= STALL_MINUTES:
        return True
    return False


def start_driver():
    """拉起 v2 driver(runner.py)，detach 成独立会话，避免被平台回收连累爬虫树。"""
    log("[driver] 未运行，拉起 runner.py (当前 done=%d)", done_count())
    set_status("RUNNING (restart)")
    try:
        with open(DRIVER_OUT, "a", encoding="utf-8") as out:
            subprocess.Popen(
                [sys.executable, str(DRIVER)],
                stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True,
                env=dict(os.environ),
            )
    except Exception as e:
        log("[driver] 拉起失败: %s", e)
        return False
    time.sleep(5)
    return True


def _stop_after_target():
    if not STOP_AFTER_FLAG.exists():
        return None
    t = STOP_AFTER_FLAG.read_text(encoding="utf-8").strip()
    if not t:
        return None
    done = set()
    for p in (STATE, FAILURES):
        if p.exists():
            done.update(l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                        if l.strip().isdigit() and len(l.strip()) == 4)
    return t if t in done else None


# ============================ 子命令 ============================
def cmd_status():
    print("=== crawler_watchdog 状态 ===")
    if STATUS.exists():
        print(STATUS.read_text(encoding="utf-8").strip())
    else:
        print("(无状态文件)")
    print("--- 进程 ---")
    for label, pat in (("看门狗", "watchdog.py"),
                       ("driver", "runner.py"),
                       ("适配器", "br_gamelog_adapter|br_pbp_adapter|crawl_br_gamelog.py")):
        pids = _pids_for(pat)
        print(f"  {label}: {'未运行' if not pids else 'pid ' + ','.join(map(str, pids))}")
    print("--- 9223 ---")
    print("alive" if cdp_alive() else "down")
    return 0


def cmd_stop():
    STOPFLAG.touch()
    print("已写 stop 标志，看门狗将在下个循环退出。")
    return 0


# ============================ 主循环 ============================
def main_loop():
    # 单例锁
    if PIDFILE.exists():
        old = PIDFILE.read_text(encoding="utf-8").strip()
        if old and _pids_for(f"^{old}$"):
            log("看门狗已在运行 (pid %s)，退出。", old)
            return 0
    PIDFILE.write_text(str(os.getpid()), encoding="utf-8")

    def cleanup(signum=None, frame=None):
        try:
            PIDFILE.unlink(missing_ok=True)
        except Exception:
            pass
        log("[watchdog] 退出 (pid %d)", os.getpid())
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    import atexit
    atexit.register(lambda: PIDFILE.unlink(missing_ok=True))

    if clear_outbound_proxy is not None:
        try:
            clear_outbound_proxy()
        except Exception:
            pass

    total = total_seasons()
    log("===== WATCHDOG START (pid %d, total_seasons=%d) =====", os.getpid(), total)
    stall_count = 0

    while True:
        # 0) 停止标志
        if STOPFLAG.exists():
            STOPFLAG.unlink(missing_ok=True)
            PIDFILE.unlink(missing_ok=True)
            log("[watchdog] 收到 stop 标志，退出。")
            return 0

        # 1) 全部赛季完成(含 500 绕开/真缺口放弃) → 成功退出（避免空跑）
        sc = done_count()
        if sc >= total:
            set_status(f"DONE: {total} 季全部处理完 (STATE+BYPASSED+FAILURES)")
            log("[watchdog] 已处理 %d/%d 季 → 全部完成，退出。", sc, total)
            PIDFILE.unlink(missing_ok=True)
            return 0

        # 2) CDP Chrome 健康
        if not cdp_alive():
            if not start_chrome():
                log("[cdp] 重启失败，60s 后重试")
                time.sleep(60)
                continue

        # 2.5) stop_after_season 防御：目标季已结束且 driver 已转向其它季 → 杀树退出
        target = _stop_after_target()
        if target is not None:
            cs = current_season()
            if cs is not None and cs != int(target):
                log("[watchdog] 目标季 %s 已结束，driver 已转向 %s —— 停止整栈。", target, cs)
                kill_crawler_tree("stop_after")
                PIDFILE.unlink(missing_ok=True)
                return 0

        # 3) driver 是否在跑
        if not _any_alive(DRIVER_PATTERNS):
            # 3.5) 目标季已结束且 driver 未运行 → 不重启，直接退出
            if target is not None and not _any_alive(DRIVER_PATTERNS):
                log("[watchdog] 目标季 %s 已结束且 driver 未运行 —— 不重启，退出。", target)
                PIDFILE.unlink(missing_ok=True)
                return 0
            # v2：拉新前先确认没有垂死的旧爬虫进程（防并发）
            if _any_alive(CRAWLER_PATTERNS):
                log("[driver] driver 未运行但 crawler 进程残留 → 先清理再拉新")
                if not kill_crawler_tree("pre_restart"):
                    time.sleep(30)
                    continue
            if not start_driver():
                time.sleep(5)
                continue
            continue

        # 4) 卡死 / CF 墙检测（两段式杀树 + 确认死透才继续）
        if is_stalled():
            stall_count += 1
            log("[stall] 检测到卡死(当前季 %d 分钟内无写入)，stall_count=%d",
                STALL_MINUTES, stall_count)
            if kill_crawler_tree("stall"):
                if stall_count >= MAX_STALL:
                    set_status(
                        f"PAUSED: 连续 {MAX_STALL} 次卡死，疑似 CF 墙 — "
                        f"需人工过 Cloudflare 验证后重启看门狗")
                    log("[watchdog] 连续 %d 次卡死 → 判定 CF 墙，PAUSE 并退出。", MAX_STALL)
                    PIDFILE.unlink(missing_ok=True)
                    return 0
            else:
                log("[stall] 爬虫树未能死透，本轮不重启（下轮重试清理）")
                time.sleep(30)
                continue
        else:
            stall_count = 0

        set_status(f"RUNNING (done={sc}/{total})")
        time.sleep(SLEEP_LOOP)


def main():
    ap = argparse.ArgumentParser(description="v2 爬虫看门狗")
    ap.add_argument("cmd", nargs="?", choices=["status", "stop"], default=None,
                    help="status=查看状态; stop=写标志下轮退出; 省略=常驻运行")
    args = ap.parse_args()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "stop":
        return cmd_stop()
    return main_loop()


if __name__ == "__main__":
    sys.exit(main() or 0)
