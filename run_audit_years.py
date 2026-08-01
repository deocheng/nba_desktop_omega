#!/usr/bin/env python3
"""父驱动：把每个赛季作为独立子进程跑，父进程在 240s 硬 kill 卡死的子进程。

背景：in-process 的 threading.Timer 看门狗杀不掉真正卡死的 chromedriver（卡死在 C
扩展的 driver 调用层，Timer 线程里调 driver.quit() 也跟着阻塞 → SeasonTimeout 抛不出
来 → 进程挂到平台 ~17 分钟硬杀，循环后 compute_totals 从没跑到，TOTALS 恒空）。

本驱动的核心修复：每个赛季起一个独立子进程跑 `audit_br_schedule.py --years Y`；父进程
起 threading.Timer(240) 看门狗，到点先 terminate() 再 killpg(SIGKILL) 杀掉整个进程组
（含 chromedriver / chrome 子树），保证卡死的浏览器子树被真正回收。无论子进程返回码如何，
父进程继续下一季（kill → 子进程死，报告已原子落盘保留已合并的季）。

续跑：启动时先 json.load 报告，若某季已“完成”（有真实 BR 比赛且非 SEASON_FETCH_FAILED
且行数达门禁）则跳过 → 平台杀掉父任务后，重启动本驱动即从断点续跑（廉价，已合并季全保留）。

为在平台 ~17 分钟硬杀前干净退出，默认自限 15 分钟（跑满则优雅退出，下轮续跑）。
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time

import psycopg2

ROOT = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = "/tmp/dirty_games_report.json"
CHILD_SCRIPT = os.path.join(ROOT, "audit_br_schedule.py")
PY = sys.executable  # 父由 venv python 启动 → 子也用 venv（含全部依赖）
SEASON_KILL_SEC = 240  # 单季子进程超时 → 硬 kill 进程组
SELF_LIMIT_SEC = 15 * 60  # 父进程自限，避免被平台 ~17min 硬杀打断原子写
DB_CONN = {
    "host": "localhost",
    "port": 5433,
    "user": "postgres",
    "password": "R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1",
    "dbname": "nba",
    "connect_timeout": 30,
}


def load_dim_regular_by_season():
    """返回 {season: 常规赛行数}，用于“完成”判定（>=0.6*dim）。"""
    try:
        conn = psycopg2.connect(**DB_CONN)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SET statement_timeout=30000;"
            "SELECT season, COUNT(*) FROM dim_games "
            "WHERE season_type='Regular Season' AND season IS NOT NULL GROUP BY season;"
        )
        out = {int(s): int(c) for s, c in cur.fetchall()}
        cur.close()
        conn.close()
        return out
    except Exception as e:
        print(f"[!] 加载 dim 行数失败（仅用 br>=200 判定完成）: {e}", flush=True)
        return {}


def season_is_done(report, dim_by_season, y):
    """判定某季是否已完成（可跳过）：
    - key 存在；
    - 无 SEASON_FETCH_FAILED 标记；
    - 有真实解析到的 BR 比赛 (br_gameid) 且 br>=200 且 br>=0.6*dim（缩水季放宽）。
    """
    recs = (report.get("seasons") or {}).get(str(y))
    if not recs:
        return False
    if any("SEASON_FETCH_FAILED" in (r.get("issues") or []) for r in recs):
        return False
    br = sum(1 for r in recs if r.get("br_gameid"))
    if br < 200:
        return False
    dim = dim_by_season.get(y, 0)
    if dim and br < 0.6 * dim:
        return False
    return True


def _hard_kill(proc):
    """先 SIGTERM 整个进程组，2s 后 SIGKILL（保证杀掉卡死的浏览器子树）。"""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    time.sleep(2)
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except Exception:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass


def run_one_season(y):
    """起子进程跑单季；240s 看门狗硬 kill；返回 (returncode, killed)。"""
    env = {**os.environ, "PYTHONPATH": ROOT}
    proc = subprocess.Popen(
        [PY, CHILD_SCRIPT, "--years", str(y)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # 独立进程组 → killpg 可杀 chromedriver/chrome 子树
    )
    killed = False
    timer = threading.Timer(SEASON_KILL_SEC, _hard_kill, args=[proc])
    timer.daemon = True
    timer.start()
    try:
        # 实时转发子进程输出到父日志（便于排查）
        for line in proc.stdout:
            try:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
            except Exception:
                pass
        rc = proc.wait()
    except Exception:
        rc = proc.wait()
    finally:
        timer.cancel()
    if killed:
        pass
    return rc, killed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2001)
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--max-minutes", type=int, default=15,
                    help="父进程自限（默认 15 分钟优雅退出，下轮续跑）")
    args = ap.parse_args()

    dim_by_season = load_dim_regular_by_season()
    start_ts = time.time()
    deadline = start_ts + args.max_minutes * 60

    print("=" * 70, flush=True)
    print(f"父驱动 run_audit_years: Y in {args.start_year}..{args.end_year} "
          f"(自限 {args.max_minutes} 分钟)", flush=True)
    print(f"child={CHILD_SCRIPT}", flush=True)
    print(f"report={REPORT_PATH}", flush=True)
    print("=" * 70, flush=True)

    done_count = 0
    run_count = 0
    for y in range(args.start_year, args.end_year + 1):
        # 自限：剩余时间不足一季预算则停止发起新季（当前季跑完即退出），
        # 避免在平台 ~17min 硬杀前还卡在半途（优雅退出 → 无孤儿浏览器进程）。
        SEASON_BUDGET = 360  # 单季最坏预算（含 CF 重试），留足缓冲
        if time.time() >= deadline - SEASON_BUDGET:
            print(f"\n[i] 剩余时间不足一季预算，停止发起新季（当前季跑完退出）。"
                  f"已跳过 {done_count} / 已跑 {run_count}", flush=True)
            break

        # 载入报告判定是否已完成（续跑 / 跳过）
        report = {}
        try:
            with open(REPORT_PATH, "r", encoding="utf-8") as f:
                report = json.load(f)
        except Exception:
            report = {}
        if season_is_done(report, dim_by_season, y):
            print(f"[skip] 季 {y} 已完成（报告已有且门禁达标），跳过", flush=True)
            done_count += 1
            continue

        print(f"\n>>> 启动子进程跑季 {y} ...", flush=True)
        t0 = time.time()
        try:
            rc, killed = run_one_season(y)
        except Exception as e:
            print(f"[!] 季 {y} 父层异常: {type(e).__name__}: {e}", flush=True)
            rc, killed = -1, False
        dt = time.time() - t0
        tag = "KILLED(240s)" if killed else f"rc={rc}"
        print(f"<<< 季 {y} 结束 ({tag}, 用时 {dt:.1f}s)", flush=True)
        run_count += 1

    print("\n" + "=" * 70, flush=True)
    print(f"父驱动本轮结束：跳过已完成 {done_count} 季，本次新跑 {run_count} 季。", flush=True)
    print("若仍有缺失季，重启动本驱动即从断点续跑（已合并季全保留）。", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
