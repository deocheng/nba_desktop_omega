#!/usr/bin/env bash
# Team PBP 爬虫启动器
# ⚠️ 在【用户本机 Mac 终端】运行；agent 沙箱连不到您的 Chrome CDP，无法代跑。
# 前置条件：
#   1) Chrome 已以 --remote-debugging-port=9222（或 9223）启动
#   2) 已手动点过 Basketball-Reference 的 Cloudflare 验证（CF 已过）
# 节流已内置：每次页面加载前强制等待 6–12s（≤~7 请求/分钟）。
#
# 用法：
#   ./run_team_pbp.sh --season 2026 --resume                  # 先单季验证（推荐首跑）
#   ./run_team_pbp.sh --all-seasons --resume --caffeinate     # 全量无人值守（防休眠）
# 若 Chrome 远程调试端口是 9223：  CHROME_CDP_URL=http://127.0.0.1:9223 ./run_team_pbp.sh ...
set -euo pipefail
cd "$(dirname "$0")"
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL="${CHROME_CDP_URL:-http://127.0.0.1:9222}"
exec .venv/bin/python external_crawler/crawler/crawl_br_team_pbp.py \
    --cache-dir /Volumes/12T/NBA/br_team_pbp_cache "$@"
