#!/usr/bin/env bash
# ④ Depth Charts 增量补 2025-26（仅单季；BR URL 年 = 2026 结束年）
# 落库复用 team_depth_chart（ALTER 后已含 position / player_id），唯一键
# (season, team_abbr, position, depth_rank)。本脚本只跑 --season 2026。
# CDP 直连用户已手动过 CF 的 Chrome (端口 64656)，全程 --resume。

# source 统一路径解析（与 Python 侧 common/nba_paths.py 对齐）
if [ -f "common/paths.sh" ]; then
  . "common/paths.sh"
fi

set -a
[ -f $PROJ_ROOT/.env ] && . $PROJ_ROOT/.env
set +a
cd $PROJ_ROOT
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:64656
export BR_COOKIE_FILE=/tmp/br_cf_cookies.json
PY=.venv/bin/python
CACHE_DIR=$PROJ_ROOT/br_depth_cache
LOG=$PROJ_ROOT/br_team_depth_crawl.log
mkdir -p "$CACHE_DIR"
if pgrep -f "crawl_br_team_depth.py" >/dev/null 2>&1; then
  echo "[guard] 已有 crawler 在跑，拒绝并行启动（避免被 BR 封禁）。退出。" | tee -a "$LOG"
  exit 1
fi

# 仅 2025-26 一季（增量更新，非全量新建）
for S in 2026; do
  echo "===== $(date) START season $S (depth-charts 2025-26) =====" >> "$LOG"
  $PY external_crawler/crawler/crawl_br_team_depth.py --season $S --resume --cache-dir "$CACHE_DIR" >> "$LOG" 2>&1
  echo "===== $(date) END season $S (exit $?) =====" >> "$LOG"
done
echo "===== $(date) TEAM DEPTH CHARTS 2025-26 DONE =====" >> "$LOG"
