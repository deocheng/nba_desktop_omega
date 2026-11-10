#!/usr/bin/env bash
# =============================================================================
# common/paths.sh — shell 侧路径解析（与 Python 侧 common/nba_paths.py 对齐）
#
# 为什么需要它
# ------------
# 历史上 37 个 .sh 把 /Users/deocheng 与 /Volumes/12T 直接写进字面量。
# 这些路径**会静默失效**：换机器 / 换盘 / 迁仓后，脚本仍能启动，
# 但读写的是错误位置（或直接报「no such file」）。
#
# 本文件把解析规则收敛成**唯一来源**，与 Python 侧一一对应：
#
#   解析项          环境变量                兜底                        Python 对应
#   --------------- ----------------------- --------------------------- -------------------
#   PROJ_ROOT       （脚本自身位置）          仓库根                       REPO_ROOT
#   DATA_ROOT       NBA_DATA_ROOT            /Volumes/12T/NBA             DATA_ROOT
#   PG_DATA_DIR     NBA_PG_DATA_DIR          ~/nba_pg（有 PG_VERSION）      PG_DATA_DIR
#                                              否则 $DATA_ROOT/nba_pg
#   WORKSPACE_ROOT  NBA_WORKSPACE_ROOT       ~/WorkBuddy/<会话>            WORKSPACE_ROOT
#   ARCHIVE_ROOT    NBA_ARCHIVE_ROOT         $DATA_ROOT/raw_archive       ARCHIVE_ROOT
#   HEADSHOTS_ROOT  NBA_HEADSHOTS_ROOT       $DATA_ROOT/headshots         HEADSHOTS_ROOT
#
# 🔴 **PG 数据目录的解析顺序必须与 Python 侧完全一致**，否则：
#    同一台机器上，shell 启动的 PG 与 Python 读到的 PG 会指向**不同目录**
#    → 连接到旧实例 / 连不上。测试 tests/test_start_crawler.py::test_default_params
#    就是守这条一致性契约的。
#
# 用法：
#   source "$(dirname "$0")/common/paths.sh"     # 仓库根下的脚本
#   source "$(dirname "$0")/../common/paths.sh"  # 子目录脚本
#
# 之后可用：$PROJ_ROOT $DATA_ROOT $PG_DATA_DIR $ARCHIVE_ROOT $HEADSHOTS_ROOT
#            $WORKSPACE_ROOT $VENV_PYTHON $WATCHDOG_SCRIPT
# =============================================================================

# 防重复 source（幂等）
if [ -n "${_NBA_PATHS_SH_LOADED:-}" ]; then
  return 0 2>/dev/null || true
fi
_NBA_PATHS_SH_LOADED=1

# ── 仓库根 ────────────────────────────────────────────────────────────────
# 🔴 **始终**从本文件自身位置推导，**不采纳外部预设的 PROJ_ROOT**：
#     Python 侧 REPO_ROOT = `Path(common/nba_paths.py).resolve().parents[1]`
#     （固定指向代码自身所在仓库，与 CWD 无关）。
#     若 shell 侧采纳外部预设的 PROJ_ROOT（各脚本自己算的），
#     两侧就可能指向**不同仓库** —— 实测第三处真实分叉。
#     外部覆盖请用 NBA_REPO_ROOT（与 Python 侧同名同义）。
#
# 🔴 **必须用 `pwd -P`（物理路径）**，不能用 `pwd`（逻辑路径）：
#     macOS 的 /tmp 是指向 /private/tmp 的符号链接 → 逻辑路径给 /tmp/...，
#     而 Python 侧 `Path(__file__).resolve()` 给 /private/tmp/... → 两侧不一致。
if [ -n "${NBA_REPO_ROOT:-}" ]; then
  PROJ_ROOT="$(cd "$NBA_REPO_ROOT" && pwd -P)"
else
  _paths_sh_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
  PROJ_ROOT="$(cd "$_paths_sh_dir/.." && pwd -P)"
fi
export PROJ_ROOT

# ── 数据盘根 ──────────────────────────────────────────────────────────────
# 🔴 解析规则**必须与 Python 侧 common/nba_paths.py 的 _resolve_data_root 一致**：
#     1. 环境变量 NBA_DATA_ROOT
#     2. 仓库父目录（**须带特征标记校验** —— 仓库被 clone 到别处时不能误判）
#     3. 硬编码兜底 /Volumes/12T/NBA
#   不一致的后果（实测 CI run 42876413458）：CI 上仓库在
#   /home/runner/work/nba_desktop_omega → Python 侧 DATA_ROOT = 其父目录，
#   而 shell 侧仍是 /Volumes/12T/NBA → 两侧 PG 目录指向不同位置。
#
#   特征标记（与 Python 侧 _DATA_ROOT_MARKERS 同源）：nba_pg / raw_archive / headshots
_data_root_has_marker() {
  local d="$1"
  [ -d "$d/nba_pg" ] || [ -d "$d/raw_archive" ] || [ -d "$d/headshots" ]
}

if [ -n "${NBA_DATA_ROOT:-}" ]; then
  DATA_ROOT="$NBA_DATA_ROOT"
else
  _repo_parent="$(cd "$PROJ_ROOT/.." 2>/dev/null && pwd -P)"
  if [ -n "$_repo_parent" ] && _data_root_has_marker "$_repo_parent"; then
    DATA_ROOT="$_repo_parent"
  else
    # 🔴 兜底与 Python 侧一致：仓库父目录（**不是**硬编码 /Volumes/12T/NBA）。
    #    硬编码会让 CI 上两侧指向不同位置（实测 run 42876413458 失败）。
    DATA_ROOT="${_repo_parent:-/Volumes/12T/NBA}"
  fi
  unset _repo_parent
fi
export DATA_ROOT

# ── PG 数据目录（解析顺序必须与 Python 侧一致）────────────────────────────
if [ -n "${NBA_PG_DATA_DIR:-}" ]; then
  PG_DATA_DIR="$NBA_PG_DATA_DIR"
elif [ -f "$HOME/nba_pg/PG_VERSION" ]; then
  PG_DATA_DIR="$HOME/nba_pg"
else
  PG_DATA_DIR="$DATA_ROOT/nba_pg"
fi
export PG_DATA_DIR

# ── 其他资产根 ────────────────────────────────────────────────────────────
ARCHIVE_ROOT="${NBA_ARCHIVE_ROOT:-$DATA_ROOT/raw_archive}"
HEADSHOTS_ROOT="${NBA_HEADSHOTS_ROOT:-$DATA_ROOT/headshots}"
export ARCHIVE_ROOT HEADSHOTS_ROOT

# ── 会话工作区 ────────────────────────────────────────────────────────────
# 默认取 ~/WorkBuddy 下**最近修改**的会话目录（与人工习惯一致）。
if [ -z "${WORKSPACE_ROOT:-}" ] && [ -n "${NBA_WORKSPACE_ROOT:-}" ]; then
  WORKSPACE_ROOT="$NBA_WORKSPACE_ROOT"
fi
if [ -z "${WORKSPACE_ROOT:-}" ] && [ -d "$HOME/WorkBuddy" ]; then
  WORKSPACE_ROOT="$(ls -1dt "$HOME"/WorkBuddy/*/ 2>/dev/null | head -1 | sed 's#/$##')"
fi
export WORKSPACE_ROOT
WORKSPACE_PARENT="${NBA_WORKSPACE_PARENT:-$HOME/WorkBuddy}"
export WORKSPACE_PARENT

# ── 运行时资产 ────────────────────────────────────────────────────────────
VENV_PYTHON="${NBA_VENV_PYTHON:-$PROJ_ROOT/.venv/bin/python}"
WATCHDOG_SCRIPT="${NBA_WATCHDOG_SCRIPT:-$HOME/.workbuddy/skills/nba-crawler-watch/scripts/watch_crawlers.py}"
export VENV_PYTHON WATCHDOG_SCRIPT

# ── WorkBuddy 托管的 Python ───────────────────────────────────────────────
# 🔴 不能写死版本目录（如 .../versions/3.13.12/bin/python3）：
#    WorkBuddy 升级后旧版本目录会被清掉 → 所有引用它的脚本一起断
#    （与 node 版本目录 22.22.2 → 22.22.2-6 是同一类失效）。
#    正确做法：读 `versions/current`（内容是当前版本号的文本文件）再拼路径。
WB_PY_ROOT="${NBA_WB_PY_ROOT:-$HOME/.workbuddy/binaries/python/versions}"
if [ -f "$WB_PY_ROOT/current" ]; then
  WB_PY_VERSION="$(tr -d '[:space:]' < "$WB_PY_ROOT/current")"
  WB_PYTHON="$WB_PY_ROOT/$WB_PY_VERSION/bin/python3"
else
  # current 缺失 → 退回 PATH 上的 python3（保证脚本仍可运行）
  WB_PYTHON="$(command -v python3 || echo python3)"
fi
export WB_PY_ROOT WB_PYTHON

# ── 便捷别名（历史脚本里用过的名字）────────────────────────────────────────
PG_DATADIR="${PG_DATADIR:-$PG_DATA_DIR}"   # 兼容旧变量名
export PG_DATADIR
