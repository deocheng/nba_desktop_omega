#!/usr/bin/env bash
# 启动 NBA 高阶指标每日快照控制面板（本地 Web GUI）。
# 用法:  bash metrics_snapshot_app/start_app.sh
# 面板地址: http://127.0.0.1:8791
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/metrics_snapshot_app"
LOG="$APP/logs/server.out"
PORT=8791

# 出网代理会干扰本地 127.0.0.1 请求，剥离之。
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

cd "$ROOT" || exit 1
mkdir -p "$APP/logs"

# 端口占用则提示，不强行杀进程（避免误伤）。
if command -v lsof >/dev/null 2>&1; then
  PID_OLD="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "${PID_OLD:-}" ]; then
    echo "⚠️ 端口 $PORT 已被占用 (pid=$PID_OLD)。直接打开浏览器即可，或先结束该进程。"
    open "http://127.0.0.1:$PORT" 2>/dev/null || true
    exit 0
  fi
fi

echo "[launch] 项目根: $ROOT"
echo "[launch] 启动面板 (venv python)…"
nohup "$ROOT/.venv/bin/python" metrics_snapshot_app/server.py >"$LOG" 2>&1 &
PID=$!
echo "$PID" > "$APP/logs/server.pid"

# 等面板起来再开浏览器。
for i in $(seq 1 20); do
  if curl --noproxy '*' -s -o /dev/null "http://127.0.0.1:$PORT/api/status" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

open "http://127.0.0.1:$PORT" 2>/dev/null || \
  echo "[launch] 浏览器未自动打开，请手动访问 http://127.0.0.1:$PORT"

echo "✅ 面板已启动  pid=$PID"
echo "   地址:      http://127.0.0.1:$PORT"
echo "   日志:      $LOG"
echo "   停止:      kill $PID   (或面板内停止任务)"
wait "$PID" 2>/dev/null || true
