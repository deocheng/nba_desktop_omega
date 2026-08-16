#!/bin/bash
# crawl_with_timeout.sh <timeout_sec> <cmd...>
# 给爬取命令加整体超时：超时则 kill -9 子进程并以 124 退出，
# 避免 crawl_br_gamelog.py 无超时地 hang 在某次 BR 请求上，
# 导致「实时日志永久不动、DB 不涨」却进程还「在跑」的假象。
# 用法（在 recrawl 脚本内，cwd 已 cd 到 crawler 目录）：
#   ./crawl_with_timeout.sh 1200 "$PY" crawl_br_gamelog.py ... </dev/null >> "$LOG" 2>&1
timeout_sec=$1
shift

"$@" &
pid=$!
start=$(date +%s)

while kill -0 "$pid" 2>/dev/null; do
  now=$(date +%s)
  if [ $((now - start)) -ge "$timeout_sec" ]; then
    echo "[crawl_with_timeout] 超过 ${timeout_sec}s，强制 kill -9 pid=$pid" >&2
    kill -9 "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    exit 124
  fi
  sleep 5
done

wait "$pid"
exit $?
