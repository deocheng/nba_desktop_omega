#!/usr/bin/env bash
# ⑤ Team Shooting 全历史回填（倒序 2026→1997；BR shot-location 数据约 1996-97 起）
# 每季单独落盘 JSON 缓存 (br_shooting_cache/shooting_<season>.json) 供 --rework 重放
# CDP 直连用户已手动过 CF 的 Chrome (端口 64656)
# 全程 --resume：已落库 team×season 自动跳过，断点可重跑。
set -a
[ -f /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env ] && . /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env
set +a
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
# 关键：CDP 走 localhost，绝不能走项目代理，否则连不上用户 Chrome
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:64656
export BR_COOKIE_FILE=/tmp/br_cf_cookies.json
PY=.venv/bin/python
CACHE_DIR=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/br_shooting_cache
LOG=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/br_team_shooting_crawl.log
mkdir -p "$CACHE_DIR"
# 单实例锁：已有 crawler 在跑就拒绝再起第二个，避免并行撞 BR 被封
if pgrep -f "crawl_br_team_shooting.py" >/dev/null 2>&1; then
  echo "[guard] 已有 crawler 在跑，拒绝并行启动（避免被 BR 封禁）。退出。" | tee -a "$LOG"
  exit 1
fi

for S in $(seq 2026 -1 1997); do
  echo "===== $(date) START season $S =====" >> "$LOG"
  $PY external_crawler/crawler/crawl_br_team_shooting.py --season $S --resume --cache-dir "$CACHE_DIR" >> "$LOG" 2>&1
  echo "===== $(date) END season $S (exit $?) =====" >> "$LOG"
done
echo "===== $(date) TEAM SHOOTING ALL DONE =====" >> "$LOG"
