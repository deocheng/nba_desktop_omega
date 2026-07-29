#!/usr/bin/env bash
# =============================================================================
# run_player_onoff_backfill.sh — player_onoff 回填管线 runner
#
# 顺序：DDL 确保（player_onoff + player_onoff_404）→ gap 测量 → 球员级
# on-off 爬虫（BROWSER_BACKEND=cdp，驱动本机已清 CF 的 9223 Chrome）。
#
# 🔴 纠错：on-off 是【球员级】页面（/players/{slug}/on-off/{year}），
# 本 runner 驱动 crawl_br_player_onoff.py，与废弃的球队级 team_on_off 无关。
#
# 反屏蔽：仅复用既有 common.browser；后端默认 cdp（直连本机已清 CF 的
# 9223 Chrome），爬虫内部已强制限速(≤15 请求/分)。
# 口令：严禁硬编码；必须由调用方通过环境变量 PGPASSWORD 注入。
#
# 用法：
#   export PGPASSWORD='<集群B口令>'
#   ./run_player_onoff_backfill.sh                          # 全量（cdp，--resume）
#   ./run_player_onoff_backfill.sh --slugs antetgi01 --years 2014   # 小子集
#   ./run_player_onoff_backfill.sh --limit 5 --dry-run      # 仅预览
#   ./run_player_onoff_backfill.sh --resume                 # 断点续跑
# =============================================================================
set -euo pipefail

# ── 口令：禁止硬编码，必须由环境变量注入 ───────────────────────────────────
: "${PGPASSWORD:?ERROR: 必须先 export PGPASSWORD 环境变量（集群B 口令）}"
export PGPASSWORD

# ── 反屏蔽后端：默认 cdp ──────────────────────────────────────────────────
EXPLICIT_BACKEND="${BROWSER_BACKEND:-}"
export BROWSER_BACKEND="${EXPLICIT_BACKEND:-cdp}"

# ── 路径：脚本位于 external_crawler/runner/，仓库根为上两级 ─────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PY="${REPO}/.venv/bin/python"
CRAWLER="${REPO}/external_crawler/crawler/crawl_br_player_onoff.py"
DDL_SQL="${REPO}/db/player_onoff.sql"
# 🔴 on-off 专用端口 9223（与 lineup 的 9222 严格隔离）。导出给爬虫 get_driver()。
CDP_URL="${CHROME_CDP_URL:-http://127.0.0.1:9223}"
export CHROME_CDP_URL="${CDP_URL}"
PSQL_BIN="${PSQL_BIN:-/opt/homebrew/bin/psql}"
PSQL_CONN="${PSQL_CONN:-host=127.0.0.1 port=5433 dbname=nba user=postgres}"

# ── 网络：CDP 永远是 localhost，强制直连 ──────────────────────────────────
# 爬虫必须直连 BR，绝不依赖任何代理（含本机/agent 临时代理）
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy 2>/dev/null || true
export NO_PROXY='*'
export no_proxy='*'

# ── 日志 ───────────────────────────────────────────────────────────────────
LOG_DIR="${REPO}/logs"
mkdir -p "${LOG_DIR}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="${LOG_DIR}/player_onoff_backfill_${TS}.log"
exec > >(tee -a "${LOG}") 2>&1
echo "=============================================================="
echo "[runner] 启动 $(date)"
echo "[runner] REPO=${REPO}"
echo "[runner] BROWSER_BACKEND=${BROWSER_BACKEND}"
echo "[runner] LOG=${LOG}"
echo "=============================================================="

# ── DDL 确保：执行 db/player_onoff.sql（幂等）──────────────────────────
echo "[runner] 确保 DDL (db/player_onoff.sql) ..."
"${PSQL_BIN}" "${PSQL_CONN}" -f "${DDL_SQL}" || {
  echo "[runner] ⚠️ DDL 执行失败（可能 dim_players 不存在导致 FK 失败）；"
  echo "          主表 CREATE TABLE IF NOT EXISTS 可能已成功，继续尝试 ..."
}

# ── gap 测量：on-off 维度 ──────────────────────────────────────────────────
# universe = player_shooting DISTINCT (player_id, season) WHERE Regular AND >=1997
#            扣除 player_onoff_404 已隔离 (slug, year) 对
# covered = player_onoff DISTINCT (player_id, season)
# gap = universe - covered
gap_onoff() {
  "${PY}" - <<'PY'
import os, psycopg2
cfg = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
           password=os.environ.get("PGPASSWORD", ""))
conn = psycopg2.connect(**cfg)
try:
    cur = conn.cursor()
    cur.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM ("
        "  SELECT DISTINCT ps.player_id, ps.season "
        "  FROM player_shooting ps "
        "  LEFT JOIN player_onoff_404 q ON q.slug = ps.player_id AND q.year = ps.season "
        "  WHERE ps.season_type='Regular' AND ps.player_id IS NOT NULL "
        "    AND ps.season >= 1997 AND q.slug IS NULL"
        ") u) "
        "- (SELECT COUNT(*) FROM ("
        "  SELECT DISTINCT player_id, season FROM player_onoff "
        "  WHERE player_id IS NOT NULL"
        ") c)"
    )
    print(cur.fetchone()[0])
finally:
    conn.close()
PY
}

gap_before="$(gap_onoff || echo ERR)"
echo "[runner] 当前 on-off 缺口 = ${gap_before}"

if [ "${gap_before}" = "0" ]; then
  echo "[runner] 缺口已为 0，跳过爬虫阶段"
  echo "[runner] 完成 $(date)"
  echo "[runner] 日志: ${LOG}"
  exit 0
fi

# ── dry-run 检测 ───────────────────────────────────────────────────────────
DRY=0
for _a in "$@"; do [ "${_a}" = "--dry-run" ] && DRY=1; done

# ── 球员级 on-off 爬虫 ─────────────────────────────────────────────────────
echo "[runner] === 球员级 on-off 爬虫 (backend=${BROWSER_BACKEND}) ==="
if [ "${DRY}" -eq 1 ]; then
  caffeinate -s "${PY}" "${CRAWLER}" --dry-run "$@" || true
else
  # caffeinate -s：阻止系统闲时睡眠，确保无人值守爬取不被机器休眠打断
  caffeinate -s "${PY}" "${CRAWLER}" --resume "$@" || true
fi

# ── gap 重算 ───────────────────────────────────────────────────────────────
gap_after="$(gap_onoff || echo ERR)"
echo "[runner] 完成：缺口 ${gap_before} -> ${gap_after}"

echo "[runner] 完成 $(date)"
echo "[runner] 日志: ${LOG}"
