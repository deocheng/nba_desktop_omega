#!/bin/bash
# RelateAnything 引擎环境安装（M4 macOS / CPU）
# 关键防御：清空 PYTHONPATH（WorkBuddy 注入的 shim 会拦截 open() 导致后台任务崩）
set -e
export PYTHONPATH=""

ROOT=/Volumes/12T/NBA/action_analysis
PY=/Users/deocheng/.workbuddy/binaries/python/versions/3.13.12/bin/python3

mkdir -p "$ROOT"
cd "$ROOT"

echo "[1/4] clone RelateAnything"
if [ ! -d "$ROOT/RelateAnything" ]; then
  git clone --depth 1 https://github.com/Maelic/RelateAnything.git
else
  echo "  already cloned"
fi

echo "[2/4] venv"
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  "$PY" -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/pip" install -q -U pip wheel

echo "[3/4] install relsgg (torch + transformers + hub)"
cd "$ROOT/RelateAnything"
"$ROOT/.venv/bin/pip" install -e ".[hub]"

echo "[4/4] version report"
"$ROOT/.venv/bin/python" - <<'PYEOF'
import sys, torch, transformers
print("python", sys.version.split()[0])
print("torch", torch.__version__, "mps", torch.backends.mps.is_available())
print("transformers", transformers.__version__)
PYEOF

echo "INSTALL_DONE"
