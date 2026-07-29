#!/usr/bin/env bash
# ① Lineups 全历史回填（倒序 2026→1997；BR lineups 数据约 1996-97 起）
# 每季单独落盘 JSON 缓存 (br_lineups_cache/lineups_<season>.json) 供 --rework 重放
# CDP 直连用户已手动过 CF 的 Chrome (端口 64656)，全程 --resume。
set -a
[ -f /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env ] && . /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env
set +a
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:64656
export BR_COOKIE_FILE=/tmp/br_cf_cookies.json
PY=.venv/bin/python
CACHE_DIR=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/br_lineups_cache
LOG=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/br_team_lineups_crawl.log
mkdir -p "$CACHE_DIR"
if pgrep -f "crawl_br_team_lineups.py" >/dev/null 2>&1; then
  echo "[guard] 已有 crawler 在跑，拒绝并行启动（避免被 BR 封禁）。退出。" | tee -a "$LOG"
  exit 1
fi

for S in $(seq 2026 -1 1997); do
  echo "===== $(date) START season $S =====" >> "$LOG"
  $PY external_crawler/crawler/crawl_br_team_lineups.py --season $S --resume --cache-dir "$CACHE_DIR" >> "$LOG" 2>&1
  echo "===== $(date) END season $S (exit $?) =====" >> "$LOG"
done
echo "===== $(date) TEAM LINEUPS ALL DONE =====" >> "$LOG"
