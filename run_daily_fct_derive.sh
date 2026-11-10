#!/usr/bin/env bash
# run_daily_fct_derive.sh — 日更收尾：从 play_by_play 重建 fct_pbp_shots（2026-10-24 立）
#
# 作用：日更爬虫（nba-cdn-ingest/daily_crawl_nba.py）把新比赛的
#       play_by_play / dim_games / player_gamelog 入库后，本脚本把
#       fct_pbp_shots（纯 DB 派生表，不是爬来的）补齐到最新。
#
# 特性：
#   · 幂等：ON CONFLICT (game_id, src_ctid) DO UPDATE，重复跑行数不变。
#   · 赛季自动探测：取 dim_games 最新比赛所属赛季（可用 $1 覆盖）。
#   · 前置校验：PG 可达 + 该季 PBP 分区存在，缺一即跳过并报错（不静默）。
#   · 清 WorkBuddy 注入的代理与 PYTHONPATH（否则 DB/网络会被拦）。
#   · 口令只从项目根 .env 取，脚本内不落明文。
#
# 用法：
#   ./run_daily_fct_derive.sh          # 自动探测赛季
#   ./run_daily_fct_derive.sh 2027     # 指定赛季
export LC_ALL=C
set -u
cd "$(dirname "$0")"
ROOT="$(pwd)"

VENV_PY="$ROOT/.venv/bin/python"
PSQL="/opt/homebrew/bin/psql -h 127.0.0.1 -p 5433 -U postgres -d nba -t -A"
LOGDIR="$ROOT/logs"
LOGFILE="$LOGDIR/daily_fct_derive.log"
mkdir -p "$LOGDIR"

# ── DB 口令：只从项目根 .env 取 ──
_ENV_FILE="$ROOT/.env"
if [ -f "$_ENV_FILE" ]; then set -a; . "$_ENV_FILE"; set +a; fi
export PGPASSWORD="${PGPASSWORD:-${DB_PASSWORD:-}}"

log(){ echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"; }

# 1) PG 可达性
if ! /opt/homebrew/bin/pg_isready -h 127.0.0.1 -p 5433 >/dev/null 2>&1; then
  log "❌ PG 5433 不可达，跳过 fct 派生"
  exit 1
fi

# 2) 赛季：命令行优先，否则取 dim_games 最新比赛所属赛季
SEASON="${1:-}"
if [ -z "$SEASON" ]; then
  SEASON=$($PSQL -c "SELECT season FROM dim_games WHERE game_date IS NOT NULL ORDER BY game_date DESC LIMIT 1;" 2>/dev/null | tail -1 | tr -d ' ')
fi
if [ -z "$SEASON" ]; then
  log "❌ 无法探测赛季（dim_games 为空或查询失败），跳过"
  exit 1
fi
log "目标赛季: $SEASON"

# 3) 该季 PBP 分区必须存在（否则 SQL 会直接报 relation 不存在）
PART=$($PSQL -c "SELECT to_regclass('play_by_play_p_${SEASON}')::text;" 2>/dev/null | tail -1 | tr -d ' ')
if [ -z "$PART" ] || [ "$PART" = "" ]; then
  log "❌ 分区 play_by_play_p_${SEASON} 不存在，跳过（新赛季需先 create_pbp_partition.py）"
  exit 1
fi

# 4) 派生前快照
PRE=$($PSQL -c "SELECT count(*)||'/'||count(DISTINCT game_id) FROM fct_pbp_shots WHERE season=${SEASON};" 2>/dev/null | tail -1 | tr -d ' ')
log "派生前: season=${SEASON} 行数/场次 = ${PRE}"

# 5) 执行派生（全季幂等 upsert；--force 因赛季本就有行，护栏会拦，此处属明确意图）
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
    PYTHONPATH= PGPASSWORD="$PGPASSWORD" \
    "$VENV_PY" "$ROOT/build_fct_pbp_shots.py" --season "$SEASON" --apply --force --id-format numeric \
    >> "$LOGFILE" 2>&1
RC=$?

POST=$($PSQL -c "SELECT count(*)||'/'||count(DISTINCT game_id) FROM fct_pbp_shots WHERE season=${SEASON};" 2>/dev/null | tail -1 | tr -d ' ')
log "派生后: season=${SEASON} 行数/场次 = ${POST} (rc=$RC)"

if [ "$RC" -ne 0 ]; then
  log "❌ fct 派生失败 rc=${RC}，详见 $LOGFILE"
  exit "$RC"
fi
log "✅ fct_pbp_shots 已同步至最新 (season=${SEASON})"
exit 0
