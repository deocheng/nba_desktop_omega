#!/usr/bin/env bash
# run_br_team_pages.sh — 统一编排器便捷启动脚本（Mac 在线 / 离线均可）。
#
# 年份分阶段滚动（匹配 docs/run_live_crawl.md）：
#   stage1  默认        2000 -> 2026（首轮推荐）
#   stage2              1980 -> 2000
#   stage3              1947 -> 1979
#   all                 stage1 + stage2 + stage3 连续
#
# 其它任意参数透传给编排器，例如：
#   ./run_br_team_pages.sh --team DET
#   ./run_br_team_pages.sh --offline-dir det2026_br
#   ./run_br_team_pages.sh --kind hof
#   ./run_br_team_pages.sh --reset-state
#
# DB 口令来自仓库根 .env 的 DB_PASSWORD（脚本自动加载）。切勿硬编码。
set -euo pipefail

# 定位仓库根（脚本所在目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 激活 .venv（不存在则提示）
if [ ! -x .venv/bin/python ]; then
  echo "ERROR: .venv/bin/python not found in $SCRIPT_DIR" >&2
  echo "       请先创建虚拟环境并安装依赖（bs4 / undetected-chromedriver / psycopg2-binary）。" >&2
  exit 1
fi

# 加载 .env（若存在），使 DB_PASSWORD 进入环境；并暴露仓库根到 PYTHONPATH
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

ARG="${1:-stage1}"
case "$ARG" in
  stage1)
    exec .venv/bin/python -m crawl_team_pages --all-teams --year-start 2000 --year-end 2026
    ;;
  stage2)
    exec .venv/bin/python -m crawl_team_pages --all-teams --year-start 1980 --year-end 2000
    ;;
  stage3)
    exec .venv/bin/python -m crawl_team_pages --all-teams --year-start 1947 --year-end 1979
    ;;
  all)
    .venv/bin/python -m crawl_team_pages --all-teams --year-start 2000 --year-end 2026
    .venv/bin/python -m crawl_team_pages --all-teams --year-start 1980 --year-end 2000
    .venv/bin/python -m crawl_team_pages --all-teams --year-start 1947 --year-end 1979
    ;;
  *)
    # 透传：./run_br_team_pages.sh --team DET / --offline-dir ... / --kind hof ...
    exec .venv/bin/python -m crawl_team_pages "$@"
    ;;
esac
