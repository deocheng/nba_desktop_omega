#!/usr/bin/env bash
# 无人值守：补爬 player_gamelog 的真实缺口季（结束年）
# 1997-2000 (1996-97~1999-00, 原 0%) + 2024 (2023-24) + 2026 (2025-26)
# 全部带 --resume：已抓球员自动跳过，可断点重跑。
set -a
[ -f /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env ] && . /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env
set +a
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
export BR_COOKIE_FILE=/tmp/br_cf_cookies.json
# CDP 直连模式：绕过无头 launch 在某些环境下的 asyncio 事件循环冲突，
# 直接驱动已开 CF 的用户 Chrome（9222）。cookies 走浏览器实时态，不依赖本文件。
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:9222
PY=.venv/bin/python
LOG=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/gamelog_crawl.log
# 单实例锁：已有 crawler 在跑就拒绝再起第二个，避免多标签页并行撞 BR 被封
if pgrep -f "crawl_br_gamelog.py" >/dev/null 2>&1; then
  echo "[guard] 已有 crawler 在跑，拒绝并行启动（避免被 BR 封禁）。退出。" | tee -a "$LOG"
  exit 1
fi

for S in 1997 1998 1999 2000 2024 2026; do
  echo "===== $(date) START season $S =====" >> "$LOG"
  $PY external_crawler/crawler/crawl_br_gamelog.py --season $S --resume >> "$LOG" 2>&1
  echo "===== $(date) END season $S (exit $?) =====" >> "$LOG"
done
echo "===== $(date) ALL DONE =====" >> "$LOG"
