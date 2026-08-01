#!/usr/bin/env bash
# 老季(结束年 1947-1996) player_gamelog 全量补爬 —— 倒序 1996→1947
# 每一季单独落盘 JSON 缓存 (gamelog_cache/gamelog_<season>.json) 供返工免重爬
# CDP 直连用户已手动过 CF 的 Chrome (端口 64656)
# 全程 --resume：已抓球员自动跳过，断点可重跑；不带 headshots 接力（保持范围聚焦）。
set -a
[ -f /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env ] && . /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env
set +a
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
# 关键：CDP 走 localhost，绝不能走项目代理(127.0.0.1:12334)，否则连不上用户 Chrome
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:64656
export BR_COOKIE_FILE=/tmp/br_cf_cookies.json
PY=.venv/bin/python
CACHE_DIR=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/gamelog_cache
LOG=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/gamelog_old_crawl.log
mkdir -p "$CACHE_DIR"
# 单实例锁：已有 crawler 在跑就拒绝再起第二个，避免多标签页并行撞 BR 被封
if pgrep -f "crawl_br_gamelog.py" >/dev/null 2>&1; then
  echo "[guard] 已有 crawler 在跑，拒绝并行启动（避免被 BR 封禁）。退出。" | tee -a "$LOG"
  exit 1
fi

for S in $(seq 1996 -1 1947); do
  echo "===== $(date) START season $S =====" >> "$LOG"
  $PY external_crawler/crawler/crawl_br_gamelog.py --season $S --resume --cache-dir "$CACHE_DIR" >> "$LOG" 2>&1
  echo "===== $(date) END season $S (exit $?) =====" >> "$LOG"
done
echo "===== $(date) GAMELOG OLD ALL DONE =====" >> "$LOG"
