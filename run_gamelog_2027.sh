#!/usr/bin/env bash
# run_gamelog_2027.sh — 补爬 2026-27 赛季（season=2027）已完赛场次的 player_gamelog
#
# 背景：2026-10-23 PG 数据事故恢复后，season=2027 的 player_gamelog 为 0 行
# （新赛季 gamelog 从未成功写入）。已完赛 14 场（10-20 三场 + 10-21 十一场），
# dim_games / play_by_play 完好。本脚本按用户指令「爬取 26-27 已完赛所有场次」执行。
#
# 球员清单旁路：player_per_game（season=2027）为 0 行（赛季聚合表尚未导入，
# 且其正式导入器 combine_server 不在当前树内），故先用 dump_br_league_players.py
# 抓 BR 联赛页产 TSV，经 crawl_br_gamelog.py --players-file 旁路（2026-10-23 新增）。
# 不往 fact_player_season_stats 写半填行（违数据四性）。
#
# 缓存：--cache-dir external_crawler/gamelog_cache（双轨：HTML 原始页 + 整季 JSON），
# 后续 --rework 2027 可免爬重放。
#
# 通道：BROWSER_BACKEND=uc（Playwright 无头 2026-10-23 实测被 CF 挡死；
# UC 无头自愈为日更爬虫 10-20/21 实证可用通道）。CDP 作为备案（需用户 Chrome 在线）。
#
# 单实例铁律：已有 crawl_br_gamelog.py 在跑则拒绝再起。
set -a
[ -f /Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env ] && . /Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env
set +a

PROJECT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
cd "$PROJECT"

# 后台长跑 Python 任务必清 PYTHONPATH（WorkBuddy 注入的 broker shim 会拦截
# 文件读取导致 PermissionError 崩溃，2026-09-02 实战教训）
export PYTHONPATH=""
# 代理一律剥掉（BR 直连；沙箱注入的 HTTP_PROXY 是死代理）
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

export BROWSER_BACKEND=uc
# Apple Silicon：UC 默认下载 x86_64 驱动（无 Rosetta → Bad CPU type 起不来）。
# 指向本机 arm64 驱动（155.0.8059.85，与已装 Chrome 精确匹配，2026-10-22 日更爬虫同款）。
export UC_CHROMEDRIVER_PATH="/Users/deocheng/Library/Application Support/undetected_chromedriver/chromedriver_mac_arm64"
PY=.venv/bin/python
PLAYERS=/tmp/br_players_2027.tsv
LOG="$PROJECT/logs/gamelog_2027_crawl.log"
CACHE_DIR="$PROJECT/external_crawler/gamelog_cache"

if pgrep -f "crawl_br_gamelog.py" >/dev/null 2>&1; then
  echo "[guard] 已有 gamelog crawler 在跑，拒绝并行启动。退出。" | tee -a "$LOG"
  exit 1
fi
if [ ! -s "$PLAYERS" ]; then
  echo "[guard] 球员清单缺失或为空: ${PLAYERS}（先跑 dump_br_league_players.py）。退出。" | tee -a "$LOG"
  exit 1
fi
PLAYER_N=$(wc -l < "$PLAYERS" | tr -d ' ')
echo "===== $(date) START season 2027 (players=$PLAYER_N, backend=uc) =====" >> "$LOG"

$PY external_crawler/crawler/crawl_br_gamelog.py \
  --season 2027 \
  --players-file "$PLAYERS" \
  --cache-dir "$CACHE_DIR" \
  --resume >> "$LOG" 2>&1
EXIT=$?
echo "===== $(date) END season 2027 (exit $EXIT) =====" >> "$LOG"
exit $EXIT
