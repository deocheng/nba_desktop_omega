#!/usr/bin/env bash
# ③ Referees 全历史回填（倒序 2026→1947；box score 早期即有裁判，随实爬校验下界）
# 每季单独落盘 JSON 缓存 (br_referees_cache/referees_<season>.json) 供 --rework 重放
# CDP 直连用户已手动过 CF 的 Chrome (端口 64656)，全程 --resume。
# 同场比赛从主客两队页各抓一次，库内按 (game_id, referee_name) 去重（upsert 幂等）。

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
CACHE_DIR=$PROJ_ROOT/br_referees_cache
LOG=$PROJ_ROOT/br_team_referees_crawl.log
mkdir -p "$CACHE_DIR"
if pgrep -f "crawl_br_team_referees.py" >/dev/null 2>&1; then
  echo "[guard] 已有 crawler 在跑，拒绝并行启动（避免被 BR 封禁）。退出。" | tee -a "$LOG"
  exit 1
fi

for S in $(seq 2026 -1 1947); do
  echo "===== $(date) START season $S =====" >> "$LOG"
  $PY external_crawler/crawler/crawl_br_team_referees.py --season $S --resume --cache-dir "$CACHE_DIR" >> "$LOG" 2>&1
  echo "===== $(date) END season $S (exit $?) =====" >> "$LOG"
done
echo "===== $(date) TEAM REFEREES ALL DONE =====" >> "$LOG"
