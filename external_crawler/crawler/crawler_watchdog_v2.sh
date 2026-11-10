#!/usr/bin/env bash
# =============================================================================
# crawler_watchdog_v2.sh — 看门狗 v2（修复 2026-08-16 代码审查 P0-②）
#
# 相对 crawler_watchdog.sh（原版保留不动）的修复：
#   [P0-②] 卡死杀进程改「TERM→等待确认→KILL→等待确认」两段式，且拉起新
#          driver 前轮询确认旧进程已死透 —— 杜绝 SIGTERM 杀不干净导致
#          新旧爬虫并发删插同一季 player_gamelog 互相踩数据。
#   [顺带] pkill 模式统一为 "recrawl_2004_2026"（同时覆盖旧 recrawl_2004_2026.sh
#          与现役 recrawl_2004_2026_autofill.sh，与 P0-③ 同源）。
#   [顺带] season_rows 查询失败与「行数=0/不变」区分：psql 加 connect_timeout，
#          失败时返回 ERR 并跳过本轮卡死判定（不把 DB 抖动累计成 CF 墙误杀）。
#
# 状态文件 / PIDFILE / STATE / STOP 标志与原版共用同一路径：
#   两版互斥（单例锁同文件），启用 v2 前先 `bash crawler_watchdog.sh stop`。
#
# 用法（与原版一致，WorkBuddy 环境）：
#   启动(常驻): Bash 工具 run_in_background 执行 `bash crawler_watchdog_v2.sh`
#   查看状态:   bash crawler_watchdog_v2.sh status
#   停止:       bash crawler_watchdog_v2.sh stop
# =============================================================================
set -u

PROJECT="/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
CRAWLER="$PROJECT/external_crawler/crawler"
DRIVER="$CRAWLER/recrawl_2004_2026_autofill.sh"
LAUNCH_CHROME="$PROJECT/launch_chrome_cdp.sh"
LOGDIR="$PROJECT/logs"
WATCHLOG="$LOGDIR/crawler_watchdog.log"
STATUS="$LOGDIR/crawler_watchdog.status"
HEARTBEAT="$LOGDIR/crawler_watchdog.heartbeat"
PIDFILE="$LOGDIR/crawler_watchdog.pid"
STOPFLAG="$LOGDIR/crawler_watchdog.stop"
STATE="$LOGDIR/recrawl_done_2004_2026.txt"
FAILURES="$LOGDIR/recrawl_failed_2004_2026.txt"
BYPASSED="$LOGDIR/recrawl_bypassed_2004_2026.txt"
STOP_AFTER_FLAG="$LOGDIR/stop_after_season.flag"
PSQL="/opt/homebrew/opt/postgresql@18/bin/psql"
CDP_PORT=9223
DBPASS=$(grep '^DB_PASSWORD=' "$PROJECT/.env" 2>/dev/null | head -1 | cut -d= -f2-)

# 实际赛季总数：从 driver 的 SEASONS 数组动态提取（与原版一致）
TOTAL_SEASONS=$(grep -oE 'SEASONS=\([^)]*\)' "$DRIVER" 2>/dev/null | grep -oE '[0-9]{4}' | wc -l | tr -d ' ')
TOTAL_SEASONS=${TOTAL_SEASONS:-23}

# 调参
SLEEP_LOOP=30
STALL_MINUTES=30
MAX_STALL=3
DRIVER_OUT="$LOGDIR/crawler_watchdog.driver.out"
KILL_TERM_WAIT=15   # TERM 后等进程自行退出的秒数
KILL_KILL_WAIT=15   # KILL 后确认消失的秒数

log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$WATCHLOG"; }
set_status(){ echo "$1" > "$STATUS"; date '+%Y-%m-%d %H:%M:%S' > "$HEARTBEAT"; echo "  $1" >> "$HEARTBEAT"; }

PY_BIN="/Users/deocheng/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
detach(){ "$PY_BIN" -c "import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])" "$@"; }

cdp_alive(){
  local code
  code=$(curl -s --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$CDP_PORT/json/version" 2>/dev/null)
  [ "$code" = "200" ]
}

start_chrome(){
  if cdp_alive; then return 0; fi
  log "[cdp] Chrome 不存活，尝试重启 (launch_chrome_cdp.sh)..."
  detach env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    bash "$LAUNCH_CHROME" >> "$LOGDIR/crawler_watchdog.chrome.out" 2>&1 &
  for i in $(seq 1 30); do
    sleep 2
    if cdp_alive; then log "[cdp] Chrome 已重启 (9223 活)"; return 0; fi
  done
  log "[cdp] !! Chrome 重启后 60s 内未就绪（可能需人工过 CF）"
  return 1
}

current_season(){
  local f
  f=$(ls -t "$LOGDIR"/recrawl_gamelog_*.log 2>/dev/null | head -1)
  [ -z "$f" ] && { echo ""; return; }
  basename "$f" | sed -E 's/.*recrawl_gamelog_([0-9]+).*/\1/'
}

# ---- 当前季 player_gamelog 行数（v2：失败返回 ERR，与数值区分）----
season_rows(){
  local S=$1 out
  [ -z "$S" ] && { echo 0; return; }
  out=$(PGPASSWORD="$DBPASS" "$PSQL" -h localhost -p 5433 -U postgres -d nba \
        -t -A -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM player_gamelog WHERE season=$S;" 2>/dev/null | tail -1)
  if [ -z "$out" ] || ! echo "$out" | grep -qE '^[0-9]+$'; then
    echo "ERR"
  else
    echo "$out"
  fi
}

state_count(){
  [ -f "$STATE" ] || { echo 0; return; }
  grep -cE '^[0-9]{4}$' "$STATE"
}

done_count(){
  local n=0
  [ -f "$STATE" ]    && n=$((n + $(grep -cE '^[0-9]{4}$' "$STATE" 2>/dev/null || echo 0)))
  [ -f "$BYPASSED" ] && n=$((n + $(grep -cE '^[0-9]{4}$' "$BYPASSED" 2>/dev/null || echo 0)))
  [ -f "$FAILURES" ] && n=$((n + $(grep -cE '^[0-9]{4}$' "$FAILURES" 2>/dev/null || echo 0)))
  echo "$n"
}

# ---- v2 核心：两段式停止爬虫树（TERM→确认→KILL→确认）----
# 模式串 "recrawl_2004_2026" 同时匹配 .sh 与 _autofill.sh 两个 driver 名。
kill_crawler_tree(){
  local label="$1" i
  pgrep -f 'recrawl_2004_2026' >/dev/null 2>&1 || pgrep -f 'crawl_br_gamelog.py' >/dev/null 2>&1 || { log "[kill:$label] 无爬虫进程，跳过"; return 0; }
  log "[kill:$label] 发送 SIGTERM (recrawl_2004_2026* + crawl_br_gamelog.py)..."
  pkill -TERM -f 'recrawl_2004_2026' 2>/dev/null
  pkill -TERM -f 'crawl_br_gamelog.py' 2>/dev/null
  for i in $(seq 1 "$KILL_TERM_WAIT"); do
    sleep 1
    pgrep -f 'recrawl_2004_2026' >/dev/null 2>&1 || pgrep -f 'crawl_br_gamelog.py' >/dev/null 2>&1 || { log "[kill:$label] TERM 后 ${i}s 内已退出"; return 0; }
  done
  log "[kill:$label] TERM ${KILL_TERM_WAIT}s 未退净，升级 kill -9（逐 pgid）..."
  # kill -9 -pgid：杀整个进程组（macOS 无 killpg 包装时的等价写法）
  for pid in $(pgrep -f 'recrawl_2004_2026' 2>/dev/null) $(pgrep -f 'crawl_br_gamelog.py' 2>/dev/null); do
    pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "$pgid" ] && kill -9 -"$pgid" 2>/dev/null
    kill -9 "$pid" 2>/dev/null
  done
  for i in $(seq 1 "$KILL_KILL_WAIT"); do
    sleep 1
    pgrep -f 'recrawl_2004_2026' >/dev/null 2>&1 || pgrep -f 'crawl_br_gamelog.py' >/dev/null 2>&1 || { log "[kill:$label] KILL 后 ${i}s 内已全部消失"; return 0; }
  done
  log "[kill:$label] !! kill -9 后仍有残留进程，本轮不拉新（防并发踩数据）"
  return 1
}

# ---- 卡死检测（v2：查询失败跳过本轮，不累计卡死也不算有进展）----
last_rows=""; last_ts=0
is_stalled(){
  local S now rows age
  S=$(current_season)
  [ -z "$S" ] && return 1
  rows=$(season_rows "$S")
  if [ "$rows" = "ERR" ]; then
    log "[stall] DB 查询失败（区别于行数不变），本轮跳过卡死判定"
    return 1
  fi
  now=$(date +%s)
  if [ "$rows" != "$last_rows" ]; then
    last_rows=$rows; last_ts=$now
    return 1   # 有增长 → 未卡死
  fi
  age=$(( (now - last_ts) / 60 ))
  if [ "$age" -ge "$STALL_MINUTES" ]; then
    return 0
  fi
  return 1
}

# ============================ 命令分支 ============================
case "${1:-}" in
  status)
    echo "=== crawler_watchdog_v2 状态 ==="
    if [ -f "$STATUS" ]; then cat "$STATUS"; else echo "(无状态文件)"; fi
    echo "--- 进程 ---"
    pgrep -af 'crawler_watchdog(_v2)?\.sh' || echo "看门狗未运行"
    pgrep -af 'recrawl_2004_2026' || echo "driver 未运行"
    pgrep -af crawl_br_gamelog.py || echo "crawler 未运行"
    echo "--- 9223 ---"; cdp_alive && echo "alive" || echo "down"
    exit 0 ;;
  stop)
    touch "$STOPFLAG"
    echo "已写 stop 标志，看门狗将在下个循环退出。"
    exit 0 ;;
esac

# ============================ 单例锁（与原版共用 PIDFILE → 两版互斥）============================
if [ -f "$PIDFILE" ]; then
  OLD=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    log "看门狗已在运行 (pid ${OLD}，可能是原版或 v2)，退出。"
    exit 0
  fi
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"; log "[watchdog-v2] 退出 (pid $$)"; exit 0' INT TERM EXIT

# ============================ 主循环 ============================
log "===== WATCHDOG-V2 START (pid $$) ====="
stall_count=0
while true; do
  # 0) 停止标志
  if [ -f "$STOPFLAG" ]; then
    rm -f "$STOPFLAG" "$PIDFILE"
    log "[watchdog-v2] 收到 stop 标志，退出。"
    exit 0
  fi

  # 1) 全部赛季完成 → 成功退出
  SC=$(done_count)
  if [ "$SC" -ge "$TOTAL_SEASONS" ]; then
    set_status "DONE: $TOTAL_SEASONS 季全部处理完 (STATE+BYPASSED+FAILURES)"
    log "[watchdog-v2] 已处理 $SC/$TOTAL_SEASONS 季 → 全部完成，退出。"
    rm -f "$PIDFILE"
    exit 0
  fi

  # 2) CDP Chrome 健康
  if ! cdp_alive; then
    start_chrome || { log "[cdp] 重启失败，60s 后重试"; sleep 60; continue; }
  fi

  # 2.5) stop_after_season 防御（杀树改用两段式，确认死透才退出）
  if [ -f "$STOP_AFTER_FLAG" ]; then
    STOPS=$(cat "$STOP_AFTER_FLAG" 2>/dev/null)
    if [ -n "$STOPS" ] && { grep -qxF "$STOPS" "$STATE" 2>/dev/null || grep -qxF "$STOPS" "$FAILURES" 2>/dev/null; }; then
      CS=$(current_season)
      if [ "$CS" != "$STOPS" ]; then
        log "[watchdog-v2] 目标季 $STOPS 已结束，driver 已转向 $CS —— 停止整栈。"
        kill_crawler_tree "stop_after" || true
        rm -f "$PIDFILE"
        exit 0
      fi
    fi
  fi

  # 3) driver 是否在跑
  if ! pgrep -f recrawl_2004_2026_autofill.sh >/dev/null; then
    # 3.5) 目标季已结束且 driver 未运行 → 不重启
    if [ -f "$STOP_AFTER_FLAG" ]; then
      STOPS=$(cat "$STOP_AFTER_FLAG" 2>/dev/null)
      if [ -n "$STOPS" ] && { grep -qxF "$STOPS" "$STATE" 2>/dev/null || grep -qxF "$STOPS" "$FAILURES" 2>/dev/null; }; then
        log "[watchdog-v2] 目标季 $STOPS 已结束且 driver 未运行 —— 不重启，退出。"
        rm -f "$PIDFILE"
        exit 0
      fi
    fi
    # v2：拉新前先确认没有垂死的旧爬虫进程（防并发）
    if pgrep -f 'crawl_br_gamelog.py' >/dev/null 2>&1; then
      log "[driver] driver 未运行但 crawler 进程残留 → 先清理再拉新"
      kill_crawler_tree "pre_restart" || { sleep 30; continue; }
    fi
    log "[driver] 未运行，拉起 driver (当前 STATE=$SC/$TOTAL_SEASONS)"
    set_status "RUNNING (restart)"
    detach bash "$DRIVER" >> "$DRIVER_OUT" 2>&1 &
    sleep 5
    continue
  fi

  # 4) 卡死 / CF 墙检测（杀树改两段式 + 确认死透才继续）
  if is_stalled; then
    stall_count=$((stall_count + 1))
    log "[stall] 检测到卡死(当前季 $STALL_MINUTES 分钟内无写入)，stall_count=$stall_count"
    if kill_crawler_tree "stall"; then
      if [ "$stall_count" -ge "$MAX_STALL" ]; then
        set_status "PAUSED: 连续 $MAX_STALL 次卡死，疑似 CF 墙 — 需人工过 Cloudflare 验证后重启看门狗"
        log "[watchdog-v2] 连续 $MAX_STALL 次卡死 → 判定 CF 墙，PAUSE 并退出。"
        rm -f "$PIDFILE"
        exit 0
      fi
    else
      log "[stall] 爬虫树未能死透，本轮不重启（下轮重试清理）"
      sleep 30
      continue
    fi
    continue
  else
    stall_count=0
  fi

  set_status "RUNNING (done=$SC/$TOTAL_SEASONS)"
  sleep "$SLEEP_LOOP"
done
