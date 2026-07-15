#!/usr/bin/env bash
# run_br_team_pages.sh — 统一编排器便捷启动（含 .env 加载）
#
# 封装三阶段「年份分阶段滚动」调用。端口/口令走 .env 的 DB_PASSWORD，
# 不硬编码；在线抓取需在本机 Mac 跑（沙箱无 Chrome/UC）。
#
# 用法：
#   bash run_br_team_pages.sh            # 阶段① 2000→2026（默认）
#   bash run_br_team_pages.sh stage1     # 2000→2026
#   bash run_br_team_pages.sh stage2     # 1980→2000
#   bash run_br_team_pages.sh stage3     # 1947→1979
#   bash run_br_team_pages.sh all        # ①②③ 连续跑
#
# 单队示例：
#   .venv/bin/python -m crawl_team_pages --team DET
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

PY="${PYTHON:-$ROOT/.venv/bin/python}"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

# 阶段①（现在）：2000 → 2026
run_stage1() {
  "$PY" -m crawl_team_pages --all-teams --year-start 2000 --year-end 2026
}

# 阶段②：1980 → 2000
run_stage2() {
  "$PY" -m crawl_team_pages --all-teams --year-start 1980 --year-end 2000
}

# 阶段③：1947 → 1979
run_stage3() {
  "$PY" -m crawl_team_pages --all-teams --year-start 1947 --year-end 1979
}

case "${1:-stage1}" in
  stage1) run_stage1 ;;
  stage2) run_stage2 ;;
  stage3) run_stage3 ;;
  all)    run_stage1; run_stage2; run_stage3 ;;
  *) echo "unknown stage: $1 (use stage1|stage2|stage3|all)" >&2; exit 2 ;;
esac
