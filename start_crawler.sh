#!/usr/bin/env bash
# =============================================================================
# start_crawler.sh — 一键启动 NBA 球员头像/数据爬虫（脱离 WorkBuddy 直接跑）
#
# 干什么：
#   1) 自动拉起已死的基础设施（Postgres 5433 / CDP Chrome 9222）——这是上一轮
#      "5433 和 Chrome 一起死了导致爬虫全员 failed" 的真实教训，本脚本专门修复它。
#   2) Cloudflare 预检：若 BR 当前被 CF 拦截，提示用户在 9222 那扇 Chrome 窗口
#      点一下验证，脚本轮询等待，点完自动续跑（不会强行启动爬虫误标 failed）。
#   3) 复用既有启动脚本（run_headshots_all.sh / run_gamelog_all.sh）启动爬虫，
#      由其内部双锁保证不与已在跑的爬虫并行。
#
# 用法：
#   ./start_crawler.sh                 # 默认：启动 headshots 头像抓取
#   ./start_crawler.sh headshots       # 同上
#   ./start_crawler.sh gamelog         # 启动 gamelog 6 季(1997/1998/1999/2000/2024/2026) + 自动接力 headshots
#   bash start_crawler.sh [headshots|gamelog]
#
# 前提：
#   - 项目根存在 .env（含 DB_PASSWORD 等），脚本会自动 source。
#   - 系统可启动 Chrome（launch_chrome_cdp.sh 用的 /Applications/Google Chrome）。
#
# CF 挑战时怎么办：
#   脚本打印「⚠️ Cloudflare 正在拦截…」后，切到 9222 端口那扇 Chrome 窗口，
#   手动点一下 "Verify you are human" / "请稍候" 验证，脚本每 15 秒自动复检，
#   验证通过即自动开跑。期间随时 Ctrl+C 取消（不会杀爬虫、不会杀用户日常 Chrome）。
#
# 注意：本脚本绝不 kill 任何已有的 Google Chrome 进程（那是你的日常浏览器），
#   也只清理 /tmp/chrome_cdp_profile 这个专用 profile 的锁文件。
# =============================================================================

set -o pipefail

# ---------------------------------------------------------------------------
# 0) 定位项目根 + source .env
# ---------------------------------------------------------------------------
PROJ_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJ_ROOT" || { echo "[fatal] 无法 cd 到脚本目录 $PROJ_ROOT"; exit 1; }

# source 项目 .env（设置 DB_PASSWORD 等），失败不致命。
set -a
if [ -f "$PROJ_ROOT/.env" ]; then
  . "$PROJ_ROOT/.env"
fi
set +a

PY="${PY:-.venv/bin/python}"
export BROWSER_BACKEND="${BROWSER_BACKEND:-cdp}"
export CHROME_CDP_URL="${CHROME_CDP_URL:-http://127.0.0.1:9222}"
export BR_COOKIE_FILE="${BR_COOKIE_FILE:-/tmp/br_cf_cookies.json}"

# 可覆盖的基础路径（测试/迁移时用）
PG_DATADIR="${PG_DATADIR:-/Users/deocheng/nba_pg}"
PG_PORT="${PG_PORT:-5433}"
CDP_PORT="${CDP_PORT:-9222}"
CDP_PROFILE="${CDP_PROFILE:-/tmp/chrome_cdp_profile}"

# ---------------------------------------------------------------------------
# 1) Postgres 5433 探测 / 拉起
# ---------------------------------------------------------------------------
pg_is_up() {
  # 返回 0 表示 5433 已在监听并接受连接
  if command -v pg_isready >/dev/null 2>&1; then
    if pg_isready -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1; then
      return 0
    fi
  fi
  if command -v lsof >/dev/null 2>&1; then
    if lsof -iTCP:"$PG_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
  fi
  if command -v curl >/dev/null 2>&1; then
    if curl -s -o /dev/null --max-time 3 "http://127.0.0.1:${PG_PORT}" >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

find_pg_ctl() {
  # 允许测试覆盖；否则健壮探测路径
  if [ -n "${PG_CTL_BIN:-}" ]; then
    echo "$PG_CTL_BIN"; return 0
  fi
  local p
  if p=$(command -v pg_ctl 2>/dev/null) && [ -n "$p" ]; then
    echo "$p"; return 0
  fi
  for cand in /opt/homebrew/bin/pg_ctl /opt/homebrew/opt/postgresql@18/bin/pg_ctl /opt/homebrew/opt/postgresql/bin/pg_ctl /usr/local/bin/pg_ctl; do
    if [ -x "$cand" ]; then echo "$cand"; return 0; fi
  done
  echo ""; return 1
}

ensure_postgres() {
  if pg_is_up; then
    echo "[infra] 5433 正常"
    return 0
  fi
  echo "[infra] 5433 未监听，尝试拉起 Postgres..."

  local pginst
  pginst="$(find_pg_ctl)"
  if [ -z "$pginst" ]; then
    echo "[infra][WARN] 找不到 pg_ctl，无法自动拉起 Postgres（请手动启动 /opt/homebrew/bin/pg_ctl）。"
    return 1
  fi

  # 仅当 postmaster.pid 指向的进程已死，才清理它，再启动
  local pmpid="$PG_DATADIR/postmaster.pid"
  if [ -f "$pmpid" ]; then
    local oldpid
    oldpid="$(head -1 "$pmpid" 2>/dev/null | tr -d ' ')"
    if [ -n "$oldpid" ] && ! kill -0 "$oldpid" 2>/dev/null; then
      echo "[infra] 发现已死的 postmaster.pid (pid=$oldpid)，清理后启动。"
      rm -f "$pmpid"
    else
      echo "[infra][WARN] postmaster.pid 指向活跃进程 $oldpid，不清理（可能有实例在跑，跳过启动）。"
      return 1
    fi
  fi

  "$pginst" -D "$PG_DATADIR" -o "-p $PG_PORT" -l /tmp/nba_pg_restart.log start

  local i=0
  while [ "$i" -lt 30 ]; do
    if pg_is_up; then
      echo "[infra] 5433 已拉起"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  echo "[infra][WARN] Postgres 启动后仍未能连上（详见 /tmp/nba_pg_restart.log），继续但爬虫可能失败。"
  return 1
}

# ---------------------------------------------------------------------------
# 2) CDP Chrome 9222 探测 / 拉起（绝不碰用户日常 Chrome）
# ---------------------------------------------------------------------------
chrome_is_up() {
  if command -v curl >/dev/null 2>&1; then
    if curl -s -o /dev/null --max-time 3 "http://127.0.0.1:${CDP_PORT}/json/version" >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

ensure_chrome() {
  if chrome_is_up; then
    echo "[infra] 9222 正常"
    return 0
  fi
  echo "[infra] 9222 未响应，尝试拉起 CDP Chrome..."

  # 只清理专用 profile 的 Singleton* 锁文件，绝不清理用户的默认 profile
  local f
  for f in SingletonLock SingletonCookie SingletonSocket; do
    if [ -e "$CDP_PROFILE/$f" ]; then
      rm -f "$CDP_PROFILE/$f" 2>/dev/null || true
    fi
  done

  # 绝不 kill 任何已有的 Google Chrome 进程；只是启动一个专用实例
  if [ -f "$PROJ_ROOT/launch_chrome_cdp.sh" ]; then
    ( cd "$PROJ_ROOT" && bash launch_chrome_cdp.sh ) >/dev/null 2>&1
  elif [ -f launch_chrome_cdp.sh ]; then
    bash launch_chrome_cdp.sh >/dev/null 2>&1
  else
    echo "[infra][WARN] 找不到 launch_chrome_cdp.sh，无法启动 CDP Chrome。"
    return 1
  fi

  local i=0
  while [ "$i" -lt 30 ]; do
    if chrome_is_up; then
      echo "[infra] 9222 已拉起"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  echo "[infra][WARN] CDP Chrome 启动后仍无响应，继续但爬虫可能被 CF 拦。"
  return 1
}

# ---------------------------------------------------------------------------
# 3) CF 预检（经 common.browser.get_driver() 加载一个 BR 球员页，一次性判挑战）
# ---------------------------------------------------------------------------
CF_TEST_URL="${CF_TEST_URL:-https://www.basketball-reference.com/players/j/jamesle01.html}"

cf_challenged() {
  # 返回 0 表示当前 BR 页处于 CF 挑战后（需要用户点验证）
  if [ ! -x "$PY" ]; then
    echo "[cf][WARN] 找不到 venv python ($PY)，跳过 CF 预检，直接开跑。"
    return 1
  fi
  BROWSER_BACKEND=cdp CHROME_CDP_URL="http://127.0.0.1:${CDP_PORT}" \
  CF_TEST_URL="$CF_TEST_URL" "$PY" - <<'PYEOF'
import os, sys, time
os.environ["BROWSER_BACKEND"] = "cdp"
os.environ["CHROME_CDP_URL"] = "http://127.0.0.1:%s" % os.environ.get("CDP_PORT_OVERRIDE", "9222")
url = os.environ.get("CF_TEST_URL", "https://www.basketball-reference.com/players/j/jamesle01.html")
try:
    from common.browser import get_driver, quit_driver
    d = get_driver()
    # 一次性导航 + 快速判挑战（不触发 get() 内部的完整等待循环）
    d._send(d._ws, "Page.enable", timeout=30)
    d._send(d._ws, "Page.navigate", {"url": url}, timeout=40)
    time.sleep(4)
    challenged = d._is_challenged()
    quit_driver()
    sys.exit(0 if challenged else 1)
except Exception as e:
    sys.stderr.write("CF precheck error: %r\n" % (e,))
    sys.exit(0)  # 无法确定时按"被挑战"处理，等用户点验证更稳妥
PYEOF
}

cf_wait_until_clear() {
  echo ""
  echo "⚠️  Cloudflare 正在拦截，请在 9222 那扇 Chrome 窗口点一下验证；"
  echo "    脚本会等您点完再继续…（每 15 秒自动复检；按 Ctrl+C 取消）"
  echo ""
  while true; do
    if ! cf_challenged; then
      echo "[cf] CF 已放行，继续启动爬虫。"
      return 0
    fi
    echo "[cf] 仍在 CF 挑战中，等待您点验证… ($(date '+%H:%M:%S'))"
    sleep 15
  done
}

# ---------------------------------------------------------------------------
# 4) 主流程
# ---------------------------------------------------------------------------
main() {
  local MODE="${1:-headshots}"
  case "$MODE" in
    headshots|gamelog) ;;
    *)
      echo "未知模式: $MODE （用 headshots 或 gamelog）"
      exit 1
      ;;
  esac

  echo "===== $(date) start_crawler.sh ($MODE) ====="
  echo "[infra] 基础设施自检 + 自动拉起..."

  # 顺序：先 PG，再 Chrome
  ensure_postgres || true
  ensure_chrome || true

  # CF 预检（仅在 Chrome 已起时做）
  if chrome_is_up; then
    if cf_challenged; then
      cf_wait_until_clear
    else
      echo "[cf] CF 当前放行，直接开跑。"
    fi
  else
    echo "[cf][WARN] 9222 未起，跳过 CF 预检（爬虫内部会自行处理挑战）。"
  fi

  # 启动爬虫（委托给既有脚本，由其内部双锁保证不并行）
  local LOG_FILE CRAWL_SCRIPT
  case "$MODE" in
    headshots)
      LOG_FILE="$PROJ_ROOT/headshots_crawl.log"
      CRAWL_SCRIPT=run_headshots_all.sh
      ;;
    gamelog)
      LOG_FILE="$PROJ_ROOT/gamelog_crawl.log"
      CRAWL_SCRIPT=run_gamelog_all.sh
      ;;
  esac

  touch "$LOG_FILE"
  echo "===== $(date) LAUNCH $CRAWL_SCRIPT =====" >> "$LOG_FILE"
  nohup bash "$CRAWL_SCRIPT" >> "$LOG_FILE" 2>&1 &
  local CRAWL_PID=$!
  echo "已启动 pid=$CRAWL_PID，日志 $CRAWL_SCRIPT -> $(basename "$LOG_FILE")"
  echo "（Ctrl+C 仅停止日志跟随，爬虫在后台继续运行 pid=$CRAWL_PID）"
  echo "---------------------------------------------------------------"
  tail -f "$LOG_FILE"
}

# 库模式（START_CRAWLER_LIB=1）：被测试 harness source 时只导出函数，不执行 main。
if [ "${START_CRAWLER_LIB:-0}" != "1" ]; then
  main "$@"
fi
