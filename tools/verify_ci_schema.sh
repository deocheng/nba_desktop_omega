#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# tools/verify_ci_schema.sh — 校验 db/schema.sql 能在干净库里零错误还原
# ---------------------------------------------------------------------------
# 用途（两道护栏）：
#   1) 提交前自检：改了 db/schema.sql 就在本地先跑一遍，别等 CI 报错；
#   2) CI 复用：CI 的 test job 用同一套命令还原 schema，本地/CI 口径一致。
#
# 为什么需要它：db/schema.sql 是 CI 里唯一的数据结构来源。
# 它若在某个 postgres 版本上还原失败，CI 会把「schema 还原失败」和
# 「代码有 bug」混在一起报错，噪音无诊断价值。本脚本把该失败单独隔离。
#
# 用法：
#   tools/verify_ci_schema.sh [目标库连接参数]
#   默认复用本机生产库端口（DB_HOST/DB_PORT/DB_NAME/DB_USER 可用 env 覆盖），
#   会在目标实例上建临时库 nba_schema_probe → 还原 → 核对表数 → 删除。
#
# 退出码：0 = 还原成功且表数与生产库一致；非 0 = 失败（原因打印在 stderr）
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_FILE="${REPO_ROOT}/db/schema.sql"
PROBE_DB="${PROBE_DB:-nba_schema_probe}"

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5433}"
DB_NAME="${DB_NAME:-nba}"
DB_USER="${DB_USER:-postgres}"

PSQL="${PSQL:-/opt/homebrew/opt/postgresql@18/bin/psql}"
if ! command -v "${PSQL}" >/dev/null 2>&1; then
  PSQL="$(command -v psql || true)"
fi
if [ -z "${PSQL}" ]; then
  echo "❌ 找不到 psql（可用 PSQL=/path/to/psql 指定）" >&2
  exit 2
fi
if [ ! -f "${SCHEMA_FILE}" ]; then
  echo "❌ 缺少 ${SCHEMA_FILE}" >&2
  exit 2
fi

run_psql() {
  LC_ALL=C LANG=C "${PSQL}" -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" "$@"
}

echo "▶ 目标实例 ${DB_HOST}:${DB_PORT} / 基准库 ${DB_NAME} / 探针库 ${PROBE_DB}"

# 1) 基准：生产库现有表数
base_count="$(run_psql -d "${DB_NAME}" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d '[:space:]')"
if [ -z "${base_count}" ] || [ "${base_count}" = "0" ]; then
  echo "❌ 无法读取基准库 ${DB_NAME} 的表数（连接失败或库不存在）" >&2
  exit 2
fi
echo "  基准库表数: ${base_count}"

# 2) 建干净探针库 → 还原 → 核对 → 删除
cleanup() {
  run_psql -d postgres -c "DROP DATABASE IF EXISTS ${PROBE_DB};" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
if ! run_psql -d postgres -c "CREATE DATABASE ${PROBE_DB};" >/dev/null 2>&1; then
  echo "❌ 无法创建探针库 ${PROBE_DB}" >&2
  exit 2
fi

apply_log="$(mktemp -t nba_schema_probe)"
# -o /dev/null：丢弃 psql 的查询回显（DLL 里 `SELECT pg_catalog.set_config(...)`
# 会打印一行 (1 row)，属噪声不是告警）；stderr 仍完整落盘 → 真实错误照常可见。
if ! LC_ALL=C LANG=C "${PSQL}" -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" \
      -d "${PROBE_DB}" -v ON_ERROR_STOP=1 -q -o /dev/null -f "${SCHEMA_FILE}" >"${apply_log}" 2>&1; then
  echo "❌ db/schema.sql 还原失败（ON_ERROR_STOP=1 已中止）" >&2
  head -20 "${apply_log}" >&2
  rm -f "${apply_log}"
  exit 1
fi
if [ -s "${apply_log}" ]; then
  echo "⚠️ 还原过程有 stderr 输出（前 5 行）:"
  head -5 "${apply_log}"
fi
rm -f "${apply_log}"

probe_count="$(run_psql -d "${PROBE_DB}" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')"
echo "  探针库表数: ${probe_count}"

if [ "${probe_count}" != "${base_count}" ]; then
  echo "❌ 表数不一致：探针 ${probe_count} ≠ 基准 ${base_count}" >&2
  echo "   （db/schema.sql 已过期 → 需按文件头注释的生成命令重新导出）" >&2
  exit 1
fi

echo "✅ db/schema.sql 还原零错误，表数与基准一致（${probe_count}）"
exit 0
