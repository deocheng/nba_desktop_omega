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
HEADSHOT_LOG=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/headshots_relay.log
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
echo "===== $(date) GAMELOG ALL DONE =====" >> "$LOG"

# === 自动接力（relay）：gamelog 全部季串行跑完后，自动触发 headshots 头像抓取 ===
# 硬约束（红线）：绝不与 gamelog 并行 —— gamelog python 进程此时已完全退出。
# 直接调 crawl_br_headshots.py（不调 run_headshots_all.sh），原因：
#   (a) 此时 pgrep -f crawl_br_gamelog.py 本就查不到，双锁中的 gamelog 互斥锁无意义；
#   (b) 直接调 python 可避免接力时又被 run_headshots_all.sh 的 gamelog 互斥锁误拦
#       （那个互斥锁是为「独立手动跑 headshots」准备的，接力场景不适用）。
# env（BROWSER_BACKEND / CHROME_CDP_URL / BR_COOKIE_FILE / DB_PASSWORD）在脚本顶部已
# export，本接力块在同一作用域，无需重复 export；且全程无 unset。
echo "=== [relay] gamelog 抓取完成 ($(date))，自动接力 headshots 头像抓取 ===" | tee -a "$LOG"
# 轻量 self-guard：若已有 headshots crawler 在跑（极端并发），跳过接力，绝不强行并行。
if pgrep -f "crawl_br_headshots.py" >/dev/null 2>&1; then
  echo "[relay] 已有 headshots crawler 在跑，跳过接力（避免并行）。" | tee -a "$LOG"
else
  echo "=== [relay] headshots 日志写入 $HEADSHOT_LOG ===" | tee -a "$LOG"
  $PY external_crawler/crawler/crawl_br_headshots.py --resume >> "$HEADSHOT_LOG" 2>&1
  RELAY_EXIT=$?
  if [ "$RELAY_EXIT" -eq 0 ]; then
    echo "[relay] headshots 接力成功完成 ($(date))。" | tee -a "$LOG"
  else
    echo "[relay] headshots 接力失败 (exit $RELAY_EXIT)，详见 $HEADSHOT_LOG；gamelog 已成功，不中断。" | tee -a "$LOG"
  fi
fi
echo "=== [relay] 全部流程结束 ($(date)) ===" | tee -a "$LOG"
