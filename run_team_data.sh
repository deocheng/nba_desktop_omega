#!/usr/bin/env bash
# run_team_data.sh — 一键回填「Team PBP 页数据」（Phase 1）。
#
# ⚠️ 2026-07-27 起 Phase 2（Team Zone 出手分布 → team_shooting）已**废弃**：
#   BR 已下架球队级 zone 分布——独立 /shooting/ 子页 404、主队页
#   #all_shooting 仅余 per-player 投篮表，team_shooting/opponent_shooting
#   表与 Restricted Area 等 zone 标签在真实页（2007/2026 抽样）均 0 命中。
#   用户决议：放弃 team_shooting 表（库保持 0 行，后续分析不依赖它）。
#   故本脚本只跑 Phase 1；Phase 2 调用已注释，勿恢复（否则会空跑并
#   在 crawl_failures 灌入 ~900 条假失败）。
#
# 顺序：
#   Phase 1  Team PBP 页数据  → team_pbp_raw + team_page_raw + logo
# 仅此一阶段，--all-seasons --resume + --caffeinate。
# 严格限速内置（每次 driver.get 前 6–12s；队间再加 6–12s）。
#
# ⚠️⚠️ 必做前置（否则连接被拒 / 卡在 Cloudflare）⚠️⚠️
# 已实测：headless 直连 BR 命中交互式 CF（"Performing security verification"），
# 120s 卡死、无法自动过；唯有一路可行 = 驱动你「已手动过 CF」的 Chrome。
#   1) 完全退出 Chrome；
#   2) 用远程调试模式重启（终端执行，或你惯用的 launch_chrome_cdp.sh）：
#        /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
#            --remote-debugging-port=9222 \
#            --user-data-dir="$HOME/Library/Application Support/Google/Chrome" &
#   3) 打开 https://www.basketball-reference.com/ ，手动点过 "Verify you are human"；
#      cf_clearance cookie 留存于该 profile，后续各队页复用，不再逐个挑战。
#   4) 保持该 Chrome 窗口打开，再运行本脚本（端口改 9223 则
#      CHROME_CDP_URL=http://127.0.0.1:9223 ./run_team_data.sh）。
#
# 运行：  ./run_team_data.sh
# 日志：  /Volumes/12T/NBA/team_data_crawl_<时间戳>.log
set -u
cd "$(dirname "$0")"   # 切到项目根
PY=.venv/bin/python
CACHE=/Volumes/12T/NBA
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL="${CHROME_CDP_URL:-http://127.0.0.1:9222}"
export PGPASSWORD='R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1'
LOG="$CACHE/team_data_crawl_$(date +%Y%m%d_%H%M).log"
exec > >(tee -a "$LOG") 2>&1

echo "=== [$(date)] 启动：Team PBP 页数据 + Zone 出手分布 回填 ==="
echo "    CDP=$CHROME_CDP_URL  cache=$CACHE  日志=$LOG"

echo "=== [$(date)] Phase 1/2: Team PBP 页数据（team_pbp_raw + team_page_raw + logo）==="
$PY external_crawler/crawler/crawl_br_team_pbp.py \
    --all-seasons --resume --caffeinate \
    --cache-dir "$CACHE/br_team_pbp_cache" \
    || echo "!! Phase 1 异常退出（详见上方日志），继续 Phase 2"

# ── Phase 2（Team Zone 出手分布 → team_shooting）已废弃，不执行 ──
# 原因：BR 已下架球队 zone 分布（/shooting/ 子页 404、主队页无
# team_shooting 表）。用户 2026-07-27 决议放弃该表。若执行会空跑并
# 污染 crawl_failures。详见 .workbuddy/memory/2026-07-27.md。
echo "=== [$(date)] Phase 2: 已废弃（BR 下架球队 zone 分布，team_shooting 表放弃），跳过 ==="

echo "=== [$(date)] 全部阶段结束。日志: $LOG ==="
