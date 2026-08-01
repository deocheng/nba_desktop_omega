#!/usr/bin/env python3
"""crawl_orchestrator.py — BR-only 轮换爬取调度器（实施计划 v1）。

核心机制：
  1. 从 orchestrator_tasks.TASKS 选下一个任务：
     优先级高 + 距上次运行最久 + 不在 cooldown + 依赖已满足 + 仍有缺口。
  2. 启动子进程（Popen, start_new_session），注入 env：
       * 代理消毒（清掉死代理，防空白页泄漏）
       * CDP=9223
       * CF_* 收紧：CF_MAX_COOLDOWNS=1 / CF_COOLDOWN=120 / CF_COOLDOWN_TRIGGER_S=90
         → 撞墙后 ~90-120s 内快速退出，由调度器接管"切任务"（而非进程内空转冷却）。
  3. 监控子进程：退出 OR 运行超 ROTATE_AFTER_S → 切下一任务（主动轮换，打破单一模式）。
  4. 退出后查探针 SQL：缺口==0 → 标记完成移出；>0 → 轮换；None 探针 → 按进程退出决策。
  5. alive/进度判据：查日志最近写入 + 缺口是否下降，防 wedged 误报（修复 handoff_watcher 盲区）。

用法：
  python crawl_orchestrator.py            # 常驻循环
  python crawl_orchestrator.py --once     # 每个任务各跑一轮（到时或退出即切）后退出（测试用）
  python crawl_orchestrator.py --dry-run  # 只打印任务选择，不启动进程

约束（遵守数据四性 / 铁律）：
  - 各任务独立落库 + 幂等 ON CONFLICT，轮换互不冲突。
  - 不重写任何爬虫核心逻辑；仅启停子进程 + 传 --resume。
  - 节流铁律不变（≤5 req/s，~7s/req）；轮换 ≠ 提速。
"""
import os
import sys
import time
import json
import signal
import subprocess
import datetime
import argparse

import psycopg2

PROJECT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
STATE_FILE = "/Volumes/12T/NBA/crawl_orchestrator_state.json"
LOG = "/Volumes/12T/NBA/crawl_orchestrator.log"
POLL_S = int(os.environ.get("ORCH_POLL_S", "30"))
ROTATE_AFTER_S = int(os.environ.get("ORCH_ROTATE_AFTER_S", "1800"))  # 主动轮换窗口
WEDGED_S = int(os.environ.get("ORCH_WEDGED_S", "900"))               # 无进度判 wedged

# ── 调度评分参数（【四性 · 完整】防低优先级任务被永久饿死）──────────────
# 旧公式 priority*1000 + idle/60 下，优先级差 20 需闲置 13.9 天才能翻盘，
# 致 team_pbp(40) / headshots·nicknames·bio_ext(30) 实际永不被调度 → 数据永不完整。
# 新公式 score = priority + min(idle_hours*IDLE_WEIGHT, IDLE_BONUS_CAP)：
#   优先级差 20 → 闲置 2h 即可翻盘；封顶防长闲任务无限霸占。
IDLE_WEIGHT = float(os.environ.get("ORCH_IDLE_WEIGHT", "10"))        # 每闲置 1 小时加分
IDLE_BONUS_CAP = float(os.environ.get("ORCH_IDLE_BONUS_CAP", "200")) # 闲置加分封顶(≈20h)
NEVER_RUN_BONUS = float(os.environ.get("ORCH_NEVER_RUN_BONUS", "1000"))  # 从未运行过的绝对优先
PG = dict(host="127.0.0.1", port=5433, user="postgres",
          password="R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1", dbname="nba")

# 注入子进程的 env：撞墙快速退出 + 代理消毒 + CDP。
CHILD_ENV_EXTRA = {
    "BROWSER_BACKEND": "cdp",
    "CHROME_CDP_URL": "http://127.0.0.1:9223",
    "CF_MAX_COOLDOWNS": "1",
    "CF_COOLDOWN": "120",
    "CF_COOLDOWN_TRIGGER_S": "90",
    "CF_COOLDOWN_GROWTH": "1",
    "CF_COOLDOWN_MAX": "120",
}
PROXY_VARS = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"tasks": {}}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log(f"WARN: 状态保存失败: {e}")


def pg_conn():
    return psycopg2.connect(**PG)


def probe_gap(task: dict):
    """返回该任务剩余缺口数；无探针返回 None。异常返回 -1（视为未知，不阻塞）。"""
    sql = task.get("probe_sql")
    if not sql:
        return None
    try:
        conn = pg_conn()
        cur = conn.cursor()
        cur.execute(sql)
        n = cur.fetchone()[0]
        cur.close()
        conn.close()
        return int(n)
    except Exception as e:
        log(f"WARN: 探针查询失败 [{task['name']}]: {e}")
        return -1


def deps_satisfied(task: dict, state: dict) -> bool:
    for d in task.get("deps", []):
        st = state["tasks"].get(d, {})
        if not st.get("done"):
            return False
    return True


def choose_next_task(state: dict, tasks: list) -> dict | None:
    now = time.time()
    candidates = []
    for t in tasks:
        name = t["name"]
        st = state["tasks"].setdefault(name, {"last_run": 0, "done": False,
                                              "cooldown_until": 0, "runs": 0})
        if st.get("done"):
            continue
        if not deps_satisfied(t, state):
            continue
        if now < st.get("cooldown_until", 0):
            continue
        gap = probe_gap(t)
        if gap == 0:
            st["done"] = True
            log(f"✅ [{name}] 探针缺口==0，标记完成")
            continue
        # 评分：优先级 + 有界的空闲加成（越久越优先，均衡轮换、防饿死）
        last_run = st.get("last_run", 0) or 0
        if last_run <= 0:
            # 从未运行过：绝对优先，确保每个任务至少获得一次窗口（完整性）。
            # 注意不可直接用 now-0 作为 idle，那会得到整个 Unix 时间戳量级的失控分值。
            idle_bonus = NEVER_RUN_BONUS
        else:
            idle_bonus = min((now - last_run) / 3600.0 * IDLE_WEIGHT, IDLE_BONUS_CAP)
        score = t.get("priority", 0) + idle_bonus
        candidates.append((score, name, t, gap))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, name, t, gap = candidates[0]
    log(f"▶ 选中任务 [{name}] 优先级={t.get('priority')} 缺口={gap}（候选 {len(candidates)} 个）")
    return t


def build_child_env() -> dict:
    env = dict(os.environ)
    # 代理消毒（防死代理 → 空白页泄漏）
    for v in PROXY_VARS:
        env.pop(v, None)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    # PG 凭据注入（子进程连 5433 需要 PGPASSWORD；agent 环境不继承，须显式下发）
    _pgpw = os.environ.get("PGPASSWORD") or "R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1"
    env["PGPASSWORD"] = _pgpw
    env["DB_PASSWORD"] = _pgpw
    env.update(CHILD_ENV_EXTRA)
    # 限速：用户 2026-07-30 要求整体放缓 +2s（均值 ~9s/req）以降低 CF 累积风险评分。
    # 注入 RATE_LIMIT_* 环境变量，所有继承 BRTeamPageCrawler 的子爬虫在 import 时读取。
    env["RATE_LIMIT_BASE_S"] = os.environ.get("RATE_LIMIT_BASE_S", "8.0")
    env["RATE_LIMIT_JITTER_S"] = os.environ.get("RATE_LIMIT_JITTER_S", "2.0")
    return env


def log_recent_write_secs(task: dict) -> float:
    path = task.get("log")
    if not path:
        return 9999.0
    try:
        return time.time() - os.path.getmtime(path)
    except Exception:
        return 9999.0


def run_task(task: dict, once: bool) -> str:
    """启动并监控一个任务。返回 'done' / 'rotate' / 'wedged'。"""
    name = task["name"]
    env = build_child_env()
    log_path = task.get("log") or f"/Volumes/12T/NBA/{name}_crawl.log"
    lf = open(log_path, "a")
    log(f"  -> 启动 [{name}]: {' '.join(task['cmd'])}")
    proc = subprocess.Popen(
        task["cmd"], cwd=PROJECT, env=env,
        stdout=lf, stderr=subprocess.STDOUT,
        start_new_session=True,  # 独立进程组，便于整组 terminate
    )
    start = time.time()
    last_log_secs = log_recent_write_secs(task)
    result = "rotate"
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                log(f"  <- [{name}] 进程退出 rc={rc}（运行 {time.time()-start:.0f}s）")
                result = "done" if rc == 0 else "rotate"
                break
            # 主动轮换窗口
            if time.time() - start >= ROTATE_AFTER_S:
                log(f"  ⏱️ [{name}] 已达轮换窗口 {ROTATE_AFTER_S}s，主动切换")
                result = "rotate"
                break
            # wedged 判据：日志很久没动（且已超过最小运行期）
            cur_secs = log_recent_write_secs(task)
            if cur_secs > WEDGED_S and time.time() - start > WEDGED_S:
                # 缺口是否下降？简单近似：连续两窗口缺口不变则判 wedged
                if cur_secs > last_log_secs + 1:
                    log(f"  ⚠️ [{name}] 日志静止 {cur_secs:.0f}s，疑似 wedged，切换")
                    result = "wedged"
                    break
            last_log_secs = cur_secs
            time.sleep(POLL_S)
    finally:
        if proc.poll() is None:
            log(f"  🛑 终止 [{name}] 进程组")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
            try:
                proc.wait(timeout=30)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        lf.close()
    return result


def update_state_after(task: dict, state: dict, result: str) -> None:
    name = task["name"]
    st = state["tasks"].setdefault(name, {})
    st["last_run"] = time.time()
    st["runs"] = st.get("runs", 0) + 1
    if result == "done":
        gap = probe_gap(task)
        if gap == 0 or gap is None:
            # 缺口==0，或无精确探针且进程正常退出 → 视为本批完成
            st["done"] = True
            log(f"✅ [{name}] 完成（缺口==0 或无探针且正常退出）")
        else:
            # 进程正常退出但仍有缺口 → 短暂冷却后下次再试
            st["cooldown_until"] = time.time() + 300
            log(f"↻ [{name}] 退出但缺口={gap}，冷却 300s 后重试")
    elif result == "wedged":
        st["cooldown_until"] = time.time() + 1800
        log(f"↻ [{name}] wedged，冷却 1800s")
    else:  # rotate
        # 切换出去，给该任务一个较短冷却，避免立即被重新选中
        st["cooldown_until"] = time.time() + 120
        log(f"↻ [{name}] 轮换，冷却 120s")


def main() -> None:
    ap = argparse.ArgumentParser(description="BR-only 轮换爬取调度器")
    ap.add_argument("--once", action="store_true", help="每个任务各跑一轮后退出（测试用）")
    ap.add_argument("--dry-run", action="store_true", help="只打印任务选择，不启动")
    args = ap.parse_args()

    from orchestrator_tasks import TASKS
    state = load_state()

    log("=== BR-only 轮换调度器启动 ===")
    log(f"ROTATE_AFTER_S={ROTATE_AFTER_S} WEDGED_S={WEDGED_S} POLL_S={POLL_S} once={args.once} dry_run={args.dry_run}")

    rounds = 0
    while True:
        # 周期性刷新探针缺口，清理已完成的（缺口==0）
        task = choose_next_task(state, TASKS)
        if task is None:
            log("全部任务完成或无可运行任务，调度结束。")
            break
        if args.dry_run:
            log(f"[dry-run] 将运行 [{task['name']}]，不实际启动")
            # 模拟一次轮换后的状态推进（不实际启动进程），使 dry-run 能真正遍历各任务
            update_state_after(task, state, "rotate")
            if args.once:
                rounds += 1
                if rounds >= len(TASKS):
                    break
            else:
                break
            continue

        result = run_task(task, args.once)
        update_state_after(task, state, result)
        save_state(state)

        if args.once:
            rounds += 1
            if rounds >= len(TASKS):
                log("--once 完成所有任务一轮，退出。")
                break
        # 常驻模式：短暂间隔后选下一个
        time.sleep(5)

    save_state(state)
    log("=== 调度器退出 ===")


if __name__ == "__main__":
    main()
