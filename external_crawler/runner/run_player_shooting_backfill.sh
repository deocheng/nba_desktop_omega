#!/usr/bin/env bash
# =============================================================================
# run_player_shooting_backfill.sh — player_shooting_backfill 管线 runner
#
# 顺序：B（回填孤儿 Playoffs player_id）先 → A（球员级 shooting 爬虫）后。
# 反屏蔽：仅复用既有 common.browser；后端选择见下方「反屏蔽后端」段。
# 口令：严禁硬编码；必须由调用方通过环境变量 PGPASSWORD 注入。
#
# 用法：
#   export PGPASSWORD='<集群B口令>'
#   ./run_player_shooting_backfill.sh                 # B + A（默认 cdp，失败退 uc）
#   BROWSER_BACKEND=cdp  ./run_player_shooting_backfill.sh   # 显式指定 cdp
#   BROWSER_BACKEND=uc    ./run_player_shooting_backfill.sh   # 显式指定 uc
#   BROWSER_BACKEND=playwright BR_COOKIE_FILE=cf.json ./run_player_shooting_backfill.sh
#   ./run_player_shooting_backfill.sh --resume        # A 断点续跑
#   ./run_player_shooting_backfill.sh --dry-run       # A 仅预览（不兜底）
#   ./run_player_shooting_backfill.sh --slugs brownja02,allenja01
# =============================================================================
set -euo pipefail

# ── 口令：禁止硬编码，必须由环境变量注入 ───────────────────────────────────
: "${PGPASSWORD:?ERROR: 必须先 export PGPASSWORD 环境变量（集群B 口令）}"
export PGPASSWORD

# ── 反屏蔽后端：默认 cdp（驱动本机已清 CF 的 9222 Chrome），失败自动退 uc ──
# 仅当用户显式 export BROWSER_BACKEND 时才尊重其选择，不做兜底切换。
# cdp 失败判定：跑前算 Regular 缺口，跑后若缺口未缩小 → 视为 cdp 失败 → 退 uc。
# （实测：CF 被拦时爬虫优雅退出 RC=0，故不能只靠退出码，必须看缺口是否推进。）
EXPLICIT_BACKEND="${BROWSER_BACKEND:-}"
export BROWSER_BACKEND="${EXPLICIT_BACKEND:-cdp}"

# ── 路径：脚本位于 external_crawler/runner/，仓库根为上两级 ─────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PY="${REPO}/.venv/bin/python"
BACKFILL="${REPO}/external_crawler/backfill/backfill_playoff_player_id.py"
CRAWLER="${REPO}/external_crawler/crawler/crawl_br_player_shooting.py"
LOG_DIR="${REPO}/logs"
mkdir -p "${LOG_DIR}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="${LOG_DIR}/player_shooting_backfill_${TS}.log"

# ── 日志：同时输出到终端与日志文件 ─────────────────────────────────────────
exec > >(tee -a "${LOG}") 2>&1
echo "=============================================================="
echo "[runner] 启动 $(date)"
echo "[runner] REPO=${REPO}"
echo "[runner] LOG=${LOG}"
echo "=============================================================="

# ── T5 DDL：确保 player_shooting 4 列唯一约束（ON CONFLICT 前置条件）──────
# T0 实测确认：player_shooting 原本 0 索引 / 0 唯一约束 → 必须建。
# 幂等：CREATE UNIQUE INDEX IF NOT EXISTS。
echo "[runner] T5: 确保唯一约束 uq_player_shooting_key ..."
"${PY}" - <<'PY'
import os, psycopg2
cfg = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
           password=os.environ.get("PGPASSWORD", ""))
conn = psycopg2.connect(**cfg)
try:
    cur = conn.cursor()
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_player_shooting_key "
        "ON player_shooting (player_id, season, season_type, team)"
    )
    conn.commit()
    print("[runner] T5: 唯一约束就绪 (uq_player_shooting_key)")
finally:
    conn.close()
PY

# ── 404 隔离表：确保 player_shooting_404 存在（404 修复 DDL，幂等）─────────
# enumerate_players / get_gap / coverage_report 均依赖本表排除失效 slug，
# 使缺口数诚实、爬虫不再对 404/corrupted slug 死循环空转。
echo "[runner] 确保 404 隔离表 player_shooting_404 ..."
"${PY}" - <<'PY'
import os, psycopg2
cfg = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
           password=os.environ.get("PGPASSWORD", ""))
conn = psycopg2.connect(**cfg)
try:
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS player_shooting_404 ("
        "  slug TEXT PRIMARY KEY,"
        "  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  note TEXT NULL)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ps404_first_seen "
                "ON player_shooting_404 (first_seen)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ps404_note "
                "ON player_shooting_404 (note)")
    conn.commit()
    print("[runner] 404 隔离表就绪 (player_shooting_404)")
finally:
    conn.close()
PY

# ── 阶段 B：回填孤儿 Playoffs player_id（纯 SQL，幂等低危）─────────────────
echo "[runner] === 阶段 B：回填 playoffs 孤儿 player_id ==="
"${PY}" "${BACKFILL}"

# ── 阶段 A：球员级 shooting 爬虫（cdp 优先，失败自动退 uc）──────────────
# 仅当未显式指定后端时启用兜底；dry-run 不触发兜底（仅预览）。
DRY=0
for _a in "$@"; do [ "${_a}" = "--dry-run" ] && DRY=1; done

run_stage_a() {
  local be="$1"; shift
  echo "[runner] === 阶段 A：球员级 shooting 爬虫 (backend=${be}) ==="
  BROWSER_BACKEND="${be}" "${PY}" "${CRAWLER}" --priority-gap "$@" || return $?
}

# Regular 缺口 = universe(≥1997 distinct slug-season) − covered(Regular)
gap_sql() {
  "${PY}" - <<'PY'
import os, psycopg2
cfg = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
           password=os.environ.get("PGPASSWORD", ""))
conn = psycopg2.connect(**cfg)
try:
    cur = conn.cursor()
    cur.execute(
        "SELECT (SELECT COUNT(*) FROM (SELECT DISTINCT br_player_id, season "
        "FROM player_gamelog WHERE br_player_id IS NOT NULL AND season >= 1997) t) "
        "- (SELECT COUNT(*) FROM (SELECT DISTINCT player_id, season "
        "FROM player_shooting WHERE season_type='Regular' AND player_id IS NOT NULL) t) "
        "- (SELECT COUNT(*) FROM (SELECT DISTINCT g.br_player_id, g.season "
        "FROM player_gamelog g JOIN player_shooting_404 q ON q.slug = g.br_player_id "
        "WHERE g.br_player_id IS NOT NULL AND g.season >= 1997) t)"
    )
    print(cur.fetchone()[0])
finally:
    conn.close()
PY
}

if [ -n "${EXPLICIT_BACKEND}" ]; then
  # 用户显式指定后端 → 直接跑，不兜底
  run_stage_a "${EXPLICIT_BACKEND}" "$@" || true
elif [ "${DRY}" -eq 1 ]; then
  # dry-run → 仅预览，不兜底
  run_stage_a "cdp" "$@" || true
else
  gap_before="$(gap_sql || true)"
  echo "[runner] 当前 Regular 缺口 = ${gap_before}"
  if [ "${gap_before}" -eq 0 ]; then
    echo "[runner] 缺口已为 0，跳过阶段 A"
  else
    run_stage_a "cdp" "$@" || true
    gap_after="$(gap_sql || true)"
    if [ "${gap_after}" -ge "${gap_before}" ]; then
      echo "[runner] cdp 未推进缺口（可能无 9222 Chrome / CF 未过），自动退 uc ..."
      run_stage_a "uc" "$@" || true
    else
      echo "[runner] cdp 已推进缺口 ${gap_before} → ${gap_after}"
    fi
  fi
fi

echo "[runner] 完成 $(date)"
echo "[runner] 日志: ${LOG}"
