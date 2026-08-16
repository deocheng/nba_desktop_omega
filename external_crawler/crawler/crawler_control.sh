#!/usr/bin/env bash
# =============================================================================
# crawler_control.sh — NBA BR 爬虫 统一爬取 / 退出控制脚本
#
# 目的：把每轮都要重推导的脆弱知识固化成单条命令，省 token。
#   固化项：
#     - ROOT / 路径常量
#     - DB_PASSWORD 安全解析（cut -d= -f2-，密码含 = 不被截断）
#     - 爬虫必需环境变量：BROWSER_BACKEND=cdp / CHROME_CDP_URL / 代理剥除
#     - Chrome 151 强制 --remote-allow-origins 旗标（无则 WS 403）→ 启动前校验/重启
#     - macOS 无 setsid 命令 → 用 python os.setsid 把看门狗/爬取独立成会话，
#       抗 WorkBuddy 后台任务回收（killpg 只命中原始进程组，不连累爬虫树）
#     - 干净退出：爬虫捕获 SIGTERM，需按进程组 kill -9 -pgid；Chrome 多进程同理
#     - 缺口补齐：verify_gaps.py --missing-ids 生成缺口名单 → --only-br-ids 定向爬
#
# 子命令：
#   start [season|all]   经看门狗拉起整栈（自动 ensure PG+Chrome，可选单季跑完即停）
#   chrome               仅启动 Chrome（带 --remote-allow-origins 旗标，抗 WS 403），不爬取
#   pg    [start|stop|status]  管理手启 PostgreSQL（5433，无 launchd）
#   fill  <season>       定向补齐单季缺口（verify_gaps 缺口 → --only-br-ids，后台 detached）
#   stop  [--kill-chrome] 写 stop 标志 + kill driver/crawler 进程树（--kill-chrome 连 Chrome 一起杀）
#   restart [season|all] stop 后 start
#   status               一眼看全：CDP / 看门狗 / driver / crawler / STATE 进度 / 当前季行数
#   verify [season|all]  权威门禁 verify_gaps（rc=0 通过）
#   gaps  [season|all]   仅打印各季缺口球员 slug（--missing-ids）
#   help                 本帮助
#
# 用法示例：
#   bash crawler_control.sh start            # 全 23 季自动补爬（近季优先，逐季 verify_gaps 门禁）
#   bash crawler_control.sh start 2024       # 2026→2024 补齐后停（STOP_AFTER 标志）
#   bash crawler_control.sh fill 2024        # 只补 2024 当前缺口球员（最省，适合收尾）
#   bash crawler_control.sh status
#   bash crawler_control.sh verify 2024
#   bash crawler_control.sh stop             # 退出爬虫栈（保留 Chrome）
#   bash crawler_control.sh stop --kill-chrome
# =============================================================================
set -o pipefail

ROOT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
CRAWLER="$ROOT/external_crawler/crawler"
PY="$ROOT/.venv/bin/python"
PY_BIN="/Users/deocheng/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
PSQL="/opt/homebrew/opt/postgresql@18/bin/psql"
LAUNCH_CHROME="$ROOT/launch_chrome_cdp.sh"
WATCHDOG="$CRAWLER/crawler_watchdog.sh"
DRIVER="$CRAWLER/recrawl_2004_2026_autofill.sh"
LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR"
CDP_PORT=9223
STOP_AFTER_FLAG="$LOGDIR/stop_after_season.flag"
STOPFLAG="$LOGDIR/crawler_watchdog.stop"
STATE="$LOGDIR/recrawl_done_2004_2026.txt"
BYPASS_FILE="$LOGDIR/gamelog_500_bypass.txt"
CACHE_DIR="$CRAWLER/gamelog_cache"
PG_CTL="/opt/homebrew/opt/postgresql@18/bin/pg_ctl"
PG_DATA="/Volumes/12T/NBA/nba_pg"
PG_LOG="/Volumes/12T/NBA/nba_pg/pg.log"

# --- DB_PASSWORD 安全解析（密码含 = 必须用 -f2-）---
DBPASS=$(grep '^DB_PASSWORD=' "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2-)

# --- 爬虫/核验 必需环境（导出，verify_gaps / crawl 子进程继承）---
export DB_PASSWORD="$DBPASS"
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL="http://127.0.0.1:$CDP_PORT"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY='*' no_proxy='*'
export PGPASSWORD="$DBPASS"

cd "$CRAWLER" || exit 1

# ============================ 工具函数 ============================
log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

cdp_alive(){
  local code
  code=$(curl -s --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$CDP_PORT/json/version" 2>/dev/null)
  [ "$code" = "200" ]
}

# Chrome 主进程是否带 --remote-allow-origins（Chrome 151 必需，否则 WS 403）
# 用 pgrep -f 直接对整条 cmdline 做正则匹配（macOS ps -o command= 会截断长 cmdline 漏判）。
# 仅主进程同时含 remote-debugging-port 与 --remote-allow-origins；两种顺序都接受。
chrome_has_flag(){
  pgrep -f "remote-debugging-port=${CDP_PORT}.*--remote-allow-origins" >/dev/null 2>&1 || \
  pgrep -f "--remote-allow-origins.*remote-debugging-port=${CDP_PORT}" >/dev/null 2>&1
}

# 按进程组强杀（爬虫捕获 SIGTERM，普通 kill 无效；Chrome 多进程同理）
kill_tree(){
  local pat="$1" p pgid
  for p in $(pgrep -f "$pat" 2>/dev/null); do
    pgid=$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')
    [ -n "$pgid" ] && kill -9 -"$pgid" 2>/dev/null
    kill -9 "$p" 2>/dev/null
  done
  pkill -9 -f "$pat" 2>/dev/null   # 二次兜底
}

season_rows(){
  local S=$1
  [ -z "$S" ] && { echo 0; return; }
  PGPASSWORD="$DBPASS" "$PSQL" -h localhost -p 5433 -U postgres -d nba -t -A -c \
    "SELECT count(*) FROM player_gamelog WHERE season=$S;" 2>/dev/null | tail -1
}

current_season(){
  local f
  f=$(ls -t "$LOGDIR"/recrawl_gamelog_*.log 2>/dev/null | head -1)
  [ -z "$f" ] && { echo ""; return; }
  basename "$f" | sed -E 's/.*recrawl_gamelog_([0-9]+).*/\1/'
}

state_count(){
  [ -f "$STATE" ] || { echo 0; return; }
  grep -cE '^[0-9]{4}$' "$STATE"
}

# --- PostgreSQL (手启, 无 launchd) ---
pg_is_up(){
  PGPASSWORD="$DBPASS" "$PSQL" -h localhost -p 5433 -U postgres -d nba -t -A -c "SELECT 1;" >/dev/null 2>&1
}
ensure_pg(){
  if pg_is_up; then return 0; fi
  log "[pg] 未运行，启动中 (pg_ctl -D $PG_DATA -o -p 5433)..."
  "$PG_CTL" -D "$PG_DATA" -o "-p 5433" -l "$PG_LOG" start >/dev/null 2>&1
  for i in $(seq 1 15); do
    sleep 2
    pg_is_up && { log "[pg] 已就绪 (5433)"; return 0; }
  done
  log "[pg] !! 启动失败，查 $PG_LOG"; return 1
}

# 确保 Chrome 以正确旗标运行（无则重启，带 --remote-allow-origins 抗 WS 403）
ensure_chrome(){
  if cdp_alive && chrome_has_flag; then
    log "[cdp] Chrome 已存活且含 --remote-allow-origins，跳过"
    return 0
  fi
  log "[cdp] Chrome 缺失/旗标不全，重启中..."
  kill_tree "remote-debugging-port=$CDP_PORT"
  rm -f /Volumes/12T/NBA/chrome_cdp_profile/SingletonLock 2>/dev/null
  # 用 python os.setsid 把 Chrome 拉进独立会话（抗回收）
  "$PY_BIN" -c "import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])" \
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    bash "$LAUNCH_CHROME" >> "$LOGDIR/crawler_control.chrome.out" 2>&1 &
  for i in $(seq 1 45); do
    sleep 2
    if cdp_alive && chrome_has_flag; then
      log "[cdp] Chrome 已就绪 (9223, 含 flag)"; return 0
    fi
  done
  # 即使循环超时，detached Chrome 仍会在后台继续起来；此时用 status 复查
  log "[cdp] !! 90s 内脚本轮询未见到就绪（大 profile 冷启动较慢）—— detached Chrome 可能已在后台就绪，请用 'status' 复查"
  return 1
}

# 用 python os.setsid 把看门狗拉进新会话（抗 WorkBuddy 后台任务回收）
launch_watchdog_detached(){
  "$PY_BIN" -c "import os,sys; os.setsid(); os.execv('/bin/bash', ['bash', '$WATCHDOG'])" \
    >> "$LOGDIR/crawler_control.watchdog.out" 2>&1 &
}

# ============================ 子命令 ============================
cmd_start(){
  local target="${1:-all}"
  if [ "$target" = "all" ]; then
    rm -f "$STOP_AFTER_FLAG"
    log "[start] 目标=全 23 季（近季优先，逐季 verify_gaps 门禁）"
  else
    printf '%s' "$target" > "$STOP_AFTER_FLAG"
    log "[start] 目标季=$target（跑完即停，写 STOP_AFTER 标志）"
  fi
  ensure_pg || { log "[start] PG 未就绪，中止"; return 1; }
  ensure_chrome || { log "[start] Chrome 未就绪，中止"; return 1; }
  if pgrep -f crawler_watchdog.sh >/dev/null 2>&1; then
    log "[start] 看门狗已在运行，跳过重复启动"
  else
    launch_watchdog_detached
    log "[start] 看门狗已 detached 启动（survive 后台回收）"
  fi
  sleep 3
  cmd_status
}

# fill：定向补齐单季缺口（最省，适合收尾）
cmd_fill(){
  local S="${1:-}"
  [ -z "$S" ] && { echo "用法: crawler_control.sh fill <season>"; return 1; }
  local GAPFILE="/tmp/gap_${S}.txt"
  ensure_pg || { log "[fill] PG 未就绪，中止"; return 1; }
  mkdir -p "$CACHE_DIR"
  "$PY" verify_gaps.py "$S" --missing-ids > "$GAPFILE" 2>/dev/null
  if [ -s "$GAPFILE" ]; then
    log "[fill] $S 缺口球员 $(wc -l < "$GAPFILE" | tr -d ' ') 人 → $GAPFILE"
    ensure_chrome || { log "[fill] Chrome 未就绪，中止"; return 1; }
    log "[fill] 后台 detached 补齐 $S (log: /tmp/fill_${S}.log)"
    "$PY_BIN" -c "import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])" \
      "$PY" crawl_br_gamelog.py --season "$S" --only-br-ids "$GAPFILE" \
      --force-fetch \
      --bypass-500-file "$BYPASS_FILE" \
      --cache-dir "$CACHE_DIR" >> "/tmp/fill_${S}.log" 2>&1 &
    log "[fill] 已启动。用 'status' / 'verify $S' 查进度"
  else
    log "[fill] $S 无逐人缺口（verify_gaps 通过），无需补齐"
  fi
}

cmd_stop(){
  local kill_chrome=0
  [ "${1:-}" = "--kill-chrome" ] && kill_chrome=1
  touch "$STOPFLAG"
  log "[stop] 已写 stop 标志（看门狗下轮退出）"
  kill_tree "crawler_watchdog.sh"
  kill_tree "recrawl_2004_2026_autofill.sh"
  kill_tree "crawl_br_gamelog.py"
  if [ "$kill_chrome" = 1 ]; then
    kill_tree "remote-debugging-port=$CDP_PORT"
    log "[stop] 已 kill Chrome 进程树"
  else
    log "[stop] 保留 Chrome（cf_clearance 宝贵）；如需杀加 --kill-chrome"
  fi
  sleep 2
  cmd_status
}

cmd_restart(){
  cmd_stop >/dev/null 2>&1
  sleep 2
  cmd_start "$@"
}

# 仅启动 Chrome（带 --remote-allow-origins 旗标，抗 WS 403），不爬取
cmd_chrome(){
  ensure_chrome && log "[chrome] Chrome 就绪（CDP 9223 + flag）" || log "[chrome] Chrome 启动失败"
}

cmd_status(){
  echo "=== crawler_control status @ $(date) ==="
  pg_is_up && echo "--- PG 5433 --- UP" || echo "--- PG 5433 --- DOWN"
  echo "--- CDP 9223 ---"; cdp_alive && echo "alive" || echo "DOWN"
  echo "--- 看门狗 ---"; pgrep -af crawler_watchdog.sh || echo "未运行"
  echo "--- driver ---"; pgrep -af recrawl_2004_2026_autofill.sh || echo "未运行"
  echo "--- crawler ---"; pgrep -af crawl_br_gamelog.py || echo "未运行"
  echo "--- STATE 进度 ---"; echo "已完成季: $(state_count) / 23"
  local S; S=$(current_season)
  [ -n "$S" ] && echo "--- 当前季 $S player_gamelog: $(season_rows "$S") 行"
  echo "--- STOP_AFTER 标志 ---"; [ -f "$STOP_AFTER_FLAG" ] && echo "目标季=$(cat "$STOP_AFTER_FLAG")" || echo "(无，全部季)"
  echo "--- stop 标志 ---"; [ -f "$STOPFLAG" ] && echo "存在(看门狗将退出)" || echo "无"
}

cmd_verify(){
  ensure_pg || { log "[verify] PG 未就绪，中止"; return 1; }
  if [ $# -eq 0 ]; then
    "$PY" verify_gaps.py --all
  else
    "$PY" verify_gaps.py "$@"
  fi
}

cmd_gaps(){
  ensure_pg || { log "[gaps] PG 未就绪，中止"; return 1; }
  if [ $# -eq 0 ]; then
    "$PY" verify_gaps.py --all --missing-ids
  else
    "$PY" verify_gaps.py "$@" --missing-ids
  fi
}

cmd_pg(){
  case "${1:-status}" in
    start) ensure_pg && log "[pg] started" ;;
    stop)  "$PG_CTL" -D "$PG_DATA" -m fast stop >/dev/null 2>&1 && log "[pg] stopped" || log "[pg] stop failed" ;;
    status) pg_is_up && echo "PG: UP (5433)" || echo "PG: DOWN" ;;
    *) echo "用法: crawler_control.sh pg [start|stop|status]" ;;
  esac
}

cmd_help(){
  sed -n '2,52p' "$0"
}

# ============================ 分发 ============================
case "${1:-help}" in
  start)    shift; cmd_start "$@" ;;
  fill)     shift; cmd_fill "$@" ;;
  stop)     shift; cmd_stop "$@" ;;
  restart)  shift; cmd_restart "$@" ;;
  chrome)   cmd_chrome ;;
  pg)       shift; cmd_pg "$@" ;;
  status)   cmd_status ;;
  verify)   shift; cmd_verify "$@" ;;
  gaps)     shift; cmd_gaps "$@" ;;
  help|-h|--help) cmd_help ;;
  *) echo "未知子命令: $1"; cmd_help; exit 1 ;;
esac
