#!/bin/bash
# freellamapi 本地 Ollama 路由网关 —— 一键启动 / 状态检查 / 停止
# 用法:
#   ./start.sh          启动(幂等，已跑则跳过)
#   ./start.sh status   查看状态
#   ./start.sh stop     停止
#
# 老程环境实测 (2026-11-10):
#  - 2026-11-10 13:14 曾报 [Errno 48] address already in use：
#    根因是同一份 server.py 被起了两个实例，第二个抢不到 8777。
#    故本脚本启动前必须做端口占用判定，而不是无条件 nohup。
#  - WorkBuddy 注入的 HTTP_PROXY / PYTHONPATH 会破坏本地直连与 site-packages 读取，
#    必须 export PYTHONPATH="" 并 unset 全部大小写代理变量。
#  - 不用 launchctl / setsid（本机已证伪）；nohup + 显式 disown 验证可用。

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/server.log"
PORT="${FREELLAMAPI_PORT:-8777}"
HOST="${FREELLAMAPI_HOST:-127.0.0.1}"

# 本机铁律：清 PYTHONPATH（避开 sitecustomize broker），绕过注入代理
export PYTHONPATH=""
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy

# 解释器优先级：同目录 .venv → anaconda3 → 系统 python3
pick_python() {
  local cands=("$DIR/../.venv/bin/python" "/opt/anaconda3/bin/python3" "$(command -v python3 2>/dev/null)")
  for c in "${cands[@]}"; do
    [ -x "$c" ] || continue
    if "$c" -c "import fastapi,uvicorn" >/dev/null 2>&1; then
      echo "$c"; return 0
    fi
  done
  return 1
}

port_up() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
port_pid() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

health() {
  curl -s --noproxy '*' --max-time 5 "http://$HOST:$PORT/health" 2>/dev/null
}

case "${1:-start}" in
  status)
    if port_up "$PORT"; then
      echo "server  : UP (http://$HOST:$PORT) pid=$(port_pid "$PORT")"
      echo "health  : $(health)"
    else
      echo "server  : DOWN (端口 $PORT 未监听)"
    fi
    ;;
  stop)
    pid=$(port_pid "$PORT")
    if [ -n "$pid" ]; then
      kill "$pid" && echo "已停止端口 $PORT (pid $pid)"
    else
      echo "端口 $PORT 本来就没在跑"
    fi
    ;;
  start)
    if port_up "$PORT"; then
      echo "server 已在运行 (pid=$(port_pid "$PORT"))，跳过启动"
      "$0" status
      exit 0
    fi
    PY=$(pick_python) || { echo "找不到带 fastapi+uvicorn 的 Python"; exit 1; }
    cd "$DIR" || exit 1
    # 用 detach.py 做双 fork + setsid 真正脱离：
    #   普通 `nohup ... &` 会被调用方的进程树回收连带杀掉（Bash 调用结束即死），
    #   导致端口随即空出、下次启动重复起实例 → [Errno 48] address already in use。
    "$PY" "$DIR/detach.py" "$LOG" "$PY" "$DIR/server.py" || { echo "detach 失败"; exit 1; }
    for i in 1 2 3 4 5 6 7 8 9 10; do
      sleep 1
      if port_up "$PORT"; then break; fi
    done
    if port_up "$PORT"; then
      echo "server 启动成功 → http://$HOST:$PORT  (解释器 $PY)"
      echo "health  : $(health)"
    else
      echo "启动失败，日志尾部："
      tail -20 "$LOG"
      exit 1
    fi
    ;;
  *) echo "用法: $0 {start|status|stop}"; exit 1;;
esac
