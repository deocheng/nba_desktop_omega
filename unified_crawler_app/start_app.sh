#!/usr/bin/env bash
# Terminal launcher for the unified crawler control panel (port 8793).
# Equivalent to double-clicking UnifiedCrawler.app, but from a shell.
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
SERVER="$ROOT/unified_crawler_app/server.py"
PORT=8793
URL="http://127.0.0.1:$PORT"

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

cd "$ROOT" || exit 1

if curl -s --noproxy '*' --max-time 2 "$URL/api/status" >/dev/null 2>&1; then
  echo "[panel] already running on $PORT — opening browser"
  open "$URL"
  exit 0
fi

nohup "$PY" "$SERVER" > "$ROOT/unified_crawler_app/panel.log" 2>&1 &
echo $! > "$ROOT/unified_crawler_app/panel.pid"
echo "[panel] starting (pid $(cat "$ROOT/unified_crawler_app/panel.pid"))..."

for i in $(seq 1 40); do
  if curl -s --noproxy '*' --max-time 2 "$URL/api/status" >/dev/null 2>&1; then
    sleep 0.5
    open "$URL"
    echo "[panel] up at $URL"
    exit 0
  fi
  sleep 0.5
done
echo "[panel] timed out — see $ROOT/unified_crawler_app/panel.log"
exit 1
