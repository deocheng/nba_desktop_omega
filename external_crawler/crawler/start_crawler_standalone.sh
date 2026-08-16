#!/bin/bash
# =============================================================================
# start_crawler_standalone.sh — 独立常驻爬虫启动器（脱离 WorkBuddy 任务树）
# -----------------------------------------------------------------------------
# 设计目标（用户 2026-08-09 决策："做成独立 app"）：
#   1. 用 os.setsid() 把 driver 放进【独立会话/进程组】，使 WorkBuddy 后台任务
#      被平台回收（killpg 原始组）时，真实工作进程(driver)不连累死亡。
#   2. 内置轻量监督循环：driver 异常退出 → 短睡后自动重启；正常跑完全部季 → 停止。
#   3. 绕过有 bug 的 crawler_watchdog（其 stall 启发式会误判 CF 墙并 SIGTERM 杀
#      健康 driver）。本启动器不做 CF 误杀，只做"崩了就重启"。
#
# 用法：
#   run_in_background 跑：  bash start_crawler_standalone.sh
#   或本机终端常驻：        nohup bash start_crawler_standalone.sh >/dev/null 2>&1 &
# =============================================================================

ROOT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
CRAWLER="$ROOT/external_crawler/crawler"
DRIVER="$CRAWLER/recrawl_2004_2026_autofill.sh"
LOG="$ROOT/logs/standalone_crawler.out"
PY_BIN="/Users/deocheng/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

SCRIPT_ABS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# ── 第一层：若尚未 setsid 脱离，则先 setsid 自身（exec 替换，PID 不变但进新会话）──
if [ -z "${_CRAWLER_DETACHED:-}" ]; then
  export _CRAWLER_DETACHED=1
  exec "$PY_BIN" -c "import os,sys; os.setsid(); os.execvp('/bin/bash', ['bash', '$SCRIPT_ABS'])"
fi

# ── 第二层：已脱离，进入监督循环 ─────────────────────────────────────────────
echo "$(ts) [standalone] detached session started (pid $$), supervising driver"

# 关键修复：setsid 脱离后，若父任务(WorkBuddy 后台)被回收，继承来的 stdin(fd0)
# 会失效，导致子进程 python 启动即 "Bad file descriptor / can't initialize sys
# standard streams"。把自身 stdin 重定向到 /dev/null，所有孙进程继承有效 stdin。
exec 0</dev/null

while true; do
  # 启动前确认 Chrome CDP 在（driver 复用既有 Chrome）；不在则尝试拉起
  if ! curl -s --noproxy '*' -o /dev/null --max-time 5 "http://127.0.0.1:9223/json/version"; then
    echo "$(ts) [standalone] Chrome CDP 未响应，尝试拉起 launch_chrome_cdp.sh"
    if [ -x "$CRAWLER/launch_chrome_cdp.sh" ]; then
      ( cd "$CRAWLER" && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy bash launch_chrome_cdp.sh ) >> "$LOG" 2>&1
      sleep 5
    fi
  fi

  echo "$(ts) [standalone] >>> launching driver"
  ( cd "$CRAWLER" && bash "$DRIVER" ) </dev/null >> "$LOG" 2>&1
  rc=$?

  if [ "$rc" -eq 0 ]; then
    echo "$(ts) [standalone] driver 正常退出(rc=0)，判定全部季完成 → 监督器停止。"
    break
  fi
  echo "$(ts) [standalone] driver 异常退出 rc=$rc，cooldown 30s 后重启"
  sleep 30
done

echo "$(ts) [standalone] 监督器退出。"
