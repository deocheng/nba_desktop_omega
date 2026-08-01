#!/bin/bash
# clean_shotchart_loop.sh — 每 300s 跑一次「核验入库即删」缓存清理。
# 由 os.setsid python 包装器拉起，脱离 agent 会话常驻（与 watchdog 解耦，可独立停止）。
PROJ=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
cd "$PROJ" || exit 1
set -a; [ -f .env ] && . ./.env; set +a
export CHROME_CDP_URL="${CHROME_CDP_URL:-http://127.0.0.1:9223}"
# 清理策略：仅删「超过 1 小时、且已入库核验」的缓存（不删 0 球垃圾页）
export CLEAN_GUARD_S=3600
export CLEAN_JUNK=0
LOG=/Volumes/12T/NBA/clean_cache.log
echo "[loop] started pid=$$ at $(date)" >> "$LOG"
while true; do
  "$PROJ/.venv/bin/python" "$PROJ/clean_shotchart_cache.py" >> "$LOG" 2>&1
  sleep 300
done
