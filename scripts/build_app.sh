#!/usr/bin/env bash
# NBACore Studio v8 — 构建本地 app（PyInstaller one-file）
#
# 用法：bash scripts/build_app.sh
# 产物：dist/NBACore（macOS/Linux 无扩展名；Windows 为 NBACore.exe）
# 说明：PostgreSQL 保持外部依赖，产物不含数据库与真实口令。详见 docs/app-build.md
#
# 🔴 门禁要求 .sh 零硬编码绝对路径 —— 一律经 common/paths.sh 取 PROJ_ROOT / VENV_PYTHON。
set -eo pipefail

_paths_sh="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)/../common/paths.sh"
# shellcheck disable=SC1090
. "$_paths_sh"

cd "$PROJ_ROOT"

PY="$VENV_PYTHON"
if [ ! -x "$PY" ]; then
  echo "[ERROR] venv python 不可用: $PY" >&2
  exit 1
fi

# 构建工具不在生产依赖里（见 pyproject.toml [project.optional-dependencies].build）
if ! "$PY" -c 'import PyInstaller' 2>/dev/null; then
  echo "[install] 未检测到 PyInstaller，安装 build extras…"
  "$PY" -m pip install "pyinstaller>=6.11,<7"
fi

# 打包前校验 spec datas 声明的资源都在，避免打出缺资源的空壳
for f in frontend NBAlogo viz/theme_tokens.json .env.example db/schema.sql main.py nbacore.spec; do
  if [ ! -e "$PROJ_ROOT/$f" ]; then
    echo "[ERROR] 缺少打包资源: $f" >&2
    exit 1
  fi
done

_ver="$("$PY" -c 'import PyInstaller; print(PyInstaller.__version__)')"
echo "[build] PyInstaller $_ver | spec: $PROJ_ROOT/nbacore.spec"
# 🔴 不加 --clean：它会递归删 PyInstaller 全局缓存（bincache，>50 文件），
#    在受限环境下触发批量删除保护而中断构建；缓存是否新鲜不影响正确性，
#    --noconfirm 已足够覆盖 dist/ 旧产物。
"$PY" -m PyInstaller --noconfirm "$PROJ_ROOT/nbacore.spec"

OUT="$PROJ_ROOT/dist/NBACore"
if [ ! -f "$OUT" ] && [ -f "$OUT.exe" ]; then
  OUT="$OUT.exe"
fi
if [ ! -f "$OUT" ]; then
  echo "[ERROR] 未产出可执行文件: $OUT" >&2
  exit 1
fi

_bytes="$(wc -c < "$OUT" | tr -d ' ')"
echo "========================================"
echo "  BUILD SUCCESS"
echo "  产物: $OUT"
echo "  体积: $_bytes 字节 / $((_bytes / 1024 / 1024)) MiB"
echo "========================================"
echo "  运行前请确认外部 PostgreSQL 可达（默认 localhost:5433 / nba）。"
echo "  无数据库仍可启动，/health 会显示 database_connected=false。"
