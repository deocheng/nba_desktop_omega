#!/usr/bin/env bash
# 无人值守：补抓 NBA 球员头像（headshot）到 12TB 盘，回写 dim_players。
#
# 双锁机制（铁律：当前 crawl_br_gamelog.py 正在运行 PID 15934，本脚本必须零干扰）：
#   ① 自身 pgrep 单实例锁 —— 已有 headshots crawler 在跑就拒绝再起第二个；
#   ② gamelog 互斥锁 —— gamelog（含 PID 15934）在跑时拒绝启动，绝不抢 9222 / 不并行争用 CF 会话。
# 任意一锁命中立即 exit 1，绝不并行。
set -a
[ -f /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env ] && . /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/.env
set +a
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
export BR_COOKIE_FILE=/tmp/br_cf_cookies.json
# CDP 直连模式：驱动已手动过 CF 的用户 Chrome（9222）。cookies 走浏览器实时态，
# 不与 gamelog 共享标签页（双锁保证两者不会并行）。
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:9222
PY=.venv/bin/python
LOG=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/headshots_crawl.log

# 双锁之一：自身单实例锁
if pgrep -f "crawl_br_headshots.py" >/dev/null 2>&1; then
  echo "[guard] 已有 headshots crawler 在跑，拒绝并行启动（避免重复抓取）。退出。" | tee -a "$LOG"
  exit 1
fi

# 双锁之二：与 gamelog 互斥（含 PID 15934），绝不在 gamelog 运行时抢 9222
if pgrep -f "crawl_br_gamelog.py" >/dev/null 2>&1; then
  echo "[guard] gamelog 爬虫正在运行，拒绝并行（避免与 gamelog 争用 CDP/9222）。退出。" | tee -a "$LOG"
  exit 1
fi

echo "===== $(date) START headshots =====" >> "$LOG"
$PY external_crawler/crawler/crawl_br_headshots.py --resume >> "$LOG" 2>&1
echo "===== $(date) END headshots (exit $?) =====" >> "$LOG"
